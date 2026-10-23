"""Guarded operations. Every inverse refers to a fresh run backup, never a historical path."""

import json
import os
from pathlib import Path
import re
import shlex
import shutil
import sys
import zipfile
from .staging import clear_verified_stage
from .artifacts import Builder, verify_package, next_version, manifest_bytes
from .common import PRIVATE, REPO, Refused, atomic_json, run, sha
from .planner import (
    CACHE_PATCHED,
    CACHE_STOCK,
    EMPTY,
    cleanup_eligibility,
    managed_package_ok,
)
from .transport import (
    CONTEXT_DB,
    PKG_DB,
    WAS_DB,
    TABLES,
    Q,
    hash_guard,
    identity_guard,
    managed_guard,
)
from .telemetry import (
    DATA,
    LEGACY_MARKER,
    LEGACY_RUNTIME,
    drain,
    legacy_action,
    service_ready,
)


def sql_value(value):
    return "NULL" if value is None else "'" + str(value).replace("'", "''") + "'"


def scope_where(action):
    scope = action.options["scope"]
    return (
        "appid='com.samsung.tv.csfs' AND key='XF86Home'"
        if scope == "home"
        else "appid=" + sql_value(scope)
    )


def route_sql(action, reverse=False):
    table = action.options["table"]
    columns = TABLES[table][2]
    where = scope_where(action)
    before, after = (
        (action.after, action.before) if reverse else (action.before, action.after)
    )
    lines = [
        "BEGIN IMMEDIATE;",
        "CREATE TEMP TABLE setup_guard(ok INTEGER CHECK(ok=1));",
        "INSERT INTO setup_guard SELECT count(*)="
        + str(len(before))
        + " FROM "
        + table
        + " WHERE "
        + where
        + ";",
    ]
    for row in before:
        predicate = " AND ".join(
            c + " IS " + sql_value(v) for c, v in zip(columns, row)
        )
        lines.append(
            "INSERT INTO setup_guard SELECT count(*)=1 FROM "
            + table
            + " WHERE "
            + predicate
            + ";"
        )
    lines.append("DELETE FROM " + table + " WHERE " + where + ";")
    for row in after:
        lines.append(
            "INSERT INTO "
            + table
            + "("
            + ",".join(columns)
            + ") VALUES("
            + ",".join(map(sql_value, row))
            + ");"
        )
    lines += ["DROP TABLE setup_guard;", "COMMIT;"]
    return "\n".join(lines) + "\n"


def observed(action, state):
    kind = action.kind
    opts = action.options
    if kind == "package":
        if not any(r[0] == opts["package"] for r in state["packages"]):
            files = {p: state["files"].get(p) for p in action.after}
            return (
                dict(registration="absent", files=files)
                if any(files.values())
                else None
            )
        return {p: state["files"].get(p) for p in action.after}
    if kind in ("file", "cache", "pairing"):
        return state["files"].get(opts["path"])
    if kind == "preferences":
        return state["preferences"]
    if kind == "setting":
        return state["settings"].get(opts["key"])
    if kind == "home_operation":
        rows = state.get("home_operation", [])
        return rows[0][3] if len(rows) == 1 else None
    if kind == "routes":
        rows = state[opts["table"]]
        if opts["scope"] != "home":
            rows = [r for r in rows if r[0] == opts["scope"]]
        return sorted(rows, key=str)
    if kind == "uninstall":
        return [r for r in state["packages"] if r[0] == opts["package"]] or None
    raise Refused("Unknown operation kind")


