import sqlite3
import tempfile
import unittest
from pathlib import Path
from research.offline_models import registration_repair as m
from tvsetup.common import Refused, read_json

class RepairModelTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup)
        self.path=Path(tmp.name)/'fixture.sqlite';self.journal=Path(tmp.name)/'intent.json'
        self.db=sqlite3.connect(self.path,timeout=.01);self.addCleanup(self.db.close)
        self.db.execute('CREATE TABLE fixture_service(package,app,version,author,component,disabled,onboot,autorestart,note)')
        self.db.executemany('INSERT INTO fixture_service VALUES(?,?,?,?,?,?,?,?,?)',[
            (m.PACKAGE,m.SERVICE,'1','synthetic-author','svcapp','false','false','false','keep'),
            ('other','other.Service','2','other-author','svcapp','true','false','true','unrelated')])
        self.db.commit()
        self.original=self.db.execute('SELECT * FROM fixture_service').fetchall()

    def begin(self):m.begin(self.db,self.journal,'own',pending=['own'])

    def test_each_reset_field_and_exact_inverse_preserve_other_columns_rows(self):
        for flags in [('false','false'),('false','true'),('true','false')]:
            with self.subTest(flags=flags):
                self.journal.unlink(missing_ok=True)
                self.db.execute('UPDATE fixture_service SET onboot=?,autorestart=? WHERE package=?',(*flags,m.PACKAGE));self.db.commit()
                original=self.db.execute('SELECT * FROM fixture_service').fetchall()
                self.begin();m.transition(self.db,self.journal,pending=['own'])
                after=self.db.execute('SELECT * FROM fixture_service').fetchall()
                self.assertEqual(after[0][:6],original[0][:6]);self.assertEqual(after[0][8:],original[0][8:]);self.assertEqual(after[1],original[1])
                m.transition(self.db,self.journal,reverse=True)
                self.assertEqual(self.db.execute('SELECT * FROM fixture_service').fetchall(),original)

    def test_interruptions_reconcile_and_inverse(self):
        for crash in ['before','before_commit','after_commit']:
            with self.subTest(crash=crash):
                self.journal.unlink(missing_ok=True);self.begin()
                with self.assertRaises(InterruptedError):m.transition(self.db,self.journal,crash=crash)
                self.assertEqual(read_json(self.journal)['phase'],'applying')
                m.transition(self.db,self.journal)
                with self.assertRaises(InterruptedError):m.transition(self.db,self.journal,reverse=True,crash='after_commit')
                m.transition(self.db,self.journal,reverse=True)
                self.assertEqual(self.db.execute('SELECT * FROM fixture_service').fetchall(),self.original)

    def test_interlocks_drift_and_lock(self):
        for pending,native in [(['other'],False),(['own'],True)]:
            with self.assertRaises(Refused):m.begin(self.db,self.journal,'own',pending,native)
        self.begin()
        with self.assertRaises(Refused):m.transition(self.db,self.journal,pending=['other'])
        lock=sqlite3.connect(self.path);self.addCleanup(lock.close);lock.execute('BEGIN IMMEDIATE')
        with self.assertRaises(sqlite3.OperationalError):m.transition(self.db,self.journal)
        lock.rollback()
        self.db.execute("UPDATE fixture_service SET version='changed' WHERE package=?",(m.PACKAGE,));self.db.commit()
        with self.assertRaises(Refused):m.transition(self.db,self.journal)
        self.db.execute("UPDATE fixture_service SET version='1' WHERE package=?",(m.PACKAGE,));self.db.commit()
        m.transition(self.db,self.journal)
        self.db.execute("UPDATE fixture_service SET autorestart='false' WHERE package=?",(m.PACKAGE,));self.db.commit()
        with self.assertRaises(Refused):m.transition(self.db,self.journal,reverse=True)

    def test_unknown_disabled_missing_and_duplicate_refuse(self):
        for column,value in [('disabled','true'),('component','uiapp'),('onboot',None)]:
            self.db.execute(f'UPDATE fixture_service SET {column}=? WHERE package=?',(value,m.PACKAGE));self.db.commit()
            with self.assertRaises(Refused):self.begin()
            self.db.execute('DELETE FROM fixture_service');self.db.executemany('INSERT INTO fixture_service VALUES(?,?,?,?,?,?,?,?,?)',self.original);self.db.commit()
        self.db.execute('INSERT INTO fixture_service SELECT * FROM fixture_service WHERE package=?',(m.PACKAGE,));self.db.commit()
        with self.assertRaises(Refused):self.begin()
        self.db.execute('DELETE FROM fixture_service WHERE package=?',(m.PACKAGE,));self.db.commit()
        with self.assertRaises(Refused):self.begin()

if __name__=='__main__':unittest.main()
