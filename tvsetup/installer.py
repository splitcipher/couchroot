"""One installer front door; offline commands never load site or device tooling.

Web and native installation share locks and the journal engine. Native requires
an explicitly enrolled baseline and pinned autonomous-root transport.
"""

import argparse
import json
import os
from pathlib import Path
import shutil
import struct
import sys
import tempfile
import zipfile

from .common import REPO, Refused, atomic_json, run, sha
from .config import LAUNCHER_COMPONENTS, profile
from .dependencies import checks as dependency_checks, tool_check
from .registry import accepted_devices, reviewed_identity

WEB_COMPONENTS = LAUNCHER_COMPONENTS


def parser():
    p = argparse.ArgumentParser(description=__doc__)
    sub = p.add_subparsers(dest="command", required=True)
    for name in (
        "plan",
        "doctor",
        "prepare",
        "inspect",
        "apply",
        "status",
        "verify",
        "resume",
        "rollback",
    ):
        c = sub.add_parser(name)
        c.add_argument(
            "--device", choices=accepted_devices(), required=name != "doctor"
        )
        c.add_argument(
            "--launcher",
            choices=("web", "native")
            if name in ("status", "verify", "resume", "rollback")
            else ("web",),
            required=name != "doctor",
            help="Signed web Hub; native is retained only for existing journal recovery",
        )
        c.add_argument("--json", action="store_true")
        if name == "doctor":
            c.add_argument(
                "--tv",
                metavar="HOST",
                help="Read-only TV reachability; no site or toolkit required",
            )
            c.add_argument(
                "--stage",
                choices=("prepare", "install"),
                default="install",
                help="Check offline preparation or installation prerequisites (default: install)",
            )
        if name == "prepare":
            c.add_argument(
                "--output",
                type=Path,
                required=True,
                help="New private directory outside the source checkout",
            )
            native = c.add_mutually_exclusive_group()
            native.add_argument(
                "--native-binary",
                type=Path,
                help="Existing ARM ELF; copied, never executed",
            )
            native.add_argument(
                "--build-native",
                action="store_true",
                help="Build with the existing offline Docker recipe/image",
            )
            c.add_argument(
                "--web-state",
                type=Path,
                help="Explicit localStorage JSON export to convert once for native; never reads a TV",
            )
            c.add_argument(
                "--native-telemetry-binary",
                type=Path,
                help="QN90A native collector ELF; produces an offline-only integration candidate",
            )
        if name in ("inspect", "apply", "status", "verify", "resume", "rollback"):
            c.add_argument("--site", type=Path)
            c.add_argument(
                "--dry-run",
                action="store_true",
                help="Print dispatch only; no configuration reads or connections",
            )
        if name in ("inspect", "apply", "status", "verify", "resume", "rollback"):
            c.add_argument(
                "--agent",
                type=Path,
                help="Private pinned root-agent enrollment (native only)",
            )
            c.add_argument(
                "--bundle",
                type=Path,
                help="Prepared native bundle (native apply/inspect)",
            )
            c.add_argument(
                "--hook-config",
                type=Path,
                help="Reviewed baseline hook/dependency enrollment",
            )
            c.add_argument(
                "--source-rearm",
                action="store_true",
                help="Opt in to native periodic saved-source re-arm",
            )
        if name in ("status", "verify"):
            c.add_argument("--run", help="Native journal to inspect/verify")
        if name in ("apply", "resume", "rollback"):
            c.add_argument("--yes", action="store_true")
            c.add_argument("--non-interactive", action="store_true")
        if name in ("resume", "rollback"):
            c.add_argument("--run", required=True)
        if name == "resume":
            c.add_argument("--retry-unchanged", action="store_true")
        if name == "apply":
            c.add_argument(
                "--activate",
                action="store_true",
                help="Explicit web launch after installation; no reboot",
            )
    survey_parser = sub.add_parser(
        "survey", help="Read-only identity survey; no toolkit or site required"
    )
    survey_parser.add_argument("host", metavar="HOST")
    survey_parser.add_argument("--json", action="store_true")
    survey_parser.add_argument(
        "--report",
        type=Path,
        metavar="DIR",
        help="Write redacted reports in a new private directory outside this checkout",
    )
    survey_parser.add_argument(
        "--profile-skeleton",
        action="store_true",
        help="Also write an UNVERIFIED skeleton; requires --report",
    )
    initialize = sub.add_parser(
        "init", help="Survey and enroll an exact model in a new private site.json"
    )
    initialize.add_argument("host", metavar="HOST", help="TV IPv4 address")
    initialize.add_argument("--json", action="store_true")
    trust = sub.add_parser(
        "trust",
        help="Print trust.json fingerprints from independently supplied certificates",
    )
    trust.add_argument("--device", choices=accepted_devices(), required=True)
    trust.add_argument("--signing-profile", required=True)
    trust.add_argument("--author-cert", type=Path, required=True)
    trust.add_argument("--distributor-cert", type=Path, required=True)
    trust.add_argument("--json", action="store_true")
    return p