class Driver:
    def __init__(self, transport, profile, choices, folder, shared=None):
        self.tv, self.profile, self.choices, self.folder = (
            transport,
            profile,
            choices,
            folder,
        )
        self.builder = Builder(profile, choices, folder / "artifacts")
        self.remote = "/opt/minimal-tv-setup/" + folder.name
        self.control = None
        self.shared = shared

    def snapshot(self):
        return self.tv.snapshot(privileged=True)

    def package_identity_ok(self, row):
        return managed_package_ok(row)

    def prepare(self, action):
        """Local builds and signature verification happen before any target mutation."""
        info = {}
        if action.options.get("artifact") == "legacy-disable":
            legacy_action(self.profile, action)
            return info
        if action.kind == "package":
            path, members = self.builder.package(action)
            prefix = "/opt/usr/apps/" + action.options["package"] + "/"
            for remote in list(action.after):
                relative = remote[len(prefix) :]
                member = (
                    relative[len("res/wgt/") :]
                    if relative.startswith("res/wgt/")
                    else relative
                )
                action.after[remote] = sha(members[member])
            info.update(artifact=str(path), sha256=sha(path.read_bytes()))
            if action.before:
                old = self.find_recovery_package(action)
                if old:
                    saved = self.folder / (action.id + "-recovery" + old.suffix)
                    shutil.copyfile(old, saved)
                    info.update(
                        recovery_package=str(saved),
                        recovery_sha256=sha(saved.read_bytes()),
                    )
                else:
                    info["recovery"] = (
                        "No matching signed package; installed-file archive is forensic only. Use Samsung Store or a separately verified signed package."
                    )
        elif action.kind in ("file", "preferences", "pairing"):
            if action.kind == "file":
                path = self.builder.file(action.options["artifact"])
            elif action.kind == "preferences":
                path = self.folder / (action.id + ".json")
                atomic_json(path, action.after)
            else:
                if self.shared is None:
                    raise Refused(
                        "Missing pairing requires read-only NAS credential verification"
                    )
                data = self.shared.pairing(self.profile)
                if self.profile["id"] == "s90d" and action.before is None:
                    previous = self.tv.snapshot(privileged=True).get(
                        "legacy_pairing_config"
                    )
                    if previous:
                        from .config import validate_endpoint

                        validate_endpoint("s90d", previous.get("endpoint"))
                        if previous.get("device_id") != "s90d":
                            raise Refused("Legacy pairing identity changed")
                        data = {**previous, **data, "endpoint": previous["endpoint"]}
                if action.before is not None:
                    previous = self.tv.snapshot(privileged=True).get("pairing_config")
                    if not isinstance(previous, dict):
                        raise Refused("Pairing disappeared during preparation")
                    data = {**previous, **data, "endpoint": previous["endpoint"]}
                data.pop("token_sha256", None)
                path = self.folder / (action.id + "-pairing.json")
                atomic_json(path, data)
            target = self.folder / (action.id + "-payload")
            with open(
                target, "wb", opener=lambda name, flags: os.open(name, flags, 0o600)
            ) as output:
                os.fchmod(output.fileno(), 0o600)
                output.write(path.read_bytes())
            info.update(artifact=str(target), sha256=sha(target.read_bytes()))
            if action.kind != "preferences":
                action.after = info["sha256"]
        if action.kind in ("setting", "home_operation", "routes"):
            self.prepare_control()
        return info

    def prepare_control(self):
        if self.control:
            return
        output = self.folder / "native"
        self.builder.command(
            [
                "dotnet",
                "build",
                REPO / "tvsetup/native/Control.csproj",
                "-c",
                "Release",
                "--nologo",
                "-v",
                "quiet",
                "-f",
                self.profile["framework"],
                "-o",
                output,
            ]
        )
        self.control = output / "Control.dll"

    def find_recovery_package(self, action):
        location = os.environ.get("TV_SETUP_RECOVERY_DIR")
        if not location:
            return None
        for path in Path(location).expanduser().glob("**/*"):
            if path.suffix not in (".wgt", ".tpk") or not path.is_file():
                continue
            try:
                with zipfile.ZipFile(path) as z:
                    for remote, digest in action.before.items():
                        name = (
                            remote.split("/res/wgt/", 1)[1]
                            if "/res/wgt/" in remote
                            else "bin/" + remote.rsplit("/", 1)[1]
                        )
                        if (
                            sha(z.read(name)) if name in z.namelist() else None
                        ) != digest:
                            break
                    else:
                        verify_package(path, self.profile, action.options["package"])
                        return path
            except (KeyError, ValueError, zipfile.BadZipFile, Refused, OSError):
                continue
        return None

    def backup(self, action, info, state):
        where = self.remote + "/" + action.id + "-" + info.get("attempt", "first")
        script = f"test ! -L /opt/minimal-tv-setup\ntest ! -L {Q(self.remote)}\nmkdir -p {Q(self.remote)}\nchmod 700 /opt/minimal-tv-setup {Q(self.remote)}\ntest ! -e {Q(where)}\nmkdir -m 700 {Q(where)}\n"
        if action.kind in ("file", "cache", "pairing", "preferences"):
            path = action.options["path"]
            before = (
                action.options.get("before_hash")
                if action.kind == "preferences"
                else action.before
            )
            script += hash_guard(path, before)
            if before is not None:
                script += (
                    f"cp --preserve=all {Q(path)} {Q(where + '/original')}\n"
                    + hash_guard(where + "/original", before)
                )
                info.update(backup=where + "/original", backup_sha256=before)
        elif action.kind == "routes":
            backup = where + "/context.db"
            script += f"sqlite3 -cmd '.timeout 2000' {CONTEXT_DB} {Q('.backup ' + backup)}\ntest \"$(sqlite3 -readonly {Q(backup)} 'pragma quick_check;')\" = ok\n"
            info["database_backup"] = backup
        elif action.kind in ("package", "uninstall"):
            pkg = action.options["package"]
            backup = where + "/packages.db"
            script += f"sqlite3 -cmd '.timeout 2000' {PKG_DB} {Q('.backup ' + backup)}\ntest \"$(sqlite3 -readonly {Q(backup)} 'pragma quick_check;')\" = ok\n"
            if self.profile["id"] == "qn90a":
                script += f"sqlite3 -cmd '.timeout 2000' {WAS_DB} {Q('.backup ' + where + '/catalog.db')}\ntest \"$(sqlite3 -readonly {Q(where + '/catalog.db')} 'pragma quick_check;')\" = ok\n"
            if action.before:
                # Only installed files, deliberately not labeled a reinstall package.
                paths = ["opt/usr/apps/" + pkg, "opt/share/packages/" + pkg + ".xml"]
                data = "/opt/usr/home/owner/apps_rw/" + pkg
                script += f'test ! -L {Q(data)}\npaths={Q(" ".join(paths))}\nif test -d {Q(data)}; then paths="$paths {data.lstrip("/")}"; fi\ntar -cf {Q(where + "/installed-files.tar")} -C / $paths\ntar -tf {Q(where + "/installed-files.tar")} >/dev/null\n'
                info["installed_file_archive"] = where + "/installed-files.tar"
            info["database_backup"] = backup
        else:
            # Settings are captured as typed values, including the native owner assignment.
            info["original_value"] = action.before
        script += f"find {Q(where)} -type f -exec sha256sum {{}} \\;\n"
        output = self.tv.root(script)
        info["backup_evidence_sha256"] = sha(output.encode())
        (self.folder / (action.id + "-backup.log")).write_text(output)
        # Keep a checked manifest of the actual remote backup hashes for later verification.
        info["backup_files"] = {
            m[2]: m[1]
            for m in re.finditer(r"(?m)^([a-f0-9]{64})  (\S+)$", output)
            if m[2].startswith(where + "/")
        }
        required = [
            info[k]
            for k in ("backup", "database_backup", "installed_file_archive")
            if k in info
        ]
        if any(p not in info["backup_files"] for p in required):
            raise Refused("Backup checksum evidence incomplete")
        return info

    def control_call(self, mode, key="", before="", after="", root=False):
        self.prepare_control()
        stage = (
            "/home/owner/share/tmp/sdk_tools/tv-setup-"
            + self.folder.name
            + "-control.dll"
        )
        self.tv.push(self.control, stage)
        args = [mode, self.profile["id"]] + (
            [key, str(before), str(after)] if mode != "reload" else []
        )
        script = f"trap 'rm -f {stage}' EXIT\n" + hash_guard(
            stage, sha(self.control.read_bytes())
        )
        script += "/usr/bin/dotnet " + Q(stage) + " " + " ".join(map(Q, args)) + "\n"
        if root:
            self.tv.root(script)
        else:
            self.tv.sdk(managed_guard(self.profile) + script)
        if mode == "reload":
            import time

            time.sleep(6)  # native context manager's documented debounce

    def file_write(self, action, info):
        path = action.options["path"]
        stage = (
            "/home/owner/share/tmp/sdk_tools/tv-setup-"
            + self.folder.name
            + "-"
            + action.id
        )
        source = Path(info["artifact"])
        if sha(source.read_bytes()) != info["sha256"]:
            raise Refused("Prepared payload changed")
        self.tv.push(source, stage)
        before = (
            action.options.get("before_hash")
            if action.kind == "preferences"
            else action.before
        )
        parent = path.rsplit("/", 1)[0]
        temporary = path + ".tv-setup-" + self.folder.name + "-" + action.id + ".new"
        script = (
            f"trap 'rm -f {stage}' EXIT\n"
            + hash_guard(path, before)
            + hash_guard(stage, info["sha256"])
            + f"test ! -L {Q(parent)}\n"
            + clear_verified_stage(temporary, info["sha256"])
        )
        if path == DATA + "/enabled":
            script += service_ready(self.profile)
        script += f"trap 'rm -f {stage} {temporary}' EXIT\n"
        script += f"test ! -L {Q(parent)}\nmkdir -p {Q(parent)}\n"
        if "/apps_rw/" not in path:
            script += f"chmod 700 {Q(parent)}\n"
        script += f"test ! -e {Q(temporary)} && test ! -L {Q(temporary)}\n"
        if before is not None:
            script += f"cp --preserve=all {Q(path)} {Q(temporary)}\ncat {Q(stage)} > {Q(temporary)}\n"
        elif action.options.get("artifact") == "renderer":
            from .transport import STOCK

            script += f"cp --preserve=all {Q(STOCK)} {Q(temporary)}\ncat {Q(stage)} > {Q(temporary)}\nchown root:root {Q(temporary)}\n"
        else:
            script += f"cp {Q(stage)} {Q(temporary)}\nchmod 600 {Q(temporary)}\n"
            if "/apps_rw/" in path:
                pkg = path.split("/apps_rw/")[1].split("/")[0]
                script += f"chown 5001:100 {Q(temporary)}\nchsmack -a {Q('User::Pkg::' + pkg)} {Q(temporary)}\n"
        script += (
            hash_guard(temporary, info["sha256"]) + f"mv {Q(temporary)} {Q(path)}\n"
        )
        self.tv.root(script)

    def execute(self, action, info, state):
        if observed(action, state) != action.before:
            raise Refused("State changed since planning: " + action.id)
        kind = action.kind
        if kind == "package":
            path = Path(info["artifact"])
            if sha(path.read_bytes()) != info["sha256"]:
                raise Refused("Prepared package changed")
            verify_package(path, self.profile, action.options["package"])
            if action.options["package"] in ("MiniHubBoot", "MiniTelemetry"):
                self.tv.sdk(managed_guard(self.profile))
            try:
                output = run(
                    [
                        self.builder.cli,
                        "install",
                        "-s",
                        self.profile["host"] + ":26101",
                        "-n",
                        path.name,
                        "--",
                        path.parent,
                    ],
                    timeout=120,
                )
            except Refused as error:
                (self.folder / (action.id + "-install.log")).write_text(
                    getattr(error, "output", str(error))
                )
                raise
            (self.folder / (action.id + "-install.log")).write_text(output)
        elif action.options.get("artifact") == "legacy-disable":
            legacy_action(self.profile, action)
            self.tv.root(
                hash_guard(LEGACY_MARKER, action.before)
                + "rm "
                + Q(LEGACY_MARKER)
                + "\n"
                + drain(LEGACY_RUNTIME)
            )
        elif kind in ("file", "pairing", "preferences"):
            self.file_write(action, info)
        elif kind == "routes":
            script = f"printf %s {Q(route_sql(action))} | sqlite3 -bail -cmd '.timeout 2000' {CONTEXT_DB}\ntest \"$(sqlite3 -readonly {CONTEXT_DB} 'pragma quick_check;')\" = ok\n"
            self.tv.root(script)
            self.control_call("reload", root=True)
        elif kind == "setting":
            self.control_call(
                "setting", action.options["key"], action.before, action.after
            )
        elif kind == "home_operation":
            self.control_call("home", "", action.before, action.after)
        elif kind == "cache":
            if self.profile["id"] != "s90d":
                raise Refused("Cache is S90D-only")
            path = action.options["path"]
            text = "[Unit]\nAfter=buxton2.service systemd-udevd.service connman.service net-config.service deviced.service\n[Service]\nExecStart=/usr/bin/dotnet /opt/minimal-saver/Boot.dll\n"
            text += "#" + " " * (209 - len(text.encode()) - 2) + "\n"
            if len(text.encode()) != 209:
                raise Refused("S90D cache patch must be exactly 209 bytes")
            # Keep the rest of the cache byte-for-byte. Refuse any unreviewed starting hash.
            temporary = (
                path + ".tv-setup-" + self.folder.name + "-" + action.id + ".new"
            )
            script = (
                hash_guard(path, CACHE_STOCK)
                + clear_verified_stage(temporary, CACHE_PATCHED)
                + f"cp --preserve=all {Q(path)} {Q(temporary)}\nprintf %s {Q(text)} | dd of={Q(temporary)} bs=1 count=209 conv=notrunc 2>/dev/null\n"
                + hash_guard(temporary, CACHE_PATCHED)
                + f"mv {Q(temporary)} {Q(path)}\nsystemctl daemon-reload\n"
            )
            self.tv.root(script, namespace=True)
        elif kind == "uninstall":
            pkg = action.options["package"]
            status, error = cleanup_eligibility(self.profile, state, pkg)
            if error or status != "drifted":
                raise Refused(error or "Cleanup state changed")
            if self.profile["id"] == "qn90a":
                # Exact original WAS mechanism, selected from the same immutable reviewed list.
                import importlib.util

                spec = importlib.util.spec_from_file_location(
                    "cleanup_targets", REPO / "tools/qn90a/cleanup.py"
                )
                m = importlib.util.module_from_spec(spec)
                spec.loader.exec_module(m)
                index = list(m.TARGETS).index(pkg)
                self.tv.root("", cleanup_index=index)
            else:
                columns = TABLES["packages"][2]
                predicate = " AND ".join(
                    c + " IS " + sql_value(v) for c, v in zip(columns, action.before[0])
                )
                query = "SELECT count(*) FROM package_info WHERE " + predicate + ";"
                deps = (
                    "SELECT count(*) FROM package_dependency_info WHERE depends_on="
                    + sql_value(pkg)
                    + ";"
                )
                self.tv.root(
                    f'test "$(sqlite3 -readonly {PKG_DB} {Q(query)})" = 1\ntest "$(sqlite3 -readonly {PKG_DB} {Q(deps)})" = 0\npkgcmd -u -n {Q(pkg)}\n'
                )
        else:
            raise Refused("Unknown mutation")

    def verify(self, action, before, after):
        if observed(action, after) != action.after:
            raise Refused("Readback differs: " + action.id)
        if action.options.get("artifact") == "legacy-disable":
            legacy_action(self.profile, action)
            self.tv.root(service_ready(self.profile))
        if action.kind == "package":
            rows = [r for r in after["packages"] if r[0] == action.options["package"]]
            if len(rows) != 1 or not managed_package_ok(rows[0]):
                raise Refused("Installed managed package protection/identity mismatch")
        if action.kind == "uninstall":
            pkg = action.options["package"]
            for table, index in [("packages", 0), ("apps", 1), ("catalog", 0)]:
                if table not in before:
                    continue
                expected = sorted(
                    [r for r in before[table] if r[index] != pkg], key=str
                )
                if sorted(after[table], key=str) != expected:
                    raise Refused("Unexpected uninstall scope: " + table)
            self.tv.sdk(
                identity_guard(self.profile)
                + f"test ! -e /opt/usr/apps/{pkg}\ntest ! -e /opt/share/packages/{pkg}.xml\n"
            )

    def rollback(self, action, info, state):
        current = observed(action, state)
        if current == action.before:
            # An inverse may have restored bytes/rows before losing the reload reply.
            if action.kind == "routes":
                self.control_call("reload", root=True)
            if action.options.get("artifact") == "legacy-disable":
                legacy_action(self.profile, action)
                self.tv.root(
                    hash_guard(DATA + "/enabled", None)
                    + drain("/tmp/minimal-telemetry-s90d")
                )
                self.tv.root("systemctl restart AT-HUB.service\n", namespace=True)
            if action.kind == "cache":
                self.tv.root("systemctl daemon-reload\n", namespace=True)
            return
        if current != action.after:
            raise Refused("Rollback would overwrite subsequent drift: " + action.id)
        if action.kind == "uninstall":
            raise Refused(
                "App uninstall needs Store/verified signed-package recovery; installed-file archives cannot undo it"
            )
        for path, digest in info.get("backup_files", {}).items():
            self.tv.root(hash_guard(path, digest))
        if action.kind == "routes":
            self.tv.root(
                f"printf %s {Q(route_sql(action, True))} | sqlite3 -bail -cmd '.timeout 2000' {CONTEXT_DB}\n"
            )
            self.control_call("reload", root=True)
        elif action.kind in ("file", "cache", "pairing", "preferences"):
            path = action.options["path"]
            expected = info["sha256"] if action.kind == "preferences" else action.after
            script = hash_guard(path, expected)
            if action.options.get("artifact") == "legacy-disable":
                legacy_action(self.profile, action)
                # The new marker is rolled back first. Do not revive the old
                # collector until the new service has released its lease.
                script += hash_guard(DATA + "/enabled", None) + drain(
                    "/tmp/minimal-telemetry-s90d"
                )
            before = (
                action.options.get("before_hash")
                if action.kind == "preferences"
                else action.before
            )
            if before is None:
                script += f"rm {Q(path)}\n"
            else:
                temporary = (
                    path
                    + ".tv-setup-"
                    + self.folder.name
                    + "-"
                    + action.id
                    + ".restore"
                )
                script += (
                    hash_guard(info["backup"], info["backup_sha256"])
                    + clear_verified_stage(temporary, info["backup_sha256"])
                    + f"cp --preserve=all {Q(info['backup'])} {Q(temporary)}\n"
                    + hash_guard(temporary, info["backup_sha256"])
                    + f"mv {Q(temporary)} {Q(path)}\n"
                )
            if action.kind == "cache":
                script += "systemctl daemon-reload\n"
            self.tv.root(script, namespace=action.kind == "cache")
            if action.options.get("artifact") == "legacy-disable":
                self.tv.root("systemctl restart AT-HUB.service\n", namespace=True)
        elif action.kind == "setting":
            self.control_call(
                "setting", action.options["key"], action.after, action.before
            )
        elif action.kind == "home_operation":
            self.control_call("home", "", action.after, action.before)
        elif action.kind == "package":
            pkg = action.options["package"]
            rows = [r for r in state["packages"] if r[0] == pkg]
            if len(rows) != 1 or not self.package_identity_ok(rows[0]):
                raise Refused(
                    "Managed package identity/protection changed before rollback"
                )
            if action.before is None:
                raise Refused(
                    "New managed app retained to preserve subsequent user data; review manual app removal after configuration rollback"
                )
            else:
                if "recovery_package" not in info:
                    raise Refused(info.get("recovery", "No signed recovery package"))
                self.reinstall_recovery(action, info)
        else:
            raise Refused("Unsupported rollback")

    def recovery_members(self, action, info):
        """Derive the only permitted recovery content from retained signed inputs."""
        source = Path(info["recovery_package"])
        if sha(source.read_bytes()) != info["recovery_sha256"]:
            raise Refused("Recovery archive changed")
        members, _ = verify_package(source, self.profile, action.options["package"])
        if sha(Path(info["artifact"]).read_bytes()) != info["sha256"]:
            raise Refused("Prepared package changed")
        _, installed_version = verify_package(
            Path(info["artifact"]), self.profile, action.options["package"]
        )
        import xml.etree.ElementTree as ET

        web = "config.xml" in members
        name = "config.xml" if web else "tizen-manifest.xml"
        xml = ET.fromstring(members[name])
        xml.set("version", next_version(installed_version, xml.get("version")))
        members[name] = manifest_bytes(xml)
        return members, xml.get("version")

    def prepare_recovery(self, action, info):
        """Sign locally; Engine persists this record before submitting an install."""
        members, version = self.recovery_members(action, info)
        web = "config.xml" in members
        folder = self.folder / (action.id + "-forward-recovery")
        # Never reuse partial or unjournaled signer output.
        try:
            folder.mkdir()
        except FileExistsError:
            raise Refused(
                "Recovery build directory exists; inspect partial output"
            ) from None
        if web:
            for n, data in members.items():
                if n in ("author-signature.xml", "signature1.xml"):
                    continue
                target = folder / n
                target.parent.mkdir(parents=True, exist_ok=True)
                target.write_bytes(data)
            self.builder.command(
                [
                    self.builder.cli,
                    "package",
                    "-t",
                    "wgt",
                    "-s",
                    self.profile["signing_profile"],
                    "-o",
                    folder,
                    "--",
                    folder,
                ]
            )
            candidates = list(folder.glob("*.wgt"))
            if len(candidates) != 1:
                raise Refused("Recovery signer did not produce exactly one WGT")
            # Tizen's install wrapper does not handle a display-name filename
            # containing spaces even when subprocess receives one argument.
            path = self.folder / (action.id + "-recovery-install.wgt")
            shutil.copyfile(candidates[0], path)
        else:
            path = folder / (action.options["package"] + "-arm.tpk")
            with zipfile.ZipFile(path, "w", zipfile.ZIP_DEFLATED) as z:
                for n, data in members.items():
                    if n not in ("author-signature.xml", "signature1.xml"):
                        z.writestr(n, data)
            self.builder.command(
                [
                    self.builder.cli,
                    "package",
                    "-t",
                    "tpk",
                    "-s",
                    self.profile["signing_profile"],
                    "--",
                    path,
                ]
            )
        record = dict(
            artifact=str(path), sha256=sha(path.read_bytes()), version=version
        )
        record["files"] = self.recovery_target(
            action, {**info, "forward_recovery": record}
        )
        return record

    def recovery_target(self, action, info):
        """Re-derive expected readback; a journal edit cannot authorize new content."""
        expected, version = self.recovery_members(action, info)
        record = info["forward_recovery"]
        path = Path(record["artifact"])
        if sha(path.read_bytes()) != record["sha256"]:
            raise Refused("Recovery archive changed")
        members, signed_version = verify_package(
            path, self.profile, action.options["package"]
        )
        signatures = {"author-signature.xml", "signature1.xml"}
        if (
            set(members) != set(expected)
            or signed_version != version
            or any(
                members[n] != data
                for n, data in expected.items()
                if n not in signatures
            )
        ):
            raise Refused("Recovery content differs from retained package")
        files = {}
        prefix = "/opt/usr/apps/" + action.options["package"] + "/"
        for remote in action.after:
            if not remote.startswith(prefix):
                raise Refused("Recovery inventory contains a foreign path")
            name = remote[len(prefix) :].removeprefix("res/wgt/")
            # Preserve the caller's consumed distributor-signature convention.
            consumed = (
                name == "signature1.xml"
                and action.before.get(remote) is None
                and action.after[remote] is None
            )
            files[remote] = (
                sha(members[name]) if name in members and not consumed else None
            )
        if record["version"] != version or (
            "files" in record and record["files"] != files
        ):
            raise Refused("Recovery record differs from verified archive")
        return files

    def verify_recovery(self, action, info, state):
        rows = [r for r in state["packages"] if r[0] == action.options["package"]]
        if (
            len(rows) != 1
            or not self.package_identity_ok(rows[0])
            or rows[0][3] != info["forward_recovery"]["version"]
        ):
            raise Refused("Recovery registration mismatch")

    def reinstall_recovery(self, action, info):
        if action.options["package"] in ("MiniHubBoot", "MiniTelemetry"):
            self.tv.sdk(managed_guard(self.profile))
        if "forward_recovery" not in info:
            raise Refused(
                "Recovery package must be prepared and journaled before install"
            )
        self.recovery_target(action, info)
        path = Path(info["forward_recovery"]["artifact"])
        try:
            output = run(
                [
                    self.builder.cli,
                    "install",
                    "-s",
                    self.profile["host"] + ":26101",
                    "-n",
                    path.name,
                    "--",
                    path.parent,
                ],
                timeout=120,
            )
        except Refused as error:
            (self.folder / (action.id + "-recovery-install.log")).write_text(
                getattr(error, "output", str(error))
            )
            raise
        (self.folder / (action.id + "-recovery-install.log")).write_text(output)
