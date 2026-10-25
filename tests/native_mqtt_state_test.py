"""Feature-2 native projection, bounded reader and real loopback MQTT tests."""
import json
import os
from pathlib import Path
import time
import unittest
import native_mqtt_test as fixtures


@unittest.skipUnless(os.environ.get('MQTT_HARNESS'), 'disposable Linux harness required')
class MqttStateTests(unittest.TestCase):
    # Reuse the broker fixture without rerunning inherited protocol cases.
    setUp = fixtures.MqttTests.setUp
    save = fixtures.MqttTests.save
    cli = fixtures.MqttTests.cli
    start = fixtures.MqttTests.start
    stop = fixtures.MqttTests.stop
    receive = fixtures.MqttTests.receive
    handshake = fixtures.MqttTests.handshake
    publish = fixtures.MqttTests.publish
    publications = fixtures.MqttTests.publications
    def projection(self, observation, fresh=True, foreground='example.App'):
        return json.loads(self.cli('projection', input=json.dumps(dict(
            observation=observation, fresh=fresh, foreground=foreground))))

    def test_read_capabilities_never_enable_any_command_entity(self):
        # Exercise discovery directly with every capability asserted, including
        # control keys: adapter support is not permission to offer a setter.
        for device in ['qn90a', 's90d']:
            self.settings.update(device=device, state=True, control=True)
            self.credentials.write_text('MQTT_USER=tv-' + device +
                                        '\nMQTT_PASSWORD=' + self.secret + '\n')
            self.save()
            cmps = json.loads(self.cli('discovery-all-supported',
                                      str(self.config), device))['cmps']
            self.assertEqual(len(cmps), 27)
            self.assertEqual(len({e['unique_id'] for e in cmps.values()}), 27)
            controls = {k for k, e in cmps.items() if 'command_topic' in e}
            self.assertEqual(controls, {'power', 'screen', 'mute', 'game_mode',
                'kid_mode', 'telemetry_block', 'source', 'app_select',
                'picture_mode', 'audio_output', 'volume', 'sleep_timer',
                'screen_message'})
            for key in controls:
                self.assertEqual(cmps[key]['availability_topic'],
                                 'tv/' + device + '/unsupported', key)
            for key in ['app', 'cpu', 'memory', 'agent_uptime']:
                self.assertEqual(cmps[key]['availability_topic'],
                                 'tv/' + device + '/availability', key)

    def test_metrics_warmup_reset_gap_malformed_and_recovery(self):
        def sample(at, stat, mem='MemTotal: 2000 kB\nMemAvailable: 500 kB\n'):
            return dict(at=at, stat=stat, mem=mem)
        rows = [sample(0, 'cpu 100 0 100 800 0 0 0 0 999 999\n'),
                sample(2000, 'cpu 150 0 150 900 0 0 0 0 9999 9999\n'),
                sample(4000, None),
                sample(6000, 'cpu 200 0 200 1000 0 0 0 0\n'),
                sample(8000, 'cpu 200 0 200 1000 0 0 0 0\n'),
                sample(10000, 'cpu 1 0 1 2 0 0 0 0\n'),
                sample(60000, 'cpu 2 0 2 4 0 0 0 0\n'),
                sample(62000, 'cpu 3 0 3 6 0 0 0 0\n'),
                sample(64000, 'cpu -1 0 1 1 0 0 0 0\n', 'MemTotal: 1 kB\nMemAvailable: 2 kB\n')]
        result = json.loads(self.cli('metrics', input=json.dumps({'samples': rows})))
        self.assertEqual([r['cpu'] for r in result], [None,50,None,None,None,None,None,50,None])
        self.assertEqual([r['memory'] for r in result], [75]*8+[None])
        for stat in ['cpu 18446744073709551616 0 1 1 0 0 0 0', 'cpu 1x 0 1 1 0 0 0 0', 'cpu 1 2']:
            r = json.loads(self.cli('metrics', input=json.dumps({'samples':[sample(0,stat,'MemTotal: 10 kB\nMemAvailable: 1 kB\nMemAvailable: 2 kB\n')]})))
            self.assertEqual(r,[{'cpu':None,'memory':None}])

    def test_capabilities_options_ambiguity_staleness_and_type_projection(self):
        observation = dict(state=dict(volume=15,muted=False,input='hdmi2',resolution='3840x2160',refresh_hz=60,app_id='example.App',app_name='Current'),
                           supported=dict(volume=True,muted=True,input=True,resolution=True,app=True),
                           apps=[dict(id='a',name='Duplicate'),dict(id='b',name='Z'),dict(id='c',name='Duplicate')],sources=['hdmi2','tv'])
        result = self.projection(observation)
        self.assertEqual(result['state']['app_name'],'Current')
        self.assertIsNone(result['state']['signal']['resolution'])
        cmps=result['discovery']['cmps']
        self.assertEqual(cmps['app_select']['options'],['Z'])
        self.assertEqual(cmps['source']['options'],['hdmi2','tv'])
        for key in ['app']:
            self.assertEqual(cmps[key]['availability_topic'],'tv/qn90a/availability')
        for key in ['input','resolution','refresh_rate','source','app_select','volume','mute','audio_output','temperature']:
            self.assertEqual(cmps[key]['availability_topic'],'tv/qn90a/unsupported')
        stale=self.projection(observation,False)
        self.assertEqual(stale['discovery'],result['discovery'])
        for key in ['app_name','volume','muted','input']:self.assertIsNone(stale['state'][key])
        self.assertIsNone(self.projection(observation,foreground='other.App')['state']['app_name'])
        observation['state'].update(volume='15',muted=1,resolution='3840x2160x',app_name='bad\0name')
        invalid=self.projection(observation)['state']
        self.assertIsNone(invalid['volume']);self.assertIsNone(invalid['muted']);self.assertIsNone(invalid['app_name'])
        self.assertIsNone(invalid['signal']['resolution'])
        for value in [None,{}, {'state':[],'supported':[]}, {'apps':'not an array','sources':True}]:
            self.assertIsNone(self.projection(value)['state']['input'])

    def test_foreground_reader_bounds_exit_hang_truncation_and_recovery(self):
        script = self.root/'reader'
        def run(body):
            script.write_text('#!/bin/sh\n'+body+'\n');script.chmod(0o700)
            started=time.monotonic()
            result=json.loads(self.cli('foreground',str(script)))
            self.assertLess(time.monotonic()-started,2)
            return result
        self.assertEqual(run('printf example.App'),dict(support=1,id='example.App'))
        self.assertEqual(run('exit 3'),dict(support=0,id=''))
        self.assertEqual(run('exit 2'),dict(support=1,id=''))
        self.assertEqual(run('while :; do :; done'),dict(support=-1,id=''))
        self.assertEqual(run('printf "bad app"'),dict(support=-1,id=''))
        self.assertEqual(run('printf '+ 'a'*300),dict(support=-1,id=''))
        self.assertEqual(run('printf recovered.App'),dict(support=1,id='recovered.App'))

    def test_runtime_inventory_changes_republish_but_state_ticks_do_not(self):
        self.start(mode='simulate'); initial=self.publications(5)
        d=json.loads(initial['homeassistant/device/tv_qn90a/config'][1])
        self.assertEqual(d['cmps']['cpu']['availability_topic'],'tv/qn90a/availability')
        observation=dict(state=dict(volume=15),supported=dict(volume=True),apps=[dict(id='app.A',name='A')],sources=['tv'])
        self.proc.stdin.write((json.dumps(observation)+'\n').encode());self.proc.stdin.flush()
        changed=self.publications(4)
        self.assertEqual(json.loads(changed['homeassistant/device/tv_qn90a/config'][1])['cmps']['app_select']['options'],['A'])
        self.assertEqual(json.loads(changed['tv/qn90a/state'][1])['volume'],15)
        observation['state']['volume']=16
        self.proc.stdin.write((json.dumps(observation)+'\n').encode());self.proc.stdin.flush()
        state=self.publications(1);self.assertEqual(list(state),['tv/qn90a/state'])
        self.assertEqual(json.loads(state['tv/qn90a/state'][1])['volume'],16)
        # A stalled coordinator's last reading becomes unknown, without dropping
        # its supported adapter or constantly republishing the same discovery.
        state=self.publications(1,timeout=9)
        self.assertIsNone(json.loads(state['tv/qn90a/state'][1])['volume'])
        observation['apps']=[]
        self.proc.stdin.write((json.dumps(observation)+'\n').encode());self.proc.stdin.flush()
        removed=self.publications(4)
        self.assertEqual(json.loads(removed['homeassistant/device/tv_qn90a/config'][1])['cmps']['app_select']['options'],[])

    def test_state_disabled_keeps_new_adapters_unavailable(self):
        self.settings['state']=False
        self.start(); initial=self.publications(5)
        d=json.loads(initial['homeassistant/device/tv_qn90a/config'][1])
        for key in ['cpu','memory','app','input','resolution']:
            self.assertEqual(d['cmps'][key]['availability_topic'],'tv/qn90a/unsupported')
        h=json.loads(initial['tv/qn90a/health'][1]);self.assertIsNone(h['cpu_pct']);self.assertIsNone(h['mem_used_pct'])
