"""Explain existing cleanup eligibility without expanding removal policy."""

from .planner import cleanup_eligibility

LIMITS = (
    "Disabled registration does not prove zero processes or zero telemetry.",
    "No matching observed process does not prove disabled boot or absence of background activity.",
    "Declared dependencies do not capture every dynamic dependency; removal needs separate authorization and Store/signed-package recovery.",
)


def explain(profile, state, inspector=None):
    """Project existing inventory; optional inspector data stays labelled recorded.

    No process-name heuristic establishes package ownership. Only an exact app-ID
    name match is reported as a match, never as complete process enumeration.
    """
    inspector = inspector if isinstance(inspector, dict) else {}
    apps = inspector.get("apps", {})
    processes = inspector.get("processes", {})
    if not isinstance(apps, dict):
        apps = {}
    if not isinstance(processes, dict):
        processes = {}
    app_rows = apps.get("rows", []) if apps.get("status") in ("ok", "partial") else []
    process_rows = (
        processes.get("rows", [])
        if processes.get("status") in ("ok", "partial")
        else []
    )
    if not isinstance(app_rows, list):
        app_rows = []
    if not isinstance(process_rows, list):
        process_rows = []
    result = []
    for pkg, entry in profile["cleanup"].items():
        status, reason = cleanup_eligibility(profile, state, pkg)
        rows = [
            r
            for r in app_rows
            if isinstance(r, dict)
            and r.get("package") == pkg
            and r.get("id") == entry["app"]
        ]
        facts = {
            key: None
            for key in ("package_disabled", "app_disabled", "on_boot", "auto_restart")
        }
        if len(rows) == 1:
            facts = {
                key: rows[0].get(key) if type(rows[0].get(key)) is bool else None
                for key in facts
            }
        matched = any(
            isinstance(r, dict) and r.get("name") == entry["app"] for r in process_rows
        )
        result.append(
            dict(
                package=pkg,
                name=entry["name"],
                profile_firmware=profile["firmware"],
                provenance="docs/lab/devices/" + profile["id"] + "/app-cleanup.md",
                reviewed_version=entry["reviewed_version"],
                eligibility=status,
                refusal=reason,
                explanation="Previously reviewed optional "
                + entry["name"]
                + " frontend/package; no core-service removal is implied.",
                recorded_registration=facts,
                process_evidence="matching_app_id_observed"
                if matched
                else "not_established",
                evidence_basis="supplied_inspector_record"
                if inspector
                else "setup_inventory_only",
                limitations=list(LIMITS),
            )
        )
    return result
