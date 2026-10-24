import copy
import unittest
from tvsetup.config import profile
from tvsetup.component_report import explain

class ComponentReportTests(unittest.TestCase):
    def test_profile_scoped_provenance_unknown_facts_and_unchanged_policy(self):
        for device in ('qn90a','s90d'):
            p=profile(device);before=copy.deepcopy(p)
            state=dict(packages=[],apps=[],dependencies=[],catalog=[],package_files={})
            result=explain(p,state)
            self.assertEqual({r['package'] for r in result},set(p['cleanup']))
            self.assertEqual(p,before)
            for row in result:
                self.assertEqual(row['profile_firmware'],p['firmware'])
                self.assertIn(device,row['provenance'])
                self.assertTrue(all(v is None for v in row['recorded_registration'].values()))
                self.assertEqual(row['process_evidence'],'not_established')
    def test_disabled_and_running_are_independent_recorded_facts(self):
        p=profile('s90d');pkg,entry=next(iter(p['cleanup'].items()))
        state=dict(packages=[],apps=[],dependencies=[])
        app=dict(id=entry['app'],package=pkg,package_disabled=False,app_disabled=True,on_boot=False,auto_restart=None)
        inspector=dict(apps=dict(status='ok',rows=[app]),processes=dict(status='partial',rows=[dict(name=entry['app'])]))
        row=explain(p,state,inspector)[0]
        self.assertTrue(row['recorded_registration']['app_disabled'])
        self.assertEqual(row['process_evidence'],'matching_app_id_observed')
        self.assertEqual(row['evidence_basis'],'supplied_inspector_record')
        inspector['apps']['rows'].append(app)
        self.assertIsNone(explain(p,state,inspector)[0]['recorded_registration']['app_disabled'])
        inspector['processes']['rows']=[]
        self.assertEqual(explain(p,state,inspector)[0]['process_evidence'],'not_established')
    def test_unknown_or_malformed_inspector_never_becomes_live_evidence(self):
        p=profile('s90d');state=dict(packages=[],apps=[],dependencies=[])
        for inspector in (None,{},dict(apps=None,processes=None),dict(apps=dict(status='ok',rows=None))):
            self.assertEqual(explain(p,state,inspector)[0]['process_evidence'],'not_established')

if __name__=='__main__':unittest.main()
