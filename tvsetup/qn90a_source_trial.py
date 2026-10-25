"""Manifest-only QN90A source-role trial, using the shared setup engine.

Packages must come from prepare_qn90a_d2tv_trial.py. This command never edits
the WAS database, launches an app, or requests a power transition.
"""

import argparse
import json
from pathlib import Path
import shutil

from .artifacts import verify_package
from .common import STATE, REPO, Refused, atomic_json, lock, read_json, safe_id, sha
from .config import resolve
from .engine import Engine, pending, run_id
from .operations import Driver, observed
from .planner import Action, managed_package_ok
from .registry import has_identity
from .site import binding, configured_profile, load_site
from .transport import Transport, Q

SCOPE = "qn90a-source-role-trial"
PREFIX = "/opt/usr/apps/MiniHub001/res/wgt/"
CONFIG = PREFIX + "config.xml"
KEY = "http://samsung.com/tv/metadata/D2TV"


def material(manifest, profile):
    """Revalidate artifacts against signatures and the exact captured baseline."""
    from scripts.prepare_qn90a_d2tv_trial import (
        verify_base,
        verify_variant,
        transform_config,
    )

    if (
        manifest.get("scope") != "qn90a-hub-d2tv-manifest-only-trial"
        or manifest.get("device") != "qn90a"
        or manifest.get("package") != "MiniHub001"
    ):
        raise Refused("Unexpected prepared package manifest")
    for key in ("baseline_wgt", "baseline_snapshot"):
        row = manifest[key]
        if sha(Path(row["path"]).read_bytes()) != row["sha256"]:
            raise Refused("Prepared baseline changed: " + key)
    base_path = Path(manifest["baseline_wgt"]["path"])
    base, _ = verify_base(
        base_path, profile, read_json(Path(manifest["baseline_snapshot"]["path"]))
    )
    result = {"base": {PREFIX + n: sha(b) for n, b in base.items()}}
    rows = manifest.get("artifacts", [])
    if len(rows) != 2 or {r.get("kind") for r in rows} != {"trial", "restore"}:
        raise Refused("Expected exactly trial and restoration packages")
    for row in rows:
        kind = row["kind"]
        path = Path(row["path"])
        if sha(path.read_bytes()) != row["sha256"]:
            raise Refused("Prepared signed package changed")
        version = "0.4.12" if kind == "trial" else "0.4.13"
        members = verify_variant(path, profile, base, version, kind == "trial")
        if members["config.xml"] != transform_config(
            base["config.xml"], version, kind == "trial"
        ):
            raise Refused("Manifest differs beyond the exact version/role change")
        result[kind] = {
            PREFIX + n: sha(b)
            for n, b in members.items()
            if n not in ("author-signature.xml", "signature1.xml")
        }
        result[kind + "_path"] = path
        result[kind + "_sha256"] = row["sha256"]
    result["base_path"] = base_path
    return result


def before_equivalent(value, materials):
    # Forward recovery intentionally advances version. Normalize ONLY the exact
    # preverified inverse member set; arbitrary manifest changes remain drift.
    return materials["base"] if value == materials["restore"] else value


class SourceDriver(Driver):
    def __init__(self, tv, profile, choices, folder, materials):
        super().__init__(tv, profile, choices, folder)
        self.materials = materials

    def snapshot(self):
        state = super().snapshot()
        row = self.tv.sdk(
            "sqlite3 -readonly /opt/dbspace/.webappservice.db "
            + Q(
                "SELECT id,tizen_id,pkgname,is_ispbound,is_hybrid_tv,hybrid_app "
                "FROM widgetinfo WHERE id='MiniHub001.Hub';"
            )
            + "\n"
        ).strip()
        state["hub_source_role"] = row
        state["source_slots"] = self.tv.sdk(
            "\n".join(
                "vconftool get " + Q(k)
                for k in (
                    "db/boot/last_service",
                    "db/was/isp_app_id",
                    "db/was/hybridtv_app_id",
                )
            )
            + "\n"
        ).strip()
        return state

    def find_recovery_package(self, action):
        return self.materials["base_path"]

    def verify(self, action, before, after):
        super().verify(action, before, after)
        if after["hub_source_role"] != "MiniHub001.Hub|MiniHub001.Hub|MiniHub001|1|0|":
            raise Refused(
                "Package installed but WAS has not registered the exact ISP role"
            )

    def rollback(self, action, info, state):
        current = observed(action, state)
        if before_equivalent(current, self.materials) == action.before:
            self.verify_restored(state)
            return
        if current != action.after:
            raise Refused("Package drift blocks source-role restoration")
        for path, digest in info.get("backup_files", {}).items():
            from .transport import hash_guard

            self.tv.root(hash_guard(path, digest))
        inverse = Action(
            action.id + "-inverse",
            action.component,
            "package",
            action.after,
            self.materials["restore"],
            action.options,
        )
        inverse_info = {
            "artifact": str(self.materials["restore_path"]),
            "sha256": self.materials["restore_sha256"],
        }
        super().execute(inverse, inverse_info, state)
        self.verify_restored(self.snapshot())

    def verify_restored(self, state):
        if state["hub_source_role"] != "MiniHub001.Hub|MiniHub001.Hub|MiniHub001|0|0|":
            raise Refused("Restoration package did not remove the WAS role")


