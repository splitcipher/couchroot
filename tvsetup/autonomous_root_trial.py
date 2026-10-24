"""Journaled, disabled-first agent installation using the shared setup engine."""

import argparse
import json
from pathlib import Path
import re
import shutil
import sys
from .artifacts import verify_package
from .autonomous_root import PACKAGE
from .common import STATE, Refused, atomic_json, read_json, sha, lock, safe_id
from .config import resolve
from .registry import accepted_devices
from .engine import Engine, pending, run_id
from .operations import Driver, observed
from .planner import Action, Plan
from .site import binding, configured_profile, load_site
from .transport import Transport, Q, hash_guard

DATA = "/opt/usr/home/owner/apps_rw/" + PACKAGE + "/data"
PREFIX = "/opt/usr/apps/" + PACKAGE + "/res/wgt/"
SCOPE = "autonomous-root-pilot"
PROVISION = ("config.json", "server-key.pem", "server.pem", "client.pem")


def required_manifest(folder, option):
    if not folder.is_dir():
        raise Refused(
            option
            + " requires a directory containing manifest.json"
            + (" and provision/, not client.json" if option == "--credentials" else "")
        )
    path = folder / "manifest.json"
    try:
        manifest = read_json(path)
    except OSError:
        raise Refused("Cannot read " + option + " manifest: " + str(path)) from None
    if not isinstance(manifest, dict):
        raise Refused("Missing or non-object " + option + " manifest: " + str(path))
    if (
        not isinstance(manifest.get("package"), str)
        or not manifest["package"]
        or not isinstance(manifest.get("package_sha256"), str)
        or not re.fullmatch("[a-f0-9]{64}", manifest["package_sha256"])
    ):
        raise Refused("Incomplete signed-package record in " + option + " manifest")
    return manifest


def disabled_baseline(folder, manifest):
    """Validate the retained enrollment locally before any privileged inspection."""
    digests = manifest.get("provisioning")
    if not isinstance(digests, dict):
        raise Refused("Missing provisioning record in --credentials manifest")
    for name in PROVISION:
        path = folder / "provision" / name
        try:
            matches = sha(path.read_bytes()) == digests.get(name)
        except OSError:
            raise Refused(
                "Missing or unreadable provisioning file: " + str(path)
            ) from None
        if not matches:
            raise Refused("Missing or changed provisioning digest: " + name)
    config = read_json(folder / "provision/config.json")
    if not isinstance(config, dict) or config.get("enabled") is not False:
        raise Refused("--credentials must contain a disabled provisioning baseline")


def package_files(members):
    return {
        PREFIX + n: (None if n == "signature1.xml" else sha(b))
        for n, b in members.items()
    }


def inventory_review(before, after):
    """Bind review to every signed member digest, not just added filenames."""
    document = dict(schema=1, package=PACKAGE, before=before, after=after)
    digest = sha(json.dumps(document, sort_keys=True, separators=(",", ":")).encode())
    return dict(
        sha256=digest,
        added=sorted(set(after) - set(before)),
        removed=sorted(set(before) - set(after)),
    )


def reviewed_inventory(before, after, reviewed=None):
    review = inventory_review(before, after)
    changed = bool(review["added"] or review["removed"])
    if (changed or reviewed is not None) and reviewed != review["sha256"]:
        raise Refused(
            "Update file inventory changed; supply the exact reviewed inventory digest"
        )
    keys = sorted(set(before) | set(after))
    return {p: before.get(p) for p in keys}, {p: after.get(p) for p in keys}, review


def review_update(device, artifact, previous, site):
    profile = configured_profile(device, site)
    packages = []
    for folder in (previous, artifact):
        manifest = read_json(folder.resolve() / "manifest.json")
        if manifest.get("device") != device or manifest.get(
            "target_binding"
        ) != binding(site, device):
            raise Refused("Review target binding differs")
        package = Path(manifest["package"])
        if sha(package.read_bytes()) != manifest["package_sha256"]:
            raise Refused("Signed package changed")
        members, version = verify_package(package, profile, PACKAGE)
        packages.append((package_files(members), version))
    before, old_version = packages[0]
    after, new_version = packages[1]
    if tuple(map(int, new_version.split("."))) <= tuple(
        map(int, old_version.split("."))
    ):
        raise Refused("Forward version required")
    return dict(
        device=device,
        previous_version=old_version,
        version=new_version,
        inventory=inventory_review(before, after),
        phase="review-only-no-device-access",
    )


