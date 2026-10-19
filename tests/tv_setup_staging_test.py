"""Execute staging guards against synthetic local files; no TV/NAS transport."""
from pathlib import Path
import os
import shlex
import subprocess
import sys
import tempfile
import unittest
from unittest.mock import Mock
from tvsetup.common import sha
from tvsetup.operations import Driver
from tvsetup.planner import Action
from tvsetup.staging import clear_verified_stage


class StagingTests(unittest.TestCase):
    def script(self,path,digest):
        # Supply portable sha256sum for the same shell guards on macOS and Linux.
        command=path.parent/'sha256sum'
        code='import hashlib,sys;from pathlib import Path;p=Path(sys.argv[1]);print(hashlib.sha256(p.read_bytes()).hexdigest()+"  "+str(p))'
        command.write_text('#!/bin/sh\nexec '+shlex.quote(sys.executable)+' -c '+shlex.quote(code)+' "$@"\n')
        command.chmod(0o700)
        return subprocess.run(['sh','-c','set -eu\n'+clear_verified_stage(str(path),digest)],env=dict(os.environ,PATH=str(path.parent)+os.pathsep+os.environ['PATH']),capture_output=True)
    def test_verified_complete_stage_can_be_recreated(self):
        with tempfile.TemporaryDirectory(prefix='couchroot staging ') as tmp:
            path=Path(tmp)/'run-owned.new';path.write_bytes(b'complete')
            self.assertEqual(self.script(path,sha(b'complete')).returncode,0)
            self.assertFalse(path.exists())
    def test_unknown_partial_stage_and_symlink_are_preserved(self):
        with tempfile.TemporaryDirectory() as tmp:
            path=Path(tmp)/'run-owned.new';path.write_bytes(b'partial')
            self.assertNotEqual(self.script(path,sha(b'complete')).returncode,0)
            self.assertEqual(path.read_bytes(),b'partial')
            path.unlink();target=Path(tmp)/'user-file';target.write_bytes(b'complete');path.symlink_to(target)
            self.assertNotEqual(self.script(path,sha(b'complete')).returncode,0)
            self.assertTrue(path.is_symlink());self.assertEqual(target.read_bytes(),b'complete')
    def test_restored_rows_still_reload_after_lost_rollback_reply(self):
        driver=Driver.__new__(Driver);driver.control_call=Mock();driver.tv=Mock()
        action=Action('route','home','routes',[],[['new']],{'table':'key_filter','scope':'home'})
        driver.rollback(action,{},dict(key_filter=[]))
        driver.control_call.assert_called_once_with('reload',root=True)
    def test_restored_s90d_cache_still_reloads_after_lost_rollback_reply(self):
        driver=Driver.__new__(Driver);driver.control_call=Mock();driver.tv=Mock()
        action=Action('cache','startup','cache','original','patched',{'path':'/test/cache'})
        driver.rollback(action,{},dict(files={'/test/cache':'original'}))
        driver.tv.root.assert_called_once_with('systemctl daemon-reload\n',namespace=True)
