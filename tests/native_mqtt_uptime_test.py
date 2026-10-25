"""Process age, wire continuity and discovery contracts; isolated loopback only."""
import json
import os
import time
import unittest

import native_mqtt_test as fixtures


@unittest.skipUnless(os.environ.get("MQTT_HARNESS"), "set MQTT_HARNESS in Linux")
class UptimeTests(unittest.TestCase):
    setUp = fixtures.MqttTests.setUp
    save = fixtures.MqttTests.save
    cli = fixtures.MqttTests.cli
    start = fixtures.MqttTests.start
    stop = fixtures.MqttTests.stop
    receive = fixtures.MqttTests.receive
    handshake = fixtures.MqttTests.handshake
    publish = fixtures.MqttTests.publish
    publications = fixtures.MqttTests.publications

    def age(self, **changes):
        sample = dict(start="25025", hz=250, seconds=103, nanoseconds=900000000)
        sample.update(changes)
        return json.loads(self.cli("process-age", input=json.dumps(sample)))["age"]

    def test_elapsed_seconds_round_down_and_include_suspended_time(self):
        self.assertEqual(self.age(), 3)
        self.assertEqual(self.age(seconds=100, nanoseconds=100000000), 0)
        self.assertEqual(self.age(seconds=101, nanoseconds=99999999), 0)
        self.assertEqual(self.age(seconds=101, nanoseconds=100000000), 1)
        self.assertEqual(self.age(seconds=3703), 3603)
        self.assertEqual(self.age(start="10010", hz=100), 3)
        self.assertEqual(self.age(start="100100", hz=1000), 3)

    def test_invalid_identity_or_clock_is_unknown_and_next_valid_read_recovers(self):
        for changes in (
            dict(start=None), dict(start=""), dict(start="-1"),
            dict(start="+1"), dict(start="1x"), dict(start=" 1"),
            dict(start="18446744073709551616"), dict(start="9" * 100),
            dict(hz=0), dict(hz=-1), dict(seconds=-1),
            dict(nanoseconds=-1), dict(nanoseconds=1000000000),
            dict(seconds=99), dict(seconds=100, nanoseconds=99999999),
            dict(no_clock=True),
        ):
            with self.subTest(changes=changes):
                self.assertIsNone(self.age(**changes))
                self.assertEqual(self.age(), 3)

    def test_birth_reconnect_preserve_process_age_restart_resets_only_process_age(self):
        self.start()
        initial = self.publications(5)
        discovery = json.loads(initial["homeassistant/device/tv_qn90a/config"][1])
        cmps = discovery["cmps"]
        self.assertEqual(len(cmps), 27)
        agent = cmps["agent_uptime"]
        self.assertEqual(agent["name"], "Agent uptime")
        self.assertEqual(agent["unique_id"], "tv_qn90a_agent_uptime")
        self.assertEqual(agent["entity_category"], "diagnostic")
        self.assertEqual(agent["availability_topic"], "tv/qn90a/availability")
        self.assertEqual(cmps["uptime"]["unique_id"], "tv_qn90a_uptime")
        self.assertEqual(cmps["uptime"]["name"], "Uptime")
        time.sleep(2.1)
        self.publish("homeassistant/status", b"online")
        birth = json.loads(self.publications(5)["tv/qn90a/health"][1])
        self.assertGreaterEqual(birth["agent_uptime_s"], 2)
        self.assertLessEqual(birth["agent_uptime_s"], birth["uptime_s"])
        self.sock.close()
        self.sock = None
        self.handshake()
        reconnect = json.loads(self.publications(5)["tv/qn90a/health"][1])
        self.assertGreaterEqual(reconnect["agent_uptime_s"], birth["agent_uptime_s"])
        self.stop()
        self.start()
        restart = json.loads(self.publications(5)["tv/qn90a/health"][1])
        self.assertLess(restart["agent_uptime_s"], reconnect["agent_uptime_s"])
        self.assertGreaterEqual(restart["uptime_s"], reconnect["uptime_s"])


if __name__ == "__main__":
    unittest.main()
