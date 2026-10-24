"""Maintenance admission uses fresh SDK evidence without weakening identity checks."""
import importlib.util
import io
import json
import os
from pathlib import Path
import sys
from types import SimpleNamespace
import unittest
from unittest.mock import Mock, patch


class LiveSdkHostTests(unittest.TestCase):
    def setUp(self):
        root = Path(__file__).resolve().parents[1]
        upstream = SimpleNamespace(SdbClient=object, route_callback_host=lambda _: '192.0.2.31')
        with patch.object(sys, 'path', [str(root / 'tools/toolkit'), *sys.path]), patch.dict(
            sys.modules, {'samsung_tv_root': SimpleNamespace(sdb=upstream), 'samsung_tv_root.sdb': upstream}
        ):
            spec = importlib.util.spec_from_file_location('live_sdk_host_fixture', root / 'tools/toolkit/samsung_tv.py')
            self.module = importlib.util.module_from_spec(spec)
            spec.loader.exec_module(self.module)
        self.client = Mock()
        self.client.capture.return_value = SimpleNamespace(
            transport_returncode=0,
            output='db/sdk/develop/ip, value = 192.0.2.31 (String)\n[exit:0]\n',
        )
        self.config = dict(tv_host='192.0.2.10', expected_model='QN65QN90AAFXZA', expected_platform='21_NEOQLED', expected_device_id='fixture-id')
        self.identity = dict(modelName=self.config['expected_model'], model=self.config['expected_platform'], id='fixture-id', developerMode='1', developerIP='127.0.0.1')

    def invoke(self, enabled='1'):
        with patch.dict(os.environ, {'TV_SETUP_LIVE_SDK_HOST': enabled}), patch.object(
            self.module, 'urlopen', return_value=io.BytesIO(json.dumps({'device': self.identity}).encode())
        ), patch.object(self.module, 'SdbClient', return_value=self.client), patch.object(self.module.socket, 'create_connection'):
            return self.module.device(self.config)

    def test_opt_in_requires_live_sdk_setting_and_connected_device(self):
        self.assertEqual(self.invoke(), '192.0.2.31')
        self.client.connect.assert_called_once()
        self.client.require_device.assert_called_once()
        self.client.capture.assert_called_once_with('vconftool get db/sdk/develop/ip', callback_host='192.0.2.31', bind_host='192.0.2.31', timeout=10)

    def test_default_still_refuses_cached_mismatch_without_sdk_command(self):
        with self.assertRaisesRegex(RuntimeError, 'Developer Mode host must match'):
            self.invoke('')
        self.client.connect.assert_not_called()

    def test_capture_footer_separator_and_transport_one_are_valid(self):
        self.client.capture.return_value = SimpleNamespace(
            transport_returncode=1,
            output='db/sdk/develop/ip, value = 192.0.2.31 (String)\n\n[exit:0]\n',
        )
        self.assertEqual(self.invoke(), '192.0.2.31')

    def test_missing_malformed_drift_or_failed_capture_refuses(self):
        good = self.client.capture.return_value.output
        for output, rc in [(good.replace('192.0.2.31', '127.0.0.1'), 0), ('', 0), (good.replace('[exit:0]', '[exit:1]'), 0), (good.replace('[exit:0]\n', ''), 0), (good + 'extra', 0), (good, 2)]:
            with self.subTest(output=output, rc=rc):
                self.client.capture.return_value = SimpleNamespace(output=output, transport_returncode=rc)
                with self.assertRaisesRegex(RuntimeError, 'Live Developer Mode host'):
                    self.invoke()

    def test_lost_callback_refuses_without_retry(self):
        self.client.capture.side_effect = TimeoutError('lost SDK callback')
        with self.assertRaises(TimeoutError):
            self.invoke()
        self.client.capture.assert_called_once()

    def test_public_identity_and_developer_mode_guard_precede_sdk(self):
        for field, value in [('id', 'other-device'), ('modelName', 'QN65QN90BAFXZA'), ('model', '22_NEOQLED'), ('developerMode', '0')]:
            with self.subTest(field=field):
                original = self.identity[field]
                self.identity[field] = value
                with self.assertRaises(RuntimeError):
                    self.invoke()
                self.client.connect.assert_not_called()
                self.identity[field] = original

    def test_live_setting_checked_even_if_http_matches(self):
        self.identity['developerIP'] = '192.0.2.31'
        self.client.capture.return_value.output = 'db/sdk/develop/ip, value = 127.0.0.1 (String)\n[exit:0]\n'
        with self.assertRaisesRegex(RuntimeError, 'Live Developer Mode host'):
            self.invoke()


if __name__ == '__main__':
    unittest.main()