def validate_selection(device, launcher):
    if launcher == "native" and device != "qn90a":
        raise Refused(
            "Native Hub supports only QN90A firmware "
            + reviewed_identity("qn90a")["firmware"]
            + "; choose --launcher web for S90D"
        )


def recipe(device, launcher):
    validate_selection(device, launcher)
    target = profile(device)
    native = launcher == "native"
    return {
        "schema": 1,
        "device": device,
        "launcher": launcher,
        "offline": True,
        "target": {
            key: target[key]
            for key in ("model", "firmware", "platform", "architecture")
        },
        "hardware_checked": False,
        "deployment_available": True,
        "components": ["hub", "home", "airplay", "native-launcher"]
        if native
        else list(WEB_COMPONENTS),
        "steps": (
            [
                "Prepare the signed web Hub fallback and preserve its ISP/Home routes.",
                "Prepare an ARM native executable and separate native preferences.",
                "Review the existing boot-hook chain and autonomous root recovery.",
                "Journal native payload staging before the final boot-hook activation.",
                "Verify readback; accept boot and recovery separately.",
            ]
            if native
            else [
                "Inspect exact physical identity, firmware, signing trust and existing routes.",
                "Build/sign the web Hub and model-specific startup dependencies.",
                "Back up and journal each change with the shared tv-setup engine.",
                "Install Hub, Home/AirPlay routes and model-specific startup.",
                "Verify readback; launch only when --activate was requested.",
            ]
        ),
        "preserve": [
            "existing preferences",
            "Samsung Home fallback",
            "telemetry choices",
            "optional apps",
            "NAS configuration",
        ],
        "blockers": [],
        "requirements": [
            "Configured signed web fallback, ISP/Home/AirPlay routes",
            "Reviewed hook/dependency enrollment and pinned root agent",
            "Separate hardware acceptance after explicit deployment authorization",
        ]
        if native
        else [],
        "notes": [
            "Universal means one interface across supported launcher/model combinations; unknown firmware remains unsupported.",
            "Offline planning is not device preflight.",
        ]
        + (
            [
                "Web Hub remains required alongside native.",
                "Native has no automatic conversion of a currently installed private trial.",
            ]
            if native
            else []
        ),
    }


def doctor(device, launcher, stage="install"):
    result = recipe(device, launcher)
    # Native installation consumes an existing bundle and enrolled root agent;
    # provisioning that agent/web fallback is a separate managed setup operation.
    component = "setup" if launcher == "web" and stage == "install" else "prepare"
    checks = dependency_checks(component)
    if component == "setup":
        checks.append(tool_check("tizen", os.environ.get("TIZEN", "tizen")))
    result["stage"] = stage
    result["checks"] = checks
    result["optional_checks"] = []
    if launcher == "native":
        result["optional_checks"] = [tool_check("docker"), tool_check("node")]
        result["notes"] += [
            "Docker is needed only for prepare --build-native; Node only for prepare --web-state.",
            "Native installation requires an already configured web fallback and root agent; their provisioning still requires managed setup.",
        ]
    result["notes"] += [
        "Certificate enrollment, SDB/toolkit, native Docker image and TV ABI still need separate validation.",
        "Offline preparation does not require .NET. Web installation still builds managed helpers.",
    ]
    return result