class PilotTransport(Transport):
    def __init__(self, profile, evidence, files, *, native_bundle=None):
        self.pilot_files = files
        super().__init__(profile, evidence, native_bundle=native_bundle)

    def snapshot(self, privileged=False):
        state = super().snapshot(privileged=False)
        # The SDK diagnostic path can elide the middle of long command output.
        # Bound each readback so a growing signed inventory remains verifiable.
        for start in range(0, len(self.pilot_files), 12):
            batch = list(enumerate(self.pilot_files[start : start + 12], start))
            script = ""
            for i, p in batch:
                # Both package layouts use a canonical package key.
                candidate = p.replace("/res/wgt/", "/") if p.startswith(PREFIX) else p
                script += 'printf "PILOT_FILE_' + str(i) + '="\n'
                script += f'p={Q(p)}\nif test ! -e "$p"; then p={Q(candidate)}; fi\nif test -L "$p"; then echo SYMLINK; elif test -f "$p"; then sha256sum "$p"; else echo ABSENT; fi\n'
            output = self.root(script)
            for i, p in batch:
                match = re.search(
                    r"PILOT_FILE_" + str(i) + r"=([a-f0-9]{64}|ABSENT|SYMLINK)", output
                )
                if not match:
                    raise Refused("Pilot file inspection incomplete")
                state["files"][p] = None if match[1] == "ABSENT" else match[1]
        output = self.root("vconftool get db/sdk/develop/ip\n")
        match = re.search(r"db/sdk/develop/ip, value = (\S+) \(String\)", output)
        if not match:
            raise Refused("Developer host unavailable")
        state["developer_host"] = match[1]
        return state


class PilotDriver(Driver):
    def package_identity_ok(self, row):
        return row[0:3] == [PACKAGE, PACKAGE + ".App", "wgt"] and row[4:] == [
            "true",
            "false",
            "false",
            "false",
        ]

    def prepare(self, action):
        if action.component != "autonomous-root":
            raise Refused("Unexpected pilot component")
        source = Path(action.options["source"])
        if action.kind == "package":
            members, _ = verify_package(source, self.profile, PACKAGE)
            expected = package_files(members)
            if action.options.get("previous_source"):
                previous, _ = verify_package(
                    Path(action.options["previous_source"]), self.profile, PACKAGE
                )
                before, expected, _ = reviewed_inventory(
                    package_files(previous),
                    expected,
                    action.options.get("reviewed_inventory_sha256"),
                )
                if before != action.before:
                    raise Refused("Previous package drift")
            if expected != action.after:
                raise Refused("Package drift")
        elif action.kind == "file":
            if action.options["path"] not in [DATA + "/" + n for n in PROVISION]:
                raise Refused("Unexpected provisioning target")
            if sha(source.read_bytes()) != action.after:
                raise Refused("Provisioning drift")
        else:
            raise Refused("Unexpected pilot operation")
        target = self.folder / (action.id + source.suffix)
        shutil.copyfile(source, target)
        target.chmod(0o600)
        return dict(artifact=str(target), sha256=sha(target.read_bytes()))

    def verify(self, action, before, after):
        if observed(action, after) != action.after:
            raise Refused("Pilot readback mismatch")
        if action.kind == "package":
            rows = [r for r in after["packages"] if r[0] == PACKAGE]
            if len(rows) != 1 or not self.package_identity_ok(rows[0]):
                raise Refused("Pilot registration mismatch")
            from .service_registration import require_expected

            require_expected(after)
        for field in ("key_filter", "task_filter", "managed_app"):
            if before.get(field) != after.get(field):
                raise Refused("Production routing changed")
        for p, value in before["files"].items():
            if (
                not p.startswith((PREFIX, DATA + "/"))
                and after["files"].get(p) != value
            ):
                raise Refused("Production file changed: " + p)
        if before["developer_host"] != after["developer_host"]:
            raise Refused("Developer host changed during disabled install")


