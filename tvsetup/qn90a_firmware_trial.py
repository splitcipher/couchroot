"""Explicit QN90A 2310.0 agent/recovery qualification, outside setup registry.

Not a general setup profile or an automatic fallback after a firmware refusal.
Callers own authorization, physical identity, locking, journaling and recovery.
"""

from .common import Refused
from .config import profile
from .transport import Transport, managed_guard, hash_guard

FIRMWARE = "T-NKM2AKUC-2310.0"
PRD_INFO_SHA256 = "3293b43134db7a5bb84fee803d4f68091c1fdb2aa3b2273b565fae12ea851db9"
TARLAUNCHER_SHA256 = "3580e6dcf5d9c6d5d0a606d43a3d878641f35eeac07317a405fb45bbed69a653"
BASELINE = {
    "id": "qn90a",
    "model": "QN85QN90AAFXZA",
    "platform": "21_NIKEM2_QTV",
    "firmware": "T-NKM2AKUC-2301.1",
    "architecture": "armv7l",
    "framework": "netcoreapp3.1",
    "runtime": "3.1.3",
    "host_sha256": "d2a35114d788c22d22d329acdb2f379c17b75b7099997fb8252cbd6dd940702e",
    "launcher_sha256": "5f33f4d63bc7eb5a09cdedf377398d6c2f4142e629a1f73921f31f08cb7791f3",
}


def safety_profile(device, firmware):
    if device != "qn90a" or firmware != FIRMWARE:
        raise Refused("Only the explicit QN90A 2310.0 agent trial is admitted")
    result = profile(device)
    if any(result.get(k) != v for k, v in BASELINE.items()):
        raise Refused("QN90A qualification baseline changed; review again")
    result.update(firmware=FIRMWARE, firmware_file_sha256=PRD_INFO_SHA256)
    # No setup/cleanup or broad hardware capability claim accompanies this trial.
    result["cleanup"] = {}
    result["capabilities"] = {k: "untested" for k in result["capabilities"]}
    return result


def configured_trial(site):
    from .site import configured_profile

    bound = configured_profile("qn90a", site)
    return {**bound, **safety_profile("qn90a", FIRMWARE)}


def guard(value):
    expected = safety_profile("qn90a", FIRMWARE)
    if any(value.get(k) != expected[k] for k in (*BASELINE, "firmware_file_sha256")):
        raise Refused("QN90A trial contract drift")
    return managed_guard(value) + hash_guard("/etc/prd_info.ini", PRD_INFO_SHA256)


class QualificationTransport(Transport):
    """Use existing transport with an additional trial-only version-file pin."""

    def sdk(self, script, timeout=30):
        return super().sdk(guard(self.profile) + script, timeout=timeout)

    def root(self, script, *args, **kwargs):
        return super().root(guard(self.profile) + script, *args, **kwargs)
