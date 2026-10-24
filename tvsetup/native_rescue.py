"""Journaled native SDK rescue commands for an already admitted root executor.

No transport, installation, root acquisition or automatic fallback is provided.
Callers own physical-device admission, the per-device lock and pending-run checks.
This orchestration is locally tested; hardware adoption remains a separate gate.
"""

import ipaddress
import json
from pathlib import Path
import re
import shlex
import time
import uuid

from .common import Refused, atomic_json, sha
from .config import profile
from .transport import hash_guard
from .registry import accepted_devices

Q = shlex.quote


def plan(
    model,
    boot_id,
    code_directory,
    binary_sha256,
    expected,
    target,
    *,
    tag=None,
    firmware=None,
):
    if model not in accepted_devices():
        raise Refused("Unsupported native rescue model")
    safety = profile(model)
    if firmware is not None and firmware != safety["firmware"]:
        from .qn90a_firmware_trial import safety_profile

        safety = safety_profile(model, firmware)
    tag = uuid.uuid4().hex if tag is None else tag
    if not isinstance(tag, str) or not re.fullmatch("[a-f0-9]{32}", tag):
        raise Refused("Invalid native rescue identity")
    if not isinstance(boot_id, str) or not re.fullmatch(
        r"[a-f0-9]{8}(?:-[a-f0-9]{4}){3}-[a-f0-9]{12}", boot_id
    ):
        raise Refused("Invalid native rescue boot binding")
    if not isinstance(code_directory, str) or not re.fullmatch(
        r"/opt/couchroot-native-recovery/[a-f0-9]{32}/code", code_directory
    ):
        raise Refused("Native rescue requires an owned versioned code directory")
    if not isinstance(binary_sha256, str) or not re.fullmatch(
        "[a-f0-9]{64}", binary_sha256
    ):
        raise Refused("Invalid native recovery digest")
    for address in (expected, target):
        try:
            parsed = ipaddress.IPv4Address(address)
            if (
                not isinstance(address, str)
                or str(parsed) != address
                or parsed.is_unspecified
            ):
                raise ValueError()
        except (ValueError, TypeError, ipaddress.AddressValueError):
            raise Refused("Native rescue requires canonical nonzero IPv4") from None
    if expected == target:
        raise Refused("Rescue must change the expected host")
    result = dict(
        schema=1,
        model=model,
        firmware=safety["firmware"],
        architecture=safety["architecture"],
        boot_id=boot_id,
        code_directory=code_directory,
        binary_sha256=binary_sha256,
        expected=expected,
        target=target,
        tag=tag,
        delay_seconds=300,
    )
    if "firmware_file_sha256" in safety:
        result["firmware_file_sha256"] = safety["firmware_file_sha256"]
    return result


def validate(value):
    try:
        bound = plan(
            *(
                value[k]
                for k in (
                    "model",
                    "boot_id",
                    "code_directory",
                    "binary_sha256",
                    "expected",
                    "target",
                )
            ),
            tag=value["tag"],
            firmware=value["firmware"],
        )
        if value != bound:
            raise Refused("Native rescue plan drift")
        return bound
    except (KeyError, TypeError):
        raise Refused("Malformed native rescue plan") from None


