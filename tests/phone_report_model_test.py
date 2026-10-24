import unittest
from research.offline_models.phone_report import render
from tvsetup.common import Refused

class PhoneReportTests(unittest.TestCase):
    def fixture(self):return dict(schema=1,date='2026-10-24',target=dict(model='QN55S90DAFXZA',platform='24_PONTUSM_UHD'),milestones={'cold_boot':dict(result='not tested',evidence='private-token')})
    def test_strict_projection_has_no_commands_network_or_arbitrary_evidence(self):
        doc=self.fixture();doc.update(token='private-token',server_key='private-key');doc['target']['firmware']='<script>secret()</script>'
        html=render(doc)
        for forbidden in ('private-token','private-key','<script','http://','https://','secret()'):self.assertNotIn(forbidden,html)
        self.assertIn('2026-10-24',html);self.assertIn("default-src 'none'",html)
        self.assertIn('not tested',html)
        doc['target']['model']='http://secret';self.assertNotIn('http://secret',render(doc))
    def test_missing_invalid_date_or_schema_refuses(self):
        for edit in ({'schema':2},{'date':'tomorrow'},{'date':None},{'target':None}):
            with self.assertRaises(Refused):render({**self.fixture(),**edit})

if __name__=='__main__':unittest.main()
