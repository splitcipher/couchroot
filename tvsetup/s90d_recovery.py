"""Checkpoint/recover one future S90D helper or cache trial; never launch a trial.

`plan` consumes saved observations offline. All device commands require --live;
checkpoint and rollback also require --yes. Importing this module is offline.
"""

import argparse
from dataclasses import asdict
import json
from pathlib import Path, PurePosixPath
import re

from .common import STATE, Refused, lock, read_json, safe_id
from .engine import Engine, pending, run_id
from .operations import Driver
from .planner import (
    Action,
    Plan,
    CACHE_PATCHED,
    CACHE_STOCK,
    CACHE_TABLE,
    KNOWN_HELPERS,
    SPLASH_NATIVE,
    SPLASH_RESOURCE,
    source_revision,
)
from .registry import reviewed_identity
from .site import binding, configured_profile, load_site
from .transport import CACHE, SAVER, Q, Transport, hash_guard

SCOPE = "s90d-boot-recovery"
HELPER = SAVER + "/Boot.dll"
# Historical composite and boot-tested splash helper; not additions to the
# installation allowlist, and never selected as replacement artifacts.
HELPERS = KNOWN_HELPERS | {
    "879e602d64887b3d706efeff916b2ecfd6c9a7d431bfe6078feb6613c377ef1d",
    "e10a33fc26a03eea25f2ce0fe63da6d29ed49633068e9cd470ebc59d710b39f7",
}
PINS = {
    CACHE: CACHE_PATCHED,
    CACHE + ".table": CACHE_TABLE,
    "/usr/bin/boot_splashscreen": SPLASH_NATIVE,
    "/usr/apps/com.samsung.tv.csfs/shared/res/homeloading.edj": SPLASH_RESOURCE,
    SAVER + "/oneservice.original": CACHE_STOCK,
}
MARKERS = (
    SAVER + "/enabled",
    "/opt/minimal-splash/enabled",
    "/opt/minimal-telemetry/enabled",
    "/opt/usr/home/owner/apps_rw/MiniTelemetry/data/enabled",
)
PATHS = (
    HELPER,
    *PINS,
    SAVER + "/Boot.runtimeconfig.json",
    SAVER + "/Boot.deps.json",
    SAVER + "/libgl-demo-app.so",
    "/opt/etc/parseinfo.sh",
    *MARKERS,
)


def digest(value):
    if not isinstance(value, str) or not re.fullmatch("[a-f0-9]{64}", value):
        raise Refused("Expected a SHA256 digest")
    return value


def parents(path):
    return "".join(
        "test ! -L " + Q(str(p)) + "\n"
        for p in reversed(PurePosixPath(path).parents)
        if str(p) != "/"
    )


def metadata_guard(path, metadata):
    return (
        f'test "$(stat -c %u:%g:%a:%h {Q(path)})" = {Q(metadata[0])}\n'
        f'test "$(chsmack {Q(path)} | cut -d " " -f 2-)" = {Q(metadata[1])}\n'
    )


def validate_state(state):
    if (
        not isinstance(state, dict)
        or state.get("device") != "s90d"
        or state.get("firmware") != reviewed_identity("s90d")["firmware"]
    ):
        raise Refused("Expected an S90D firmware-pinned recovery snapshot")
    files, meta = state.get("files", {}), state.get("metadata", {})
    if (
        not isinstance(files, dict)
        or not isinstance(meta, dict)
        or set(files) != set(PATHS)
        or set(meta) != set(PATHS)
    ):
        raise Refused(
            "Incomplete recovery snapshot (including marker absence and metadata)"
        )
    for path, value in files.items():
        if value is None and path in MARKERS:
            if meta[path] is not None:
                raise Refused("Absent marker has metadata")
            continue
        digest(value)
        row = meta[path]
        if (
            not isinstance(row, list)
            or len(row) != 2
            or not isinstance(row[0], str)
            or not re.fullmatch(r"\d+:\d+:[0-7]{3,4}:1", row[0])
            or not isinstance(row[1], str)
            or not row[1]
            or "\n" in row[1]
        ):
            raise Refused("Invalid file metadata or non-exclusive inode: " + path)
    return state


