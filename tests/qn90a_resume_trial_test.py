import copy
import json
from pathlib import Path
import tempfile
import unittest
from unittest.mock import patch

from tvsetup.common import Refused
from tvsetup.planner import HUB, STOCK_HOME
from tvsetup.registry import reviewed_identity
from tvsetup import qn90a_resume_trial as trial


class FakeTransport:
    def __init__(self, profile, evidence, state=None):
        self.profile = profile
        self.state = copy.deepcopy(state or {'device':'qn90a','settings':dict(trial.BASELINE)})
        self.evidence = evidence

    def snapshot(self, privileged=False):
        return copy.deepcopy(self.state)


class FakeDriver:
    def __init__(self, transport, profile, choices, folder):
        self.tv, self.profile, self.folder = transport, profile, folder

    def snapshot(self):
        return self.tv.snapshot()

    def prepare(self, action):
        return {'original_value':action.before}

    def backup(self, action, info, state):
        return info

    def execute(self, action, info, state):
        if state['settings'][action.options['key']] != action.before:
            raise Refused('state changed')
        self.tv.state['settings'][action.options['key']] = action.after

    def verify(self, action, before, after):
        if after['settings'][action.options['key']] != action.after:
            raise Refused('readback mismatch')

    def rollback(self, action, info, state):
        if state['settings'][action.options['key']] == action.after:
            self.tv.state['settings'][action.options['key']] = action.before
        elif state['settings'][action.options['key']] != action.before:
            raise Refused('drift')


class Qn90aResumeTrialTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        self.state = Path(self.tmp.name)
        self.site = {'devices':{'qn90a':{'host':'192.0.2.10','device_id':'uuid:00000000-1234-1234-1234-123456789abc'}}, '_trust':{}}
        self.profile = {'id':'qn90a', **reviewed_identity('qn90a')}
        self.transport = FakeTransport(self.profile, self.state)
        patches = [
            patch.object(trial, 'STATE', self.state),
            patch.object(trial, 'configured_profile', return_value=self.profile),
            patch.object(trial, 'TrialDriver', FakeDriver),
            patch.object(trial, 'Transport', side_effect=lambda p,e:self.transport),
        ]
        self.stack=[]
        for p in patches: self.stack.append(p); p.start()

    def tearDown(self):
        for p in reversed(self.stack):p.stop()
        self.tmp.cleanup()

    def test_wrong_model_or_firmware_refused_before_snapshot(self):
        for key in ('model', 'firmware'):
            with patch.object(trial, 'configured_profile', return_value={**self.profile, key:'wrong'}):
                with self.assertRaises(Refused):trial.start(self.site)
        self.assertFalse((self.state/'runs').exists())

    def test_unexpected_baseline_refused_without_widening(self):
        self.transport.state['settings'][trial.FIRSTSCREEN]='org.tizen.tv-viewer'
        with self.assertRaisesRegex(Refused,'Unexpected baseline'):
            trial.start(self.site)
        self.assertEqual(self.transport.state['settings'][trial.FIRSTSCREEN],'org.tizen.tv-viewer')
        self.assertEqual(trial.pending(self.state,'qn90a'),[])

    def test_start_changes_exactly_two_settings_and_leaves_pending_journal(self):
        result=trial.start(self.site)
        self.assertEqual(result['phase'],'configuration-applied')
        self.assertEqual(self.transport.state['settings'],trial.DESIRED)
        pending=trial.pending(self.state,'qn90a')
        self.assertEqual(len(pending),1)
        identity,doc=pending[0]
        self.assertEqual(doc['scope'],trial.SCOPE)
        self.assertIsNone(doc['local_before'])
        self.assertEqual(len(doc['actions']),2)
        self.assertEqual(trial.inspect(identity,self.site)['matches_trial'],True)

    def test_rollback_restores_exact_original_values_and_closes_pending(self):
        result=trial.start(self.site)
        self.assertEqual(trial.rollback(result['run'],self.site)['phase'],'rolled-back')
        self.assertEqual(self.transport.state['settings'],trial.BASELINE)
        self.assertEqual(trial.pending(self.state,'qn90a'),[])

    def test_prepared_trial_can_be_cancelled_without_mutating_tv(self):
        prepared=trial.prepare(self.site)
        self.assertEqual(prepared['phase'],'prepared')
        self.assertEqual(self.transport.state['settings'],trial.BASELINE)
        self.assertEqual(len(trial.pending(self.state,'qn90a')),1)
        rolled=trial.rollback(prepared['run'],self.site)
        self.assertEqual(rolled['phase'],'rolled-back')
        self.assertEqual(self.transport.state['settings'],trial.BASELINE)
        self.assertEqual(trial.pending(self.state,'qn90a'),[])

    def test_accept_closes_journal_without_changing_saved_choices_or_ledger(self):
        choices=self.state/'qn90a-choices.json';ledger=self.state/'qn90a-ledger.json'
        choices.write_text('{"components":["hub"]}\n');ledger.write_text('{"files":{"x":"y"}}\n')
        result=trial.start(self.site)
        before=(choices.read_bytes(),ledger.read_bytes())
        accepted=trial.accept(result['run'],self.site)
        self.assertEqual(accepted['phase'],'complete')
        self.assertFalse(accepted['saved_choices_ledger_changed'])
        self.assertEqual((choices.read_bytes(),ledger.read_bytes()),before)
        self.assertEqual(trial.pending(self.state,'qn90a'),[])

    def test_accept_rejects_drift_and_leaves_pending_journal(self):
        result=trial.start(self.site)
        self.transport.state['settings'][trial.AUTOSTART]=0
        with self.assertRaisesRegex(Refused,'readback do not match'):
            trial.accept(result['run'],self.site)
        self.assertEqual(len(trial.pending(self.state,'qn90a')),1)

    def test_accept_rejects_partial_or_uncertain_journal(self):
        result=trial.start(self.site)
        journal=self.state/'runs'/result['run']/'journal.json'
        doc=json.loads(journal.read_text());doc['actions'][1]['phase']='uncertain';journal.write_text(json.dumps(doc))
        with self.assertRaisesRegex(Refused,'uncertain, partial'):
            trial.accept(result['run'],self.site)
        self.assertEqual(len(trial.pending(self.state,'qn90a')),1)

    def test_rollback_refuses_external_drift_without_overwrite(self):
        result=trial.start(self.site)
        self.transport.state['settings'][trial.FIRSTSCREEN]='org.tizen.tv-viewer'
        with self.assertRaisesRegex(Refused,'outside the exact baseline/trial pair'):
            trial.rollback(result['run'],self.site)
        self.assertEqual(self.transport.state['settings'][trial.FIRSTSCREEN],'org.tizen.tv-viewer')
        self.assertEqual(len(trial.pending(self.state,'qn90a')),1)

    def test_helper_allowlist_is_explicit_and_separate_from_s90d_branch(self):
        source=(Path(__file__).parents[1]/'tvsetup/native/Control.cs').read_text()
        self.assertIn('qn90a-firstscreen',source)
        self.assertIn('a[1]!="qn90a" || a.Length!=5',source)
        self.assertIn('if(a[1]!="s90d" || a.Length!=5)',source)
        self.assertIn('db/first_screen/type',source)
        self.assertIn('db/menu/smart_hub/ontvsetting/auto_start',source)


if __name__ == '__main__': unittest.main()
