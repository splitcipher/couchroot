"""Validated registry of the TV profiles this toolkit explicitly supports."""

import json
import re

from .common import REPO, Refused

PROFILE_DIR = REPO / "tvsetup/profiles"
# These are the only reviewed identities. Adding a profile requires an explicit
# support review; a stray JSON file must never make a new target accepted.
ACCEPTED_PROFILE_IDS = frozenset(("qn90a", "s90d"))
CAPABILITIES = frozenset(
    ("transport", "signed_install", "launcher", "home", "startup", "cleanup", "standby")
)
CAPABILITY_VALUES = frozenset(
    ("verified", "verified_other_firmware", "untested", "refused")
)
IDENTITY_FIELDS = (
    "id",
    "name",
    "model",
    "platform",
    "firmware",
    "architecture",
    "framework",
    "runtime",
    "host_sha256",
    "startup",
    "chart_prefix",
    "snapshot",
    "launcher_sha256",
)


def profiles():
    """Load and validate every profile file on disk; do not cache validation."""
    result = {}
    try:
        paths = sorted(PROFILE_DIR.glob("*.json"))
    except OSError as error:
        raise Refused("Cannot read TV profile registry") from error
    if not paths:
        raise Refused("TV profile registry is empty")
    for path in paths:
        try:
            with path.open(encoding="utf-8") as source:
                value = json.load(source)
        except (OSError, json.JSONDecodeError) as error:
            raise Refused("Invalid TV profile file " + path.name) from error
        if not isinstance(value, dict):
            raise Refused("TV profile must be a JSON object: " + path.name)
        if _has_unverified_marker(value):
            raise Refused("Unverified profile skeleton cannot enter the registry")
        identity = value.get("id")
        if identity != path.stem or identity not in ACCEPTED_PROFILE_IDS:
            raise Refused("Unknown or mismatched TV profile identity: " + path.name)
        if identity in result:
            raise Refused("Duplicate TV profile identity: " + identity)
        capabilities = value.get("capabilities")
        if not isinstance(capabilities, dict) or set(capabilities) != CAPABILITIES:
            raise Refused("Invalid capabilities in TV profile " + identity)
        if any(
            not isinstance(status, str) or status not in CAPABILITY_VALUES
            for status in capabilities.values()
        ):
            raise Refused("Unknown capability value in TV profile " + identity)
        if any(
            not isinstance(value.get(key), str) or not value[key]
            for key in IDENTITY_FIELDS
        ):
            raise Refused("Missing or invalid schema fields in TV profile " + identity)
        if (
            not re.fullmatch(r"[A-Z0-9]+", value["model"])
            or not re.fullmatch(r"[A-Z0-9_]+", value["platform"])
            or not re.fullmatch(r"[A-Z0-9.-]+", value["firmware"])
            or not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+", value["runtime"])
        ):
            raise Refused("Invalid identity/runtime format in TV profile " + identity)
        if not isinstance(value.get("cleanup"), dict) or not isinstance(
            value.get("reasons"), dict
        ):
            raise Refused(
                "Missing cleanup or component reasons in TV profile " + identity
            )
        for key in (
            "host_sha256",
            "launcher_sha256",
            "helper_sha256",
            "collector_sha256",
        ):
            if key in value and (
                not isinstance(value[key], str)
                or len(value[key]) != 64
                or any(c not in "0123456789abcdef" for c in value[key])
            ):
                raise Refused("Invalid profile digest " + key + " in " + identity)
        for key in (
            "service_artifacts",
            "boot_artifacts",
            "saver_generated",
            "source_hashes",
        ):
            if key in value and not isinstance(value[key], dict):
                raise Refused("Invalid profile field " + key + " in " + identity)
            if key in value and any(
                not isinstance(digest, str) or not re.fullmatch(r"[a-f0-9]{64}", digest)
                for digest in value[key].values()
            ):
                raise Refused("Invalid digest map " + key + " in " + identity)
        result[identity] = value
    if set(result) != ACCEPTED_PROFILE_IDS:
        raise Refused("TV profile registry must contain exactly qn90a and s90d")
    return result


def _has_unverified_marker(value):
    if isinstance(value, str):
        return value == "UNVERIFIED"
    if isinstance(value, dict):
        return any(
            _has_unverified_marker(key) or _has_unverified_marker(item)
            for key, item in value.items()
        )
    if isinstance(value, list):
        return any(_has_unverified_marker(item) for item in value)
    return False


def accepted_devices():
    """Return the supported model identifiers from the validated registry."""
    return tuple(sorted(profiles()))


def profile(device):
    """Return a validated profile, refusing identifiers outside the registry."""
    try:
        return profiles()[device]
    except (KeyError, TypeError) as error:
        raise Refused("Unsupported TV profile: " + str(device)) from error


def reviewed_identity(device):
    """Return the reviewed model/firmware pair; the profile is the only source."""
    value = profile(device)
    return {key: value[key] for key in ("model", "firmware")}


def has_identity(value, device):
    """Whether a configured profile or record still carries the reviewed identity."""
    expected = reviewed_identity(device)
    return isinstance(value, dict) and all(
        value.get(key) == expected[key] for key in expected
    )
