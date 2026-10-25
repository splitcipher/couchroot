"""The 2310.0 setup/cleanup trial must stay quarantined from ordinary setup."""
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch

from tvsetup.common import Refused
from tvsetup.config import profile
from tvsetup import qn90a_setup_trial as trial
from tvsetup.transport import managed_guard


def _bound():
    return {**profile("qn90a"), "host": "192.0.2.10", "device_id": "synthetic"}


class Qn90aSetupTrialTests(unittest.TestCase):
    def test_scope_firmware_and_cleanup_allowlist(self):
        self.assertEqual(trial.SCOPE, "qn90a-2310-setup-cleanup-trial")
        self.assertEqual(trial.FIRMWARE, "T-NKM2AKUC-2310.0")
        # Cleanup is limited to the one app still installed on 2310.0 (Xbox).
        self.assertEqual(trial.CLEANUP, {"GHI3a0zMSx": "4.55.698"})

    def test_contract_pins_2310_without_changing_the_registry(self):
        original = profile("qn90a")
        with patch("tvsetup.site.configured_profile", return_value=_bound()):
            value = trial.contract({})
        # The ordinary registry profile is untouched and still 2301.1 — the
        # quarantine invariant from qn90a_firmware_trial_test holds here too.
        self.assertEqual(profile("qn90a"), original)
        self.assertEqual(original["firmware"], "T-NKM2AKUC-2301.1")
        self.assertNotIn(trial.FIRMWARE, managed_guard(original))
        # The trial contract itself is pinned to 2310.0.
        self.assertEqual(value["firmware"], trial.FIRMWARE)

    def test_contract_refuses_when_ordinary_baseline_drifts(self):
        # If the private profile were mutated off the reviewed 2301.1 baseline,
        # the delegated safety_profile refuses — the trial cannot operate on a
        # changed registry.
        drifted = {**profile("qn90a"), "firmware": "T-NKM2AKUC-2311.0"}
        with patch.object(trial.firmware_trial, "profile", return_value=drifted):
            with patch("tvsetup.site.configured_profile", return_value=drifted):
                with self.assertRaises(Refused):
                    trial.contract({})

    def test_prepare_refuses_without_the_signed_package_producer(self):
        # The offline producer is a certification deliverable, not shipped here.
        self.assertFalse((trial.REPO / trial.BUILDER).exists())
        with self.assertRaises(Refused):
            trial._builder_digest()

    def test_context_refuses_unknown_run_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            with patch.object(trial, "STATE", Path(tmp)):
                with patch("tvsetup.site.configured_profile", return_value=_bound()):
                    with self.assertRaises(Refused):
                        trial.context(trial.run_id(), {})


if __name__ == "__main__":
    unittest.main()
