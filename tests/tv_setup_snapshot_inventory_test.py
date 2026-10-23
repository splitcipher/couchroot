"""Keep each snapshot's query and result inventory consistent without stale caching."""

import re
import unittest
from unittest.mock import Mock, patch

from tvsetup.config import profile
from tvsetup.planner import hub_sources
from tvsetup.transport import Transport, paths


class SnapshotInventoryTests(unittest.TestCase):
    def test_each_snapshot_reads_hub_sources_once_and_reuses_its_inventory(self):
        for device in ("qn90a", "s90d"):
            with self.subTest(device=device):
                tv = Transport.__new__(Transport)
                tv.profile = profile(device)

                def sdk(script, timeout):
                    blocks = []
                    for name in re.findall(r"TVSETUP_BEGIN:([a-zA-Z0-9_.]+)", script):
                        value = {
                            "boot": "00000000-0000-4000-8000-000000000001",
                            "uptime": "42.0 0.0",
                            "integrity": "ok",
                        }.get(name, "")
                        if name.startswith("file"):
                            value = "%064x" % int(name[4:])
                        blocks.append(
                            "\nTVSETUP_BEGIN:"
                            + name
                            + "\n"
                            + value
                            + "\nTVSETUP_END:"
                            + name
                            + "\n"
                        )
                    return "".join(blocks)

                tv.sdk = Mock(side_effect=sdk)
                with (
                    patch("tvsetup.planner.hub_sources", wraps=hub_sources) as sources,
                    patch("tvsetup.transport.paths", wraps=paths) as inventory,
                ):
                    first = tv.snapshot()
                    inventory.assert_called_once_with(device)
                    sources.assert_called_once_with(device)
                    second = tv.snapshot()
                    self.assertEqual(inventory.call_count, 2)
                    self.assertEqual(sources.call_count, 2)
                expected = {path: "%064x" % n for n, path in enumerate(paths(device))}
                self.assertEqual(first["files"], expected)
                self.assertEqual(second["files"], expected)


if __name__ == "__main__":
    unittest.main()
