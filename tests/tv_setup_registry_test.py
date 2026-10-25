import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tvsetup import registry
from tvsetup.common import Refused


REPO = Path(__file__).resolve().parents[1]


class RegistryTest(unittest.TestCase):
    def test_registry_has_only_the_two_reviewed_devices_and_capability_tables(self):
        profiles = registry.profiles()
        self.assertEqual(set(profiles), {"qn90a", "s90d"})
        self.assertEqual(registry.accepted_devices(), ("qn90a", "s90d"))
        for value in profiles.values():
            self.assertEqual(set(value["capabilities"]), registry.CAPABILITIES)
            self.assertTrue(
                set(value["capabilities"].values()) <= registry.CAPABILITY_VALUES
            )

    def _temporary_profiles(self):
        temporary = tempfile.TemporaryDirectory()
        folder = Path(temporary.name)
        for name in ("qn90a", "s90d"):
            source = REPO / "tvsetup/profiles" / (name + ".json")
            (folder / source.name).write_text(source.read_text())
        return temporary, folder

    def test_malformed_capability_value_is_a_hard_error_on_each_load(self):
        temporary, folder = self._temporary_profiles()
        self.addCleanup(temporary.cleanup)
        target = folder / "qn90a.json"
        data = json.loads(target.read_text())
        data["capabilities"]["standby"] = "experimental"
        target.write_text(json.dumps(data))
        with patch.object(registry, "PROFILE_DIR", folder):
            with self.assertRaisesRegex(Refused, "Unknown capability value"):
                registry.profiles()

    def test_malformed_capability_schema_is_a_hard_error(self):
        temporary, folder = self._temporary_profiles()
        self.addCleanup(temporary.cleanup)
        target = folder / "s90d.json"
        data = json.loads(target.read_text())
        del data["capabilities"]["cleanup"]
        target.write_text(json.dumps(data))
        with patch.object(registry, "PROFILE_DIR", folder):
            with self.assertRaisesRegex(Refused, "Invalid capabilities"):
                registry.profile("s90d")

    def test_invalid_runtime_or_nested_digest_is_a_hard_error(self):
        temporary, folder = self._temporary_profiles()
        self.addCleanup(temporary.cleanup)
        target = folder / "s90d.json"
        data = json.loads(target.read_text())
        data["runtime"] = "6.0; touch /tmp/unsafe"
        target.write_text(json.dumps(data))
        with patch.object(registry, "PROFILE_DIR", folder):
            with self.assertRaisesRegex(Refused, "identity/runtime format"):
                registry.profile("s90d")
        data["runtime"] = "6.0.9"
        data["service_artifacts"]["Service.dll"] = "not-a-digest"
        target.write_text(json.dumps(data))
        with patch.object(registry, "PROFILE_DIR", folder):
            with self.assertRaisesRegex(Refused, "Invalid digest map"):
                registry.profile("s90d")

    def test_unreviewed_or_unverified_profile_cannot_expand_registry(self):
        temporary, folder = self._temporary_profiles()
        self.addCleanup(temporary.cleanup)
        (folder / "s90c.json").write_text(
            json.dumps({"id": "s90c", "capabilities": {}})
        )
        with patch.object(registry, "PROFILE_DIR", folder):
            with self.assertRaisesRegex(Refused, "Unknown or mismatched"):
                registry.accepted_devices()

    def test_profile_skeleton_with_null_identity_or_hash_is_rejected(self):
        temporary, folder = self._temporary_profiles()
        self.addCleanup(temporary.cleanup)
        target = folder / "qn90a.json"
        data = json.loads(target.read_text())
        data["host_sha256"] = None
        target.write_text(json.dumps(data))
        with patch.object(registry, "PROFILE_DIR", folder):
            with self.assertRaisesRegex(Refused, "schema fields"):
                registry.profile("qn90a")

    def test_profile_skeleton_unverified_marker_is_rejected(self):
        temporary, folder = self._temporary_profiles()
        self.addCleanup(temporary.cleanup)
        target = folder / "qn90a.json"
        data = json.loads(target.read_text())
        data["skeleton_status"] = "UNVERIFIED"
        target.write_text(json.dumps(data))
        with patch.object(registry, "PROFILE_DIR", folder):
            with self.assertRaisesRegex(Refused, "skeleton"):
                registry.profile("qn90a")

    def test_reviewed_identity_is_read_from_the_profile_file(self):
        for device in ("qn90a", "s90d"):
            value = registry.profile(device)
            self.assertEqual(
                registry.reviewed_identity(device),
                {"model": value["model"], "firmware": value["firmware"]},
            )
            self.assertTrue(registry.has_identity(value, device))
            for key in ("model", "firmware"):
                self.assertFalse(registry.has_identity({**value, key: "changed"}, device))
                missing = {k: v for k, v in value.items() if k != key}
                self.assertFalse(registry.has_identity(missing, device))
        self.assertFalse(registry.has_identity(None, "qn90a"))
        temporary, folder = self._temporary_profiles()
        self.addCleanup(temporary.cleanup)
        target = folder / "qn90a.json"
        data = json.loads(target.read_text())
        data["firmware"] = "T-NKM2AKUC-9999.0"
        target.write_text(json.dumps(data))
        with patch.object(registry, "PROFILE_DIR", folder):
            self.assertEqual(
                registry.reviewed_identity("qn90a")["firmware"], "T-NKM2AKUC-9999.0"
            )

    def test_product_modules_do_not_hardcode_reviewed_identity(self):
        # Identity lives in the profile. Only the firmware trial's explicit
        # historical BASELINE pin may repeat it, to detect profile drift.
        literals = {
            value[key]
            for value in registry.profiles().values()
            for key in ("model", "firmware")
        }
        allowed = {"qn90a_firmware_trial.py"}
        found = [
            path.name + ":" + literal
            for path in sorted((REPO / "tvsetup").glob("*.py"))
            if path.name not in allowed
            for literal in sorted(literals)
            if literal in path.read_text()
        ]
        self.assertEqual(found, [])


if __name__ == "__main__":
    unittest.main()
