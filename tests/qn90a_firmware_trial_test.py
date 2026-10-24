"""A firmware trial cannot silently expand ordinary setup or recovery scope."""
import unittest
from unittest.mock import patch

from tvsetup.common import Refused
from tvsetup.config import profile
from tvsetup import native_rescue, qn90a_firmware_trial as trial
from tvsetup.transport import managed_guard


class FirmwareTrialTests(unittest.TestCase):
    def test_explicit_trial_retains_pins_and_does_not_change_registry(self):
        original = profile("qn90a")
        value = trial.safety_profile("qn90a", trial.FIRMWARE)
        self.assertEqual(profile("qn90a"), original)
        for key in trial.BASELINE.keys() - {"firmware"}:
            self.assertEqual(value[key], original[key])
        self.assertEqual(value["cleanup"], {})
        self.assertEqual(set(value["capabilities"].values()), {"untested"})
        guard = trial.guard(value)
        for required in (trial.FIRMWARE, trial.PRD_INFO_SHA256,
                         original["host_sha256"], original["launcher_sha256"],
                         "uname -m", "test ! -L /etc/prd_info.ini", "3.1.3"):
            self.assertIn(required, guard)
        self.assertNotIn(trial.FIRMWARE, managed_guard(original))
        for key in (*trial.BASELINE, "firmware_file_sha256"):
            with self.assertRaises(Refused):
                trial.guard({**value, key: "changed"})

    def test_other_firmware_model_or_baseline_drift_refuses(self):
        for device, firmware in (("s90d", trial.FIRMWARE), ("qn90a", "2310"),
                                 ("qn90a", trial.FIRMWARE + "\n"),
                                 ("qn90a", "T-NKM2AKUC-2311.0")):
            with self.assertRaises(Refused):
                trial.safety_profile(device, firmware)
        for key in trial.BASELINE:
            wrong = {**profile("qn90a"), key: "changed"}
            with patch.object(trial, "profile", return_value=wrong):
                with self.assertRaises(Refused):
                    trial.safety_profile("qn90a", trial.FIRMWARE)

    def test_configured_trial_preserves_enrolled_binding_and_trust(self):
        bound = {**profile("qn90a"), "host": "192.0.2.10",
                 "device_id": "synthetic", "author_sha256": "a" * 64}
        with patch("tvsetup.site.configured_profile", return_value=bound):
            value = trial.configured_trial({})
        for key in ("host", "device_id", "author_sha256"):
            self.assertEqual(value[key], bound[key])

    def test_rescue_explicitly_binds_exact_firmware_and_file_digest(self):
        args = ("qn90a", "00000000-0000-4000-8000-000000000001",
                "/opt/couchroot-native-recovery/" + "a" * 32 + "/code",
                "b" * 64, "127.0.0.1", "192.0.2.10")
        old = native_rescue.plan(*args, tag="c" * 32)
        self.assertNotIn("firmware_file_sha256", old)
        value = native_rescue.plan(*args, tag="c" * 32, firmware=trial.FIRMWARE)
        for script in native_rescue.commands(value).values():
            self.assertIn(trial.FIRMWARE, script)
            self.assertIn(trial.PRD_INFO_SHA256, script)
            self.assertIn(args[1], script)
        self.assertIn("b" * 64, native_rescue.commands(value)["arm"])
        for changed in ({**value, "firmware_file_sha256": "c" * 64},
                        {k: v for k, v in value.items() if k != "firmware_file_sha256"},
                        {**value, "firmware": "T-NKM2AKUC-2311.0"}):
            with self.assertRaises(Refused):
                native_rescue.commands(changed)
        with self.assertRaises(Refused):
            native_rescue.plan(*args, firmware="*")


if __name__ == "__main__":
    unittest.main()
