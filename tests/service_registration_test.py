"""Execute the production SELECT against real SQLite fixtures, without a TV."""
import hashlib
import sqlite3
import subprocess
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tvsetup import service_registration as reg


def expected_registration():
    values = [reg.SERVICE, reg.PACKAGE, 'svcapp', 'false', 'true', 'true', 'false']
    return reg.parse_capture('OK\n' + '|'.join('text|' + value.encode().hex() for value in values))


class RegistrationTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self.tmp.cleanup)
        self.path = Path(self.tmp.name) / 'fixture.db'
        self.db = sqlite3.connect(self.path)
        self.addCleanup(self.db.close)
        self.db.executescript('CREATE TABLE package_info(package,package_disable);'
            'CREATE TABLE package_app_info(app_id,package,app_component,app_disable,app_onboot,app_autorestart);')
        self.db.execute('INSERT INTO package_info VALUES(?,?)', (reg.PACKAGE,'false'))
        self.insert()
        self.db.execute("INSERT INTO package_app_info VALUES('Other.Service','Other','svcapp','false','false','true')")
        self.db.commit()

    def insert(self, app=reg.SERVICE, package=reg.PACKAGE, component='svcapp'):
        self.db.execute('INSERT INTO package_app_info VALUES(?,?,?,?,?,?)', (app,package,component,'false','true','true'))
        self.db.commit()

    def capture(self):
        self.db.commit()
        before = hashlib.sha256(self.path.read_bytes()).digest()
        with patch.object(reg, 'PKG_DB', str(self.path)):
            output = subprocess.check_output(['sh','-c',reg.capture_command()], text=True)
        self.assertEqual(before, hashlib.sha256(self.path.read_bytes()).digest())
        return reg.parse_capture(output)

    def test_expected_and_reset_flags(self):
        self.assertEqual(self.capture()['status'], 'expected')
        for column in ('app_onboot','app_autorestart'):
            self.db.execute(f"UPDATE package_app_info SET {column}='false' WHERE app_id=?", (reg.SERVICE,))
            self.assertEqual(self.capture()['reason'], 'startup_flags_disabled')
            self.db.execute(f"UPDATE package_app_info SET {column}='true' WHERE app_id=?", (reg.SERVICE,))
        self.assertEqual(self.db.execute("SELECT app_onboot FROM package_app_info WHERE package='Other'").fetchone()[0], 'false')

    def test_null_integer_and_unrecognized_flags_stay_unknown_and_redacted(self):
        for value in (None,1,'credential-secret'):
            self.db.execute('UPDATE package_app_info SET app_onboot=? WHERE app_id=?',(value,reg.SERVICE))
            result=self.capture()
            self.assertEqual(result['status'],'unknown')
            self.assertNotIn('credential-secret',str(result))

    def test_disabled_app_and_package(self):
        self.db.execute("UPDATE package_info SET package_disable='true'")
        self.assertEqual(self.capture()['reason'],'registration_disabled')
        self.db.execute("UPDATE package_info SET package_disable='false'")
        self.db.execute("UPDATE package_app_info SET app_disable='true'")
        self.assertEqual(self.capture()['reason'],'registration_disabled')

    def test_missing_duplicate_wrong_package_and_component(self):
        self.insert()
        self.assertEqual(self.capture()['reason'],'duplicate_rows')
        self.db.execute('DELETE FROM package_app_info WHERE package=?',(reg.PACKAGE,))
        self.assertEqual(self.capture()['reason'],'missing_row')
        self.insert(package='Other')
        self.assertEqual(self.capture()['reason'],'missing_row')
        self.insert(component='uiapp')
        self.assertEqual(self.capture()['reason'],'component_mismatch')

    def test_schema_and_read_failures(self):
        self.db.execute('DROP TABLE package_app_info')
        self.assertEqual(self.capture()['reason'],'unsupported_schema')
        with patch.object(reg,'PKG_DB',str(self.path.parent/'missing.db')):
            result=reg.parse_capture(subprocess.check_output(['sh','-c',reg.capture_command()],text=True))
        self.assertEqual(result['reason'],'read_error')
        self.assertFalse((self.path.parent/'missing.db').exists())

    def test_malformed_capture_does_not_claim_health(self):
        for text in ('', 'OK\ntext|invalid', 'OK\n'+'|'.join(['text','ZZ']*7)):
            result=reg.parse_capture(text)
            self.assertEqual(result['status'],'unknown')
            self.assertEqual(result['worker_ready'],'not_observed')
            self.assertEqual(result['new_boot_ready'],'not_observed')


if __name__ == '__main__': unittest.main()
