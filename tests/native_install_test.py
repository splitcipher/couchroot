"""Offline transaction fault injection. No AgentTransport or network is used."""
import copy
import io
import json
import os
from pathlib import Path
import shutil
import shlex
import re
import subprocess
import tempfile
import unittest
from unittest.mock import patch
import contextlib

from tvsetup.common import Refused, atomic_json, read_json, sha
from tvsetup.config import profile
from tvsetup import installer, native_cli
from tvsetup.native_hook import HOOK, STATE_PATH, enrollment, layout, render
from tvsetup.native_install import capture, engine_for, NativeDriver, RemoteIO, replacement
from tvsetup.planner import Action
from installer_test import elf

BASELINE = b'#!/usr/bin/awk -f\nBEGIN { exit 0 }\n'
DEPENDENCY = '/opt/reviewed/dependency.awk'
RECOVERY = '/opt/reviewed/root-enabled'


class MemoryIO:
    def __init__(self):
        self.files = {HOOK: BASELINE, DEPENDENCY: b'dependency', RECOVERY: b'enabled'}
        self.events = []
        self.fail_stage = None
        self.lose_switch_reply = False
        self.bad_prerequisites = False
        self.metadata_ok = True

    def hashes(self, paths):
        return {p: sha(self.files[p]) if p in self.files else None for p in paths}

    def guards(self, files):
        if self.hashes(list(files)) != files:raise Refused('guard drift')

    def prerequisites(self):
        self.events.append('prerequisites')
        if self.bad_prerequisites:raise Refused('web fallback absent')

    def backup(self, identity, before):
        self.guards({HOOK: before})
        p = layout(identity)
        self.files.setdefault(p['previous'], self.files[HOOK])
        self.guards({p['previous']: before})
        self.events.append('backup')

    def stage(self, identity, payloads, preference):
        for index, (path, data) in enumerate(payloads.items()):
            if path in self.files and self.files[path] != data:raise Refused('staged drift')
            self.files[path] = data
            self.events.append('stage:'+path)
            if self.fail_stage == index:raise Refused('lost staging reply')
        self.files.setdefault(STATE_PATH, preference)

    def verify_payloads(self, identity, files):
        self.guards(files)
        if not self.metadata_ok:raise Refused('metadata drift')
        self.events.append('verified')

    def switch(self, identity, before, after, reverse=False):
        p = layout(identity)
        source = p['previous'] if reverse else p['hook']
        self.guards({HOOK: before, source: after})
        self.files[HOOK] = self.files[source]
        self.events.append('restore' if reverse else 'switch')
        if self.lose_switch_reply:raise Refused('lost switch reply')


def fixture(root):
    bundle = root/'bundle';bundle.mkdir()
    (bundle/'native-hub').write_bytes(elf())
    prefs = b'COUCHROOT1 0 0 0 0\nexample.app\tExample\n'
    (bundle/'native-state').write_bytes(prefs)
    atomic_json(bundle/'manifest.json', {'kind':'couchroot-preparation', 'device':'qn90a', 'launcher':'native',
                'target': {k:profile('qn90a')[k] for k in ('model','firmware','platform','architecture')},
                'files': {n:{'sha256':sha((bundle/n).read_bytes()), 'bytes':(bundle/n).stat().st_size}
                          for n in ('native-hub','native-state')}})
    (root/'baseline.awk').write_bytes(BASELINE)
    (root/'dep.awk').write_bytes(b'dependency')
    baseline = root/'enrollment.json'
    atomic_json(baseline, {'schema':1, 'device':'qn90a', 'firmware':profile('qn90a')['firmware'],
                          'hook':{'path':HOOK, 'file':'baseline.awk', 'sha256':sha(BASELINE)},
                          'dependencies':[{'path':DEPENDENCY,'file':'dep.awk','sha256':sha(b'dependency')}],
                          'recovery_guards':{RECOVERY:sha(b'enabled')}})
    return bundle, baseline


