from service_registration_test import expected_registration
"""Exercise the real journal/driver path; only signing and installation are fixtures."""

import copy
import json
import tempfile
import unittest
import xml.etree.ElementTree as ET
import zipfile
from pathlib import Path
from unittest.mock import Mock, patch

from tvsetup.autonomous_root_trial import PilotDriver, PACKAGE, PREFIX, package_files
from tvsetup.common import Refused, read_json, sha
from tvsetup.engine import Engine
from tvsetup.operations import Driver
from tvsetup.planner import Action, Plan


def archive(path, members):
    with zipfile.ZipFile(path, "w") as z:
        for name, data in members.items():
            z.writestr(name, data)


def verified(path, profile, package):
    with zipfile.ZipFile(path) as z:
        members = {name: z.read(name) for name in z.namelist()}
    name = "config.xml" if "config.xml" in members else "tizen-manifest.xml"
    return members, ET.fromstring(members[name]).get("version")


class PackageRecoveryTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory()
        self.addCleanup(self.temp.cleanup)
        self.base = Path(self.temp.name)
        self.folder = self.base / "run"
        self.old = self.base / "old.wgt"
        self.new = self.base / "new.wgt"
        self.prior = {
            "config.xml": b'<widget xmlns="http://www.w3.org/ns/widgets" version="0.7.52"/>',
            "author-signature.xml": b"old author",
            "signature1.xml": b"old distributor",
            "old.js": b"old code",
            "shared.js": b"prior code",
        }
        self.desired = {
            "config.xml": b'<widget xmlns="http://www.w3.org/ns/widgets" version="0.7.53"/>',
            "author-signature.xml": b"new author",
            "signature1.xml": b"new distributor",
            "new.js": b"new code",
            "shared.js": b"updated code",
        }
        archive(self.old, self.prior)
        archive(self.new, self.desired)
        before, after = package_files(self.prior), package_files(self.desired)
        keys = set(before) | set(after)
        before = {k: before.get(k) for k in keys}
        after = {k: after.get(k) for k in keys}
        self.action = Action(
            "001-update",
            "autonomous-root",
            "package",
            before,
            after,
            dict(package=PACKAGE, source=str(self.new)),
        )
        self.original_before = copy.deepcopy(before)
        self.driver = PilotDriver(
            None, {"host": "192.0.2.1", "signing_profile": "fixture"}, {}, self.folder
        )
        self.state = self.state_for(self.desired, "0.7.53")
        self.driver.snapshot = lambda: copy.deepcopy(self.state)
        self.engine = Engine(self.driver, self.folder, "s90d", {})
        self.enterContext(
            patch("tvsetup.operations.verify_package", side_effect=verified)
        )
        self.enterContext(
            patch("tvsetup.autonomous_root_trial.verify_package", side_effect=verified)
        )
        self.driver.prepare = lambda action: dict(
            artifact=str(self.new),
            sha256=sha(self.new.read_bytes()),
            recovery_package=str(self.old),
            recovery_sha256=sha(self.old.read_bytes()),
        )
        self.engine.prepare(
            Plan("s90d", actions=[self.action]), self.state_for(self.prior, "0.7.52")
        )
        self.engine.doc["actions"][0]["phase"] = "applied"
        self.engine.doc["phase"] = "configuration-applied"
        self.engine.save()
        self.installs = 0
        self.signs = 0
        self.failure = None
        self.signer_drift = False
        self.enterContext(
            patch.object(self.driver.builder, "command", side_effect=self.sign)
        )
        self.enterContext(patch("tvsetup.operations.run", side_effect=self.install))

    def state_for(self, members, version):
        files = package_files(members)
        return dict(
            agent_registration=expected_registration(),
            files={k: files.get(k) for k in self.action.after},
            packages=[
                [
                    PACKAGE,
                    PACKAGE + ".App",
                    "wgt",
                    version,
                    "true",
                    "false",
                    "false",
                    "false",
                ]
            ],
        )

    def sign(self, argv):
        self.signs += 1
        folder = Path(argv[-1])
        members = {
            p.relative_to(folder).as_posix(): p.read_bytes()
            for p in folder.rglob("*")
            if p.is_file()
        }
        members.update(
            {
                "author-signature.xml": b"recovery author",
                "signature1.xml": b"recovery distributor",
            }
        )
        if self.signer_drift:
            members["old.js"] = b"unexpected code"
        archive(folder / "recovery.wgt", members)

    def install(self, argv, **kwargs):
        self.installs += 1
        self.assertEqual(argv[1], "install")
        # The full recovery identity and expected hashes must be durable BEFORE submission.
        row = read_json(self.engine.path)["actions"][0]
        self.assertEqual(row["phase"], "rolling-back")
        record = row["info"]["forward_recovery"]
        source = Path(argv[-1]) / argv[argv.index("-n") + 1]
        self.assertEqual(record["sha256"], sha(source.read_bytes()))
        if self.failure == "before":
            raise Refused("lost install reply")
        members, version = verified(source, {}, PACKAGE)
        self.state = self.state_for(members, version)
        if self.failure == "flags":
            self.state["agent_registration"]["status"] = "disabled"
        if self.failure == "drift":
            self.state["files"][PREFIX + "old.js"] = sha(b"foreign")
        if self.failure == "version":
            self.state["packages"][0][3] = "0.7.53"
        if self.failure == "after":
            raise Refused("lost install reply")
        return "installed"

    def test_forward_version_and_signatures_are_verified_without_changing_original(
        self,
    ):
        self.assertEqual(self.engine.rollback(), [])
        row = read_json(self.engine.path)["actions"][0]
        record = row["info"]["forward_recovery"]
        self.assertEqual(record["version"], "0.7.54")
        self.assertEqual(row["action"]["before"], self.original_before)
        self.assertNotEqual(
            record["files"][PREFIX + "config.xml"],
            self.original_before[PREFIX + "config.xml"],
        )
        self.assertNotEqual(
            record["files"][PREFIX + "author-signature.xml"],
            self.original_before[PREFIX + "author-signature.xml"],
        )
        self.assertEqual(record["files"][PREFIX + "old.js"], sha(self.prior["old.js"]))
        self.assertIsNone(record["files"][PREFIX + "new.js"])
        self.assertEqual(self.state["files"], record["files"])
        self.assertEqual(row["phase"], "rolled-back")
        self.assertEqual((self.signs, self.installs), (1, 1))

    def test_lost_reply_after_install_reconciles_without_resigning_or_reinstalling(
        self,
    ):
        self.failure = "after"
        with self.assertRaisesRegex(Refused, "lost install reply"):
            self.engine.rollback()
        self.engine.load()
        self.assertEqual(self.engine.rollback(), [])
        self.assertEqual((self.signs, self.installs), (1, 1))

    def test_unchanged_uncertain_install_is_not_replayed(self):
        self.failure = "before"
        with self.assertRaisesRegex(Refused, "lost install reply"):
            self.engine.rollback()
        self.engine.load()
        with self.assertRaisesRegex(Refused, "unconfirmed"):
            self.engine.rollback()
        self.assertEqual((self.signs, self.installs), (1, 1))

    def test_wrong_payload_still_fails_readback(self):
        self.failure = "drift"
        with self.assertRaisesRegex(Refused, "readback"):
            self.engine.rollback()
        self.engine.load()
        with self.assertRaisesRegex(Refused, "drift"):
            self.engine.rollback()
        self.assertEqual(self.installs, 1)

    def test_wrong_registration_fails_readback(self):
        self.failure = "version"
        with self.assertRaisesRegex(Refused, "registration"):
            self.engine.rollback()
        self.engine.load()
        with self.assertRaisesRegex(Refused, "registration"):
            self.engine.rollback()
        self.assertEqual(self.installs, 1)

    def test_recovery_reset_flags_remains_pending_without_reinstall(self):
        self.failure = "flags"
        with self.assertRaisesRegex(Refused, "startup registration"):
            self.engine.rollback()
        self.assertEqual(self.engine.doc['phase'], 'rollback-partial')
        self.engine.load()
        with self.assertRaisesRegex(Refused, "startup registration"):
            self.engine.rollback()
        self.assertEqual(self.installs, 1)
        self.state['agent_registration'] = expected_registration()
        self.assertEqual(self.engine.rollback(), [])
        self.assertEqual(self.installs, 1)

    def test_signer_cannot_change_recovered_payload(self):
        self.signer_drift = True
        with self.assertRaisesRegex(Refused, "Recovery content"):
            self.engine.rollback()
        self.assertEqual(self.installs, 0)

    def test_archive_and_record_tampering_refused_on_reconcile(self):
        self.failure = "after"
        with self.assertRaises(Refused):
            self.engine.rollback()
        record = self.engine.doc["actions"][0]["info"]["forward_recovery"]
        original = copy.deepcopy(record)
        record["files"][PREFIX + "old.js"] = sha(b"foreign")
        self.engine.save()
        with self.assertRaisesRegex(Refused, "Recovery record"):
            self.engine.rollback()
        record.clear()
        record.update(original)
        Path(record["artifact"]).write_bytes(b"changed")
        self.engine.save()
        with self.assertRaisesRegex(Refused, "Recovery archive"):
            self.engine.rollback()
        self.assertEqual(self.installs, 1)

    def test_external_drift_is_not_overwritten(self):
        self.state["files"][PREFIX + "shared.js"] = sha(b"foreign")
        with self.assertRaisesRegex(Refused, "drift"):
            self.engine.rollback()
        self.assertEqual((self.signs, self.installs), (0, 0))

    def test_agent_identity_exception_does_not_accept_other_apps_or_protection_flags(
        self,
    ):
        original = copy.deepcopy(self.state["packages"])
        for index, value in ((1, "Other.App"), (2, "tpk"), (4, "false"), (5, "true")):
            self.state["packages"] = copy.deepcopy(original)
            self.state["packages"][0][index] = value
            with self.assertRaises(Refused):
                self.driver.rollback(
                    self.action, self.engine.doc["actions"][0]["info"], self.state
                )
        self.assertEqual(self.installs, 0)
        self.assertFalse(Driver.package_identity_ok(self.driver, original[0]))

    def test_already_original_needs_no_signing_or_install(self):
        self.state = self.state_for(self.prior, "0.7.52")
        self.assertEqual(self.engine.rollback(), [])
        self.assertEqual((self.signs, self.installs), (0, 0))

    def test_legacy_uncertain_recovery_cannot_be_resubmitted(self):
        self.engine.doc["actions"][0]["phase"] = "rolling-back"
        self.engine.save()
        with self.assertRaisesRegex(Refused, "unconfirmed"):
            self.engine.rollback()
        self.assertEqual((self.signs, self.installs), (0, 0))

    def test_partial_build_is_not_reused(self):
        folder = self.folder / (self.action.id + "-forward-recovery")
        folder.mkdir()
        (folder / "foreign").write_text("keep")
        with self.assertRaisesRegex(Refused, "partial output"):
            self.engine.rollback()
        self.assertEqual((folder / "foreign").read_text(), "keep")
        self.assertEqual((self.signs, self.installs), (0, 0))

    def test_tpk_recovery_uses_verified_version_and_runtime_guard(self):
        folder = self.base / "native-run"
        profile = {"host": "192.0.2.1", "signing_profile": "fixture"}
        tv = Mock()
        driver = Driver(tv, profile, {}, folder)
        pkg = "MiniTelemetry"
        prefix = "/opt/usr/apps/" + pkg + "/"
        old = self.base / "old.tpk"
        new = self.base / "new.tpk"
        manifest = b'<manifest xmlns="http://tizen.org/ns/packages" package="MiniTelemetry" version="1.0.%d"/>'
        previous = {
            "tizen-manifest.xml": manifest % 0,
            "bin/old": b"old",
            "signature1.xml": b"sig",
            "author-signature.xml": b"sig",
        }
        desired = {**previous, "tizen-manifest.xml": manifest % 1, "bin/new": b"new"}
        archive(old, previous)
        archive(new, desired)

        def hashes(members):
            return {
                prefix + n: (
                    None
                    if n == "signature1.xml" or n not in members
                    else sha(members[n])
                )
                for n in desired
            }

        action = Action(
            "001-native",
            "telemetry",
            "package",
            hashes(previous),
            hashes(desired),
            {"package": pkg},
        )
        info = dict(
            artifact=str(new),
            sha256=sha(new.read_bytes()),
            recovery_package=str(old),
            recovery_sha256=sha(old.read_bytes()),
        )

        def sign(argv):
            path = Path(argv[-1])
            members, _ = verified(path, {}, pkg)
            members.update(
                {"signature1.xml": b"recovery", "author-signature.xml": b"recovery"}
            )
            archive(path, members)

        with (
            patch.object(driver.builder, "command", side_effect=sign),
            patch("tvsetup.operations.managed_guard", return_value="runtime guard"),
            patch("tvsetup.operations.run", return_value="installed") as install,
        ):
            info["forward_recovery"] = driver.prepare_recovery(action, info)
            driver.reinstall_recovery(action, info)
            self.assertEqual(info["forward_recovery"]["version"], "1.0.2")
            self.assertIsNone(info["forward_recovery"]["files"][prefix + "bin/new"])
            tv.sdk.assert_called_once_with("runtime guard")
            install.assert_called_once()


if __name__ == "__main__":
    unittest.main()
