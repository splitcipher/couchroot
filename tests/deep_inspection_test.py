import copy
import json
import unittest
from tvsetup.deep_inspection import report
from tvsetup.common import Refused

class DeepInspectionTests(unittest.TestCase):
    def evidence(self):return dict(source_revision='a'*40,stage='listing',outcome='observed',listing_exit=0,
        listing='Microsoft.NETCore.App 6.0.9 [/usr/share/dotnet/shared/Microsoft.NETCore.App]',
        files={'libcoreclr.so':True,'System.Private.CoreLib.dll':True})
    def test_standard_explicit_choice_remains_separate_and_non_authorizing(self):
        evidence=self.evidence();evidence['explicit_choice']='3.1';before=copy.deepcopy(evidence)
        result=report(evidence)
        self.assertEqual(result['detected'],['6.0.9']);self.assertEqual(result['explicit_choice'],'3.1')
        self.assertIn('choice_detection_mismatch',result['refusals'])
        self.assertIsNone(result['selected_runtime']);self.assertFalse(result['install_authorized']);self.assertFalse(result['profile_modified'])
        self.assertEqual(evidence,before)
    def test_standard_fallback_and_alternate_layouts(self):
        for path in ['/usr/share/dotnet/shared/Microsoft.NETCore.App/3.1.3','/usr/share/dotnet.tizen/netcoreapp/6.0.9','/usr/share/dotnet.tizen/net6.0/6.0.9']:
            e=self.evidence();e.update(listing_exit=255,listing='Unknown option --list-runtimes',active_path=path)
            r=report(e);self.assertEqual(r['active_path'],path);self.assertEqual(r['detection_source'],'active_clr_fallback')
            self.assertFalse(r['install_authorized'])
    def test_missing_files_unknown_runtime_and_unsupported_choice(self):
        e=self.evidence();e['files']={};e['explicit_choice']='8.0';e['listing']=e['listing'].replace('6.0.9','8.0.1')
        r=report(e)
        for reason in ['required_files_unconfirmed','unsupported_explicit_choice','unreviewed_runtime_family']:self.assertIn(reason,r['refusals'])
    def test_malformed_injection_and_private_fields_are_not_exported(self):
        for path in ['/tmp/private-token/6.0.9','/usr/share/dotnet.tizen/netcoreapp/6.0.9;$(echo secret)','/usr/share/dotnet/../secret/6.0.9']:
            e=self.evidence();e.update(listing_exit=255,listing='Unknown option --list-runtimes',active_path=path,token='private-token',profile_mismatch=['firmware','private-token'])
            r=report(e);self.assertEqual(r['detected'],[]);self.assertNotIn('private-token',json.dumps(r));self.assertEqual(r['profile_mismatch'],['firmware'])
        for code,text in [(255,'other error'),(0,'private-token'),(None,'')]:
            e=self.evidence();e.update(listing_exit=code,listing=text)
            self.assertEqual(report(e)['detected'],[])
    def test_timeout_rejection_and_input_bounds(self):
        for stage in ['control','callback','cleanup']:
            for outcome in ['timeout','rejected','unknown']:
                e=self.evidence();e.update(stage=stage,outcome=outcome)
                r=report(e);self.assertEqual(r['stage'],stage);self.assertEqual(r['outcome'],outcome);self.assertFalse(r['install_authorized'])
        with self.assertRaises(Refused):report({'listing':'x'*16385})
        with self.assertRaises(Refused):report(None)

if __name__=='__main__':unittest.main()
