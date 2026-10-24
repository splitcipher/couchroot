"""Offline, redacted runtime evidence. Never selects a runtime or contacts a TV."""

import re
from .common import Refused

VERSION = r"[0-9]{1,3}\.[0-9]{1,3}\.[0-9]{1,5}"
BASE = r"/usr/share/(?:dotnet|dotnet\.tizen)/(?:shared/Microsoft\.NETCore\.App|netcoreapp|netcoreapp3\.1|net6\.0)"
ACTIVE = re.compile(BASE + "/(" + VERSION + r")\Z")
LISTING = re.compile(
    r"Microsoft\.NETCore\.App (" + VERSION + r") \[(" + BASE + r")\]\Z"
)
STAGES = (
    "connect",
    "listing",
    "active_path",
    "files",
    "identity",
    "control",
    "callback",
    "cleanup",
)
OUTCOMES = ("observed", "timeout", "rejected", "unavailable", "unknown")
LIBS = ("libcoreclr.so", "System.Private.CoreLib.dll")


def report(evidence):
    """Accept a bounded capture envelope, return schema 1 without raw output.

    Exit-255 fallback is observation only and requires the exact known diagnostic;
    arbitrary failed listing commands cannot masquerade as fallback discovery.
    """
    if not isinstance(evidence, dict):
        raise Refused("Invalid deeper-inspection envelope")
    listing = evidence.get("listing", "")
    if not isinstance(listing, str) or len(listing) > 16384:
        raise Refused("Runtime listing exceeds bounded text contract")
    revision = evidence.get("source_revision")
    if not isinstance(revision, str) or not re.fullmatch("[a-f0-9]{40}", revision):
        revision = None
    choice = evidence.get("explicit_choice")
    safe_choice = choice if choice in ("3.1", "6.0") else None
    stage = evidence.get("stage")
    outcome = evidence.get("outcome")
    result = dict(
        schema=1,
        kind="offline-runtime-evidence",
        source_revision=revision,
        stage=stage if stage in STAGES else "unknown",
        outcome=outcome if outcome in OUTCOMES else "unknown",
        detected=[],
        detection_source="none",
        explicit_choice=safe_choice,
        active_path=None,
        required_files={key: None for key in LIBS},
        refusals=[],
        install_authorized=False,
        profile_modified=False,
        selected_runtime=None,
    )
    if choice is not None and safe_choice is None:
        result["refusals"].append("unsupported_explicit_choice")
    code = evidence.get("listing_exit")
    if type(code) is int and code == 0:
        lines = listing.strip().splitlines()
        matches = [LISTING.fullmatch(line) for line in lines]
        if lines and all(matches):
            result["detected"] = sorted(set(match[1] for match in matches))
            result["detection_source"] = "standard_listing"
        else:
            result["refusals"].append("malformed_listing")
    elif (
        type(code) is int
        and code == 255
        and listing.strip() == "Unknown option --list-runtimes"
    ):
        active = evidence.get("active_path")
        match = (
            ACTIVE.fullmatch(active)
            if isinstance(active, str) and len(active) < 512
            else None
        )
        if match:
            result["active_path"] = active
            result["detected"] = [match[1]]
            result["detection_source"] = "active_clr_fallback"
        else:
            result["refusals"].append("unrecognized_active_path")
    else:
        result["refusals"].append("listing_unavailable")
    files = evidence.get("files")
    if isinstance(files, dict):
        for name in LIBS:
            value = files.get(name)
            result["required_files"][name] = value if type(value) is bool else None
    if any(value is not True for value in result["required_files"].values()):
        result["refusals"].append("required_files_unconfirmed")
    if any(not version.startswith(("3.1.", "6.0.")) for version in result["detected"]):
        result["refusals"].append("unreviewed_runtime_family")
    if (
        safe_choice
        and result["detected"]
        and not any(v.startswith(safe_choice + ".") for v in result["detected"])
    ):
        result["refusals"].append("choice_detection_mismatch")
    # Only field names, never arbitrary expected/found values, leave this envelope.
    mismatch = evidence.get("profile_mismatch", [])
    result["profile_mismatch"] = (
        sorted(
            set(
                k
                for k in mismatch
                if isinstance(k, str)
                and k
                in (
                    "firmware",
                    "architecture",
                    "runtime",
                    "host_hash",
                    "signature",
                    "callback",
                )
            )
        )
        if isinstance(mismatch, list)
        else []
    )
    if result["profile_mismatch"]:
        result["refusals"].append("profile_mismatch")
    return result
