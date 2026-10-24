"""Durable intent → backup → submit-once → readback state machine."""

from dataclasses import asdict
import copy
import contextlib
import json
from pathlib import Path
import uuid
from datetime import datetime, timezone
from .common import Refused, atomic_json, atomic_remove, read_json, safe_id
from .planner import Action, source_revision, artifact_group, component_revision
from .operations import observed

TERMINAL = {
    "complete",
    "rolled-back",
    "preparation-failed",
    "rolled-back-manual-recovery",
    "cancelled",
}


def run_id():
    return (
        datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ")
        + "-"
        + uuid.uuid4().hex[:8]
    )


def pending(state_dir, device):
    found = []
    for path in (state_dir / "runs").glob("*/journal.json"):
        doc = read_json(path)
        if doc.get("device") == device and doc.get("phase") not in TERMINAL:
            found.append((path.parent.name, doc))
    return sorted(found)


class Engine:
    def __init__(
        self,
        driver,
        folder,
        device,
        choices,
        nas=None,
        target_binding=None,
        state_dir=None,
        scope="setup",
    ):
        self.driver, self.folder, self.device, self.choices, self.nas = (
            driver,
            folder,
            device,
            choices,
            nas,
        )
        self.state_dir = state_dir
        self.target_binding = target_binding
        self.scope = scope
        self.path = folder / "journal.json"
        self.doc = None

    def save(self):
        atomic_json(self.path, self.doc)

    def start(self, plan, state):
        self.prepare(plan, state)
        return self.apply()

    def prepare(self, plan, state):
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.doc = dict(
            local_before=self.local_state() if self.state_dir is not None else None,
            target_binding=self.target_binding,
            schema=2,
            scope=self.scope,
            run=self.folder.name,
            device=self.device,
            choices=self.choices,
            phase="preparing",
            source_revision=source_revision(),
            before=state,
            actions=[
                dict(action=asdict(a), phase="planned", info={}) for a in plan.actions
            ],
        )
        self.save()
        try:
            for row in self.doc["actions"]:
                a = Action(**row["action"])
                row["info"] = (
                    self.nas.prepare(a) if a.kind == "nas" else self.driver.prepare(a)
                )
                row["action"] = asdict(a)
                row["phase"] = "prepared"
                self.save()
        except BaseException:
            self.doc["phase"] = "preparation-failed"
            with contextlib.suppress(OSError):
                self.save()
            raise
        self.doc["phase"] = "prepared"
        self.save()
        return self.doc

    def load(self):
        self.doc = read_json(self.path)
        if (
            not self.doc
            or self.doc.get("schema") != 2
            or self.doc.get("device") != self.device
        ):
            raise Refused(
                "Journal identity/schema mismatch; use the original checkout for older runs"
            )
        if self.doc["phase"] == "preparation-failed":
            raise Refused(
                "Preparation failed before device mutation; start a fresh apply"
            )

    def value(self, a, state):
        return self.nas.snapshot()["files"] if a.kind == "nas" else observed(a, state)

    def reconcile(self, retry_unchanged=False):
        self.check_resume()
        if self.doc["phase"] in ("configuration-applied", "finalizing"):
            return
        state = self.driver.snapshot()
        for row in self.doc["actions"]:
            if row["phase"] not in ("applying", "uncertain", "backing-up"):
                continue
            a = Action(**row["action"])
            value = self.value(a, state)
            if row["phase"] == "backing-up":
                if value != a.before:
                    raise Refused("State changed during backup; inspect " + a.id)
                row["phase"] = "prepared"
                self.save()
                continue
            if value == a.after:
                if a.kind == "routes":
                    self.driver.control_call("reload", root=True)
                if a.kind == "cache":
                    self.driver.tv.root("systemctl daemon-reload\n", namespace=True)
                if a.kind == "nas":
                    self.nas.check_shared(a, row["info"])
                    self.nas.restart()
                else:
                    self.driver.verify(a, row["before_state"], state)
                row["phase"] = "applied"
                row["reconciled"] = True
                self.save()
            elif value == a.before:
                if not retry_unchanged:
                    raise Refused(
                        a.id
                        + " completion uncertain and state unchanged; inspect the private operation log, ensure no installer is running, then use --resume "
                        + self.folder.name
                        + " --retry-unchanged or rollback"
                    )
                if a.kind in ("package", "uninstall"):
                    self.driver.tv.sdk(
                        'set -eu\n! ps -eo comm | grep -E "^(pkgcmd|pkgmgr|wrt-installer|wgt-installer)$"\n'
                    )
                row["phase"] = "prepared"
                row["retry_authorized"] = True
                self.save()
            else:
                raise Refused(
                    a.id
                    + " is partially applied or externally drifted; rollback the run or inspect the journal before repair"
                )

    def check_resume(self):
        if self.doc["source_revision"] != source_revision():
            raise Refused(
                "Source changed since this run; use the original checkout for recovery"
            )
        if self.doc["phase"] not in (
            "prepared",
            "partial",
            "applying",
            "configuration-applied",
            "finalizing",
        ):
            raise Refused(
                "This run cannot resume apply; continue rollback or start a new run"
            )

    def apply(self):
        self.check_resume()
        if self.doc["phase"] in ("configuration-applied", "finalizing"):
            return self.doc
        self.doc["phase"] = "applying"
        self.save()
        try:
            for row in self.doc["actions"]:
                a = Action(**row["action"])
                if row["phase"] == "applied":
                    current = self.driver.snapshot()
                    if self.value(a, current) != a.after:
                        raise Refused("Previously applied action drifted: " + a.id)
                    if a.kind == "package":
                        # Matching bytes do not establish current service registration.
                        # Reuse the driver contract without replaying installation.
                        self.driver.verify(a, row["before_state"], current)
                    continue
                if row["phase"] not in ("prepared", "backed-up"):
                    raise Refused("Reconcile incomplete action first: " + a.id)
                before = self.driver.snapshot()
                if self.value(a, before) != a.before:
                    raise Refused("Concurrent change before " + a.id)
                row["before_state"] = before
                if row["phase"] == "prepared":
                    row["phase"] = "backing-up"
                    row["info"]["attempt"] = uuid.uuid4().hex[:8]
                    self.save()
                    row["info"] = (
                        self.nas.backup(a, row["info"])
                        if a.kind == "nas"
                        else self.driver.backup(a, row["info"], before)
                    )
                    row["phase"] = "backed-up"
                    self.save()
                row["phase"] = "applying"
                self.save()  # durable intent before submitting any uncertain mutation
                if a.kind == "nas":
                    self.nas.execute(a, row["info"])
                else:
                    self.driver.execute(a, row["info"], before)
                after = self.driver.snapshot()
                if a.kind == "nas":
                    if self.nas.snapshot()["files"] != a.after:
                        raise Refused("NAS readback failed")
                else:
                    self.driver.verify(a, before, after)
                row["phase"] = "applied"
                self.save()
            self.doc["after"] = self.driver.snapshot()
            self.doc["phase"] = "configuration-applied"
            self.save()
            return self.doc
        except BaseException:
            for row in self.doc["actions"]:
                if row["phase"] == "applying":
                    row["phase"] = "uncertain"
            self.doc["phase"] = "partial"
            with contextlib.suppress(OSError):
                self.save()
            raise

    def rollback(self):
        if self.doc["source_revision"] != source_revision():
            raise Refused(
                "Source changed since this run; use the original checkout for recovery"
            )
        if "local_commit" in self.doc:
            self.validate_local_state()
        self.doc["phase"] = "rolling-back"
        self.save()
        manual = []
        try:
            for row in reversed(self.doc["actions"]):
                if row["phase"] in (
                    "planned",
                    "prepared",
                    "backing-up",
                    "backed-up",
                    "rolled-back",
                ):
                    continue
                a = Action(**row["action"])
                state = self.driver.snapshot()
                target = a.before
                if a.kind == "uninstall" and self.value(a, state) != a.before:
                    manual.append(a.options["package"])
                    row["phase"] = "manual-recovery"
                    self.save()
                    continue
                if (
                    a.kind == "package"
                    and (a.before is None or not row["info"].get("recovery_package"))
                    and self.value(a, state) != a.before
                ):
                    if self.value(a, state) != a.after:
                        raise Refused("Package drift blocks recovery: " + a.id)
                    row["manual_recovery_reason"] = (
                        "Retained new app to preserve subsequent user data"
                        if a.before is None
                        else "No verified signed reinstall package"
                    )
                    manual.append(a.options["package"])
                    row["phase"] = "manual-recovery"
                    self.save()
                    continue
                if (
                    a.kind == "package"
                    and a.before is not None
                    and row["info"].get("recovery_package")
                    and self.value(a, state) != a.before
                ):
                    record = row["info"].get("forward_recovery")
                    if record:
                        target = self.driver.recovery_target(a, row["info"])
                        if self.value(a, state) == target:
                            self.driver.verify_recovery(a, row["info"], state)
                            row["phase"] = "rolled-back"
                            self.save()
                            continue
                    if self.value(a, state) != a.after:
                        raise Refused("Package drift blocks recovery: " + a.id)
                    if row["phase"] == "rolling-back":
                        raise Refused(
                            "Recovery install outcome unconfirmed; inspect without replay: "
                            + a.id
                        )
                    if not record:
                        row["info"]["forward_recovery"] = self.driver.prepare_recovery(
                            a, row["info"]
                        )
                        self.save()
                    target = self.driver.recovery_target(a, row["info"])
                row["phase"] = "rolling-back"
                self.save()
                if a.kind == "nas":
                    self.nas.rollback(a, row["info"])
                else:
                    self.driver.rollback(a, row["info"], state)
                after = self.driver.snapshot()
                if self.value(a, after) != target:
                    raise Refused("Rollback readback failed: " + a.id)
                if target != a.before:
                    self.driver.verify_recovery(a, row["info"], after)
                row["phase"] = "rolled-back"
                self.save()
            self.restore_local_state()
            self.doc["phase"] = (
                "rolled-back-manual-recovery" if manual else "rolled-back"
            )
            self.doc["manual_recovery"] = manual
            self.save()
            return manual
        except BaseException:
            self.doc["phase"] = "rollback-partial"
            with contextlib.suppress(OSError):
                self.save()
            raise

    def local_state(self):
        if self.state_dir is None:
            raise Refused("A state directory is required to finalize saved choices")
        return {
            name: read_json(self.state_dir / (self.device + "-" + name + ".json"))
            for name in ("choices", "ledger")
        }

    def finalize(self):
        """Finish a recoverable two-file local transaction; never contact the TV."""
        self.check_resume()
        if self.doc["phase"] not in ("configuration-applied", "finalizing"):
            raise Refused("Verify all device changes before finalizing saved choices")
        if "local_commit" not in self.doc:
            before = self.doc.get("local_before")
            if before is None:
                raise Refused(
                    "Run lacks saved-state backups; use its original checkout for recovery"
                )
            if self.local_state() != before:
                raise Refused(
                    "Saved choices or ledger changed during this run; preserve the edits before recovery"
                )
            old = before["ledger"] or {}
            new = self.ledger()
            new["run"] = self.doc["run"]
            new["files"] = {**old.get("files", {}), **new["files"]}
            new["artifact_sources"] = {
                **old.get("artifact_sources", {}),
                **new["artifact_sources"],
            }
            choices = (
                before["choices"]
                if self.doc.get("scope") in ("ui", "launcher-web", "launcher-native")
                else self.choices
            )
            self.doc["local_commit"] = {
                "before": before,
                "after": {"choices": choices, "ledger": new},
            }
        self.doc["phase"] = "finalizing"
        self.save()
        self.write_local_state(reverse=False)
        self.doc["phase"] = "complete"
        self.save()

    def validate_local_state(self):
        transaction = self.doc["local_commit"]
        current = self.local_state()
        # Validate both records before writing either. Do not overwrite later edits.
        for name, value in current.items():
            if value not in (transaction["before"][name], transaction["after"][name]):
                raise Refused(
                    "Saved "
                    + name
                    + " changed outside this run; refusing to overwrite it"
                )

    def write_local_state(self, reverse=False):
        self.validate_local_state()
        transaction = self.doc["local_commit"]
        wanted = transaction["before" if reverse else "after"]
        for name, value in wanted.items():
            path = self.state_dir / (self.device + "-" + name + ".json")
            if read_json(path) not in (
                transaction["before"][name],
                transaction["after"][name],
            ):
                raise Refused("Saved " + name + " changed concurrently")
            # Always fsync, even when a prior replace succeeded but its fsync failed.
            if value is None:
                atomic_remove(path)
            else:
                atomic_json(path, value)

    def restore_local_state(self):
        if "local_commit" in self.doc:
            self.write_local_state(reverse=True)

    def ledger(self):
        files = {}
        for row in self.doc["actions"]:
            if row["phase"] != "applied":
                continue
            a = Action(**row["action"])
            if a.kind == "package":
                files.update(a.after)
            elif a.kind in ("file", "cache"):
                files[a.options["path"]] = a.after
        sources = {
            p: component_revision(artifact_group(p)) for p in files if artifact_group(p)
        }
        return dict(
            source_revision=self.doc["source_revision"],
            files=files,
            artifact_sources=sources,
        )
