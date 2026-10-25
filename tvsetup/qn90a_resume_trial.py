"""Bounded QN90A first-screen preference trial using the setup engine.

`start` applies exactly two allowlisted settings and leaves a pending journal.
`inspect` reads current values; `rollback` restores only from the exact trial state.
This tool never reboots the TV, launches apps, or finalizes saved deployment choices.
"""

import argparse
import json

from .common import STATE, Refused, lock, read_json, safe_id
from .engine import Engine, pending, run_id
from .operations import Driver
from .planner import Action, STOCK_HOME, HUB
from .config import resolve
from .registry import has_identity, reviewed_identity
from .site import binding, configured_profile, load_site
from .transport import Transport

SCOPE = "qn90a-firstscreen-resume-trial"


def trial_choices():
    return resolve(
        "qn90a",
        overrides={
            "components": [],
            "exclude": [],
            "keep": [],
            "remove": [],
            "artifacts": {},
        },
    )


FIRSTSCREEN = "db/first_screen/type"
AUTOSTART = "db/menu/smart_hub/ontvsetting/auto_start"
BASELINE = {FIRSTSCREEN: STOCK_HOME, AUTOSTART: 0}
DESIRED = {FIRSTSCREEN: HUB, AUTOSTART: 1}


class TrialDriver(Driver):
    """Map only the two QN90A trial settings onto the restricted native helper mode."""

    def control_call(self, mode, key="", before="", after="", root=False):
        if mode == "setting" and key in (FIRSTSCREEN, AUTOSTART):
            if self.profile.get("id") != "qn90a":
                raise Refused("First-screen trial is QN90A-only")
            return super().control_call(
                "qn90a-firstscreen", key, before, after, root=root
            )
        if mode == "qn90a-firstscreen":
            raise Refused(
                "Use setting actions; direct first-screen helper calls are not exposed"
            )
        return super().control_call(mode, key, before, after, root=root)


def validate_doc(doc, identity, profile, target_binding):
    if (
        not isinstance(doc, dict)
        or doc.get("schema") != 2
        or doc.get("scope") != SCOPE
        or doc.get("run") != identity
        or doc.get("device") != "qn90a"
        or doc.get("target_binding") != target_binding
        or doc.get("source_revision") is None
    ):
        raise Refused("First-screen trial journal identity/scope mismatch")
    actions = doc.get("actions")
    if not isinstance(actions, list) or len(actions) != 2:
        raise Refused("Trial journal does not contain exactly two setting actions")
    expected = {(FIRSTSCREEN, STOCK_HOME, HUB), (AUTOSTART, 0, 1)}
    actual = set()
    for row in actions:
        try:
            a = row["action"]
            actual.add((a["options"]["key"], a["before"], a["after"]))
            if a["kind"] != "setting" or a["component"] != "resume-firstscreen":
                raise ValueError()
        except (KeyError, TypeError, ValueError):
            raise Refused("Malformed action in first-screen trial journal")
    if actual != expected:
        raise Refused("Trial journal action set differs from the exact allowlist")
    if profile.get("id") != "qn90a" or not has_identity(profile, "qn90a"):
        raise Refused("Configured QN90A identity/firmware changed")
    return doc


def actions_from_state(state):
    if state.get("device") != "qn90a":
        raise Refused("Readback is not from QN90A")
    settings = state.get("settings", {})
    for key, expected in BASELINE.items():
        if settings.get(key) != expected:
            raise Refused(
                "Unexpected baseline for "
                + key
                + "; refusing to widen the trial or rollback"
            )
    return [
        Action(
            "001-firstscreen-type",
            "resume-firstscreen",
            "setting",
            STOCK_HOME,
            HUB,
            {"key": FIRSTSCREEN},
        ),
        Action(
            "002-firstscreen-autostart",
            "resume-firstscreen",
            "setting",
            0,
            1,
            {"key": AUTOSTART},
        ),
    ]


def _context(identity, site, transport_factory=None):
    transport_factory = transport_factory or Transport
    safe_id(identity)
    profile = configured_profile("qn90a", site)
    target_binding = binding(site, "qn90a")
    folder = STATE / "runs" / identity
    doc = read_json(folder / "journal.json")
    validate_doc(doc, identity, profile, target_binding)
    tv = transport_factory(profile, folder / "transport")
    choices = trial_choices()
    driver = TrialDriver(tv, profile, choices, folder)
    engine = Engine(
        driver,
        folder,
        "qn90a",
        choices,
        target_binding=target_binding,
        state_dir=None,
        scope=SCOPE,
    )
    engine.doc = doc
    return folder, doc, tv, driver, engine, profile, target_binding


def _prepare_locked(site, transport_factory):
    profile = configured_profile("qn90a", site)
    if not has_identity(profile, "qn90a"):
        pinned = reviewed_identity("qn90a")
        raise Refused(
            "This trial is pinned to " + pinned["model"] + " / " + pinned["firmware"]
        )
    if pending(STATE, "qn90a"):
        raise Refused("Resolve the pending QN90A setup/trial operation first")
    identity = run_id()
    folder = STATE / "runs" / identity
    tv = transport_factory(profile, folder / "transport")
    state = tv.snapshot(privileged=True)
    actions = actions_from_state(state)
    choices = trial_choices()
    driver = TrialDriver(tv, profile, choices, folder)
    engine = Engine(
        driver,
        folder,
        "qn90a",
        choices,
        target_binding=binding(site, "qn90a"),
        state_dir=None,
        scope=SCOPE,
    )
    plan = type("TrialPlan", (), {"actions": actions})()
    engine.prepare(plan, state)
    return {"run": identity, "phase": engine.doc["phase"], "settings": BASELINE.copy()}


