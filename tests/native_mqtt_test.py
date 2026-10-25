"""MQTT tests in a disposable Linux container, no TV/broker/NAS access."""

import json
import os
from pathlib import Path
import select
import signal
import socket
import subprocess
import tempfile
import time
import unittest

ROOT = Path(__file__).resolve().parents[1]


def packet(kind, body=b""):
    out = bytes([kind])
    n = len(body)
    while True:
        digit = n % 128
        n //= 128
        out += bytes([digit | (128 if n else 0)])
        if not n:
            return out + body


def utf(value):
    value = value.encode()
    return len(value).to_bytes(2, "big") + value


@unittest.skipUnless(
    os.environ.get("MQTT_HARNESS"), "set MQTT_HARNESS in disposable Linux container"
)
class MqttTests(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory(dir="/opt")
        self.addCleanup(self.tmp.cleanup)
        self.root = Path(self.tmp.name)
        self.root.chmod(0o700)
        self.credentials = self.root / "credentials.env"
        self.secret = "x" * 32
        self.credentials.write_text(
            "MQTT_USER=tv-qn90a\nMQTT_PASSWORD=" + self.secret + "\n"
        )
        self.credentials.chmod(0o600)
        self.config = self.root / "config.json"
        self.settings = dict(
            device="qn90a",
            device_name="Example TV",
            broker_host="127.0.0.1",
            broker_port=1883,
            credentials_file=str(self.credentials),
        )
        self.save()
        self.bin = os.environ["MQTT_HARNESS"]
        self.sock = None
        self.proc = None
        self.pending = bytearray()

    def save(self):
        self.config.write_text(json.dumps(self.settings))
        self.config.chmod(0o600)

    def cli(self, mode, *args, input=None):
        result = subprocess.run(
            [self.bin, mode, *args],
            input=input,
            text=True,
            capture_output=True,
            timeout=5,
        )
        self.assertEqual(result.returncode, 0, result.stderr)
        self.assertNotIn(self.secret, result.stdout + result.stderr)
        return result.stdout.strip()

    def config_ok(self):
        return self.cli("config", str(self.config), "qn90a")

    def start(self, before_suback=False, mode="run"):
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.listener.settimeout(6)
        self.addCleanup(self.listener.close)
        self.settings["broker_port"] = self.listener.getsockname()[1]
        self.save()
        self.proc = subprocess.Popen(
            [self.bin, mode, str(self.config), "qn90a"],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.PIPE,
        )
        self.addCleanup(self.stop)
        self.assertEqual(self.proc.stdout.readline(), b"ready\n")
        self.handshake(before_suback)

    def stop(self):
        if self.proc is not None:
            self.proc.send_signal(signal.SIGTERM)
            out, err = self.proc.communicate(timeout=5)
            self.assertEqual(self.proc.returncode, 0, err)
            self.assertNotIn(self.secret.encode(), out + err)
            self.assertNotIn(b"AddressSanitizer", err)
            self.proc = None
        if self.sock is not None:
            self.sock.close()
            self.sock = None

    def receive(self, timeout=5):
        until = time.monotonic() + timeout
        while True:
            if len(self.pending) >= 2:
                n = 0
                mult = 1
                at = 1
                while at < len(self.pending):
                    b = self.pending[at]
                    at += 1
                    n += (b & 127) * mult
                    mult *= 128
                    if not b & 128:
                        if len(self.pending) >= at + n:
                            kind = self.pending[0]
                            body = bytes(self.pending[at : at + n])
                            del self.pending[: at + n]
                            if kind == 0xC0:
                                self.sock.sendall(packet(0xD0))
                                break
                            return kind, body
                        break
            remaining = until - time.monotonic()
            if remaining <= 0:
                raise TimeoutError()
            if not select.select([self.sock], [], [], remaining)[0]:
                raise TimeoutError()
            data = self.sock.recv(65536)
            if not data:
                raise EOFError()
            self.pending.extend(data)

    def handshake(self, before_suback=False):
        self.sock, _ = self.listener.accept()
        self.pending = bytearray()
        kind, body = self.receive()
        self.assertEqual(kind, 0x10)
        self.assertEqual(body[:10], b"\x00\x04MQTT\x04\xe6\x00\x1e")
        values = []
        at = 10
        while at < len(body):
            n = int.from_bytes(body[at : at + 2], "big")
            at += 2
            values.append(body[at : at + n])
            at += n
        self.assertEqual(
            values,
            [
                b"tv_qn90a",
                b"tv/qn90a/availability",
                b"offline",
                b"tv-qn90a",
                self.secret.encode(),
            ],
        )
        self.sock.sendall(packet(0x20, b"\0\0"))
        kind, body = self.receive()
        self.assertEqual(kind, 0x82)
        self.assertEqual(
            body,
            b"\0\1"
            + utf("homeassistant/status")
            + b"\0"
            + utf("tv/qn90a/cmd/+")
            + b"\0",
        )
        if before_suback:
            self.publish("homeassistant/status", b"online")
        self.sock.sendall(packet(0x90, b"\0\1\0\0"))

    def publish(self, topic, payload, retain=False):
        self.sock.sendall(packet(0x31 if retain else 0x30, utf(topic) + payload))

    def publications(self, count, timeout=5):
        out = {}
        for _ in range(count):
            kind, body = self.receive(timeout)
            self.assertIn(kind, (0x30, 0x31))
            n = int.from_bytes(body[:2], "big")
            topic = body[2 : n + 2].decode()
            self.assertTrue(
                topic.startswith("tv/qn90a/")
                or topic == "homeassistant/device/tv_qn90a/config",
                topic,
            )
            out[topic] = (bool(kind & 1), body[n + 2 :])
        return out

    def test_private_config_credentials_and_device_binding(self):
        self.assertEqual(self.config_ok(), "valid")
        for mode in (0o644, 0o640, 0o4600):
            self.credentials.chmod(mode)
            self.assertEqual(self.config_ok(), "invalid")
        self.credentials.chmod(0o600)
        original = self.credentials.read_text()
        for raw in (
            original.replace("tv-qn90a", "tv-s90d"),
            original + "EXTRA=yes\n",
            original.replace("MQTT_USER=", "export MQTT_USER="),
            original.replace(self.secret, "short"),
            original.replace("\nMQTT_PASSWORD", "\nMQTT_USER=duplicate\nMQTT_PASSWORD"),
        ):
            self.credentials.write_text(raw)
            self.assertEqual(self.config_ok(), "invalid")
        self.credentials.write_text(original.replace("\n", "\r\n"))
        self.assertEqual(self.config_ok(), "valid")
        moved = self.root / "real"
        self.credentials.rename(moved)
        self.credentials.symlink_to(moved)
        self.assertEqual(self.config_ok(), "invalid")
        self.credentials.unlink()
        moved.rename(self.credentials)
        self.root.chmod(0o777)
        self.assertEqual(self.config_ok(), "invalid")
        self.root.chmod(0o700)
        os.link(self.credentials, self.root / "hardlink")
        self.assertEqual(self.config_ok(), "invalid")

    @unittest.skipUnless(
        os.environ.get("NATIVE_WORKER")
        and os.environ.get("COUCHROOT_PARITY_CONTAINER"),
        "isolated production worker required",
    )
    def test_real_production_worker_lease_and_shutdown(self):
        import native_worker_test

        folder = Path("/opt/couchroot/mqtt")
        folder.mkdir(parents=True, exist_ok=False)
        self.addCleanup(folder.rmdir)
        config = folder / "config.json"
        self.addCleanup(lambda: config.unlink(missing_ok=True))
        self.listener = socket.socket()
        self.listener.bind(("127.0.0.1", 0))
        self.listener.listen()
        self.listener.settimeout(6)
        self.addCleanup(self.listener.close)
        self.settings["broker_port"] = self.listener.getsockname()[1]
        config.write_text(json.dumps(self.settings))
        config.chmod(0o600)
        native = native_worker_test.NativeWorkerTests("runTest")
        native.extra_worker_args = ["--production"]
        native.setUp()
        self.addCleanup(native.tearDown)
        self.assertIn("mqtt-bridge-v1", native.op("status")["result"]["capabilities"])
        # Optional configuration must yield before allocating descriptors needed
        # by the protocol/monitor; recovery after pressure needs no worker reset.
        import resource
        original = resource.prlimit(native.worker_pid, resource.RLIMIT_NOFILE)
        occupied = {int(p.name) for p in Path(f"/proc/{native.worker_pid}/fd").iterdir()}
        limit = free = 0
        while free < 3:
            if limit not in occupied: free += 1
            limit += 1
        try:
            resource.prlimit(native.worker_pid, resource.RLIMIT_NOFILE, (limit, original[1]))
            self.assertEqual(native.op("mqtt.start",device="qn90a",firmware="TEST-FIRMWARE-1.0",version="test-build")["result"]["state"],"unconfigured")
        finally:
            resource.prlimit(native.worker_pid, resource.RLIMIT_NOFILE, original)
        self.assertTrue(native.op("status")["ok"])
        self.assertEqual(
            native.op(
                "mqtt.start",
                device="qn90a",
                firmware="TEST-FIRMWARE-1.0",
                version="test-build",
            )["result"]["state"],
            "started",
        )
        self.handshake()
        self.addCleanup(self.stop)
        initial = self.publications(5)
        self.assertEqual(initial["tv/qn90a/availability"], (True, b"online"))
        health = json.loads(initial["tv/qn90a/health"][1])
        self.assertIsInstance(health["agent_uptime_s"], int)
        self.assertGreaterEqual(health["agent_uptime_s"], 0)
        self.assertLessEqual(health["agent_uptime_s"], health["uptime_s"])
        result = native.op(
            "mqtt.start", device="qn90a", firmware="TEST-FIRMWARE-1.0",
            version="test-build", observations=json.dumps({"state":{"volume":17},"supported":{"volume":True}}),
        )["result"]
        self.assertTrue(result["observe_state"])
        self.assertEqual(json.loads(self.publications(1)["tv/qn90a/state"][1])["volume"],17)
        self.assertEqual(
            native.op(
                "mqtt.start",
                device="s90d",
                firmware="TEST-FIRMWARE-1.0",
                version="test-build",
            )["result"]["state"],
            "metadata_drift",
        )
        self.publish("tv/qn90a/cmd/exec", b'{"command":"false"}')
        self.assertEqual(
            json.loads(self.publications(1)["tv/qn90a/cmd_result"][1])["error"],
            "unknown_command",
        )
        self.assertTrue(native.op("status")["ok"])
        native.seq += 1
        native.send(f"SHUTDOWN\t{native.seq}")
        native.receive()
        native.proc.wait(timeout=5)
        with self.assertRaises(EOFError):
            self.receive()

    def test_config_malformed_refuses_without_crashing(self):
        for key, value in [
            ("broker_port", "1883"),
            ("device", "other"),
            ("enabled", 1),
            ("resilience", True),
            ("extra", "value"),
        ]:
            saved = dict(self.settings)
            self.settings[key] = value
            self.save()
            self.assertEqual(self.config_ok(), "invalid")
            self.settings = saved
        self.save()
        self.config.write_text(self.config.read_text() + " garbage")
        self.assertEqual(self.config_ok(), "invalid")

    def test_command_contract_and_unknown_fields(self):
        valid = {
            "power": {"on": False},
            "screen": {"on": True},
            "source": {"input": "hdmi2"},
            "launch_app": {"name": "Example", "deep_link": "example://play"},
            "volume": {"level": 15},
            "mute": {"on": True},
            "picture_mode": {"mode": "Movie"},
            "audio_output": {"output": "arc"},
            "game_mode": {"on": False},
            "sleep_timer": {"minutes": 0},
            "key": {"key": "HOME"},
            "notify": {
                "title": "Test",
                "message": "Person",
                "image_url": "https://ha.example.invalid/api/frigate/notifications/event/snapshot.jpg",
                "duration_s": 8,
            },
            "kid_mode": {"on": False},
            "telemetry_block": {"on": False},
        }
        for name, value in valid.items():
            value["id"] = "t1"
            self.assertEqual(
                self.cli("command", name, input=json.dumps(value)), "valid", name
            )
            self.assertEqual(
                self.cli("command", name, input=json.dumps({**value, "shell": "bad"})),
                "invalid_payload",
            )
        for name, raw in [
            ("volume", '{"level":1,"level":2}'),
            ("volume", '{"level":1.1}'),
            ("volume", '{"level":true}'),
            ("volume", '{"level":101}'),
            ("key", '{"key":"EXEC"}'),
            ("launch_app", '{"app_id":"x","name":"y"}'),
            ("notify", '{"title":"x","message":"y","duration_s":61}'),
            ("volume", '{"level":1}junk'),
            ("power", '{"on":null}'),
            ("volume", '{"level":1,"id":"\\u0000"}'),
        ]:
            self.assertEqual(self.cli("command", name, input=raw), "invalid_payload")
        self.assertEqual(self.cli("command", "exec", input="{}"), "unknown_command")
        self.assertEqual(self.cli("debounce"), "ok")

    def test_discovery_golden_and_unknown_state(self):
        for device in ("qn90a", "s90d"):
            self.settings["device"] = device
            self.save()
            self.credentials.write_text(
                "MQTT_USER=tv-" + device + "\nMQTT_PASSWORD=" + self.secret + "\n"
            )
            actual = json.loads(self.cli("discovery", str(self.config), device))
            golden = json.loads(
                (ROOT / "tests/fixtures" / ("mqtt-" + device + ".json")).read_text()
            )
            self.assertEqual(actual, golden)

    def test_connect_birth_reconnect_retained_and_nonretained_results(self):
        self.start()
        initial = self.publications(5)
        self.assertEqual(initial["tv/qn90a/availability"], (True, b"online"))
        state = json.loads(initial["tv/qn90a/state"][1])
        self.assertIsNone(state["power"])
        self.assertNotIn("bedtime_lock", state)
        self.publish("homeassistant/status", b"online")
        self.assertEqual(
            self.publications(5)["tv/qn90a/state"], initial["tv/qn90a/state"]
        )
        self.publish("tv/qn90a/cmd/volume", b'{"level":15,"id":"t1"}')
        retained, raw = self.publications(1)["tv/qn90a/cmd_result"]
        self.assertFalse(retained)
        self.assertEqual(
            json.loads(raw),
            dict(cmd="volume", id="t1", ok=False, error="unsupported_capability"),
        )
        self.publish("tv/qn90a/cmd/power", b'{"on":false,"id":"old"}', retain=True)
        self.assertEqual(
            json.loads(self.publications(1)["tv/qn90a/cmd_result"][1])["error"],
            "retained_command",
        )
        self.sock.close()
        self.handshake()
        self.assertEqual(
            self.publications(5)["tv/qn90a/state"], initial["tv/qn90a/state"]
        )

    def test_oversized_frame_disconnects_and_shutdown_is_bounded(self):
        self.start()
        self.publications(5)
        self.sock.sendall(b"\x30\xff\xff\x7f")
        with self.assertRaises(EOFError):
            self.receive()

    def test_birth_before_suback_does_not_prevent_discovery(self):
        self.start(before_suback=True)
        self.assertIn("homeassistant/device/tv_qn90a/config", self.publications(5))

    def test_trickled_packet_has_whole_frame_timeout(self):
        self.start()
        self.publications(5)
        self.sock.sendall(b"\x30\x80")
        with self.assertRaises(EOFError):
            self.receive(timeout=5)

    def test_coordinator_lease_expiry_publishes_offline_then_disconnects(self):
        self.start(mode="expire")
        self.publications(5)
        self.assertEqual(
            self.publications(1)["tv/qn90a/availability"], (True, b"offline")
        )
        self.assertEqual(self.receive(), (0xE0, b""))
        with self.assertRaises(EOFError):
            self.receive()

    def test_periodic_latest_state_and_health(self):
        self.start()
        initial = self.publications(5)
        # Answer PINGREQ while waiting; the real 60-second interval is intentional.
        refreshed = self.publications(2, timeout=65)
        self.assertEqual(refreshed["tv/qn90a/state"], initial["tv/qn90a/state"])
        self.assertTrue(refreshed["tv/qn90a/health"][0])
        self.assertGreater(
            json.loads(refreshed["tv/qn90a/health"][1])["uptime_s"],
            json.loads(initial["tv/qn90a/health"][1])["uptime_s"],
        )

    def test_malformed_utf8_and_embedded_nul_have_no_effect(self):
        self.start()
        self.publications(5)
        for raw in (b'{"title":"\\xff","message":"test"}', b'{"level":15}\\x00{}'):
            raw = raw.replace(b"\\xff", bytes([255])).replace(b"\\x00", bytes([0]))
            self.publish("tv/qn90a/cmd/notify", raw)
            self.assertEqual(
                json.loads(self.publications(1)["tv/qn90a/cmd_result"][1])["error"],
                "invalid_payload",
            )

    def test_rate_limit_has_bounded_burst(self):
        self.start()
        self.publications(5)
        self.sock.sendall(
            b"".join(
                packet(0x30, utf("tv/qn90a/cmd/volume") + b'{"level":5}')
                for _ in range(100)
            )
        )
        count = 0
        try:
            while True:
                self.publications(1, timeout=0.2)
                count += 1
        except TimeoutError:
            pass
        self.assertGreaterEqual(count, 20)
        self.assertLessEqual(count, 24)


if __name__ == "__main__":
    unittest.main()
