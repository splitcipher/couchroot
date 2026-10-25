"""Explicit QN90A 2310.0 setup/cleanup + interrupted-upgrade trial contract.

A sanctioned, caller-authorized path to exercise full setup/cleanup and upgrade
recovery on the reviewed QN90A firmware WITHOUT promoting it into the ordinary
setup registry. The ordinary registry deliberately refuses 2310.0 (see
``qn90a_firmware_trial`` and ``tests/qn90a_firmware_trial_test``); this module never
changes that, is never an automatic fallback after a firmware refusal, and the
caller owns authorization, physical identity, locking, journaling and recovery.

The pin, binary digests and ``/etc/prd_info.ini`` guard are reused verbatim from
``qn90a_firmware_trial`` so every transport call is gated by the exact 2310.0
contract. Signed setup/cleanup packages come from the offline producer named by
``BUILDER`` (analogue of ``scripts/prepare_qn90a_d2tv_trial.py``); this module pins
its digest and refuses if it is absent or changed.
"""

import argparse
import json
from pathlib import Path

from .common import STATE, REPO, Refused, atomic_json, lock, read_json, safe_id, sha
from .engine import Engine, pending, run_id
from . import qn90a_firmware_trial as firmware_trial

SCOPE = "qn90a-2310-setup-cleanup-trial"
FIRMWARE = firmware_trial.FIRMWARE  # the reviewed QN90A firmware, from the trial pin
# Cleanup is limited to the live-re-reviewed allowlist on 2310.0: of the ten apps
# in the historical 2301.1 map, only Xbox remains installed (read-only evidence
# capture, 2026-10-25). Certification must not silently widen this.
CLEANUP = {"GHI3a0zMSx": "4.55.698"}  # Xbox
# Offline signed-package producer for the 2310.0 setup/cleanup packages. It is
# produced from reviewed source during certification (needs the device baseline);
# it is intentionally NOT part of this module. The trial pins its digest.
BUILDER = "scripts/prepare_qn90a_2310_setup_trial.py"


def contract(site):
    """Pinned 2310.0 trial profile; refuses anything but the QN90A at 2310.0.

    Delegates to the firmware trial, so this inherits every refusal (wrong device,
    model, firmware, trailing newline, BASELINE drift) and the ``/etc/prd_info.ini``
    plus binary-digest guards. Because ``firmware_trial.safety_profile`` asserts the
    ordinary registry profile is unchanged, this path cannot operate if someone has
    already mutated the private profile — the quarantine stays enforced.
    """
    return firmware_trial.configured_trial(site)


def _builder_digest():
    path = REPO / BUILDER
    if not path.is_file():
        raise Refused(
            "2310.0 setup/cleanup package producer is absent; certification must "
            "build " + BUILDER + " from reviewed source before this trial can run"
        )
    return sha(path.read_bytes())


def context(identity, site, prepared=None):
    """Pin the 2310.0 contract and bind an engine to this run's journal.

    Mirrors ``qn90a_source_trial.context``: validates journal identity, pins the
    offline builder digest, and refuses a mismatch. The engine/driver wiring and
    package classification are reached only on the prepared device path.
    """
    from .site import binding
    from .operations import Driver
    from .planner import plan, order_actions

    safe_id(identity)
    profile = contract(site)  # refuses unless QN90A @ 2310.0, pins intact
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
            raise Refused("2310.0 setup-trial journal identity mismatch")
        if sha((folder / "packages.json").read_bytes()) != doc.get("packages_sha256"):
            raise Refused("Prepared 2310.0 package manifest changed")
        if _builder_digest() != doc.get("builder_sha256"):
            raise Refused("Offline package producer changed since trial preparation")
        prepared = read_json(folder / "packages.json")
    # Device path: scope the plan to the setup components plus the Xbox-only
    # cleanup, under the pinned qualification transport. Structurally identical to
    # qn90a_source_trial; exercised only on the live 2310.0 TV after the pending
    # pilot is reconciled and BUILDER exists.
    transport = firmware_trial.QualificationTransport(profile, folder / "evidence")
    driver = Driver(transport, profile, _choices(prepared), folder)
    engine = Engine(
        driver,
        folder,
        "qn90a",
        _choices(prepared),
        target_binding=binding(site, "qn90a"),
        state_dir=None,
        scope=SCOPE,
    )
    engine.doc = doc
    actions = order_actions(plan(driver.snapshot(), _choices(prepared), profile))
    return folder, driver, engine, actions


def _choices(prepared):
    from .config import resolve

    return resolve(
        "qn90a",
        overrides={
            "remove": list(CLEANUP),
            "artifacts": prepared.get("artifacts", {}) if prepared else {},
        },
    )


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    prepare = sub.add_parser("prepare")
    prepare.add_argument("--manifest", type=Path, required=True)
    for command in ("apply", "inspect", "rollback", "accept"):
        sub.add_parser(command).add_argument("--run", required=True)
    args = parser.parse_args(argv)
    from .site import load_site

    site = load_site()
    with lock(STATE / "qn90a.lock"):
        identity = run_id() if args.command == "prepare" else args.run
        if any(name != identity for name, _ in pending(STATE, "qn90a")):
            raise Refused("Another QN90A run is pending; reconcile it first")
        if args.command == "prepare":
            _builder_digest()  # refuse early if the producer is absent
            folder, driver, engine, actions = context(
                identity, site, read_json(args.manifest)
            )
            raise Refused(
                "2310.0 setup/cleanup preparation is not yet certified to run: build "
                "and review " + BUILDER + ", reconcile the pending pilot, then enable "
                "the prepared device path"
            )
        folder, driver, engine, actions = context(identity, site)
        if args.command == "apply":
            if engine.doc["phase"] != "prepared":
                raise Refused("Only a prepared trial can submit an installation")
            engine.apply()
        elif args.command == "rollback":
            engine.rollback()
        elif args.command == "accept":
            engine.check_resume()
            if engine.doc["phase"] != "configuration-applied":
                raise Refused("Only an applied and verified setup may be accepted")
            engine.doc["phase"] = "complete"
            engine.save()
        state = driver.snapshot()
        atomic_json(folder / ("latest-" + args.command + ".json"), state)
        print(json.dumps({"run": identity, "phase": engine.doc["phase"]}))


if __name__ == "__main__":
    main()