def install(device, artifact, site, *, native_bundle=None):
    artifact = artifact.resolve()
    manifest = read_json(artifact / "manifest.json")
    profile = configured_profile(device, site)
    if manifest.get("device") != device or manifest.get("target_binding") != binding(
        site, device
    ):
        raise Refused("Artifact target binding differs")
    pkg = Path(manifest["package"])
    if sha(pkg.read_bytes()) != manifest["package_sha256"]:
        raise Refused("Artifact changed")
    members, _ = verify_package(pkg, profile, PACKAGE)
    # Samsung consumes signature1.xml; verification still authenticates every archive member.
    expected = {
        PREFIX + n: (None if n == "signature1.xml" else sha(b))
        for n, b in members.items()
    }
    for n in PROVISION:
        if (
            sha((artifact / "provision" / n).read_bytes())
            != manifest["provisioning"][n]
        ):
            raise Refused("Provisioning changed")
    if read_json(artifact / "provision/config.json").get("enabled") is not False:
        raise Refused("First installation must be disabled")
    with lock(STATE / (device + ".lock")):
        if pending(STATE, device):
            raise Refused("Resolve pending device operation first")
        identity = run_id()
        folder = STATE / "runs" / identity
        files = list(expected) + [DATA + "/" + n for n in PROVISION]
        tv = PilotTransport(
            profile, folder / "transport", files, native_bundle=native_bundle
        )
        state = tv.snapshot()
        if any(r[0] == PACKAGE for r in state["packages"]) or any(
            state["files"].get(p) is not None for p in files
        ):
            raise Refused(
                "Pilot already exists; inspect and recover rather than overwrite"
            )
        plan = Plan(device)
        plan.actions = [
            Action(
                "001-root-package",
                "autonomous-root",
                "package",
                None,
                expected,
                dict(
                    package=PACKAGE,
                    artifact="autonomous-root",
                    previous_version=None,
                    source=str(pkg),
                ),
            )
        ]
        for i, n in enumerate(PROVISION, 2):
            plan.actions.append(
                Action(
                    str(i).zfill(3) + "-root-provision",
                    "autonomous-root",
                    "file",
                    None,
                    manifest["provisioning"][n],
                    dict(
                        path=DATA + "/" + n,
                        artifact="autonomous-root",
                        source=str(artifact / "provision" / n),
                    ),
                )
            )
        choices = resolve(
            device,
            overrides={
                "components": [],
                "exclude": [],
                "keep": [],
                "remove": [],
                "artifacts": {},
            },
        )
        driver = PilotDriver(tv, profile, choices, folder)
        engine = Engine(
            driver,
            folder,
            device,
            choices,
            target_binding=binding(site, device),
            scope=SCOPE,
        )
        engine.prepare(plan, state)
        engine.doc["pilot"] = dict(
            artifact=str(artifact),
            files=files,
            developer_host=state["developer_host"],
            status="disabled-install",
            root_acquisition=tv.root_acquisition,
        )
        engine.save()
        engine.apply()
        # Do not finalize normal setup choices or mark pilot acceptance complete.
        return dict(run=identity, phase=engine.doc["phase"], device=device)


