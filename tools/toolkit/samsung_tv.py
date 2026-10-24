"""Bounded diagnostics for the owner’s S90D; no automatic root/flash operations."""
import argparse
import hashlib
import importlib.metadata
import json
import os
from pathlib import Path, PurePosixPath
import re
import socket
import subprocess
import sys
from datetime import datetime, timezone
from urllib.request import urlopen

ROOT = Path(os.environ.get("SAMSUNG_TV_TOOLKIT", Path.home() / ".local/share/samsung-tv-research")).expanduser().resolve()
sys.path.insert(0, str(ROOT / "upstream/src"))
from samsung_tv_root.sdb import SdbClient as _UpstreamSdbClient, route_callback_host  # noqa: E402
import samsung_tv_root.sdb as _sdb_transport  # noqa: E402
from sdb_connection import connect_if_needed  # noqa: E402
# This firmware rejected a 495-byte inline request; stage before that boundary.
_sdb_transport.SDB_APPINSTALL_MAX_SAFE_BYTES = 400


class SdbClient(_UpstreamSdbClient):
    """Pinned transport client with serialized, ready-device reuse."""

    def connect(self) -> None:
        connect_if_needed(self, ROOT / "locks", super().connect)

SNAPSHOT = """id
uname -a
cat /etc/tizen-release
uptime
cat /proc/meminfo
df -h /opt
cat /sys/block/zram0/mm_stat
cat /sys/class/misc/mali0/device/gpuinfo
"""

def run_local(args):
    return subprocess.check_output(args, text=True, stderr=subprocess.STDOUT, timeout=15).strip()

def doctor(config):
    print("Toolkit:", ROOT)
    actual = run_local(["git", "-C", str(ROOT / "upstream"), "rev-parse", "HEAD"])
    if actual != config["upstream_commit"]:
        raise RuntimeError("Upstream checkout no longer matches the reviewed commit")
    print("Reviewed source:", actual)
    print(run_local([str(ROOT / "bin/sdb"), "version"]))
    for name in ("capstone", "pyelftools"):
        try:
            print(f"{name}: {importlib.metadata.version(name)}")
        except importlib.metadata.PackageNotFoundError:
            print(f"{name}: not installed (optional for root-check)")
    if sys.platform == "darwin":
        print("Disassembler:", run_local(["xcrun", "--find", "llvm-objdump"]))
    print(".NET SDKs:\n" + run_local(["dotnet", "--list-sdks"]))
    ilspy = ROOT / "dotnet-tools/ilspycmd"
    if ilspy.exists():
        print(run_local([str(ilspy), "--version"]))
    if (ROOT / "bin/ghidra-headless").exists():
        print("Ghidra launcher:", ROOT / "bin/ghidra")
        print("Ghidra project: ~/Research/samsung-tv/ghidra/S90D_20260919.gpr")
    manifest_path = ROOT / "sha256.json"
    if manifest_path.exists():
        manifest = json.loads(manifest_path.read_text())
        for relative, expected in manifest.items():
            if hashlib.sha256((ROOT / relative).read_bytes()).hexdigest() != expected:
                raise RuntimeError(f"Checksum changed: {relative}")
        print(f"Verified {len(manifest)} saved binary checksums")
    else:
        print("No private binary manifest installed; source-only toolkit")

def identity_refusal(message, fields):
    try:
        from tvsetup.common import Refused
    except ImportError:
        return RuntimeError(message)
    return Refused(
        message,
        code="CR-ID-DEVICE",
        fields=fields,
        next_steps=[
            "Check the selected model and site identity.",
            "See docs/guides/refusal-codes.md#cr-id-device",
        ],
    )

def verify_live_sdk_host(host, callback):
    """Confirm live admission during an explicitly authorized maintenance window."""
    client = SdbClient(ROOT / "bin/sdb", host)
    client.connect()
    client.require_device()
    result = client.capture(
        "vconftool get db/sdk/develop/ip",
        callback_host=callback,
        bind_host=callback,
        timeout=10,
    )
    expected = "db/sdk/develop/ip, value = " + callback + " (String)"
    if result.transport_returncode not in (0, 1) or not re.fullmatch(
        re.escape(expected) + r"\r?\n(?:\r?\n)?\[exit:0\]\s*", result.output
    ):
        raise RuntimeError("Live Developer Mode host is unavailable or differs from this computer; stop maintenance")