def validate_native_binary(data):
    """Reject the wrong architecture and malformed load segments without execution.

    This structural check is not a firmware ABI/signature/hardware acceptance test.
    """
    if (
        len(data) < 52
        or len(data) > 32 * 1024 * 1024
        or data[:7] != b"\x7fELF\x01\x01\x01"
    ):
        raise Refused(
            "Native payload must be a 32-bit little-endian ARM ELF (maximum 32 MiB)"
        )
    fields = struct.unpack_from("<HHIIIIIHHHHHH", data, 16)
    kind, machine, version, entry, phoff, _, flags, ehsize, phsize, phnum, _, _, _ = (
        fields
    )
    if (
        kind not in (2, 3)
        or machine != 40
        or version != 1
        or not entry
        or ehsize != 52
        or phsize != 32
        or not phnum
    ):
        raise Refused("Unsupported native ELF header or executable layout")
    if flags & 0x400 or (flags >> 24) != 5:
        raise Refused("Native payload requires ARM EABI5 soft-float ABI")
    if phoff < ehsize or phoff + phnum * phsize > len(data):
        raise Refused("Truncated native ELF program headers")
    executable = False
    for i in range(phnum):
        segment, offset, address, _, size, memory_size, permissions, _ = (
            struct.unpack_from("<IIIIIIII", data, phoff + i * phsize)
        )
        if offset + size > len(data):
            raise Refused("Truncated native ELF segment")
        if segment == 1:
            if size > memory_size:
                raise Refused("Malformed native ELF load segment")
            executable |= bool(
                permissions & 1 and address <= entry < address + memory_size
            )
    if not executable:
        raise Refused("Native entry point is outside executable load segments")


