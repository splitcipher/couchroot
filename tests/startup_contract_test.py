import unittest
from dataclasses import replace
from research.offline_models.startup import Evidence, DelayedLaunch

class StartupContractTests(unittest.TestCase):
    def setUp(self):self.base=Evidence('synthetic-boot','viewer','tv','default-startup',1)
    def test_default_startup_and_once_per_boot_even_after_failed_request(self):
        claims=set();model=DelayedLaunch(self.base,claims)
        self.assertIsNone(model.tick(10,self.base,lambda:self.base))
        token=model.tick(20,self.base,lambda:self.base)
        model.complete(token,False,self.base)
        self.assertEqual(model.outcome,'request-failed')
        self.assertIsNone(model.tick(21,self.base,lambda:self.base))
        restart=DelayedLaunch(self.base,claims)
        self.assertIsNone(restart.tick(22,self.base,lambda:self.base))
    def test_user_input_changes_same_viewer_owner_or_generation_cancel_permanently(self):
        for field,value in [('source','hdmi1'),('owner','user'),('generation',2),('app','player'),('boot','new-boot'),('powered',False)]:
            with self.subTest(field=field):
                model=DelayedLaunch(self.base,set())
                self.assertIsNone(model.tick(21,replace(self.base,**{field:value}),lambda:self.base))
                self.assertIsNone(model.tick(22,self.base,lambda:self.base))
                self.assertTrue(model.cancelled)
    def test_unknown_evidence_expiry_and_last_moment_change_fail_closed(self):
        for evidence in [replace(self.base,source=None),replace(self.base,generation=None),replace(self.base,source='unknown')]:
            model=DelayedLaunch(evidence,set());self.assertIsNone(model.tick(20,evidence,lambda:evidence))
        model=DelayedLaunch(self.base,set());self.assertIsNone(model.tick(111,self.base,lambda:self.base))
        model=DelayedLaunch(self.base,set())
        self.assertIsNone(model.tick(20,self.base,lambda:replace(self.base,app='player')))
    def test_old_callback_after_cancellation_is_ignored(self):
        model=DelayedLaunch(self.base,set());token=model.tick(20,self.base,lambda:self.base)
        model.complete(token,True,replace(self.base,source='hdmi2'))
        model.complete(token,True,self.base)
        self.assertEqual(model.outcome,'cancelled')

if __name__=='__main__':unittest.main()