def device(config):
    host = config["tv_host"]
    try:
        with urlopen(f"http://{host}:8001/api/v2/", timeout=5) as response:
            data = json.load(response)["device"]
    except Exception:
        # urllib exception messages can contain the configured host.
        raise RuntimeError("TV identity endpoint failed; check the configured address and port 8001") from None
    for field, expected in (("modelName", config["expected_model"]), ("model", config["expected_platform"])):
        if data.get(field) != expected:
            candidate = data.get(field)
            pattern = {"modelName": r"[A-Z]{2}[0-9]{2,3}[A-Z0-9]{5,20}", "model": r"[0-9]{2}_[A-Z0-9]+_[A-Z0-9_]+"}[field]
            found = candidate
            if not isinstance(candidate, str) or not re.fullmatch(pattern, candidate):
                found = "[redacted]"
            for name, item in data.items():
                if name not in ("modelName", "model", "developerMode") and isinstance(item, str) and item and isinstance(candidate, str) and item in candidate:
                    found = "[redacted]"
                    break
            raise identity_refusal(
                f"Target mismatch: {field}={found!r}, expected {expected!r}",
                [{"field": field, "expected": expected, "found": found}],
            )
    if config.get('expected_device_id') is not None and data.get('id') != config['expected_device_id']:
        raise identity_refusal(
            'Physical TV identity differs from site configuration; no SDK command was sent: id does not match site.json',
            [{"field": "id", "expected": "[redacted]", "found": "[redacted]"}],
        )
    callback = route_callback_host(host)
    if str(data.get("developerMode")) != "1":
        raise RuntimeError("Enable Developer Mode on the TV before shell diagnostics")
    if os.environ.get("TV_SETUP_LIVE_SDK_HOST") == "1":
        # HTTP developerIP is cached on these TVs after a runtime host change.
        # Opt-in replaces that one observation with exact live SDK readback;
        # model, physical identity, Developer Mode and later firmware guards stay.
        verify_live_sdk_host(host, callback)
    elif data.get("developerIP") != callback:
        raise RuntimeError(
            "Developer Mode host must match this Mac's routed address: " + callback
        )
    with socket.create_connection((host, 26101), timeout=5):
        pass
    return callback

def capture(config, callback, command, timeout, label):
    client = SdbClient(ROOT / "bin/sdb", config["tv_host"])
    client.connect()
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S.%fZ")
    session = ROOT / "sessions" / f"{stamp}-{label}"
    session.mkdir(parents=True, mode=0o700)
    (session / "command.sh").write_text(command + "\n")
    print("Evidence:", session, flush=True)
    try:
        # The upstream helper appends a semicolon. A trailing newline/comment in
        # a file can otherwise break its wrapper before the callback opens.
        # A subshell also lets an explicit script `exit` reach the exit marker.
        wrapped_command = f"(\n{command}\n)"
        result = client.capture(wrapped_command, callback_host=callback, bind_host=callback, timeout=timeout)
        (session / "output.txt").write_text(result.output)
        match = re.search(r"\n\[exit:(\d+)\]\s*\Z", result.output)
        (session / "result.json").write_text(json.dumps({
            "transport_returncode": result.transport_returncode,
            "remote_exit": int(match[1]) if match else None,
        }, indent=2) + "\n")
        if len(result.output) <= 8000:
            print(result.output)
        else:
            print(result.output[:4000])
            print(f"[Console preview shortened; full {len(result.output)} characters saved to output.txt]")
            print(result.output[-1500:])
        if not match:
            raise RuntimeError("No final exit marker: completion is unconfirmed; command was not retried")
        if result.transport_returncode not in (0, 1) or int(match[1]):
            raise RuntimeError("Remote command or transport reported failure; see saved result")
    except Exception as error:
        (session / "error.txt").write_text(str(error) + "\n")
        raise

def main():
    parser = argparse.ArgumentParser(description=__doc__)
    sub = parser.add_subparsers(dest="action", required=True)
    sub.add_parser("doctor", help="Verify local tools, pinned source, and binary checksums")
    sub.add_parser("status", help="Verify the TV model, developer settings, route, and SDB port")
    sub.add_parser("reconnect", help="Refresh this TV's SDB connection without repeating a command")
    sub.add_parser("snapshot", help="Collect SDK identity, OS, memory, storage, and GPU details")
    sub.add_parser("root-check", help="Run the temporary S90D root identity probe and remove its files")
    sample = sub.add_parser("sample", help="Record vmstat and process snapshots while navigating menus")
    sample.add_argument("--seconds", type=int, default=30, choices=range(5, 61), metavar="5..60")
    script = sub.add_parser("run", help="Execute an explicitly supplied shell file once as SDK; can change the TV")
    script.add_argument("file", type=Path)
    script.add_argument("--timeout", type=int, default=30, choices=range(5, 121), metavar="5..120")
    args = parser.parse_args()
    config = json.loads((ROOT / "config.json").read_text())
    if args.action == "doctor":
        doctor(config)
        return
    callback = device(config)
    if args.action == "status":
        return
    if args.action == "root-check":
        from samsung_tv_root_check import run
        run(config, callback)
        return
    if args.action == "reconnect":
        client = SdbClient(ROOT / "bin/sdb", config["tv_host"])
        client.connect()
        print("SDB connection is ready")
        return
    if args.action == "snapshot":
        capture(config, callback, SNAPSHOT, 25, "snapshot")
    elif args.action == "sample":
        command = ("date -u; uptime; top -b -n 1; "
                   f"vmstat 1 {args.seconds + 1}; sample_rc=$?; "
                   "top -b -n 1; cat /proc/pressure/cpu /proc/pressure/memory /proc/pressure/io 2>/dev/null; "
                   "cat /sys/block/zram0/mm_stat; date -u; (exit $sample_rc)")
        capture(config, callback, command, args.seconds + 15, "sample")
    else:
        capture(config, callback, args.file.read_text(), args.timeout, "run")

if __name__ == "__main__":
    try:
        main()
    except (Exception, KeyboardInterrupt) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        sys.exit(1)
