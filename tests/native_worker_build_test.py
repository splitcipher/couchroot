"""Native candidate build and package boundary checks; no device access."""
import json
from pathlib import Path
import struct
import tempfile
import unittest
from unittest.mock import patch

from tvsetup import autonomous_root, native_worker
from tvsetup.common import Refused, sha


def elf():
    data=bytearray(64)
    data[:7]=b'\x7fELF\x01\x01\x01'
    struct.pack_into('<HH',data,16,3,40)
    struct.pack_into('<I',data,36,0x05000200)
    return bytes(data)


REPORT='[Requesting program interpreter: /lib/ld-linux.so.3]\n (NEEDED) Shared library: [libc.so.6]\n Name: GLIBC_2.17\n'


class Compiler:
    def __init__(self, invalid=None):
        self.invalid=invalid;self.calls=[];self.builds=0
    def __call__(self, args):
        args=[str(a) for a in args];self.calls.append(args)
        if 'inspect' in args:
            return 'tag-only' if self.invalid=='image' else 'sha256:'+'a'*64
        if '-dumpfullversion' in args:return '10.2.1'
        if 'arm-linux-gnueabi-readelf' in args:return REPORT
        if '/src/native-observer/build.sh' in args:
            output=Path(next(a[:-5] for a in args if a.endswith(':/out')))
            data=elf()
            if self.invalid=='observer-different' and self.builds==2:data+=b'changed'
            if self.invalid=='observer-large':data+=b'x'*(128*1024)
            (output/'process-observer').write_bytes(data)
            return ''
        if '--worker-only' in args:
            self.builds+=1
            output=Path(next(a[:-5] for a in args if a.endswith(':/out')))
            data=elf()
            if self.invalid=='different' and self.builds==2:data+=b'changed'
            if self.invalid=='fault':data+=b'--test-child-fault'
            for name in ('worker','app-launcher'):(output/name).write_bytes(data)
            if self.invalid=='extra':(output/'worker-fault-test').write_bytes(data)
            if self.invalid=='symlink':
                (output/'worker').unlink();(output/'worker').symlink_to(output/'app-launcher')
            return ''
        raise AssertionError(args)