class NativeTransactionTests(unittest.TestCase):
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory();self.addCleanup(self.temp.cleanup)
        self.root = Path(self.temp.name).resolve()
        self.bundle, self.baseline = fixture(self.root)
        self.folder = self.root/'state/runs/run-001'
        self.info = capture(self.folder, self.bundle, self.baseline)
        self.io = MemoryIO()
        self.driver, self.engine = engine_for(self.io, self.folder, self.info, 'bound', self.root/'state')

    def start(self):
        self.driver.preflight()
        self.engine.prepare(self.driver.proposal(), self.driver.snapshot())
        self.engine.apply();self.engine.finalize()

    def reload(self):
        doc = read_json(self.engine.path)
        self.driver, self.engine = engine_for(self.io, self.folder, doc['actions'][0]['info'], 'bound', self.root/'state')
        self.engine.load()

    def test_install_verifies_before_switch_and_preserves_choices(self):
        saved = {'components':['dashboard'], 'artifacts':{'hub':'private'}}
        atomic_json(self.root/'state/qn90a-choices.json', saved)
        self.start()
        self.assertEqual(self.engine.doc['scope'], 'launcher-native')
        self.assertEqual(self.engine.doc['phase'], 'complete')
        self.assertLess(self.io.events.index('verified'), self.io.events.index('switch'))
        self.assertEqual(self.io.hashes([HOOK])[HOOK], self.driver.after)
        self.assertEqual(read_json(self.root/'state/qn90a-choices.json'), saved)
        self.assertEqual(self.io.files[DEPENDENCY], b'dependency')
        self.assertEqual(self.io.files[RECOVERY], b'enabled')

    def test_recovery_never_rebuilds_from_mutated_or_deleted_original_inputs(self):
        self.start()
        shutil.rmtree(self.bundle);self.baseline.unlink();(self.root/'baseline.awk').write_bytes(b'changed')
        self.reload();self.engine.rollback()
        self.assertEqual(self.io.files[HOOK], BASELINE)
        self.assertEqual(self.engine.doc['phase'], 'rolled-back')
        self.assertIn(layout(self.folder.name)['binary'], self.io.files)
        self.assertIn(STATE_PATH, self.io.files)

    def test_lost_activation_reply_reconciles_without_second_switch(self):
        self.io.lose_switch_reply = True
        with self.assertRaises(Refused):self.start()
        self.assertEqual(self.engine.doc['phase'], 'partial')
        self.io.lose_switch_reply = False
        self.reload();self.engine.reconcile();self.engine.apply();self.engine.finalize()
        self.assertEqual(self.io.events.count('switch'), 1)
        self.assertEqual(self.engine.doc['phase'], 'complete')

    def test_each_partial_staging_failure_requires_explicit_retry_then_completes(self):
        for index in range(len(self.info['payload_paths'])):
            with self.subTest(index=index):
                io = MemoryIO();io.fail_stage = index
                folder = self.root/'state/runs'/('stage-'+str(index))
                info = capture(folder, self.bundle, self.baseline)
                (self.root/'stage-state').mkdir(exist_ok=True)
                d, e = engine_for(io, folder, info, 'bound', self.root/'stage-state')
                with self.assertRaises(Refused):e.start(d.proposal(), d.snapshot())
                self.assertEqual(io.files[HOOK], BASELINE)
                with self.assertRaisesRegex(Refused, 'retry-unchanged'):e.reconcile()
                io.fail_stage = None;e.reconcile(True);e.apply();e.finalize()
                self.assertEqual(io.events.count('switch'), 1)

    def test_rollback_partial_staging_retains_data_and_does_not_activate(self):
        self.io.fail_stage = 2
        with self.assertRaises(Refused):self.start()
        self.reload();self.engine.rollback()
        self.assertEqual(self.io.files[HOOK], BASELINE)
        self.assertNotIn('switch', self.io.events)
        self.assertEqual(self.engine.doc['phase'], 'rolled-back')

    def test_lost_rollback_reply_can_be_reconciled_without_replaying_restore(self):
        self.start();self.io.lose_switch_reply = True
        with self.assertRaises(Refused):self.engine.rollback()
        self.assertEqual(self.engine.doc['phase'], 'rollback-partial')
        self.io.lose_switch_reply = False
        self.reload();self.engine.rollback()
        self.assertEqual(self.io.events.count('restore'), 1)
        self.assertEqual(self.io.files[HOOK], BASELINE)

    def test_backup_loss_retries_verified_backup_before_activation(self):
        original = self.io.backup
        def lost(*args):original(*args);raise Refused('lost backup reply')
        with patch.object(self.io, 'backup', side_effect=lost), self.assertRaises(Refused):self.start()
        self.reload();self.engine.reconcile();self.engine.apply();self.engine.finalize()
        self.assertEqual(self.io.events.count('switch'), 1)

    def test_hook_drift_never_overwritten_on_rollback(self):
        self.start();self.io.files[HOOK] = b'owner edit'
        with self.assertRaises(Refused):self.engine.rollback()
        self.assertEqual(self.io.files[HOOK], b'owner edit')

    def test_corrupt_remote_backup_or_dependencies_block_restore(self):
        self.start()
        for path in (layout(self.folder.name)['previous'], DEPENDENCY, RECOVERY):
            with self.subTest(path=path):
                old = self.io.files[path];self.io.files[path] = b'drift'
                with self.assertRaises(Refused):self.engine.rollback()
                self.assertEqual(self.io.hashes([HOOK])[HOOK], self.driver.after)
                self.io.files[path] = old

    def test_corrupt_native_payload_blocks_reconcile_but_not_hook_recovery(self):
        self.io.lose_switch_reply = True
        with self.assertRaises(Refused):self.start()
        self.io.lose_switch_reply = False
        self.io.files[layout(self.folder.name)['binary']] = b'bad native'
        with self.assertRaises(Refused):self.engine.reconcile()
        self.engine.rollback()
        self.assertEqual(self.io.files[HOOK], BASELINE)

    def test_preserves_runtime_preferences_across_install_and_rollback(self):
        self.io.files[STATE_PATH] = b'owner preferences'
        self.start();self.engine.rollback()
        self.assertEqual(self.io.files[STATE_PATH], b'owner preferences')

    def test_metadata_or_fallback_failure_prevents_hook_activation(self):
        for field in ('metadata_ok', 'bad_prerequisites'):
            with self.subTest(field=field):
                setattr(self.io, field, field == 'bad_prerequisites')
                with self.assertRaises(Refused):self.start()
                self.assertEqual(self.io.files[HOOK], BASELINE)
                setattr(self.io, field, field == 'metadata_ok')

    def test_mutated_captured_payload_blocks_apply(self):
        path = self.folder/'native-inputs'/self.info['files'][layout(self.folder.name)['binary']]['file']
        path.write_bytes(b'bad')
        with self.assertRaises(Refused):self.engine.prepare(self.driver.proposal(), self.driver.snapshot())
        self.assertEqual(self.io.files[HOOK], BASELINE)

    def test_journal_capture_mismatch_and_foreign_action_refused(self):
        changed = copy.deepcopy(self.info);changed['files'][HOOK]['sha256'] = sha(b'other')
        with self.assertRaises(Refused):NativeDriver(self.io, self.folder, changed)
        action = Action('foreign','startup','file',self.driver.before,self.driver.after,{'path':'/opt/foreign'})
        with self.assertRaises(Refused):self.driver.prepare(action)

    def test_preexisting_staged_drift_blocks_retry(self):
        self.io.fail_stage = 0
        with self.assertRaises(Refused):self.start()
        first = self.info['payload_paths'][0];self.io.files[first] = b'foreign'
        self.io.fail_stage = None;self.engine.reconcile(True)
        with self.assertRaises(Refused):self.engine.apply()
        self.assertEqual(self.io.files[HOOK], BASELINE)