def web_package(device, destination):
    # Same model-aware sources as the shared signing builder, still unsigned.
    from .planner import hub_sources

    members = hub_sources(device)
    with zipfile.ZipFile(destination, "x", zipfile.ZIP_DEFLATED) as archive:
        for name, data in sorted(members.items()):
            info = zipfile.ZipInfo(name, (2026, 9, 19, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o100600 << 16
            archive.writestr(info, data)


def local_command(argv, *, env=None):
    try:
        run(argv, cwd=REPO, env=env, timeout=300)
    except (OSError, Refused):
        # Converter errors can contain private preferences. Never echo raw output.
        # The shared runner also terminates the host process group on timeout.
        raise Refused(
            "Local build/conversion failed or timed out; check prerequisites and input; no bundle published"
        ) from None


def prepare(args):
    result = recipe(args.device, args.launcher)
    native = args.launcher == "native"
    if native:
        raise Refused("Pure-native preparation is retired; use the WebView experiment")
    if not native and (
        args.native_binary
        or args.build_native
        or args.web_state
        or args.native_telemetry_binary
    ):
        raise Refused(
            "Native binary/build/preference options require --launcher native"
        )
    if native and not (args.native_binary or args.build_native):
        raise Refused(
            "Native preparation requires --native-binary PATH or --build-native"
        )
    # All inputs are resolved before creating output. Never overwrite prior bundles.
    requested = args.output.expanduser().absolute()
    if requested.exists() or requested.is_symlink():
        raise Refused("Output already exists; choose a new private directory")
    output = requested.resolve()
    if output == REPO or REPO in output.parents:
        raise Refused("Keep installer bundles outside the source checkout")
    binary = None
    telemetry = None
    if args.native_telemetry_binary:
        from .native_hook import read_bounded
        from .native_telemetry import prepare as prepare_telemetry

        telemetry = prepare_telemetry(
            read_bounded(args.native_telemetry_binary.expanduser(), 32 * 1024 * 1024)
        )
    if args.native_binary:
        path = args.native_binary.expanduser()
        if path.stat().st_size > 32 * 1024 * 1024:
            raise Refused("Native binary exceeds 32 MiB")
        binary = path.read_bytes()
        validate_native_binary(binary)
    if args.web_state:
        export = args.web_state.expanduser().resolve()
        if not export.is_file() or export.stat().st_size > 1024 * 1024:
            raise Refused("Web state must be an explicit JSON export of at most 1 MiB")
    output.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
    staging = Path(tempfile.mkdtemp(prefix=".couchroot-prepare-", dir=output.parent))
    try:
        web_package(args.device, staging / "MinimalHub-unsigned.wgt")
        choices = {
            "components": list(WEB_COMPONENTS),
            "exclude": [],
            "keep": [],
            "remove": [],
            "telemetry_enabled": None,
            "endpoint": None,
            "artifacts": {},
        }
        atomic_json(staging / "web-choices.json", choices)
        result.update(
            kind="couchroot-preparation",
            phase="prepared-not-installed",
            signed=False,
            apply_consumes_bundle=native,
            files={
                p.name: {"sha256": sha(p.read_bytes()), "bytes": p.stat().st_size}
                for p in sorted(staging.iterdir())
                if p.is_file()
            },
        )
        result["notes"] += [
            "The web apply command builds/signs from the current checkout; this bundle is an offline review artifact, not a signed deployment input."
        ]
        atomic_json(staging / "manifest.json", result)
        # mkdir is an exclusive reservation, including if another preparation won
        # the race while building. Publish the manifest last inside that directory.
        output.mkdir(mode=0o700)
        try:
            for item in sorted(
                staging.iterdir(), key=lambda p: p.name == "manifest.json"
            ):
                item.rename(output / item.name)
        except BaseException:
            shutil.rmtree(output)
            raise
        result["output"] = str(output)
        return result
    finally:
        shutil.rmtree(staging)


def dispatch(args):
    result = recipe(args.device, args.launcher)
    if args.launcher == "native":
        result.update(
            command=args.command, setup_arguments=None, scope="launcher-native"
        )
        return result
    command = {"inspect": "plan", "resume": "apply"}.get(args.command, args.command)
    forwarded = [command, "--device", args.device]
    if args.site is not None:
        forwarded += ["--site", str(args.site.expanduser().resolve())]
    if args.json:
        forwarded += ["--json"]
    if args.command not in ("resume", "rollback"):
        # Lists override saved full-setup choices. No cleanup, telemetry, NAS or
        # screensaver changes are implicitly brought in by this launcher installer.
        forwarded += [
            "--components",
            ",".join(WEB_COMPONENTS),
            "--exclude",
            "",
            "--remove",
            "",
        ]
    for name in ("yes", "non_interactive", "activate", "retry_unchanged"):
        if getattr(args, name, False):
            forwarded.append("--" + name.replace("_", "-"))
    if args.command == "resume":
        forwarded += ["--resume", args.run]
    if args.command == "rollback":
        forwarded += ["--run", args.run]
    result.update(
        command=args.command,
        offline=bool(args.dry_run),
        scope="launcher-web",
        setup_arguments=forwarded,
    )
    return result


def emit(result, as_json):
    if as_json:
        print(json.dumps(result, indent=2))
        return
    print(
        f"{result['device']}: {result['launcher']} launcher — "
        + ("offline preparation" if result["offline"] else "explicit device operation")
    )
    print("Target: " + result["target"]["model"] + " / " + result["target"]["firmware"])
    for step in result["steps"]:
        print("  " + step)
    for check in result.get("checks", []):
        print(("  OK: " if check["available"] else "  MISSING: ") + check["name"])
    for check in result.get("optional_checks", []):
        print(
            "  Optional: "
            + check["name"]
            + (" available" if check["available"] else " missing")
        )
    for requirement in result.get("requirements", []):
        print("  Requires: " + requirement)
    for blocker in result["blockers"]:
        print("  Blocked: " + blocker)
    if result.get("setup_arguments"):
        import shlex

        print(
            "  Shared engine arguments (launcher-web scope): "
            + shlex.join(result["setup_arguments"])
        )
    if result.get("output"):
        print("Prepared (not installed): " + result["output"])
    for note in result["notes"]:
        print("  " + note)


def main(argv=None):
    raw_argv = list(sys.argv[1:] if argv is None else argv)
    try:
        argument_parser = parser()
        args = argument_parser.parse_args(raw_argv)
    except Refused as error:
        if "--json" in raw_argv:
            print(json.dumps(error.as_json(), indent=2))
        else:
            print("couchroot-install: " + str(error), file=sys.stderr)
        return 1
    if args.command == "doctor":
        if args.tv:
            if args.device or args.launcher or args.stage != "install":
                argument_parser.error(
                    "doctor --tv cannot be combined with --device, --launcher or --stage prepare"
                )
        elif not args.device or not args.launcher:
            argument_parser.error(
                "doctor requires --device and --launcher, or --tv HOST"
            )
    if args.command == "survey" and args.profile_skeleton and not args.report:
        argument_parser.error("--profile-skeleton requires --report DIR")
    try:
        if args.command == "survey":
            from .survey import emit as emit_survey, survey

            result = survey(args.host)
            if args.report:
                from .device_report import write_report

                write_report(
                    result, args.report, profile_skeleton=args.profile_skeleton
                )
                result["report_written"] = True
            emit_survey(result, args.json)
            if args.report and not args.json:
                print(
                    "Redacted device reports written to the requested private directory."
                )
            return 0
        if args.command == "doctor" and args.tv:
            from .onboarding import doctor as doctor_tv

            result = doctor_tv(args.tv)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                for check in result["checks"]:
                    print(f"{check['name']}: {check['status']} — {check['hint']}")
            return 0 if result["ok"] else 2
        if args.command == "init":
            from .onboarding import init

            result = init(args.host)
            if args.json:
                print(json.dumps(result, indent=2))
            else:
                print(
                    "Created private site.json for "
                    + result["device"]
                    + ". Firmware and signing trust still require independent checks."
                )
            return 0
        if args.command == "trust":
            from .onboarding import trust_entry

            print(
                json.dumps(
                    trust_entry(
                        args.device,
                        args.signing_profile,
                        args.author_cert,
                        args.distributor_cert,
                    ),
                    indent=2,
                )
            )
            return 0
        validate_selection(args.device, args.launcher)
        if args.command == "plan":
            emit(recipe(args.device, args.launcher), args.json)
            return 0
        if args.command == "doctor":
            result = doctor(args.device, args.launcher, args.stage)
            emit(result, args.json)
            return 0 if all(c["available"] for c in result["checks"]) else 2
        if args.command == "prepare":
            emit(prepare(args), args.json)
            return 0
        result = dispatch(args)
        if args.dry_run:
            emit(result, args.json)
            return 0
        if args.launcher == "native":
            from .native_cli import main as native_main

            return native_main(args)
        if (
            args.agent
            or args.bundle
            or args.hook_config
            or args.source_rearm
            or (args.command in ("status", "verify") and args.run)
        ):
            raise Refused(
                "Native enrollment/bundle/run options require --launcher native"
            )
        # Importing the device engine is intentionally below all offline paths and
        # dispatch. This is the web gateway to private site/device access.
        from .cli import main as setup_main

        return setup_main(result["setup_arguments"], launcher_only=True)
    except (Refused, OSError, ValueError) as error:
        if args.json:
            refusal = (
                error
                if isinstance(error, Refused)
                else Refused(
                    "Local input/output failure; check the supplied paths and available space"
                )
            )
            print(json.dumps(refusal.as_json(), indent=2))
            return 1
        print(
            "couchroot-install: "
            + (
                str(error)
                if isinstance(error, Refused)
                else "Local input/output failure; check the supplied paths and available space"
            ),
            file=sys.stderr,
        )
        return 1
    except KeyboardInterrupt:
        print("couchroot-install: Interrupted; no automatic retry", file=sys.stderr)
        return 1
