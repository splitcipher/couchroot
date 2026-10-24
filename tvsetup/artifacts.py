"""Rebuild from source; verify pinned signatures and every signed archive member."""

import base64
import hashlib
import json
import os
from pathlib import Path, PurePosixPath
import shutil
import stat
import sys
import tempfile
import xml.etree.ElementTree as ET
import zipfile
from .common import PRIVATE, REPO, Refused, atomic_json, run, sha
from .planner import RENDERER, hub_sources, component_revision

DS = "http://www.w3.org/2000/09/xmldsig#"
EXC = "http://www.w3.org/2001/10/xml-exc-c14n#"


def manifest_bytes(manifest):
    # Samsung's installer expects unprefixed manifest/widget elements.
    # ElementTree otherwise rewrites the default namespace as ns0.
    namespace = manifest.tag.split("}")[0].lstrip("{")
    if namespace not in (
        "http://tizen.org/ns/packages",
        "http://www.w3.org/ns/widgets",
    ):
        raise Refused("Unexpected manifest namespace")
    ET.register_namespace("", namespace)
    ET.register_namespace("tizen", "http://tizen.org/ns/widgets")
    return ET.tostring(manifest, encoding="utf-8", xml_declaration=True)


def verify_package(path, profile, package_id):
    require_trust(profile)
    try:
        from lxml import etree
    except ImportError:
        raise Refused(
            "Signed artifact verification requires lxml; install tvsetup/requirements.txt"
        )
    with zipfile.ZipFile(path) as archive:
        names = archive.namelist()
        if (
            len(names) != len(set(names))
            or sum(x.file_size for x in archive.infolist()) > 100 * 1024 * 1024
        ):
            raise Refused("Duplicate members or oversized signed archive")
        for entry in archive.infolist():
            name = entry.filename
            if stat.S_ISLNK(entry.external_attr >> 16):
                raise Refused("Symlinks are forbidden in signed packages")
            normalized = PurePosixPath(name).as_posix() + (
                "/" if name.endswith("/") else ""
            )
            if normalized != name:
                raise Refused("Noncanonical archive path")
            if (
                name.startswith("/")
                or ".." in PurePosixPath(name).parts
                or "\\" in name
            ):
                raise Refused("Unsafe archive path")
        members = {n: archive.read(n) for n in names if not n.endswith("/")}
    parser = etree.XMLParser(resolve_entities=False, no_network=True)
    for filename, pin in [
        ("author-signature.xml", profile["author_cert_sha256"]),
        ("signature1.xml", profile["distributor_cert_sha256"]),
    ]:
        if filename not in members:
            raise Refused("Missing " + filename)
        document = etree.fromstring(members[filename], parser)
        if document.getroottree().docinfo.doctype:
            raise Refused("DTD is forbidden in package signatures")
        ns = {"d": DS}
        signed = document.find("d:SignedInfo", ns)
        if (
            signed is None
            or signed.find("d:CanonicalizationMethod", ns).get("Algorithm") != EXC
        ):
            raise Refused("Unsupported signature canonicalization")
        method = signed.find("d:SignatureMethod", ns).get("Algorithm")
        algorithm = {
            "http://www.w3.org/2001/04/xmldsig-more#rsa-sha256": "sha256",
            "http://www.w3.org/2001/04/xmldsig-more#rsa-sha512": "sha512",
        }.get(method)
        if not algorithm:
            raise Refused("Unsupported signing algorithm")
        cert = base64.b64decode(document.find(".//d:X509Certificate", ns).text)
        if sha(cert) != pin:
            raise Refused(
                "Signing identity differs from reviewed " + profile["id"] + " profile"
            )
        referenced = set()
        for ref in signed.findall("d:Reference", ns):
            from urllib.parse import unquote

            uri = unquote(ref.get("URI", ""))
            if uri.startswith("#"):
                matches = document.xpath("//*[@Id=$id]", id=uri[1:])
                if len(matches) != 1:
                    raise Refused("Ambiguous signature object")
                data = etree.tostring(
                    etree.fromstring(etree.tostring(matches[0]), parser),
                    method="c14n",
                    exclusive=False,
                )
                if any(
                    key.startswith("{http://www.w3.org/XML/1998/namespace}")
                    for node in matches[0].iter()
                    for key in node.attrib
                ):
                    raise Refused("Unsupported XML attributes in signature properties")
            else:
                if uri not in members or uri in referenced:
                    raise Refused("Invalid signed member reference")
                referenced.add(uri)
                data = members[uri]
            transforms = ref.findall("d:Transforms/d:Transform", ns)
            if any(
                t.get("Algorithm") not in (EXC, "http://www.w3.org/2006/12/xml-c14n11")
                for t in transforms
            ):
                raise Refused("Unsupported signature transform")
            method = ref.find("d:DigestMethod", ns).get("Algorithm")
            digest_algorithm = {
                "http://www.w3.org/2001/04/xmlenc#sha256": "sha256",
                "http://www.w3.org/2001/04/xmlenc#sha512": "sha512",
            }.get(method)
            if not digest_algorithm or hashlib.new(
                digest_algorithm, data
            ).digest() != base64.b64decode(ref.find("d:DigestValue", ns).text):
                raise Refused("Signed content digest mismatch: " + uri)
        expected = (
            set(members)
            - {"signature1.xml"}
            - (
                {"author-signature.xml"}
                if filename == "author-signature.xml"
                else set()
            )
        )
        if referenced != expected:
            raise Refused("Archive contains unsigned content")
        with tempfile.TemporaryDirectory(prefix="tv-signature-") as folder:
            folder = Path(folder)
            (folder / "cert.der").write_bytes(cert)
            (folder / "public.pem").write_text(
                run(
                    [
                        "openssl",
                        "x509",
                        "-inform",
                        "DER",
                        "-in",
                        folder / "cert.der",
                        "-pubkey",
                        "-noout",
                    ]
                )
            )
            (folder / "signed.bin").write_bytes(
                etree.tostring(signed, method="c14n", exclusive=True)
            )
            (folder / "signature.bin").write_bytes(
                base64.b64decode(document.find("d:SignatureValue", ns).text)
            )
            run(
                [
                    "openssl",
                    "dgst",
                    "-" + algorithm,
                    "-verify",
                    folder / "public.pem",
                    "-signature",
                    folder / "signature.bin",
                    folder / "signed.bin",
                ]
            )
    is_web = "config.xml" in members
    manifest = ET.fromstring(members["config.xml" if is_web else "tizen-manifest.xml"])
    if is_web:
        app = manifest.find("{http://tizen.org/ns/widgets}application")
        actual = app.get("package") if app is not None else None
    else:
        actual = manifest.get("package")
    if actual != package_id:
        raise Refused("Unexpected signed package identity")
    if package_id == "MiniRoot01":
        from .service_registration import verify_manifest_contract

        verify_manifest_contract(manifest)
    return members, manifest.get("version")