def commands(value):
    p = validate(value)
    unit = "couchroot-native-rescue-" + p["tag"]
    description = "couchroot-native-rescue:" + sha(
        json.dumps(p, sort_keys=True).encode()
    )
    code = p["code_directory"]
    binary = code + "/sdk-host-recovery"
    prefix = (
        "set -eu\nexport PATH=/usr/bin:/bin\n"
        "export DBUS_SYSTEM_BUS_ADDRESS=kernel:path=/sys/fs/kdbus/0-system/bus\n"
        'test "$(id -u)" = 0\n'
        'test "$(cat /proc/sys/kernel/random/boot_id)" = ' + Q(p["boot_id"]) + "\n"
        "grep -qx " + Q("Version=" + p["firmware"] + ";") + " /etc/prd_info.ini\n"
        'test "$(uname -m)" = ' + Q(p["architecture"]) + "\n"
    )
    if "firmware_file_sha256" in p:
        prefix += hash_guard("/etc/prd_info.ini", p["firmware_file_sha256"])
    guards = 'test "$(readlink -f ' + Q(code) + ')" = ' + Q(code) + "\n"
    # Every ancestor is root-owned and non-writable by group/other; never repair it.
    for path in (
        "/opt",
        "/opt/couchroot-native-recovery",
        str(Path(code).parent),
        code,
    ):
        guards += "test ! -L " + Q(path) + "; test -d " + Q(path) + "\n"
        guards += (
            'case "$(stat -c %u:%g:%a '
            + Q(path)
            + ')" in 0:0:700|0:0:755|0:0:500|0:0:555) ;; *) exit 1;; esac\n'
        )
    guards += (
        "test -f "
        + Q(binary)
        + '\ntest "$(stat -c %u:%g:%a '
        + Q(binary)
        + ')" = 0:0:500\n'
        + hash_guard(binary, p["binary_sha256"])
    )
    invocation = (
        prefix
        + hash_guard(binary, p["binary_sha256"])
        + "/usr/bin/env -i PATH=/usr/bin:/bin "
        + Q(binary)
        + " set "
        + Q(p["expected"])
        + " "
        + Q(p["target"])
        + " 0\n"
        "/usr/bin/systemctl restart sdbd.service\n"
    )
    arm = prefix + guards
    for suffix in (".service", ".timer"):
        arm += (
            'test "$(systemctl show -p LoadState '
            + unit
            + suffix
            + ')" = LoadState=not-found\n'
        )
    arm += (
        "vconftool get db/sdk/develop/ip | grep -Fx "
        + Q("db/sdk/develop/ip, value = " + p["expected"] + " (String)")
        + " >/dev/null\n"
        "systemd-run --unit="
        + unit
        + " --description="
        + description
        + " --on-active=300s --timer-property=AccuracySec=1s "
        "-p Type=oneshot -p RemainAfterExit=yes -p User=0 -p Group=0 -p SmackProcessLabel=System "
        "-p PrivateMounts=yes -p BindReadOnlyPaths="
        + Q(code)
        + " /bin/sh -c "
        + Q(invocation)
        + "\n"
        'test "$(systemctl show -p ActiveState '
        + unit
        + '.timer)" = ActiveState=active\n'
        'test "$(systemctl show -p ExecMainStartTimestampMonotonic '
        + unit
        + '.service)" = ExecMainStartTimestampMonotonic=0\n'
        "echo NATIVE_RESCUE_ARMED\n"
    )
    retire = prefix + (
        'test "$(systemctl show -p Description '
        + unit
        + '.service)" = '
        + Q("Description=" + description)
        + "\n"
        'test "$(systemctl show -p RemainAfterExit '
        + unit
        + '.service)" = RemainAfterExit=yes\n'
        "systemctl stop " + unit + ".timer\n"
        'test "$(systemctl show --all -p Job ' + unit + '.service)" = Job=\n'
    )
    # Check AFTER stopping the timer: a trigger racing retirement must be reported,
    # never called unfired, and its independently running rescue must not be killed.
    for prop, expected in (
        ("ExecMainStartTimestampMonotonic", "0"),
        ("MainPID", "0"),
        ("ActiveState", "inactive"),
    ):
        retire += (
            'test "$(systemctl show -p '
            + prop
            + " "
            + unit
            + '.service)" = '
            + prop
            + "="
            + expected
            + "\n"
        )
    retire += (
        'test "$(systemctl show -p ActiveState '
        + unit
        + '.timer)" = ActiveState=inactive\n'
        "echo NATIVE_RESCUE_RETIRED_UNFIRED\n"
    )
    return dict(arm=arm, retire=retire)


def submit(value, action, directory, execute):
    """Submit once through execute(request_id, shell); persist unknown outcomes.

    The executor must return exit_code, timed_out and stdout. A lost/failed reply
    leaves a non-replayable record. Retirement may reconcile an uncertain arm,
    but only the exact boot/unit binding and an unfired service can pass it.
    """
    scripts = commands(value)
    if action not in scripts:
        raise Refused("Unknown native rescue action")
    directory = Path(directory)
    if directory.is_symlink():
        raise Refused("Rescue journal must not be a symlink")
    directory.mkdir(parents=True, exist_ok=True, mode=0o700)
    from .common import lock

    with lock(directory / "lock"):
        file = directory / (action + ".json")
        if file.exists() or file.is_symlink():
            raise Refused("Rescue action already submitted; reconcile without replay")
        plan_path = directory / "plan.json"
        if plan_path.is_symlink():
            raise Refused("Rescue plan must not be a symlink")
        if plan_path.exists():
            if json.loads(plan_path.read_text()) != value:
                raise Refused("Rescue journal binding changed")
        elif action != "arm":
            raise Refused("Retirement requires the original arm journal")
        else:
            atomic_json(plan_path, value)
        if action == "retire":
            arm_path = directory / "arm.json"
            if arm_path.is_symlink() or not arm_path.is_file():
                raise Refused("Retirement requires the original arm intent")
            arm = json.loads(arm_path.read_text())
            if (
                arm.get("action") != "arm"
                or arm.get("script") != scripts["arm"]
                or arm.get("state") not in ("submitted", "unknown", "completed")
            ):
                raise Refused("Original arm intent binding changed")
        record = dict(
            id=str(uuid.uuid4()),
            action=action,
            state="submitted",
            script=scripts[action],
            submitted_monotonic=time.monotonic(),
            submitted_utc_seconds=time.time(),
        )
        atomic_json(file, record)
        try:
            result = execute(record["id"], record["script"])
            record["result"] = result
            marker = (
                "NATIVE_RESCUE_ARMED"
                if action == "arm"
                else "NATIVE_RESCUE_RETIRED_UNFIRED"
            )
            if (
                result.get("exit_code") != 0
                or result.get("timed_out") is not False
                or result.get("stdout", "").splitlines()[-1:] != [marker]
            ):
                raise Refused(
                    "Native rescue outcome unconfirmed; inspect without replay"
                )
            record.update(state="completed", result=result)
        except Exception as error:
            record.update(state="unknown", error_type=type(error).__name__)
            atomic_json(file, record)
            raise
        atomic_json(file, record)
        return record
