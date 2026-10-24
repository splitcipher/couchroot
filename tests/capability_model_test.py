import unittest
from research.offline_models.capabilities import display_methods, sources
from tvsetup.common import Refused

class CapabilityModelTests(unittest.TestCase):
    def test_signatures_bound_to_firmware_never_authorize_control(self):
        xml='<node><interface name="fixture.Display"><method name="Read"><arg type="i"/><arg direction="out" type="a{sv}"/></method></interface></node>'
        r=display_methods(xml,'T-FIXTURE-1.0');row=r['methods'][0]
        self.assertEqual(row['input_signature'],'i');self.assertEqual(row['output_signature'],'a{sv}')
        self.assertFalse(row['write_admitted']);self.assertFalse(r['live_probe']);self.assertFalse(r['control_admission'])
        for bad in ['<', '<!DOCTYPE node>'+xml, xml.replace('direction="out"','direction="other"'),xml.replace('type="i"','type="$(bad)"'),xml.replace('</interface>','<method name="Read"/></interface>')]:
            with self.assertRaises(Refused):display_methods(bad,'T-FIXTURE-1.0')
    def test_sources_disconnected_multiple_unknown_and_duplicates(self):
        records=[dict(type='TV',number=0,connected=True),dict(type='HDMI',number=1,connected=False),dict(type='HDMI',number=2,connected=True)]
        r=sources(records);self.assertEqual(len(r),3);self.assertEqual(r[2]['signal'],'not_observed')
        self.assertEqual(r[2]['handoff'],'not_verified');self.assertEqual(sources([]),[])
        for bad in [records+[records[0]],[dict(type='unknown',number=1,connected=True)],[None]]:
            with self.assertRaises(Refused):sources(bad)

if __name__=='__main__':unittest.main()
