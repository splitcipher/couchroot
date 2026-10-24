import re
import tempfile
import unittest
from pathlib import Path
from unittest.mock import patch
from tvsetup.autonomous_root_trial import PilotTransport,PilotDriver,DATA,PREFIX,PROVISION,PACKAGE,package_files,inventory_review,reviewed_inventory,review_update
from tvsetup.operations import observed
from tvsetup.common import Refused,sha
from tvsetup.planner import Action
from service_registration_test import expected_registration

class PilotTests(unittest.TestCase):
    def test_inventory_changes_require_exact_content_bound_review(self):
        before=package_files({'service/old.js':b'old','config.xml':b'v1'})
        after=package_files({'service/new.js':b'new','config.xml':b'v2'})
        review=inventory_review(before,after)
        self.assertEqual(review['added'],[PREFIX+'service/new.js'])
        self.assertEqual(review['removed'],[PREFIX+'service/old.js'])
        for supplied in (None,'0'*64,True):
            with self.assertRaises(Refused):reviewed_inventory(before,after,supplied)
        old,new,accepted=reviewed_inventory(before,after,review['sha256'])
        self.assertEqual(accepted,review)
        self.assertIsNone(old[PREFIX+'service/new.js'])
        self.assertIsNone(new[PREFIX+'service/old.js'])
        self.assertEqual(set(old),set(new))
        # Even a changed existing member invalidates a review with identical names.
        after[PREFIX+'config.xml']=sha(b'drift')
        with self.assertRaises(Refused):reviewed_inventory(before,after,review['sha256'])
        self.assertEqual(reviewed_inventory(before,before)[0],before)

    def test_package_preparation_reverifies_both_signed_inventories(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);old=folder/'old.wgt';new=folder/'new.wgt'
            old.write_bytes(b'old archive');new.write_bytes(b'new archive')
            prior={'old.js':b'old','config.xml':b'v1'};desired={'new.js':b'new','config.xml':b'v2'}
            a,b,review=reviewed_inventory(package_files(prior),package_files(desired),inventory_review(package_files(prior),package_files(desired))['sha256'])
            action=Action('001-update','autonomous-root','package',a,b,dict(package=PACKAGE,source=str(new),previous_source=str(old),reviewed_inventory_sha256=review['sha256']))
            driver=PilotDriver(None,{'id':'qn90a'},{},folder)
            def verified(source,*args):return (prior if source==old else desired),'1.0.0'
            with patch('tvsetup.autonomous_root_trial.verify_package',side_effect=verified) as verify:
                self.assertEqual(driver.prepare(action)['sha256'],sha(b'new archive'))
                self.assertEqual(verify.call_count,2)
                prior['old.js']=b'drift'
                with self.assertRaises(Refused):driver.prepare(action)
                prior['old.js']=b'old';desired['new.js']=b'drift'
                with self.assertRaises(Refused):driver.prepare(action)

    def test_package_readback_requires_removed_files_absent_and_rollback_union(self):
        before=package_files({'old.js':b'old'});after=package_files({'new.js':b'new'})
        before,after,_=reviewed_inventory(before,after,inventory_review(before,after)['sha256'])
        action=Action('001-update','autonomous-root','package',before,after,dict(package=PACKAGE))
        state=dict(agent_registration=expected_registration(),files=before,packages=[[PACKAGE,PACKAGE+'.App','wgt','1.0.0','true','false','false','false']],developer_host='192.0.2.1')
        desired={**state,'files':after}
        with tempfile.TemporaryDirectory() as d:
            driver=PilotDriver(None,{}, {},Path(d))
            driver.verify(action,state,desired)
            self.assertEqual(observed(action,state),action.before)
            for files in ({**after,PREFIX+'old.js':sha(b'old')},{**after,PREFIX+'new.js':None}):
                with self.assertRaises(Refused):driver.verify(action,state,{**desired,'files':files})

    def test_inventory_review_does_not_construct_device_transport(self):
        import json
        with tempfile.TemporaryDirectory() as d:
            root=Path(d);folders=[]
            for name in ('old','new'):
                folder=root/name;folder.mkdir();package=folder/'package.wgt';package.write_bytes(name.encode())
                (folder/'manifest.json').write_text(json.dumps(dict(device='qn90a',target_binding={'fixture':True},package=str(package),package_sha256=sha(package.read_bytes()))))
                folders.append(folder)
            with patch('tvsetup.autonomous_root_trial.configured_profile',return_value={}),patch('tvsetup.autonomous_root_trial.binding',return_value={'fixture':True}),patch('tvsetup.autonomous_root_trial.verify_package',side_effect=[({'old.js':b'old'},'1.0.0'),({'new.js':b'new'},'1.0.1')]),patch('tvsetup.autonomous_root_trial.PilotTransport',side_effect=AssertionError('No device access')):
                result=review_update('qn90a',folders[1],folders[0],{})
            self.assertEqual(result['phase'],'review-only-no-device-access')
            self.assertEqual(result['inventory']['added'],[PREFIX+'new.js'])

    def test_provisioning_is_exactly_scoped_and_hash_checked(self):
        with tempfile.TemporaryDirectory() as d:
            folder=Path(d);source=folder/'input';source.write_bytes(b'disabled')
            driver=PilotDriver(None,{'id':'qn90a'},{},folder)
            action=Action('001-file','autonomous-root','file',None,sha(b'disabled'),dict(path=DATA+'/config.json',source=str(source)))
            self.assertEqual(driver.prepare(action)['sha256'],sha(b'disabled'))
            action.options['path']='/etc/passwd'
            with self.assertRaises(Refused):driver.prepare(action)
            action.options['path']=DATA+'/config.json';source.write_bytes(b'drift')
            with self.assertRaises(Refused):driver.prepare(action)
    def test_verification_preserves_production_and_developer_host(self):
        with tempfile.TemporaryDirectory() as d:
            driver=PilotDriver(None,{'id':'qn90a'},{},Path(d))
            target=DATA+'/config.json';action=Action('001-file','autonomous-root','file',None,'new',dict(path=target))
            before=dict(files={target:None,'/production':'old'},developer_host='192.0.2.1')
            after=dict(files={target:'new','/production':'old'},developer_host='192.0.2.1')
            driver.verify(action,before,after)
            after['files']['/production']='changed'
            with self.assertRaises(Refused):driver.verify(action,before,after)
            after['files']['/production']='old';after['developer_host']='127.0.0.1'
            with self.assertRaises(Refused):driver.verify(action,before,after)

