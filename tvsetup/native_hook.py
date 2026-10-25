"""QN90A native boot-hook rendering and immutable, reviewed baseline enrollment.

No transport is imported here. Enrollment is data; baseline code is never run on
this host. The previous hook and its absolute dependencies remain intact.
"""

import json
from pathlib import Path
import re

from .common import Refused, sha, safe_id
from .registry import reviewed_identity
from .transport import Q, hash_guard

HOOK = "/opt/etc/parseinfo.sh"
SCOPE = "launcher-native"
UNIT = "couchroot-native-hub-boot"
STATE_PATH = "/opt/couchroot-native-state/preferences"
MAX_FILE = 4 * 1024 * 1024


def remote_path(value):
    if (
        not isinstance(value, str)
        or not re.fullmatch(r"/opt/[A-Za-z0-9_./-]+", value)
        or any(x in ("", ".", "..") for x in value.split("/")[1:])
    ):
        raise Refused("Enrollment paths must be canonical /opt file paths")
    return value


def digest(value):
    if not isinstance(value, str) or not re.fullmatch(r"[0-9a-f]{64}", value):
        raise Refused("Enrollment requires lowercase SHA256 digests")
    return value


def read_bounded(path, maximum=MAX_FILE):
    if path.is_symlink() or not path.is_file() or path.stat().st_size > maximum:
        raise Refused("Expected a bounded regular local input file (no symlinks)")
    value = path.read_bytes()
    if len(value) > maximum:
        raise Refused("Input grew beyond its size limit")
    return value


def enrollment(path):
    """Explicit copies/pins, not a promise to discover arbitrary shell dependencies."""
    path = Path(path).expanduser().resolve()
    data = json.loads(read_bounded(path).decode())
    expected = {
        "schema",
        "device",
        "firmware",
        "hook",
        "dependencies",
        "recovery_guards",
    }
    if (
        not isinstance(data, dict)
        or set(data) != expected
        or data["schema"] != 1
        or data["device"] != "qn90a"
        or data["firmware"] != reviewed_identity("qn90a")["firmware"]
    ):
        raise Refused("Invalid QN90A hook enrollment schema/firmware")
    entries = (
        [data["hook"]] + data["dependencies"]
        if isinstance(data["dependencies"], list)
        else []
    )
    if (
        not entries
        or len(entries) > 64
        or not isinstance(data["recovery_guards"], dict)
        or not data["recovery_guards"]
    ):
        raise Refused(
            "Enroll the hook, bounded dependency copies and at least one autonomous-root recovery guard"
        )
    files = {}
    for entry in entries:
        if (
            not isinstance(entry, dict)
            or set(entry) != {"path", "file", "sha256"}
            or not isinstance(entry["file"], str)
        ):
            raise Refused("Each enrolled file requires path, file and sha256")
        remote = remote_path(entry["path"])
        if remote in files or remote.startswith(
            ("/opt/couchroot-native-", "/opt/couchroot-native/")
        ):
            raise Refused("Duplicate or installer-owned enrollment path")
        source = Path(entry["file"]).expanduser()
        if not source.is_absolute():
            source = path.parent / source
        content = read_bounded(source)
        if sha(content) != digest(entry["sha256"]):
            raise Refused("Enrolled file differs from its reviewed hash")
        # A private native trial must be rolled back using its own journal. Do not
        # layer a second dispatcher over an existing one, even in a dependency.
        if b"couchroot-native-hub-boot" in content or b"COUCHROOT_NATIVE_" in content:
            raise Refused(
                "Existing native dispatch found; restore its baseline with the original journal first"
            )
        files[remote] = content
    if data["hook"]["path"] != HOOK or not files[HOOK].startswith(
        b"#!/usr/bin/awk -f\n"
    ):
        raise Refused("Expected the reviewed QN90A AWK parseinfo hook")
    guards = {remote_path(p): digest(h) for p, h in data["recovery_guards"].items()}
    if HOOK in guards or any(p.startswith("/opt/couchroot-native-") for p in guards):
        raise Refused(
            "Recovery guards cannot reference the replaced hook or new native state"
        )
    if len(guards) > 64 or any(
        p in files and sha(files[p]) != h for p, h in guards.items()
    ):
        raise Refused("Conflicting or oversized recovery guards")
    return {"files": files, "guards": guards}


def layout(identity):
    safe_id(identity)
    base = "/opt/couchroot-native-" + identity
    return {
        "base": base,
        "bin": base + "/bin",
        "binary": base + "/bin/native-hub",
        "previous": base + "/previous.awk",
        "dispatch": base + "/dispatch.sh",
        "watch": base + "/watch.sh",
        "hook": base + "/hook.awk",
        "enabled": base + "/enabled",
    }


def awk_wrapper(script):
    command = "/bin/sh -c " + Q(script)
    # JSON quoting uses the same escapes as AWK for this ASCII-only generated code.
    return (
        '#!/usr/bin/awk -f\nBEGIN { if (ARGV[1] == "couchroot-probe") { print "COUCHROOT_NATIVE_INSTALLER_OK"; exit 0 }\n'
        "rc=system(" + json.dumps(command) + "); exit (rc == 0 ? 0 : 1); }\n"
    ).encode()