def proposal(state, kind, trial_hash):
    validate_state(state)
    digest(trial_hash)
    if state["files"][HELPER] not in HELPERS:
        raise Refused(
            "Unreviewed composite helper; reconcile evidence before checkpointing"
        )
    if any(state["files"][p] != h for p, h in PINS.items()):
        raise Refused("Cache/table/original-cache or splash prerequisites differ")
    if kind not in ("helper", "cache"):
        raise Refused("Expected helper or cache trial")
    path = HELPER if kind == "helper" else CACHE
    if trial_hash == state["files"][path]:
        raise Refused("Trial must differ from baseline")
    action = Action(
        "001-boot-trial",
        "boot-recovery",
        "file" if kind == "helper" else "cache",
        state["files"][path],
        trial_hash,
        {"path": path},
    )
    return Plan("s90d", actions=[action])


class RecoveryDriver(Driver):
    def __init__(self, tv, target, folder, baseline=None, action=None):
        super().__init__(tv, target, {}, folder)
        self.baseline, self.action = baseline, action

    def snapshot(self):
        script = "set -eu\n"
        for i, path in enumerate(PATHS):
            script += parents(path) + f'test ! -L {Q(path)}\nprintf "RECOVERY_{i}\\n"\n'
            script += (
                f"if test -f {Q(path)}; then\n"
                f'sha256sum {Q(path)} | cut -d " " -f 1\n'
                f"stat -c %u:%g:%a:%h {Q(path)}\n"
                f'chsmack {Q(path)} | cut -d " " -f 2-\n'
                f"else test ! -e {Q(path)}; echo ABSENT; fi\n"
            )
        output = self.tv.root(script, namespace=True)
        state = dict(
            device="s90d",
            firmware=reviewed_identity("s90d")["firmware"],
            files={},
            metadata={},
        )
        for i, path in enumerate(PATHS):
            match = re.search(
                r"(?:^|\n)RECOVERY_" + str(i) + r"\n(.*?)(?=\nRECOVERY_|\Z)",
                output,
                re.S,
            )
            if not match:
                raise Refused("Incomplete recovery observation")
            lines = match[1].strip().splitlines()
            if lines == ["ABSENT"]:
                state["files"][path] = state["metadata"][path] = None
            elif len(lines) == 3:
                state["files"][path], state["metadata"][path] = lines[0], lines[1:]
            else:
                raise Refused("Malformed recovery observation")
        validate_state(state)
        if self.baseline is not None:
            self.check(state)
        return state

    def check(self, state):
        validate_state(state)
        for path in PATHS:
            allowed = (
                (self.action.before, self.action.after)
                if path == self.action.options["path"]
                else (self.baseline["files"][path],)
            )
            if (
                state["files"][path] not in allowed
                or state["metadata"][path] != self.baseline["metadata"][path]
            ):
                raise Refused("Recovery state drift: " + path)

    def guards(self, state):
        self.check(state)
        script = "set -eu\n"
        for path in PATHS:
            script += parents(path) + hash_guard(path, state["files"][path])
            if state["files"][path] is not None:
                script += metadata_guard(path, state["metadata"][path])
        return script

    def prepare(self, action):
        return {}  # No payload build, signing, upload or trial execution.

    def execute(self, *args):
        raise Refused("Recovery checkpoints cannot execute trials")

    def backup(self, action, info, state):
        where = self.remote + "/" + action.id + "-first"
        backup = where + "/original"
        script = self.guards(state) + parents(backup)
        script += f"test ! -e {Q(where)}\nmkdir -p {Q(self.remote)}\n"
        script += f"chmod 700 /opt/minimal-tv-setup {Q(self.remote)}\nmkdir -m 700 {Q(where)}\n"
        script += f"cp --preserve=all {Q(action.options['path'])} {Q(backup)}\n"
        script += hash_guard(backup, action.before) + metadata_guard(
            backup, state["metadata"][action.options["path"]]
        )
        self.tv.root(script, namespace=True)
        return dict(
            backup=backup,
            backup_sha256=action.before,
            backup_files={backup: action.before},
        )

    def rollback(self, action, info, state):
        # Recheck the entire checkpoint in the same namespace invocation as the
        # inverse, including unchanged markers and the other trial candidate.
        script = self.guards(state)
        path = action.options["path"]
        if state["files"][path] != action.before:
            backup = info["backup"]
            temporary = (
                path + ".tv-setup-" + self.folder.name + "-" + action.id + ".restore"
            )
            from .staging import clear_verified_stage

            script += parents(backup) + hash_guard(backup, action.before)
            script += metadata_guard(backup, self.baseline["metadata"][path])
            script += clear_verified_stage(temporary, action.before)
            script += f"cp --preserve=all {Q(backup)} {Q(temporary)}\n"
            script += hash_guard(temporary, action.before) + metadata_guard(
                temporary, self.baseline["metadata"][path]
            )
            script += f"mv {Q(temporary)} {Q(path)}\n"
        if path == CACHE:
            script += "systemctl daemon-reload\n"
        self.tv.root(script, namespace=True)