def start(site, transport_factory=None):
    transport_factory = transport_factory or Transport
    with lock(STATE / "qn90a.lock"):
        prepared = _prepare_locked(site, transport_factory)
        return _apply_locked(prepared["run"], site, transport_factory)


def prepare(site, transport_factory=None):
    transport_factory = transport_factory or Transport
    with lock(STATE / "qn90a.lock"):
        return _prepare_locked(site, transport_factory)


def _apply_locked(identity, site, transport_factory):
    if any(name != identity for name, _ in pending(STATE, "qn90a")):
        raise Refused("Another pending QN90A operation must be reconciled first")
    folder, doc, tv, driver, engine, profile, target_binding = _context(
        identity, site, transport_factory
    )
    if doc.get("phase") != "prepared":
        raise Refused("Only a prepared first-screen trial can be applied")
    state = tv.snapshot(privileged=True)
    for key, expected in BASELINE.items():
        if state.get("settings", {}).get(key) != expected:
            raise Refused("Baseline changed before apply for " + key)
    engine.apply()
    # Intentionally remain nonterminal/pending. Never call Engine.finalize().
    return {"run": identity, "phase": engine.doc["phase"], "settings": DESIRED.copy()}


def apply(identity, site, transport_factory=None):
    transport_factory = transport_factory or Transport
    with lock(STATE / "qn90a.lock"):
        return _apply_locked(identity, site, transport_factory)


def inspect(identity, site, transport_factory=None):
    transport_factory = transport_factory or Transport
    with lock(STATE / "qn90a.lock"):
        folder, doc, tv, driver, engine, profile, target_binding = _context(
            identity, site, transport_factory
        )
        state = tv.snapshot(privileged=True)
        current = {key: state.get("settings", {}).get(key) for key in DESIRED}
        return {
            "run": identity,
            "phase": doc["phase"],
            "current": current,
            "matches_trial": current == DESIRED,
            "pending": doc["phase"] not in ("rolled-back", "complete"),
        }


def rollback(identity, site, transport_factory=None):
    transport_factory = transport_factory or Transport
    with lock(STATE / "qn90a.lock"):
        if any(name != identity for name, _ in pending(STATE, "qn90a")):
            raise Refused("Another pending QN90A operation must be reconciled first")
        folder, doc, tv, driver, engine, profile, target_binding = _context(
            identity, site, transport_factory
        )
        if doc.get("phase") not in (
            "prepared",
            "configuration-applied",
            "partial",
            "rollback-partial",
            "rolling-back",
        ):
            raise Refused("Trial is not in a rollback-eligible active phase")
        state = tv.snapshot(privileged=True)
        # Refuse before invoking Engine if either key drifted from the trial target.
        for key, expected in DESIRED.items():
            current = state.get("settings", {}).get(key)
            if current not in (BASELINE[key], expected):
                raise Refused(
                    "Current setting is outside the exact baseline/trial pair for "
                    + key
                    + "; preserve journal and inspect"
                )
        result = engine.rollback()
        return {
            "run": identity,
            "phase": engine.doc["phase"],
            "manual_recovery": result,
        }


def accept(identity, site, transport_factory=None):
    """Close a verified successful trial without committing setup choices."""
    transport_factory = transport_factory or Transport
    with lock(STATE / "qn90a.lock"):
        if any(name != identity for name, _ in pending(STATE, "qn90a")):
            raise Refused("Another pending QN90A operation must be reconciled first")
        folder, doc, tv, driver, engine, profile, target_binding = _context(
            identity, site, transport_factory
        )
        if doc.get("phase") != "configuration-applied":
            raise Refused("Only a fully applied trial can be accepted")
        engine.check_resume()  # validates frozen source revision and active phase
        if any(row.get("phase") != "applied" for row in doc.get("actions", [])):
            raise Refused("Trial has uncertain, partial, or unsubmitted actions")
        state = tv.snapshot(privileged=True)
        values = {key: state.get("settings", {}).get(key) for key in DESIRED}
        if values != DESIRED:
            raise Refused(
                "Exact trial settings/readback do not match; preserve the pending journal"
            )
        doc["accepted_readback"] = {
            "settings": values,
            "boot": state.get("boot"),
            "uptime": state.get("uptime"),
        }
        doc["accepted"] = True
        doc["phase"] = "complete"
        engine.save()
        return {
            "run": identity,
            "phase": doc["phase"],
            "settings": values,
            "saved_choices_ledger_changed": False,
        }


def main(argv=None):
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="command", required=True)
    sub.add_parser("start")
    sub.add_parser("prepare")
    command = sub.add_parser("apply")
    command.add_argument("--run", required=True)
    for name in ("inspect", "rollback", "accept"):
        command = sub.add_parser(name)
        command.add_argument("--run", required=True)
    args = parser.parse_args(argv)
    site = load_site()
    if args.command == "start":
        result = start(site)
    elif args.command == "prepare":
        result = prepare(site)
    elif args.command == "apply":
        result = apply(args.run, site)
    elif args.command == "inspect":
        result = inspect(args.run, site)
    elif args.command == "rollback":
        result = rollback(args.run, site)
    else:
        result = accept(args.run, site)
    print(json.dumps(result, sort_keys=True), flush=True)


if __name__ == "__main__":
    main()
