import copy
import tempfile
import unittest
from pathlib import Path
from research.offline_models.saver import BackendDriver, patch_cache, selector_app
from tvsetup.engine import Engine
from tvsetup.common import Refused, sha

class SaverModelTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory();self.addCleanup(tmp.cleanup);self.root=Path(tmp.name)
        self.base=dict(backend='native',namespace='fixture-init',diagnostic_ok=True,app='fixture-signed-and-present',
            mounts=[dict(owner='fixture-couchroot',backend='native',readonly=True)],
            cache_suffix='synthetic-suffix',splash='original-splash',telemetry='original-telemetry')
        self.selector=b'<ContentList><App id="FixtureSaver.App"/></ContentList>'
    def engine(self,case='run'):
        d=BackendDriver(self.base,self.selector);e=Engine(d,self.root/case,'s90d',{})
        e.prepare(d.plan('web',experimental=True),d.snapshot());return d,e
    def test_shared_engine_plan_apply_inverse_preserves_splash_and_telemetry(self):
        d,e=self.engine();e.apply();self.assertEqual(d.state['backend'],'web')
        self.assertEqual(d.state['splash'],self.base['splash']);self.assertEqual(d.state['telemetry'],self.base['telemetry'])
        e.rollback();self.assertEqual(d.state,self.base)
    def test_interruptions_and_failed_unwind_keep_journal_recoverable(self):
        for fail in ('unmount','after_unmount','after_mount','remount','remount_and_unwind','after_commit'):
            with self.subTest(fail=fail):
                d,e=self.engine(fail);d.failure=fail
                with self.assertRaises((Refused,InterruptedError)):e.apply()
                self.assertEqual(e.doc['phase'],'partial')
                if fail=='after_commit':e.load();e.reconcile();self.assertTrue(e.doc['actions'][0]['reconciled'])
                d.failure=None;e.rollback();self.assertEqual(d.state,self.base)
    def test_unknown_overlay_and_failed_inverse_never_broadly_unmount(self):
        d,e=self.engine();e.apply();d.state['mounts'][0]['owner']='foreign'
        before=copy.deepcopy(d.state)
        with self.assertRaises(Refused):e.rollback()
        self.assertEqual(d.state,before)
        d.state['mounts'][0]['owner']='fixture-couchroot';d.failure='rollback_unmount'
        with self.assertRaises(Refused):e.rollback()
        self.assertEqual(e.doc['phase'],'rollback-partial')
        d.failure=None;e.rollback();self.assertEqual(d.state,self.base)
    def test_admission_missing_app_namespace_diagnostic_and_dual_overlay(self):
        for field,value in [('namespace','wrong'),('diagnostic_ok',False),('app','missing'),('mounts',self.base['mounts']*2)]:
            d=BackendDriver({**self.base,field:value},self.selector)
            with self.assertRaises(Refused):d.plan('web',experimental=True)
        d=BackendDriver(self.base,self.selector)
        with self.assertRaises(Refused):d.plan('web')
        for data in (b'<',b'<ContentList/>',b'<ContentList><App id="Other"/></ContentList>',b'<!DOCTYPE x><ContentList/>'):
            with self.assertRaises(Refused):selector_app(data)
    def test_exact_synthetic_cache_suffix_and_hash_admission(self):
        cache=b'a'*209+b'untouched\x00suffix';head=b'b'*209
        self.assertEqual(patch_cache(cache,head,sha(cache))[209:],cache[209:])
        for data,unit,digest in [(cache,head,'0'*64),(cache,b'short',sha(cache)),(b'short',head,sha(b'short'))]:
            with self.assertRaises(Refused):patch_cache(data,unit,digest)

if __name__=='__main__':unittest.main()