def arm(engine, state, plan):
    """Durably save inverse before any separately authorized trial can run."""
    engine.prepare(plan, state)
    row = engine.doc["actions"][0]
    try:
        row["phase"] = "backing-up"
        engine.save()
        row["info"] = engine.driver.backup(plan.actions[0], row["info"], state)
        if engine.driver.snapshot() != state:
            raise Refused("Checkpoint changed during backup")
    except BaseException:
        # Only backup files were written; no trial was admitted. Retain evidence
        # but do not strand an unusable pending run after a failed checkpoint.
        engine.doc["phase"] = "preparation-failed"
        engine.save()
        raise
    # Treat a future external trial like an uncertain submission. Shared Engine
    # rollback accepts only before/after and journals interrupted inverses.
    row["phase"] = "uncertain"
    engine.doc["phase"] = "partial"
    engine.doc["checkpoint_ready"] = True
    engine.save()


def load_checkpoint(folder, target):
    doc = read_json(folder / "journal.json")
    if (
        not doc
        or doc.get("schema") != 2
        or doc.get("scope") != SCOPE
        or doc.get("device") != "s90d"
        or doc.get("run") != folder.name
        or doc.get("target_binding") != target
        or doc.get("source_revision") != source_revision()
        or not doc.get("checkpoint_ready")
        or len(doc.get("actions", [])) != 1
        or doc.get("phase")
        not in ("partial", "rolling-back", "rollback-partial", "rolled-back")
    ):
        raise Refused("Incomplete, changed-source or mismatched recovery checkpoint")
    row = doc["actions"][0]
    if row.get("phase") not in ("uncertain", "rolling-back", "rolled-back"):
        raise Refused("Unexpected checkpoint action phase")
    action = Action(**row["action"])
    kind = "helper" if action.options.get("path") == HELPER else "cache"
    expected = proposal(doc["before"], kind, action.after).actions[0]
    backup = (
        "/opt/minimal-tv-setup/" + folder.name + "/" + action.id + "-first/original"
    )
    if (
        asdict(expected) != row["action"]
        or row["info"].get("backup") != backup
        or row["info"].get("backup_sha256") != action.before
        or row["info"].get("backup_files") != {backup: action.before}
    ):
        raise Refused("Checkpoint action or backup differs from recovery allowlist")
    return doc, action


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    plan = sub.add_parser("plan")
    plan.add_argument("--snapshot", required=True, type=Path)
    checkpoint = sub.add_parser("checkpoint")
    for p in (plan, checkpoint):
        p.add_argument("--kind", required=True, choices=("helper", "cache"))
        p.add_argument("--trial-sha256", required=True)
    sub.add_parser("inspect")
    for name in ("rollback", "verify"):
        sub.add_parser(name).add_argument("--run", required=True)
    sub.add_parser("status").add_argument("--run", required=True)
    cancel = sub.add_parser("cancel-incomplete")
    cancel.add_argument("--run", required=True)
    cancel.add_argument("--yes", action="store_true")
    for name, p in sub.choices.items():
        if name not in ("plan", "status", "cancel-incomplete"):
            p.add_argument("--site", required=True, type=Path)
            p.add_argument("--live", action="store_true")
        if name in ("checkpoint", "rollback"):
            p.add_argument("--yes", action="store_true")
    args = parser.parse_args(argv)
    try:
        if args.command == "plan":
            result = proposal(
                read_json(args.snapshot), args.kind, args.trial_sha256
            ).json()
            print(
                json.dumps(
                    dict(offline=True, recovery_ready=False, plan=result), indent=2
                )
            )
            return 0
        if args.command == "status":
            doc = read_json(STATE / "runs" / safe_id(args.run) / "journal.json")
            if not doc or doc.get("scope") != SCOPE:
                raise Refused("Not a boot recovery checkpoint")
            print(
                json.dumps(
                    {k: doc.get(k) for k in ("run", "phase", "checkpoint_ready")},
                    indent=2,
                )
            )
            return 0
        if args.command == "cancel-incomplete":
            if not args.yes:
                raise Refused(
                    "Cancelling an incomplete local checkpoint requires --yes"
                )
            with lock(STATE / "s90d.lock"):
                folder = STATE / "runs" / safe_id(args.run)
                doc = read_json(folder / "journal.json")
                if (
                    not doc
                    or doc.get("scope") != SCOPE
                    or doc.get("device") != "s90d"
                    or doc.get("run") != folder.name
                    or doc.get("checkpoint_ready")
                    or doc.get("phase")
                    not in ("preparing", "prepared", "preparation-failed")
                    or any(
                        r.get("phase") not in ("planned", "prepared", "backing-up")
                        for r in doc.get("actions", [])
                    )
                ):
                    raise Refused(
                        "Only an incomplete, never-armed checkpoint can be cancelled offline"
                    )
                from .common import atomic_json

                doc["phase"] = "cancelled"
                atomic_json(folder / "journal.json", doc)
            print(
                "Incomplete checkpoint cancelled locally; retained remote backups were not accessed."
            )
            return 0
        if not args.live or (
            args.command in ("checkpoint", "rollback") and not args.yes
        ):
            raise Refused(
                "Device access requires --live; checkpoint/rollback also require --yes"
            )
        site = load_site(args.site)
        target = binding(site, "s90d")
        p = configured_profile("s90d", site)
        with lock(STATE / "s90d.lock"):
            identity = safe_id(args.run) if hasattr(args, "run") else run_id()
            folder = STATE / "runs" / identity
            if args.command in ("rollback", "verify"):
                doc, action = load_checkpoint(folder, target)
                driver = RecoveryDriver(None, p, folder, doc["before"], action)
                engine = Engine(
                    driver, folder, "s90d", {}, target_binding=target, scope=SCOPE
                )
                engine.doc = doc
                driver.tv = Transport(p, folder / "evidence")
                if args.command == "rollback":
                    engine.rollback()
                state = driver.snapshot()
                if state != doc["before"]:
                    raise Refused("Trial still present; baseline not restored")
                print(
                    json.dumps(
                        dict(
                            run=identity,
                            phase=engine.doc["phase"],
                            baseline_restored=True,
                            hardware_boot_verified=False,
                        )
                    )
                )
                return 0
            if args.command == "checkpoint" and pending(STATE, "s90d"):
                raise Refused("Resolve pending S90D setup/recovery run first")
            driver = RecoveryDriver(Transport(p, folder / "evidence"), p, folder)
            state = driver.snapshot()
            if args.command == "inspect":
                print(json.dumps(state, indent=2))
                return 0
            plan = proposal(state, args.kind, args.trial_sha256)
            driver.baseline, driver.action = state, plan.actions[0]
            engine = Engine(
                driver, folder, "s90d", {}, target_binding=target, scope=SCOPE
            )
            arm(engine, state, plan)
            print(
                json.dumps(
                    dict(run=identity, checkpoint_ready=True, trial_applied=False)
                )
            )
            return 0
    except (Refused, OSError, ValueError, KeyError, TypeError) as error:
        print("Refused: " + str(error))
        return 1


if __name__ == "__main__":
    raise SystemExit(main())