class PilotReadbackTests(unittest.TestCase):
    def test_large_inventory_uses_bounded_complete_batches(self):
        tv=object.__new__(PilotTransport)
        tv.pilot_files=[PREFIX+'service/file'+str(i)+'.js' for i in range(69)]
        calls=[]
        def root(command):
            calls.append(command)
            indices=re.findall(r'PILOT_FILE_(\d+)=',command)
            self.assertLessEqual(len(indices),12)
            if not indices:return 'db/sdk/develop/ip, value = 127.0.0.1 (String)'
            return ''.join('PILOT_FILE_'+i+'='+('ABSENT' if i=='1' else 'SYMLINK' if i=='2' else 'a'*64)+'\n' for i in indices)
        tv.root=root
        with patch('tvsetup.transport.Transport.snapshot',return_value={'files':{}}):
            state=tv.snapshot()
        self.assertEqual(len(calls),7)
        self.assertEqual(len(state['files']),69)
        self.assertIsNone(state['files'][tv.pilot_files[1]])
        self.assertEqual(state['files'][tv.pilot_files[2]],'SYMLINK')
        self.assertEqual(state['files'][tv.pilot_files[-1]],'a'*64)
        self.assertEqual(state['developer_host'],'127.0.0.1')

    def test_missing_middle_batch_entry_still_refuses(self):
        tv=object.__new__(PilotTransport);tv.pilot_files=[PREFIX+str(i) for i in range(30)]
        def root(command):
            return ''.join('PILOT_FILE_'+i+'='+'a'*64+'\n' for i in re.findall(r'PILOT_FILE_(\d+)=',command) if i!='15')
        tv.root=root
        with patch('tvsetup.transport.Transport.snapshot',return_value={'files':{}}):
            with self.assertRaisesRegex(Refused,'inspection incomplete'):tv.snapshot()


class NativeInstallerSelectionTests(unittest.TestCase):
    def test_cli_forwards_explicit_bundle_to_install_and_update_only(self):
        from tvsetup import autonomous_root_trial as trial
        base=['trial','--device','qn90a','--artifact','/tmp/new',
              '--native-bundle','/tmp/native','--yes']
        for previous in (False,True):
            args=base+(['--previous','/tmp/old'] if previous else [])
            with self.subTest(previous=previous),patch('sys.argv',args), \
                 patch.object(trial,'load_site',return_value={}), \
                 patch.object(trial,'install',return_value={}) as install, \
                 patch.object(trial,'update',return_value={}) as update, \
                 patch('builtins.print'):
                self.assertEqual(trial.main(),0)
                selected=update if previous else install
                other=install if previous else update
                self.assertEqual(selected.call_args.kwargs['native_bundle'],Path('/tmp/native'))
                other.assert_not_called()
        with patch('sys.argv',base+['--previous','/tmp/old','--review-inventory']), \
             patch.object(trial,'load_site',return_value={}), \
             patch.object(trial,'review_update',return_value={}) as review, \
             patch.object(trial,'PilotTransport',side_effect=AssertionError('device contacted')), \
             patch('builtins.print'):
            self.assertEqual(trial.main(),0)
            review.assert_called_once()

    def test_pilot_transport_propagates_selection(self):
        with patch('tvsetup.transport.Transport.__init__',return_value=None) as init:
            PilotTransport({},Path('/tmp/evidence'),[],native_bundle=Path('/tmp/native'))
        init.assert_called_once_with({},Path('/tmp/evidence'),native_bundle=Path('/tmp/native'))
