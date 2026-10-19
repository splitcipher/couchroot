"""S89C preparation checks use synthetic identity responses, without a TV."""
import contextlib
import http.client
import io
import json
import subprocess
import sys
import unittest
from unittest.mock import patch

from tvsetup.common import REPO, Refused


class S89CInspectionTests(unittest.TestCase):
    def test_help_runs_without_sdk_signing_or_device_configuration(self):
        result = subprocess.run(
            [sys.executable, '-m', 'tvsetup.s89c_inspect', '--help'],
            cwd=REPO, capture_output=True, text=True, timeout=5)
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertIn('host', result.stdout)

    def test_identity_read_uses_one_get_and_omits_personal_identifiers(self):
        from tvsetup import s89c_inspect
        response = io.BytesIO(json.dumps({'version': '2.0.25', 'device': {
            'modelName': 'QN77S89CBFXZA', 'model': 'synthetic-platform',
            'OS': 'Tizen', 'developerMode': '1', 'developerIP': '192.0.2.30',
            'id': 'private-uuid', 'duid': 'duid-x', 'wifiMac': 'private-mac',
            'name': 'private-room-name'}}).encode())
        response.status = 200
        with patch.object(s89c_inspect.http.client, 'HTTPConnection', autospec=True) as connect:
            connect.return_value.getresponse.return_value = response
            result = s89c_inspect.inspect('192.0.2.50')
        connect.assert_called_once_with('192.0.2.50', 8001, timeout=5)
        connect.return_value.request.assert_called_once_with('GET', '/api/v2/')
        connect.return_value.close.assert_called_once()
        self.assertEqual(result['device'], {
            'modelName': 'QN77S89CBFXZA', 'model': 'synthetic-platform',
            'OS': 'Tizen', 'developerMode': '1', 'developerIP': '192.0.2.30'})
        self.assertFalse(result['setup_supported'])
        self.assertNotIn('private-', json.dumps(result))
        self.assertNotIn('2.0.25', json.dumps(result))

    def test_invalid_destinations_are_refused_before_connecting(self):
        from tvsetup import s89c_inspect
        with patch.object(s89c_inspect.http.client, 'HTTPConnection') as connect:
            for host in ('tv.local', '127.0.0.1', '0.0.0.0', '224.0.0.1',
                         '8.8.8.8', '::1', '192.0.2.50/path', '192.0.2.50:8001'):
                with self.subTest(host=host), self.assertRaises(Refused):
                    s89c_inspect.inspect(host)
            connect.assert_not_called()

    def test_unexpected_models_and_malformed_identities_are_refused(self):
        from tvsetup import s89c_inspect
        for payload in (
            [], {}, {'device': []},
            {'device': {'modelName': 'QN55S90DAFXZA', 'model': 'synthetic-platform'}},
            {'device': {'modelName': 'QN77S89CBFXZA'}},
            {'device': {'modelName': 'QN77S89CBFXZA', 'model': {'id': 'private-id'}}},
            {'device': {'modelName': 'QN77S89CBFXZA', 'model': 'synthetic-platform',
                        'developerMode': {'token': 'private-token'}}}):
            response = io.BytesIO(json.dumps(payload).encode())
            response.status = 200
            with self.subTest(payload=payload), \
                 patch.object(s89c_inspect.http.client, 'HTTPConnection') as connect:
                connect.return_value.getresponse.return_value = response
                with self.assertRaises(Refused):
                    s89c_inspect.inspect('192.0.2.50')
                connect.return_value.close.assert_called_once()

    def test_redirects_errors_and_invalid_bodies_fail_without_retrying(self):
        from tvsetup import s89c_inspect
        for status, body in ((302, b'private-redirect'), (500, b'private-error'),
                             (200, b'{broken-json'), (200, b'\xff'),
                             (200, b' ' * 65537)):
            response = io.BytesIO(body)
            response.status = status
            with self.subTest(status=status, size=len(body)), \
                 patch.object(s89c_inspect.http.client, 'HTTPConnection') as connect:
                connect.return_value.getresponse.return_value = response
                with self.assertRaises(Refused):
                    s89c_inspect.inspect('192.0.2.50')
                self.assertEqual(connect.return_value.request.call_count, 1)
                connect.return_value.close.assert_called_once()

    def test_connection_errors_produce_no_identity_or_raw_error_output(self):
        from tvsetup import s89c_inspect
        for error in (OSError('private-network-detail'),
                      http.client.HTTPException('private-http-detail')):
            out, err = io.StringIO(), io.StringIO()
            with self.subTest(error=type(error).__name__), \
                 patch.object(s89c_inspect.http.client, 'HTTPConnection') as connect, \
                 contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
                connect.return_value.request.side_effect = error
                self.assertEqual(s89c_inspect.main(['192.0.2.50']), 1)
                connect.return_value.close.assert_called_once()
            self.assertEqual(out.getvalue(), '')
            self.assertNotIn('private-', err.getvalue())

    def test_existing_installer_still_refuses_s89c_before_device_access(self):
        from tvsetup.cli import parser
        with contextlib.redirect_stderr(io.StringIO()), self.assertRaises(SystemExit) as error:
            parser().parse_args(['apply', '--device', 's89c', '--yes'])
        self.assertEqual(error.exception.code, 2)


if __name__ == '__main__':
    unittest.main()
