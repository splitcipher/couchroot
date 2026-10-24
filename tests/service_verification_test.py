import copy
import tempfile
import unittest
from pathlib import Path
from unittest.mock import Mock, patch
from xml.etree import ElementTree as ET
from tvsetup.autonomous_root_trial import PilotDriver, PACKAGE, PREFIX
from tvsetup.common import Refused, read_json
from tvsetup.engine import Engine, pending
from tvsetup.planner import Plan, Action
from tvsetup.service_registration import verify_manifest_contract
from service_registration_test import expected_registration


class VerificationTests(unittest.TestCase):
    def setUp(self):
        tmp=tempfile.TemporaryDirectory(); self.addCleanup(tmp.cleanup)
        self.root=Path(tmp.name); self.folder=self.root/'runs'/'fixture'
        self.driver=PilotDriver(Mock(),{}, {},self.folder)
        self.state=dict(files={PREFIX+'file':'before'}, developer_host='192.0.2.1',
            packages=[[PACKAGE,PACKAGE+'.App','wgt','1.0.0','true','false','false','false']],
            agent_registration=expected_registration())
        self.action=Action('update','autonomous-root','package',self.state['files'].copy(),{PREFIX+'file':'after'},dict(package=PACKAGE))
        self.driver.snapshot=lambda:copy.deepcopy(self.state)
        self.driver.prepare=lambda a:{}
        self.driver.backup=lambda a,i,s:i
        self.calls=0;self.failure=None;self.flags='expected'
        def execute(a,i,s):
            self.calls+=1
            self.assertEqual(read_json(self.engine.path)['actions'][0]['phase'],'applying')
            if self.failure=='before': raise Refused('lost reply')
            self.state['files']=a.after.copy()
            self.state['agent_registration']['status']=self.flags
            if self.failure=='after': raise Refused('lost reply')
        self.driver.execute=execute
        self.engine=Engine(self.driver,self.folder,'qn90a',{},state_dir=self.root)

    def start(self): self.engine.start(Plan('qn90a',actions=[self.action]),self.driver.snapshot())

    def test_correct_bytes_with_reset_flags_stay_partial_and_resume_without_install(self):
        self.flags='disabled'
        with self.assertRaisesRegex(Refused,'startup registration'): self.start()
        self.assertEqual(self.engine.doc['phase'],'partial')
        self.assertEqual(len(pending(self.root,'qn90a')),1)
        self.engine.load()
        with self.assertRaises(Refused):self.engine.reconcile()
        self.assertEqual(self.calls,1)
        # Represents separate, reviewed restoration, not a verifier write.
        self.state['agent_registration']=expected_registration()
        self.engine.reconcile();self.engine.apply();self.engine.finalize()
        self.assertEqual(self.calls,1)
        self.assertEqual(self.state['agent_registration']['new_boot_ready'],'not_observed')

    def test_intact_flags_and_lost_reply(self):
        self.failure='after'
        with self.assertRaisesRegex(Refused,'lost reply'):self.start()
        self.engine.load();self.engine.reconcile();self.engine.apply()
        self.assertEqual(self.calls,1)

    def test_pre_submission_failure_does_not_infer_installation(self):
        self.failure='before'
        with self.assertRaises(Refused):self.start()
        with self.assertRaisesRegex(Refused,'uncertain'):self.engine.reconcile()
        self.assertEqual(self.state['files'],self.action.before)
        self.assertEqual(self.calls,1)

    def test_resume_rechecks_previously_applied_package_registration(self):
        self.start()
        # Another later action could leave a run partial after the package passed.
        self.engine.doc['phase']='partial';self.engine.save()
        self.state['agent_registration']['status']='disabled'
        self.engine.load()
        with self.assertRaisesRegex(Refused,'startup registration'):self.engine.apply()
        self.assertEqual(self.calls,1)
        self.assertEqual(self.engine.doc['phase'],'partial')

    def test_wrong_identity_still_refuses(self):
        self.state['packages'][0][1]='Other.App'
        with self.assertRaisesRegex(Refused,'registration mismatch'):self.start()

    def test_old_snapshot_missing_record_is_unknown_and_old_checkout_pin_remains(self):
        del self.state['agent_registration']
        self.driver.execute=lambda a,i,s:self.state.update(files=a.after.copy())
        with self.assertRaisesRegex(Refused,'fresh schema-1'):self.start()
        with patch('tvsetup.engine.source_revision',return_value='different-checkout'):
            with self.assertRaisesRegex(Refused,'original checkout'):self.engine.reconcile()
        self.assertEqual(self.engine.doc['schema'],2)

    def test_manifest_requires_exact_single_service_and_both_flags(self):
        xml='<widget xmlns:t="http://tizen.org/ns/widgets"><t:service id="MiniRoot01.Service" on-boot="true" auto-restart="true"/></widget>'
        verify_manifest_contract(ET.fromstring(xml))
        for invalid in (xml.replace('on-boot="true"','on-boot="false"'),xml.replace('MiniRoot01.Service','Other.Service'),xml.replace('</widget>', '<t:service id="MiniRoot01.Service"/></widget>')):
            with self.assertRaises(Refused):verify_manifest_contract(ET.fromstring(invalid))

if __name__=='__main__':unittest.main()