class SourceEngine(Engine):
    def value(self, action, state):
        value = super().value(action, state)
        if self.doc and self.doc.get("phase") in (
            "rolling-back",
            "rollback-partial",
            "rolled-back",
        ):
            return before_equivalent(value, self.driver.materials)
        return value


def context(identity, site, prepared=None):
    safe_id(identity)
    profile = configured_profile("qn90a", site)
    if not has_identity(profile, "qn90a"):
        raise Refused("This source trial is pinned to the QN90A firmware")
    folder = STATE / "runs" / identity
    doc = read_json(folder / "journal.json")
    if prepared is None:
        if (
            not doc
            or doc.get("schema") != 2
            or doc.get("scope") != SCOPE
            or doc.get("run") != identity
            or doc.get("device") != "qn90a"
            or doc.get("target_binding") != binding(site, "qn90a")
        ):
            raise Refused("Source trial journal identity mismatch")
        prepared = read_json(folder / "packages.json")
        if sha((folder / "packages.json").read_bytes()) != doc.get("packages_sha256"):
            raise Refused("Prepared package manifest changed")
        if sha((REPO / "scripts/prepare_qn90a_d2tv_trial.py").read_bytes()) != doc.get(
            "builder_sha256"
        ):
            raise Refused("Offline package builder changed since trial preparation")
    materials = material(prepared, profile)
    choices = resolve(
        "qn90a",
        overrides={
            "components": [],
            "exclude": [],
            "keep": [],
            "remove": [],
            "artifacts": {"hub": str(materials["trial_path"])},
        },
    )
    tv = Transport(profile, folder / "evidence")
    driver = SourceDriver(tv, profile, choices, folder, materials)
    engine = SourceEngine(
        driver,
        folder,
        "qn90a",
        choices,
        target_binding=binding(site, "qn90a"),
        state_dir=None,
        scope=SCOPE,
    )
    engine.doc = doc
    if doc:
        rows = doc.get("actions", [])
        expected = Action(
            "001-source-package",
            "source-role",
            "package",
            materials["base"],
            materials["trial"],
            {"artifact": "hub", "package": "MiniHub001", "previous_version": "0.4.11"},
        )
        from dataclasses import asdict

        if len(rows) != 1 or rows[0]["action"] != asdict(expected):
            raise Refused(
                "Source trial action differs from the exact package allowlist"
            )
    return folder, driver, engine


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--manifest", type=Path, required=True)
    for command in ("apply", "inspect", "rollback", "accept"):
        sub.add_parser(command).add_argument("--run", required=True)
    args = parser.parse_args(argv)
    site = load_site()
    with lock(STATE / "qn90a.lock"):
        identity = run_id() if args.command == "prepare" else args.run
        if any(name != identity for name, _ in pending(STATE, "qn90a")):
            raise Refused("Another QN90A run is pending")
        if args.command == "prepare":
            folder, driver, engine = context(identity, site, read_json(args.manifest))
            state = driver.snapshot()
            rows = [r for r in state["packages"] if r[0] == "MiniHub001"]
            if (
                len(rows) != 1
                or not managed_package_ok(rows[0])
                or rows[0][3] != "0.4.11"
            ):
                raise Refused("Hub baseline identity/version/protection differs")
            driver.verify_restored(state)
            action = Action(
                "001-source-package",
                "source-role",
                "package",
                driver.materials["base"],
                driver.materials["trial"],
                {
                    "artifact": "hub",
                    "package": "MiniHub001",
                    "previous_version": "0.4.11",
                },
            )
            if observed(action, state) != action.before:
                raise Refused(
                    "Installed Hub bytes no longer match the prepared baseline"
                )
            shutil.copyfile(args.manifest, folder / "packages.json")
            (folder / "packages.json").chmod(0o600)
            engine.prepare(type("Plan", (), {"actions": [action]})(), state)
            engine.doc["packages_sha256"] = sha((folder / "packages.json").read_bytes())
            engine.doc["builder_sha256"] = sha(
                (REPO / "scripts/prepare_qn90a_d2tv_trial.py").read_bytes()
            )
            engine.save()
        else:
            folder, driver, engine = context(identity, site)
            if args.command == "apply":
                if engine.doc["phase"] != "prepared":
                    raise Refused(
                        "Only a prepared trial can submit an installation; inspect uncertain runs"
                    )
                engine.apply()
            elif args.command == "rollback":
                engine.rollback()
            elif args.command == "accept":
                engine.check_resume()
                if engine.doc["phase"] != "configuration-applied":
                    raise Refused(
                        "Only an applied and verified registration may be accepted"
                    )
                row = engine.doc["actions"][0]
                driver.verify(
                    Action(**row["action"]), row["before_state"], driver.snapshot()
                )
                engine.doc["phase"] = "complete"
                engine.doc["accepted_registration_only"] = True
                engine.save()
        state = driver.snapshot()
        atomic_json(folder / ("latest-" + args.command + ".json"), state)
        print(
            json.dumps(
                {
                    "run": identity,
                    "phase": engine.doc["phase"],
                    "role": state["hub_source_role"],
                    "source_slots": state["source_slots"],
                }
            )
        )


if __name__ == "__main__":
    main()