class HookEnrollmentTests(unittest.TestCase):
    def test_enrollment_rejects_missing_hashes_traversal_and_existing_native_chain(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp);_, config = fixture(root);original = read_json(config)
            changes = [lambda x:x['hook'].update(sha256='bad'),
                       lambda x:x['dependencies'][0].update(path='/opt/x/../file'),
                       lambda x:x.update(recovery_guards={}),
                       lambda x:x.update(recovery_guards={HOOK:sha(BASELINE)}),
                       lambda x:x.update(firmware='unknown')]
            for edit in changes:
                data = copy.deepcopy(original);edit(data);atomic_json(config,data)
                with self.assertRaises(Refused):enrollment(config)
            atomic_json(config, original)
            (root/'dep.awk').write_bytes(b'COUCHROOT_NATIVE_HOME=1')
            original['dependencies'][0]['sha256'] = sha((root/'dep.awk').read_bytes());atomic_json(config,original)
            with self.assertRaisesRegex(Refused, 'Existing native'):enrollment(config)

    def test_generated_shell_syntax_and_awk_probe_are_offline(self):
        with tempfile.TemporaryDirectory() as tmp:
            for rearm in (False, True):
                files = render('example-run', sha(elf()), sha(BASELINE), {DEPENDENCY:sha(b'dependency')}, rearm=rearm)
                self.assertEqual(b'COUCHROOT_NATIVE_SOURCE_REARM=1' in files['dispatch.sh'], rearm)
                for name in ('dispatch.sh','watch.sh'):
                    result = subprocess.run(['/bin/sh','-n'],input=files[name],capture_output=True)
                    self.assertEqual(result.returncode,0,result.stderr.decode())
                encoded = re.search(r'rc=system\((.*)\); exit', files['hook.awk'].decode())[1]
                command = shlex.split(json.loads(encoded))
                shell = subprocess.run(['/bin/sh','-n'],input=command[2].encode(),capture_output=True)
                self.assertEqual(shell.returncode,0,shell.stderr.decode())
                path = Path(tmp)/'hook.awk';path.write_bytes(files['hook.awk'])
                probe = subprocess.run(['awk','-f',str(path),'couchroot-probe'],capture_output=True,text=True)
                self.assertEqual(probe.returncode,0,probe.stderr)
                self.assertEqual(probe.stdout.strip(),'COUCHROOT_NATIVE_INSTALLER_OK')
                self.assertNotIn(b'--source-rearm-shutdown',files['dispatch.sh'])
                self.assertNotIn(b'Reboot',files['dispatch.sh'])
                self.assertIn(b'--native-guard --stay',files['dispatch.sh'])
                self.assertIn(b'CPUSchedulingPolicy=other',files['dispatch.sh'])

    def test_failed_native_admission_still_runs_the_known_synthetic_baseline(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();p=layout('fallback-test')
            baseline=b'#!/usr/bin/awk -f\nBEGIN { print "BASELINE_OK" }\n'
            files=render('fallback-test',sha(elf()),sha(baseline),{RECOVERY:sha(b'enabled')})
            encoded=re.search(r'rc=system\((.*)\); exit',files['hook.awk'].decode())[1]
            script=shlex.split(json.loads(encoded))[2].replace('/opt',str(root/'opt'))
            previous=root/'opt'/p['previous'].removeprefix('/opt/');previous.parent.mkdir(parents=True);previous.write_bytes(baseline)
            dispatch=root/'opt'/p['dispatch'].removeprefix('/opt/');dispatch.write_bytes(b'echo SHOULD_NOT_RUN\n')
            guard=root/'opt'/RECOVERY.removeprefix('/opt/');guard.parent.mkdir(parents=True)
            env = dict(os.environ)
            if not shutil.which('sha256sum'):
                commands=root/'commands';commands.mkdir()
                checksum=commands/'sha256sum';checksum.write_text('#!/bin/sh\nexec shasum -a 256 "$@"\n');checksum.chmod(0o755)
                env['PATH']=str(commands)+os.pathsep+env['PATH']
            # Test both a missing recovery guard and a corrupt native dispatcher.
            for guard_present in (False,True):
                if guard_present:guard.write_bytes(b'enabled')
                completed=subprocess.run(['/bin/sh'],input=script.encode(),capture_output=True,env=env)
                self.assertEqual(completed.returncode,0,completed.stderr.decode())
                self.assertEqual(completed.stdout.strip(),b'BASELINE_OK')

    def test_atomic_replace_script_on_local_files_and_foreign_temp_refusal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve();bins = root/'bin';bins.mkdir()
            # Portable cp shim for macOS; all files remain in this temporary tree.
            cp = bins/'cp';cp.write_text('#!/bin/sh\nif test "$1" = --preserve=all; then shift; fi\nexec /bin/cp -p "$@"\n');cp.chmod(0o755)
            if not shutil.which('sha256sum'):
                h=bins/'sha256sum';h.write_text('#!/bin/sh\nexec shasum -a 256 "$@"\n');h.chmod(0o755)
            current, source, temporary = [root/x for x in ('current','source','new')]
            current.write_bytes(b'before');source.write_bytes(b'after')
            script = replacement(str(current),str(source),sha(b'before'),sha(b'after'),str(temporary))
            env={**os.environ,'PATH':str(bins)+os.pathsep+os.environ['PATH']}
            temporary.write_bytes(b'foreign')
            r=subprocess.run(['/bin/sh'],input=script.encode(),env=env,capture_output=True)
            self.assertNotEqual(r.returncode,0);self.assertEqual(current.read_bytes(),b'before')
            temporary.unlink()
            r=subprocess.run(['/bin/sh'],input=script.encode(),env=env,capture_output=True)
            self.assertEqual(r.returncode,0,r.stderr.decode());self.assertEqual(current.read_bytes(),b'after')
            self.assertFalse(temporary.exists())


class SandboxTV:
    """Run generated file-management shell only in a temporary local /opt tree.

    Device-only ownership/Smack operations are stubbed; no service/startup shell
    or captured baseline program is ever executed here.
    """
    def __init__(self, root):
        self.root = root
        self.uploads = 0
        bins = root/'commands';bins.mkdir()
        scripts = {
            'cp': '#!/bin/sh\nif test "$1" = --preserve=all; then shift; fi\nexec /bin/cp -p "$@"\n',
            'chown': '#!/bin/sh\nexit 0\n',
            'chsmack': '#!/bin/sh\nif test "$1" = -a; then exit 0; fi\nprintf \'%s\\n\' \'access="User"\'\n',
            'stat': '#!/bin/sh\ncase "$3" in */preferences) echo 5001:100:600;; *) if test -d "$3"; then echo 0:0:755; else echo 0:0:555; fi;; esac\n',
        }
        if not shutil.which('sha256sum'):scripts['sha256sum'] = '#!/bin/sh\nexec shasum -a 256 "$@"\n'
        for name, text in scripts.items():
            path = bins/name;path.write_text(text);path.chmod(0o755)
        self.env = {**os.environ, 'PATH': str(bins)+os.pathsep+os.environ['PATH']}

    def path(self, remote):return self.root/'opt'/remote.removeprefix('/opt/')

    def root_command(self, script):
        # Guards are generated too; reject any accidental service operations in
        # the install/recovery layer before executing even in this sandbox.
        assert 'systemctl' not in script and 'systemd-run' not in script and 'vconftool' not in script
        script = script.replace('/opt', str(self.root/'opt'))
        value = subprocess.run(['/bin/sh'], input=script.encode(), env=self.env, capture_output=True)
        if value.returncode:raise Refused('sandbox shell refused: '+value.stderr.decode())
        return value.stdout.decode()

    def _upload(self, data, target):
        self.uploads += 1
        with self.path(target).open('xb') as stream:stream.write(data)


class RemoteShellTests(unittest.TestCase):
    def test_actual_staging_verification_activation_and_restore_shell(self):
        with tempfile.TemporaryDirectory() as tmp:
            root = Path(tmp).resolve();tv = SandboxTV(root)
            # Avoid shadowing the root() transport method with the sandbox path.
            adapter = type('Adapter', (), {'root': staticmethod(tv.root_command), '_upload': staticmethod(tv._upload)})()
            remote = RemoteIO(adapter)
            original = tv.path(HOOK);original.parent.mkdir(parents=True);original.write_bytes(BASELINE)
            identity = 'shell-run';p=layout(identity)
            remote.backup(identity, sha(BASELINE))
            files = render(identity, sha(elf()), sha(BASELINE), {})
            payloads = {p['binary']: elf(), **{p['base']+'/'+n:b for n,b in files.items()}}
            pref = b'COUCHROOT1 0 0 0 0\n'
            remote.stage(identity,payloads,pref)
            hashes={path:sha(data) for path,data in payloads.items()}
            remote.verify_payloads(identity,hashes)
            count=tv.uploads
            tv.path(STATE_PATH).write_bytes(b'owner changed preferences')
            remote.stage(identity,payloads,pref)
            self.assertEqual(tv.uploads,count)
            self.assertEqual(tv.path(STATE_PATH).read_bytes(),b'owner changed preferences')
            remote.switch(identity,sha(BASELINE),sha(files['hook.awk']))
            self.assertEqual(original.read_bytes(),files['hook.awk'])
            remote.switch(identity,sha(files['hook.awk']),sha(BASELINE),reverse=True)
            self.assertEqual(original.read_bytes(),BASELINE)
            self.assertTrue(tv.path(p['binary']).exists())

    def test_unowned_state_directory_is_not_adopted_or_overwritten(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp).resolve();tv=SandboxTV(root)
            adapter=type('Adapter',(),{'root':staticmethod(tv.root_command),'_upload':staticmethod(tv._upload)})()
            remote=RemoteIO(adapter)
            original=tv.path(HOOK);original.parent.mkdir(parents=True);original.write_bytes(BASELINE)
            state=tv.path(STATE_PATH);state.parent.mkdir();state.write_bytes(b'foreign')
            remote.backup('foreign-test',sha(BASELINE))
            with self.assertRaises(Refused):remote.stage('foreign-test',{},b'new')
            self.assertEqual(state.read_bytes(),b'foreign')


class NativePreflightTests(unittest.TestCase):
    def test_web_fallback_drift_is_refused_before_any_root_mutation(self):
        from unittest.mock import Mock
        from tv_setup_planner_test import accepted, profile as fixture_profile
        tv=Mock();tv.profile=fixture_profile('qn90a');tv.snapshot.return_value=accepted('qn90a')
        remote=RemoteIO(tv);remote.prerequisites()
        self.assertEqual(tv.root.call_count,1)
        self.assertIn('vconftool get',tv.root.call_args.args[0])
        self.assertNotIn('vconftool set',tv.root.call_args.args[0])
        tv.root.reset_mock()
        tv.snapshot.return_value['files']['/opt/usr/apps/MiniHub001/res/wgt/style.css']='changed'
        with self.assertRaises(Refused):remote.prerequisites()
        tv.root.assert_not_called()

    def test_agent_binding_changes_with_pins_and_client_identity(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);cert=root/'client.crt';cert.write_bytes(b'public test certificate')
            config={'device':'qn90a','host':'192.0.2.11','port':28443,'server_sha256':'a'*64,'client_certificate':str(cert)}
            path=root/'client.json';atomic_json(path,config)
            site={'devices':{'qn90a':{'host':'192.0.2.11','device_id':'uuid:00000000-0000-4000-8000-000000000001'}}}
            before=native_cli.agent_binding(site,'qn90a',path)
            config['server_sha256']='b'*64;atomic_json(path,config)
            self.assertNotEqual(before,native_cli.agent_binding(site,'qn90a',path))
            config['server_sha256']='a'*64;atomic_json(path,config);cert.write_bytes(b'other public certificate')
            self.assertNotEqual(before,native_cli.agent_binding(site,'qn90a',path))


def invoke_recovery_backend(args):
    """Seed old journals through the retained backend, not the retired front door."""
    values=list(args); values[values.index('--launcher')+1]='web'
    parsed=installer.parser().parse_args(values); parsed.launcher='native'
    try:
        if parsed.dry_run:
            installer.emit(installer.dispatch(parsed), parsed.json)
            return 0
        return native_cli.main(parsed)
    except Refused:
        return 1


class NativeCLITests(unittest.TestCase):
    def invoke(self,args):
        out=io.StringIO()
        with contextlib.redirect_stdout(out),contextlib.redirect_stderr(io.StringIO()):
            code=invoke_recovery_backend(args)
        return code,out.getvalue()

    def test_full_cli_apply_status_resume_rollback_uses_captured_journal(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bundle,baseline=fixture(root);state=root/'state';memory=MemoryIO()
            common=['--device','qn90a','--launcher','native','--json']
            with patch.object(native_cli,'STATE',state),patch.object(native_cli,'load_site',return_value={}),patch.object(native_cli,'configured_profile',return_value={}),patch.object(native_cli,'agent_binding',return_value='bound'),patch.object(native_cli,'connect',return_value=memory) as connect:
                args=['apply',*common,'--yes','--agent','unused','--bundle',str(bundle),'--hook-config',str(baseline)]
                code,out=self.invoke(args);self.assertEqual(code,0,out)
                run=json.loads(out)['run']
                shutil.rmtree(bundle);baseline.unlink()
                connect.reset_mock()
                code,out=self.invoke(['status',*common,'--run',run]);self.assertEqual(code,0,out);connect.assert_not_called()
                code,out=self.invoke(['verify',*common,'--agent','unused','--run',run]);self.assertEqual(code,0,out)
                code,out=self.invoke(['rollback',*common,'--yes','--agent','unused','--run',run]);self.assertEqual(code,0,out)
                self.assertEqual(json.loads(out)['phase'],'rolled-back');self.assertEqual(memory.files[HOOK],BASELINE)
                code,out=self.invoke(['verify',*common,'--agent','unused','--run',run]);self.assertEqual(code,0,out)
                self.assertEqual(json.loads(out)['configuration'],'baseline-restored')

    def test_native_input_errors_and_dry_run_never_connect(self):
        with patch.object(native_cli,'connect') as connect,patch.object(native_cli,'load_site') as site:
            code,_=self.invoke(['apply','--device','qn90a','--launcher','native','--yes'])
            self.assertEqual(code,1)
            code,_=self.invoke(['apply','--device','qn90a','--launcher','native','--dry-run'])
            self.assertEqual(code,0);connect.assert_not_called();site.assert_not_called()

    def test_pending_run_blocks_new_apply_and_changed_binding_blocks_recovery(self):
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bundle,baseline=fixture(root);state=root/'state';memory=MemoryIO()
            common=['--device','qn90a','--launcher','native','--json']
            with patch.object(native_cli,'STATE',state),patch.object(native_cli,'load_site',return_value={}),patch.object(native_cli,'configured_profile',return_value={}),patch.object(native_cli,'agent_binding',return_value='bound') as binding,patch.object(native_cli,'connect',return_value=memory) as connect:
                memory.lose_switch_reply=True
                args=['apply',*common,'--yes','--agent','unused','--bundle',str(bundle),'--hook-config',str(baseline)]
                code,_=self.invoke(args);self.assertEqual(code,1)
                run=next((state/'runs').iterdir()).name
                connect.reset_mock()
                code,_=self.invoke(args);self.assertEqual(code,1);connect.assert_not_called()
                binding.return_value='different'
                code,_=self.invoke(['rollback',*common,'--yes','--agent','unused','--run',run])
                self.assertEqual(code,1);connect.assert_not_called()

    def test_finalization_resume_has_no_device_connection(self):
        from tvsetup.engine import Engine
        with tempfile.TemporaryDirectory() as tmp:
            root=Path(tmp);bundle,baseline=fixture(root);state=root/'state';memory=MemoryIO()
            common=['--device','qn90a','--launcher','native','--json']
            with patch.object(native_cli,'STATE',state),patch.object(native_cli,'load_site',return_value={}),patch.object(native_cli,'configured_profile',return_value={}),patch.object(native_cli,'agent_binding',return_value='bound'),patch.object(native_cli,'connect',return_value=memory) as connect:
                with patch.object(Engine,'finalize',side_effect=OSError('disk full')):
                    code,_=self.invoke(['apply',*common,'--yes','--agent','unused','--bundle',str(bundle),'--hook-config',str(baseline)])
                    self.assertEqual(code,1)
                run=next((state/'runs').iterdir()).name
                connect.reset_mock()
                code,out=self.invoke(['resume',*common,'--yes','--agent','unused','--run',run])
                self.assertEqual(code,0,out);connect.assert_not_called()
                self.assertEqual(json.loads(out)['phase'],'complete')

    def test_identity_mismatch_refuses_before_agent_constructor(self):
        with patch.object(native_cli,'identity',side_effect=Refused('wrong device')),patch('tvsetup.agent_transport.AgentTransport') as agent:
            with self.assertRaises(Refused):native_cli.connect({},Path('/unused'),Path('/unused'))
            agent.assert_not_called()


if __name__ == '__main__':unittest.main()