def next_version(current, base):
    def parts(value):
        try:
            values = tuple(int(x) for x in value.split("."))
            if len(values) != 3 or any(x < 0 or x > 65535 for x in values):
                raise ValueError()
            return values
        except (ValueError, AttributeError):
            raise Refused("Invalid package version")

    v = parts(base)
    if current and parts(current) >= v:
        v = parts(current)
        v = (v[0], v[1], v[2] + 1)
    if v[2] > 65535:
        raise Refused("Package version exhausted")
    return ".".join(map(str, v))


def require_trust(profile):
    if not all(
        profile.get(k) for k in ("author_cert_sha256", "distributor_cert_sha256")
    ):
        raise Refused(
            "Signing trust is not enrolled; configure an independently reviewed trust_file in site.json (docs/guides/tv-setup.md)"
        )


class Builder:
    def __init__(self, profile, choices, folder):
        self.profile, self.choices, self.folder = profile, choices, folder
        self.folder.mkdir(parents=True, exist_ok=True, mode=0o700)
        self.cli = os.environ.get(
            "TIZEN",
            shutil.which("tizen") or str(PRIVATE / "tizen-sdk/cli/tools/ide/bin/tizen"),
        )
        self.helper_built = False

    def command(self, argv):
        try:
            output = run(argv, timeout=240, cwd=REPO)
        except Refused as e:
            (self.folder / "build-error.log").write_text(getattr(e, "output", str(e)))
            raise Refused(
                "Build/signing failed; inspect " + str(self.folder / "build-error.log")
            ) from e
        with (self.folder / "build.log").open("a") as f:
            f.write(output + "\n")
        return output

    def build_managed(self, project, output, *, native_app_launcher=None):
        extra = (
            ["-p:NativeAppLauncher=" + str(Path(native_app_launcher).resolve())]
            if native_app_launcher
            else []
        )
        self.command(
            [
                "dotnet",
                "build",
                project,
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
            + extra
        )

    def find_renderer(self):
        path = self.choices["artifacts"].get("renderer")
        if path:
            path = Path(path).expanduser()
            if sha(path.read_bytes()) != RENDERER:
                raise Refused(
                    "Renderer override is not the reviewed S90D Asteroids binary"
                )
            return path
        local = REPO / "native/system-screensaver/bin/libgl-demo-app.so"
        candidates = [local]
        for p in candidates:
            if p.is_file() and not p.is_symlink() and sha(p.read_bytes()) == RENDERER:
                return p
        raise Refused(
            "Build the S90D renderer with native/system-screensaver/build.sh; set artifacts.renderer to the verified output"
        )

    def generated_saver(self, stage):
        # Reuse content only by reviewed digest, not a session name or previous deployment ledger.
        needed = self.profile["saver_generated"]
        if self.profile.get("source_hashes", {}).get("saver") != component_revision(
            "saver"
        ):
            self.command(["sh", REPO / "native/qn90a-screensaver/build-web.sh"])
            for name in needed:
                shutil.copyfile(
                    REPO / "native/qn90a-screensaver/web" / name, stage / name
                )
            return
        for name, digest in needed.items():
            p = REPO / "native/qn90a-screensaver/web" / name
            if p.exists() and sha(p.read_bytes()) == digest:
                shutil.copyfile(p, stage / name)
        if all((stage / n).exists() for n in needed):
            return
        self.command(["sh", REPO / "native/qn90a-screensaver/build-web.sh"])
        for name in needed:
            shutil.copyfile(REPO / "native/qn90a-screensaver/web" / name, stage / name)

    def package(self, action):
        require_trust(self.profile)
        key = action.options["artifact"]
        pkg = action.options["package"]
        override = self.choices["artifacts"].get(key)
        if override:
            path = Path(override).expanduser().resolve()
            members, version = verify_package(path, self.profile, pkg)
            for remote, expected in action.after.items():
                name = (
                    remote.split("/res/wgt/", 1)[1]
                    if "/res/wgt/" in remote
                    else "bin/" + remote.rsplit("/", 1)[1]
                )
                if name not in members or sha(members[name]) != expected:
                    raise Refused(
                        "Artifact override differs from accepted component source: "
                        + name
                    )
            if action.options["previous_version"] and tuple(
                map(int, version.split("."))
            ) <= tuple(map(int, action.options["previous_version"].split("."))):
                raise Refused("Override must use a forward version for in-place update")
            out = self.folder / (pkg + path.suffix)
            shutil.copyfile(path, out)
            return out, members
        stage = self.folder / (pkg + "-source")
        stage.mkdir()
        if key in ("hub", "saver"):
            source = REPO / ("web" if key == "hub" else "native/qn90a-screensaver/web")
            files = (
                hub_sources(self.profile["id"])
                if key == "hub"
                else {
                    n: (source / n).read_bytes()
                    for n in ("index.html", "saver.js", "icon.png")
                }
            )
            for n, data in files.items():
                (stage / n).write_bytes(data)
            if key == "saver":
                self.generated_saver(stage)
            config_bytes = (
                files["config.xml"]
                if key == "hub"
                else (source / "config.xml").read_bytes()
            )
            config = ET.fromstring(config_bytes)
            version = next_version(
                action.options["previous_version"], config.get("version")
            )
            # Preserve namespace declarations exactly; only the widget version changes.
            import re

            text = config_bytes.decode()
            text = re.sub(
                r'(<widget\b[^>]*\bversion=")[^"]+',
                lambda m: m[1] + version,
                text,
                count=1,
            )
            (stage / "config.xml").write_text(text)
            self.command(
                [
                    self.cli,
                    "package",
                    "-t",
                    "wgt",
                    "-s",
                    self.profile["signing_profile"],
                    "-o",
                    stage,
                    "--",
                    stage,
                ]
            )
            candidates = list(stage.glob("*.wgt"))
            if len(candidates) != 1:
                raise Refused("Signer did not produce exactly one WGT")
            out = self.folder / (pkg + ".wgt")
            shutil.move(candidates[0], out)
        else:
            sources = []
            if key == "boot":
                project = REPO / "native/qn90a-boot-relay"
                output = stage / "compiled"
                self.build_managed(project / "Boot.csproj", output)
                sources = [
                    (output / n, "bin/" + n)
                    for n in ("Boot.dll", "Boot.deps.json", "Boot.runtimeconfig.json")
                ]
            else:
                project = REPO / "telemetry/qn90a-startup"
                for name, proj in [
                    ("Service", project),
                    ("Bootstrap", REPO / "telemetry/qn90a-bootstrap"),
                ]:
                    output = stage / name
                    self.build_managed(proj / (name + ".csproj"), output)
                    sources += [
                        (p, "bin/" + p.name)
                        for p in output.glob(name + ".*")
                        if p.suffix != ".pdb"
                    ]
                output = stage / "collector"
                self.command(
                    [
                        "dotnet",
                        "build",
                        REPO / "telemetry/s90d-collector/Telemetry.csproj",
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
                sources.append((output / "Telemetry.dll", "bin/Telemetry.dll"))
            manifest = ET.fromstring((project / "tizen-manifest.xml").read_bytes())
            manifest.set(
                "version",
                next_version(
                    action.options["previous_version"], manifest.get("version")
                ),
            )
            out = self.folder / (pkg + "-arm.tpk")
            with zipfile.ZipFile(out, "w", zipfile.ZIP_DEFLATED) as z:
                z.writestr("tizen-manifest.xml", manifest_bytes(manifest))
                for source, target in sources:
                    z.write(source, target)
            self.command(
                [
                    self.cli,
                    "package",
                    "-t",
                    "tpk",
                    "-s",
                    self.profile["signing_profile"],
                    "--",
                    out,
                ]
            )
        members, _ = verify_package(out, self.profile, pkg)
        return out, members

    def file(self, kind):
        if kind == "renderer":
            return self.find_renderer()
        if kind == "empty":
            path = self.folder / "empty"
            path.write_bytes(b"")
            return path
        if not self.helper_built:
            self.command([sys.executable, REPO / "telemetry/s90d/build.py"])
            self.helper_built = True
        if kind == "collector":
            return REPO / "telemetry/s90d-collector/bin/Release/net6.0/Telemetry.dll"
        name = "Boot.dll" if kind == "helper" else kind
        return REPO / "telemetry/s90d/bin/helper/bin/Release/net6.0" / name