class NativeWorkerBuildTests(unittest.TestCase):
    def test_repeatable_build_manifest_pins_inputs_and_ordinary_outputs(self):
        with tempfile.TemporaryDirectory() as temp:
            compiler=Compiler();folder=native_worker.build(temp,compiler)
            manifest=json.loads((folder/'native-manifest.json').read_text())
            self.assertEqual(manifest['selection'],'managed')
            self.assertFalse(manifest['device_qualified'])
            self.assertEqual(manifest['reproducible_builds'],2)
            self.assertEqual(manifest['toolchain']['image'],'sha256:'+'a'*64)
            self.assertEqual(manifest['schema'],2)
            self.assertEqual(set(manifest['artifacts']),{'native-worker','native-app-launcher','native-process-observer'})
            self.assertIn('native-observer/process-observer.c',manifest['source'])
            self.assertIn('native-observer/service-profile.h',manifest['source'])
            self.assertFalse(any('test-service-profile' in name for name in manifest['source']))
            for name,record in manifest['artifacts'].items():
                self.assertEqual(record['sha256'],sha((folder/name).read_bytes()))
                self.assertEqual(record['interpreter'],'/lib/ld-linux.so.3')
            for name,digest in manifest['source'].items():
                self.assertEqual(digest,sha((folder/'source'/name).read_bytes()))
            self.assertFalse(any('accept.c' in name or 'bench.c' in name for name in manifest['source']))
            for args in compiler.calls:
                if 'run' in args:
                    self.assertIn('--network',args);self.assertIn('none',args)
                    self.assertIn('sha256:'+'a'*64,args)
            self.assertEqual(compiler.builds,2)

    def test_failures_never_publish_candidate_manifest(self):
        for invalid in ('image','different','fault','extra','symlink','observer-different','observer-large'):
            with self.subTest(invalid=invalid),tempfile.TemporaryDirectory() as temp:
                with self.assertRaises(Refused):native_worker.build(temp,Compiler(invalid))
                self.assertFalse((Path(temp)/'native-manifest.json').exists())

    def test_existing_output_is_not_overwritten(self):
        with tempfile.TemporaryDirectory() as temp:
            path=Path(temp)/'retained';path.write_bytes(b'keep')
            compiler=Compiler()
            with self.assertRaises(Refused):native_worker.build(temp,compiler)
            self.assertEqual(path.read_bytes(),b'keep');self.assertEqual(compiler.calls,[])

    def test_abi_dependency_and_test_artifact_refusals(self):
        bad_machine=bytearray(elf());bad_machine[18]=62
        hard_float=bytearray(elf());struct.pack_into('<I',hard_float,36,0x05000400)
        for data,report in ((bytes(bad_machine),REPORT),(bytes(hard_float),REPORT),
                (elf(),REPORT.replace('ld-linux.so.3','ld-linux-armhf.so.3')),
                (elf(),REPORT.replace('libc.so.6','libunexpected.so')),
                (elf(),REPORT.replace('2.17','2.34')),
                (elf(),REPORT.replace('GLIBC_2.17','')),
                (elf()+b'host-test-without-Smack',REPORT)):
            with self.subTest(report=report,data=data[:20]):
                with self.assertRaises(Refused):native_worker.inspect_binary(data,report)
        self.assertEqual(native_worker.inspect_binary(elf(),REPORT.replace('2.17','2.28'))['glibc_max'],'2.28.0')
        with self.assertRaises(Refused):native_worker.inspect_binary(elf(),REPORT.replace('2.17','2.28'),(2,17,0))

    def test_retired_entry_probe_option_refuses_before_preparation(self):
        with patch('sys.argv', ['prepare', '--device', 'qn90a', '--native-entry-probe']), \
             patch.object(autonomous_root, 'prepare') as prepare, \
             patch.object(autonomous_root, 'load_site') as load_site:
            with self.assertRaises(SystemExit) as raised:
                autonomous_root.main()
            self.assertEqual(raised.exception.code, 2)
            prepare.assert_not_called()
            load_site.assert_not_called()

    def test_package_contains_only_native_worker_and_required_entry_bridge(self):
        with tempfile.TemporaryDirectory() as temp:
            compiler=Compiler()
            class Builder:
                def __init__(self,*args):self.command=compiler
                def build_managed(self,source,output,**kwargs):
                    output.mkdir(parents=True)
                    for suffix in ('dll','deps.json','runtimeconfig.json'):
                        (output/(source.stem+'.'+suffix)).write_text('managed fixture')
            def certificate(builder,folder,name):
                for suffix in ('-key.pem','.pem'):(folder/(name+suffix)).write_text('fixture')
                return 'b'*64
            def acquisition(profile, folder, command, service=False):
                from tvsetup.native_root import FILES
                self.assertTrue(service)
                (folder/'artifacts').mkdir(parents=True)
                for name in FILES: (folder/'artifacts'/name).write_bytes(b'native acquisition fixture')
                return {'kind':'native-service-acquisition'}
            profile=dict(framework='net6.0',host_sha256='c'*64,firmware='fixture',host='tv.example.invalid')
            with patch.object(autonomous_root,'PRIVATE',Path(temp)),patch.object(autonomous_root,'Builder',Builder),patch.object(autonomous_root,'configured_profile',return_value=profile),patch.object(autonomous_root,'binding',return_value={'fixture':True}),patch.object(autonomous_root,'certificate',side_effect=certificate),patch('tvsetup.native_root.build',side_effect=acquisition):
                result=autonomous_root.prepare('qn90a',{},sign=False,native_candidate=True)
            folder=Path(result['folder']);payload=folder/'package/payload'
            service=folder/'package/service'
            self.assertTrue((service/'mqtt-lifecycle.js').is_file())
            self.assertTrue((service/'mqtt-state.js').is_file())
            sources=json.loads((payload/'native-manifest.json').read_text())['source']
            for name in ('config','discovery','commands','wire','bridge','foreground','metrics','state','fd'):
                self.assertIn('native-worker/mqtt/'+name+'.h',sources)
            self.assertFalse((service/'managed-return.js').exists())
            self.assertFalse((service/'managed-launch.js').exists())
            # Real packaged require graph must remain complete without fallbacks.
            import re
            for source in service.rglob('*.js'):
                for relative in re.findall(r"require\(['\"](\.[^'\"]+)['\"]\)", source.read_text()):
                    target=(source.parent/relative)
                    if not target.suffix: target=target.with_suffix('.js')
                    self.assertTrue(target.is_file(), (source.name, relative))

            self.assertFalse((payload/'SamsungTvRootAgent.dll').exists())
            self.assertFalse((payload/'SamsungTvArchiveRoot.dll').exists())
            self.assertTrue((payload/'NativeEntry.dll').is_file())
            manifest=json.loads((payload/'manifest.json').read_text())
            for name in ('native-worker','native-app-launcher','native-process-observer','native-manifest.json'):
                self.assertEqual(manifest[name],sha((payload/name).read_bytes()))
            candidate=json.loads((payload/'native-manifest.json').read_text())
            self.assertEqual(candidate['selection'],'managed')
            config=json.loads((folder/'provision/config.json').read_text())
            self.assertFalse(config['enabled']);self.assertNotIn('worker_implementation',config)
            self.assertNotIn('libentry-receipt.so',manifest)
            self.assertNotIn('entry-receipt.json',manifest)
            self.assertEqual(result['phase'],'prepared-not-installed')
