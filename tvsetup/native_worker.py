"""Reproducible ordinary native candidate artifacts; no TV access or selection."""

from pathlib import Path
import re
import shutil
import struct

from .common import REPO, Refused, atomic_json, sha
from .root_launcher import IMAGE
from .registry import accepted_devices

SOURCE = REPO / "agent"
ARTIFACTS = {
    "native-worker": "worker",
    "native-app-launcher": "app-launcher",
    "native-process-observer": "process-observer",
}
ALLOWED_NEEDED = {
    "libc.so.6",
    "libdl.so.2",
    "libpthread.so.0",
    "librt.so.1",
    "libgcc_s.so.1",
    "ld-linux.so.3",
}


def inspect_binary(data, report, glibc_limit=(2, 28, 0)):
    if (
        len(data) < 52
        or len(data) > 4 * 1024 * 1024
        or data[:7] != b"\x7fELF\x01\x01\x01"
        or struct.unpack_from("<H", data, 16)[0] not in (2, 3)
        or struct.unpack_from("<H", data, 18)[0] != 40
    ):
        raise Refused("Native candidate must be an ARM ELF32 little-endian executable")
    flags = struct.unpack_from("<I", data, 36)[0]
    if flags >> 24 != 5 or flags & 0x400:
        raise Refused("Native candidate must use ARM EABI5 without hard-float ABI")
    interpreters = re.findall(r"Requesting program interpreter:\s*([^\]]+)\]", report)
    if interpreters != ["/lib/ld-linux.so.3"]:
        raise Refused("Native candidate interpreter mismatch")
    needed = sorted(set(re.findall(r"\(NEEDED\).*?\[([^\]]+)\]", report)))
    if "libc.so.6" not in needed or set(needed) - ALLOWED_NEEDED:
        raise Refused("Native candidate has unexpected dynamic dependencies")
    versions = re.findall(r"GLIBC_(\d+)\.(\d+)(?:\.(\d+))?", report)
    parsed = [tuple(int(x or 0) for x in version) for version in versions]
    if not parsed or max(parsed) > glibc_limit:
        raise Refused("Native candidate requires an unsupported GLIBC version")
    # Supplement the ordinary-build source path check with known test-only strings.
    if any(
        marker in data
        for marker in (
            b"--test-child-fault",
            b"COUCHROOT_NATIVE_JOB_INTENT_FAULT",
            b"host-test-without-Smack",
            b"COUCHROOT_IO_TEST_PATH",
        )
    ):
        raise Refused("Test controls found in native candidate")
    return dict(
        abi="armv7-eabi5-softfp",
        interpreter=interpreters[0],
        needed=needed,
        glibc_max=".".join(map(str, max(parsed))),
    )


def build(folder, command):
    folder = Path(folder).resolve()
    if folder.exists() and any(folder.iterdir()):
        raise Refused("Native candidate output must be empty")
    folder.mkdir(parents=True, exist_ok=True)
    snapshot = folder / "source"
    # Snapshot only worker inputs, not benchmark/observer/acceptance controllers.
    # Keep the fault headers: worker.c includes them, with controls compiled out.
    headers = (
        "common.h",
        "descriptor-budget.h",
        "fault-events.h",
        "progress.h",
        "request-io.h",
        "file-policy.h",
        "jobs.h",
        "helpers.h",
        "runtime.h",
        "containment.h",
        "guardian.h",
        "reconcile.h",
        "fault-test.h",
        "offline-reconcile.h",
        "mqtt/config.h",
        "mqtt/discovery.h",
        "mqtt/commands.h",
        "mqtt/wire.h",
        "mqtt/bridge.h",
    )
    inputs = [SOURCE / "native-worker" / name for name in headers] + [
        SOURCE / "native-worker/worker.c",
        SOURCE / "native-worker/build.sh",
        SOURCE / "native-launcher/app-launcher.c",
        SOURCE / "native-launcher/build.sh",
        SOURCE / "native-observer/process-observer.c",
        SOURCE / "native-observer/service-profile.h",
        SOURCE / "native-observer/build.sh",
    ]
    source_hashes = {}
    for source in sorted(inputs):
        if source.is_symlink() or not source.is_file():
            raise Refused("Native candidate source must be a regular file")
        relative = source.relative_to(SOURCE)
        destination = snapshot / relative
        destination.parent.mkdir(parents=True, exist_ok=True)
        data = source.read_bytes()
        destination.write_bytes(data)
        source_hashes[str(relative)] = sha(data)
    image = command(
        ["docker", "image", "inspect", "--format", "{{.Id}}", IMAGE]
    ).strip()
    if not re.fullmatch(r"sha256:[a-f0-9]{64}", image):
        raise Refused("Cannot pin native compiler image identity")
    base = ["docker", "run", "--rm", "--platform", "linux/amd64", "--network", "none"]
    compiler = command(
        base + [image, "arm-linux-gnueabi-gcc", "-dumpfullversion", "-dumpversion"]
    ).strip()
    if not re.fullmatch(r"\d+(?:\.\d+){1,2}", compiler):
        raise Refused("Cannot identify native compiler version")
    runs = []
    for index in (1, 2):
        output = folder / ("build-" + str(index))
        output.mkdir()
        command(
            base
            + [
                "-v",
                str(snapshot) + ":/src:ro",
                "-v",
                str(output) + ":/out",
                image,
                "sh",
                "/src/native-worker/build.sh",
                "/out",
                "--worker-only",
            ]
        )
        command(
            base
            + [
                "-v",
                str(snapshot) + ":/src:ro",
                "-v",
                str(output) + ":/out",
                image,
                "sh",
                "/src/native-observer/build.sh",
                "/out",
            ]
        )
        if {p.name for p in output.iterdir()} != set(ARTIFACTS.values()):
            raise Refused("Ordinary native build emitted unexpected artifacts")
        records = {}
        for name, compiled in ARTIFACTS.items():
            binary = output / compiled
            if binary.is_symlink() or not binary.is_file():
                raise Refused("Native build artifact must be a regular file")
            data = binary.read_bytes()
            report = command(
                base
                + [
                    "-v",
                    str(output) + ":/out:ro",
                    image,
                    "arm-linux-gnueabi-readelf",
                    "-l",
                    "-d",
                    "-V",
                    "/out/" + compiled,
                ]
            )
            if name == "native-process-observer" and len(data) > 128 * 1024:
                raise Refused("Native observer exceeds service artifact limit")
            records[name] = dict(
                sha256=sha(data),
                size=len(data),
                **inspect_binary(
                    data, report, (2, 28, 0) if name == "native-worker" else (2, 17, 0)
                ),
            )
        runs.append(records)
    if runs[0] != runs[1]:
        raise Refused("Repeated native candidate builds differ")
    manifest = dict(
        schema=2,
        kind="native-worker-candidate",
        implementation="native-prototype",
        selection="managed",
        device_qualified=False,
        candidate_profiles=list(accepted_devices()),
        source=source_hashes,
        toolchain=dict(image=image, compiler=compiler),
        reproducible_builds=2,
        artifacts=runs[0],
        runtime_loads={
            "json_c": ["libjson-c.so.5", "libjson-c.so.4"],
            "crypto": ["libcrypto.so.1.1", "libcrypto.so.3"],
        },
    )
    for name, compiled in ARTIFACTS.items():
        shutil.copyfile(folder / "build-1" / compiled, folder / name)
        (folder / name).chmod(0o755)
        if sha((folder / name).read_bytes()) != runs[0][name]["sha256"]:
            raise Refused("Published native artifact differs from verified build")
    atomic_json(folder / "native-manifest.json", manifest)
    return folder