def update(
    device,
    artifact,
    previous,
    site,
    credentials=None,
    reviewed_inventory_sha256=None,
    *,
    native_bundle=None,
):
    artifact = artifact.resolve()
    previous = previous.resolve()
    profile = configured_profile(device, site)
    new = required_manifest(artifact, "--artifact")
    old = required_manifest(previous, "--previous")
    credentials = (credentials or previous).resolve()
    credential_manifest = required_manifest(credentials, "--credentials")
    for item in (new, old, credential_manifest):
        if item.get("device") != device or item.get("target_binding") != binding(
            site, device
        ):
            raise Refused("Update target binding differs")
        try:
            digest = sha(Path(item["package"]).read_bytes())
        except OSError:
            raise Refused("Signed package missing or unreadable") from None
        if digest != item["package_sha256"]:
            raise Refused("Signed package changed")
    disabled_baseline(credentials, credential_manifest)
    current, old_version = verify_package(Path(old["package"]), profile, PACKAGE)
    desired, new_version = verify_package(Path(new["package"]), profile, PACKAGE)
    if tuple(map(int, new_version.split("."))) <= tuple(
        map(int, old_version.split("."))
    ):
        raise Refused("Forward version required")
    before, after, review = reviewed_inventory(
        package_files(current), package_files(desired), reviewed_inventory_sha256
    )
    with lock(STATE / (device + ".lock")):
        if pending(STATE, device):
            raise Refused("Resolve pending run first")
        identity = run_id()
        folder = STATE / "runs" / identity
        files = list(after) + [DATA + "/" + n for n in PROVISION]
        tv = PilotTransport(
            profile, folder / "transport", files, native_bundle=native_bundle
        )
        state = tv.snapshot()
        if {p: state["files"][p] for p in before} != before:
            raise Refused("Installed package differs from previous signed artifact")
        for n in PROVISION:
            if state["files"][DATA + "/" + n] != credential_manifest["provisioning"][n]:
                raise Refused(
                    "Provisioning must be restored to disabled baseline before update"
                )
        a = Action(
            "001-root-update",
            "autonomous-root",
            "package",
            before,
            after,
            dict(
                package=PACKAGE,
                artifact="autonomous-root",
                previous_version=old_version,
                source=new["package"],
                previous_source=old["package"],
                reviewed_inventory_sha256=reviewed_inventory_sha256,
            ),
        )
        choices = resolve(
            device,
            overrides={
                "components": [],
                "exclude": [],
                "keep": [],
                "remove": [],
                "artifacts": {},
            },
        )
        driver = PilotDriver(tv, profile, choices, folder)
        engine = Engine(
            driver,
            folder,
            device,
            choices,
            target_binding=binding(site, device),
            scope=SCOPE,
        )
        plan = Plan(device, actions=[a])
        engine.prepare(plan, state)
        recovery = folder / "previous-signed.wgt"
        shutil.copyfile(old["package"], recovery)
        engine.doc["actions"][0]["info"].update(
            recovery_package=str(recovery), recovery_sha256=sha(recovery.read_bytes())
        )
        engine.doc["pilot"] = dict(
            artifact=str(artifact),
            credentials_artifact=str(credentials),
            files=files,
            developer_host=state["developer_host"],
            status="disabled-update",
            inventory_review=review,
            root_acquisition=tv.root_acquisition,
        )
        engine.save()
        engine.apply()
        return dict(run=identity, phase=engine.doc["phase"], device=device)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--device", choices=accepted_devices(), required=True)
    parser.add_argument("--artifact", type=Path, required=True)
    parser.add_argument(
        "--credentials",
        type=Path,
        help="Disabled provisioning directory containing manifest.json and provision/ "
        "(defaults to --previous); not the authenticated client's client.json",
    )
    parser.add_argument("--previous", type=Path)
    parser.add_argument("--site", type=Path)
    parser.add_argument("--yes", action="store_true")
    parser.add_argument(
        "--review-inventory",
        action="store_true",
        help="Verify signed packages and report inventory digest without device access",
    )
    parser.add_argument(
        "--reviewed-inventory-sha256",
        help="Exact digest from a reviewed inventory report",
    )
    parser.add_argument(
        "--native-bundle",
        type=Path,
        help="Use a prebuilt native setup acquisition bundle; retains the .NET entry bridge",
    )
    args = parser.parse_args()
    if args.review_inventory and not args.previous:
        parser.error("Inventory review requires --previous")
    if args.reviewed_inventory_sha256 and not args.previous:
        parser.error("Inventory review digest requires --previous")
    if not args.review_inventory and not args.yes:
        parser.error("Installation requires --yes")
    try:
        if args.review_inventory:
            result = review_update(
                args.device, args.artifact, args.previous, load_site(args.site)
            )
        else:
            result = (
                update(
                    args.device,
                    args.artifact,
                    args.previous,
                    load_site(args.site),
                    args.credentials,
                    args.reviewed_inventory_sha256,
                    native_bundle=args.native_bundle,
                )
                if args.previous
                else install(
                    args.device,
                    args.artifact,
                    load_site(args.site),
                    native_bundle=args.native_bundle,
                )
            )
        print(json.dumps(result))
    except Refused as e:
        print(str(e), file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    sys.exit(main())
