"""Exercise the restart barrier with a real, delayed-exit Linux process."""
import os
from pathlib import Path
import shlex
import subprocess
import sys
import tempfile
import threading
import unittest

SCRIPT = Path(__file__).resolve().parents[1]/'agent/restart-service.sh'
HOST = '''import ctypes,signal,time,os
ctypes.CDLL(None).prctl(15,os.environ.get('TEST_HOST_NAME','wrt-service').encode(),0,0,0)
def stop(*args):
 time.sleep(3)
 raise SystemExit()
signal.signal(signal.SIGTERM,stop)
print('ready',flush=True)
while True: time.sleep(1)
'''
LAUNCHER = '''import os,signal,sys
from pathlib import Path
p=Path(os.environ['TEST_STATE']);pid=int(os.environ['TEST_PID'])
with (p/'calls').open('a') as f:f.write(sys.argv[1]+'\\n')
if sys.argv[1]=='-r':
 stopped=(p/'stopped').exists()
 if stopped and os.environ.get('BAD_STATUS'): print('unexpected');sys.exit(1)
 if stopped and os.environ.get('FILTER_COUNT'): print('Failed to get filter count')
 print('result: not running' if stopped else 'result: running');sys.exit(1 if stopped else 0)
elif sys.argv[1]=='-k':
 (p/'stopped').touch()
 if not os.environ.get('NEVER_EXIT'):os.kill(pid,signal.SIGTERM)
elif sys.argv[1]=='-s':
 # The wrapper already reports stopped while its WRT host is still exiting.
 # Starting during that interval would reproduce the S90D race.
 assert not Path('/proc/'+str(pid)).exists(), 'started inside old host lifetime'
 (p/'started').touch()
'''


@unittest.skipUnless(sys.platform == 'linux', 'Linux /proc process identity required')
class ServiceRestartTests(unittest.TestCase):
    host_name = 'wrt-service'
    def setUp(self):
        self.temp = tempfile.TemporaryDirectory(); self.addCleanup(self.temp.cleanup)
        self.work = Path(self.temp.name)
        self.host = subprocess.Popen([sys.executable, '-c', HOST], stdout=subprocess.PIPE, text=True,
                                     env={**os.environ, 'TEST_HOST_NAME': self.host_name})
        self.assertEqual(self.host.stdout.readline(), 'ready\n')
        def cleanup():
            if self.host.poll() is None:self.host.kill()
            self.host.wait(); self.host.stdout.close()
        self.addCleanup(cleanup)
        self.started = Path('/proc/'+str(self.host.pid)+'/stat').read_text().split(') ')[1].split()[19]
        self.boot = Path('/proc/sys/kernel/random/boot_id').read_text().strip()
        # Reap the child so the actual /proc entry disappears, as on the TV.
        self.waiter = threading.Thread(target=self.host.wait, daemon=True); self.waiter.start()
        stub = self.work/'launcher.py'; stub.write_text(LAUNCHER)
        launcher = self.work/'app_launcher'
        launcher.write_text('#!/bin/sh\nexec '+shlex.quote(sys.executable)+' '+shlex.quote(str(stub))+' "$@"\n');launcher.chmod(0o700)
        self.env = {**os.environ, 'PATH':str(self.work)+':'+os.environ['PATH'],
                    'TEST_STATE':str(self.work), 'TEST_PID':str(self.host.pid)}

    def run_restart(self, *, boot=None, started=None, **env):
        return subprocess.run(['/bin/sh', str(SCRIPT), boot or self.boot, str(self.host.pid), started or self.started],
                              env={**self.env, **env}, text=True, capture_output=True, timeout=15)

    def test_waits_for_host_exit_after_wrapper_reports_stopped(self):
        result = self.run_restart()
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertEqual((self.work/'calls').read_text(), '-r\n-k\n-r\n-s\n')
        self.assertTrue((self.work/'started').exists())
        self.assertIn('SERVICE_START_SUBMITTED', result.stdout)

    def test_wrong_boot_or_stale_pid_binding_never_stops_service(self):
        for kwargs in ({'boot':'00000000-0000-4000-8000-000000000001'},
                       {'started':str(int(self.started)+1)}, {'boot':'bad; echo injected'}):
            with self.subTest(kwargs=kwargs):
                self.assertNotEqual(self.run_restart(**kwargs).returncode, 0)
                self.assertFalse((self.work/'calls').exists())

    def test_qn90a_filter_count_prefix_still_requires_host_exit(self):
        result = self.run_restart(FILTER_COUNT='1')
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertTrue((self.work/'started').exists())
        self.assertEqual((self.work/'calls').read_text(), '-r\n-k\n-r\n-s\n')

    def test_nonexiting_host_withholds_start_without_forced_kill(self):
        sleep = self.work/'sleep';sleep.write_text('#!/bin/sh\nexit 0\n');sleep.chmod(0o700)
        result = self.run_restart(NEVER_EXIT='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertIn('start withheld', result.stderr)
        self.assertIsNone(self.host.poll())
        self.assertEqual((self.work/'calls').read_text(), '-r\n-k\n')

    def test_unexpected_application_state_withholds_start(self):
        result = self.run_restart(BAD_STATUS='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.work/'started').exists())


@unittest.skipUnless(sys.platform == 'linux', 'Linux /proc process identity required')
class Qn90aServiceRestartTests(ServiceRestartTests):
    host_name = 'MiniRoot01.Serv'

    def setUp(self):
        super().setUp()
        reader = self.work/'readlink'
        reader.write_text('#!/bin/sh\nif test "${WRONG_EXECUTABLE:-0}" = 1; then echo /usr/bin/foreign; else echo /usr/bin/wrt-service; fi\n')
        reader.chmod(0o700)

    def test_qn90a_name_with_wrong_executable_never_stops_service(self):
        result = self.run_restart(WRONG_EXECUTABLE='1')
        self.assertNotEqual(result.returncode, 0)
        self.assertFalse((self.work/'calls').exists())