def render(
    identity, binary_hash, previous_hash, guards, *, rearm=False, telemetry_boot=None
):
    p = layout(identity)
    watch = f"""#!/bin/sh
set -eu
within() {{ read up rest < /proc/uptime; test "${{up%%.*}}" -le "$1"; }}
trap 'rm -f /tmp/couchroot-early-hub-enabled' EXIT
while within 65; do
    if ! test -f {p["enabled"]} || ! test -e /tmp/init_mode_background; then
        systemctl stop {UNIT}.service
        exit 0
    fi
    sleep 1
done
""".encode()
    dispatch = f"""#!/bin/sh
set -eu
umask 077
exec > /run/couchroot-early-hub.log 2>&1
within() {{ read up rest < /proc/uptime; test "${{up%%.*}}" -le "$1"; }}
within 20
test -f {p["enabled"]}
for path in /tmp/minimal-root-hub-boot /tmp/minimal-hub-boot /tmp/couchroot-native-hub /tmp/couchroot-early-hub-enabled; do
    test ! -e "$path"; test ! -L "$path"
done
mkdir -m 700 /tmp/minimal-root-hub-boot /tmp/minimal-hub-boot /tmp/couchroot-native-hub
printf native-installer > /tmp/minimal-root-hub-boot/couchroot-owner
printf native-installer > /tmp/minimal-hub-boot/claimed
(set -C; printf enabled > /tmp/couchroot-early-hub-enabled)
trap 'rm -f /tmp/couchroot-early-hub-enabled; systemctl stop {UNIT}.service 2>/dev/null || true' EXIT
chmod 644 /tmp/couchroot-early-hub-enabled
chown 5001:100 /tmp/minimal-hub-boot /tmp/minimal-hub-boot/claimed /tmp/couchroot-native-hub
chsmack -a User /tmp/minimal-hub-boot /tmp/minimal-hub-boot/claimed /tmp/couchroot-native-hub /tmp/couchroot-early-hub-enabled
while within 20; do
    test -f {p["enabled"]} || exit 0
    if test -e /tmp/init_mode_background && test -d /run/user/5001; then break; fi
    sleep 0.2
done
test -e /tmp/init_mode_background; test -d /run/user/5001
{hash_guard(p["binary"], binary_hash)}{hash_guard(p["watch"], sha(watch))}systemd-run --no-block --unit={UNIT} -p DefaultDependencies=no -p CPUSchedulingPolicy=other -p User=5001 -p Group=100 -p SmackProcessLabel=User -p BindReadOnlyPaths={p["bin"]} -p RemainAfterExit=yes --setenv=DBUS_SESSION_BUS_ADDRESS=kernel:path=/sys/fs/kdbus/5001-user/bus --setenv=ECORE_EVAS_ENGINE=wayland_egl --setenv=XDG_RUNTIME_DIR=/run/user/5001 --setenv=COUCHROOT_NATIVE_STATE={STATE_PATH} --setenv=COUCHROOT_NATIVE_HOME=1 {"--setenv=COUCHROOT_NATIVE_SOURCE_REARM=1 " if rearm else ""}--setenv=WAYLAND_DISPLAY=wayland-0 /bin/sh -c {Q("exec " + p["binary"] + " --native-guard --stay > /tmp/couchroot-native-hub/boot.log 2>&1")}
systemd-run --no-block --unit=couchroot-early-hub-watch --service-type=oneshot -p DefaultDependencies=no -p TimeoutStartSec=80s /bin/sh {p["watch"]}
trap - EXIT
""".encode()
    # Synchronous submission preserves the marker ordering before the previous
    # web-launch chain. The dispatch itself is uptime-bounded; drawing is async.
    admission = (
        "set -eu\n"
        + "".join(hash_guard(path, h) for path, h in sorted(guards.items()))
        + hash_guard(p["dispatch"], sha(dispatch))
        + "/bin/sh "
        + Q(p["dispatch"])
        + "\n"
    )
    optional = ""
    if telemetry_boot is not None:
        path = remote_path(telemetry_boot["path"])
        expected = digest(telemetry_boot["sha256"])
        # A separate, asynchronous submission. Failure cannot skip the retained
        # hook or make telemetry a condition of drawing the launcher.
        optional = (
            "/bin/sh -c "
            + Q("set -eu\n" + hash_guard(path, expected) + "/bin/sh " + Q(path))
            + " || true\n"
        )
    hook = awk_wrapper(
        "set -eu\n"
        + hash_guard(p["previous"], previous_hash)
        + "/bin/sh -c "
        + Q(admission)
        + " || true\n"
        + optional
        + "exec /usr/bin/awk -f "
        + Q(p["previous"])
        + "\n"
    )
    return {
        "dispatch.sh": dispatch,
        "watch.sh": watch,
        "hook.awk": hook,
        "enabled": b"enabled\n",
    }
