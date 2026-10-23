"""Verify synthetic Tizen signature properties, SHA-512 and certificate lists."""

import base64
import hashlib
from pathlib import Path
import tempfile
import unittest
import zipfile

from lxml import etree as E

from tvsetup.artifacts import DS, EXC, verify_package
from tvsetup.common import Refused, run, sha


class TizenSignatureTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.tmp = tempfile.TemporaryDirectory()
        cls.addClassCleanup(cls.tmp.cleanup)
        cls.root = Path(cls.tmp.name)
        for name in ("issuer", "signer"):
            run(
                [
                    "openssl",
                    "req",
                    "-new",
                    "-newkey",
                    "rsa:2048",
                    "-nodes",
                    "-keyout",
                    cls.root / (name + ".key"),
                    "-out",
                    cls.root / (name + ".csr"),
                    "-subj",
                    "/CN=Synthetic " + name,
                ]
            )
        run(
            [
                "openssl",
                "x509",
                "-req",
                "-in",
                cls.root / "issuer.csr",
                "-signkey",
                cls.root / "issuer.key",
                "-days",
                "1",
                "-set_serial",
                "1",
                "-out",
                cls.root / "issuer.pem",
            ]
        )
        run(
            [
                "openssl",
                "x509",
                "-req",
                "-in",
                cls.root / "signer.csr",
                "-CA",
                cls.root / "issuer.pem",
                "-CAkey",
                cls.root / "issuer.key",
                "-set_serial",
                "2",
                "-days",
                "1",
                "-out",
                cls.root / "signer.pem",
            ]
        )
        cls.certs = []
        for name in ("signer", "issuer"):
            run(
                [
                    "openssl",
                    "x509",
                    "-in",
                    cls.root / (name + ".pem"),
                    "-outform",
                    "DER",
                    "-out",
                    cls.root / (name + ".der"),
                ]
            )
            cls.certs.append((cls.root / (name + ".der")).read_bytes())
        cls.profile = dict(
            id="test",
            author_cert_sha256=sha(cls.certs[0]),
            distributor_cert_sha256=sha(cls.certs[0]),
        )

    def signature(self, files, role):
        ns = "{" + DS + "}"
        props = "http://www.w3.org/2009/xmldsig-properties"
        root = E.Element(ns + "Signature", nsmap={None: DS}, Id="Signature")
        signed = E.SubElement(root, ns + "SignedInfo")
        E.SubElement(signed, ns + "CanonicalizationMethod", Algorithm=EXC)
        E.SubElement(
            signed,
            ns + "SignatureMethod",
            Algorithm="http://www.w3.org/2001/04/xmldsig-more#rsa-sha512",
        )
        value = E.SubElement(root, ns + "SignatureValue")
        info = E.SubElement(root, ns + "KeyInfo")
        certs = E.SubElement(info, ns + "X509Data")
        for cert in self.certs:
            E.SubElement(certs, ns + "X509Certificate").text = base64.b64encode(
                cert
            ).decode()
        obj = E.SubElement(root, ns + "Object", Id="SignedProperties")
        properties = E.SubElement(obj, ns + "SignatureProperties")
        for name, attr, text in (
            ("Profile", "URI", "http://www.w3.org/ns/widgets-digsig#profile"),
            ("Role", "URI", "http://www.w3.org/ns/widgets-digsig#role-" + role),
            ("Identifier", None, "synthetic-" + role),
        ):
            prop = E.SubElement(
                properties, ns + "SignatureProperty", Id=name, Target="#Signature"
            )
            item = E.SubElement(prop, "{" + props + "}" + name, nsmap={"dsp": props})
            if attr:
                item.set(attr, text)
            else:
                item.text = text
        references = dict(files)
        references["#SignedProperties"] = E.tostring(
            E.fromstring(E.tostring(obj)), method="c14n", exclusive=False
        )
        for name, data in references.items():
            ref = E.SubElement(signed, ns + "Reference", URI=name)
            if name.startswith("#"):
                transforms = E.SubElement(ref, ns + "Transforms")
                E.SubElement(
                    transforms,
                    ns + "Transform",
                    Algorithm="http://www.w3.org/2006/12/xml-c14n11",
                )
            E.SubElement(
                ref,
                ns + "DigestMethod",
                Algorithm="http://www.w3.org/2001/04/xmlenc#sha512",
            )
            E.SubElement(ref, ns + "DigestValue").text = base64.b64encode(
                hashlib.sha512(data).digest()
            ).decode()
        (self.root / "signed").write_bytes(
            E.tostring(signed, method="c14n", exclusive=True)
        )
        run(
            [
                "openssl",
                "dgst",
                "-sha512",
                "-sign",
                self.root / "signer.key",
                "-out",
                self.root / "signature",
                self.root / "signed",
            ]
        )
        value.text = base64.b64encode((self.root / "signature").read_bytes()).decode()
        return E.tostring(root)

    def package(self, mutate=None):
        files = {
            "config.xml": b'<widget xmlns="http://www.w3.org/ns/widgets" xmlns:tizen="http://tizen.org/ns/widgets" version="1.0.0"><tizen:application package="MiniHub001" id="MiniHub001.Hub"/></widget>',
            "index.html": b"<html>synthetic fixture</html>",
        }
        files["author-signature.xml"] = self.signature(files, "author")
        files["signature1.xml"] = self.signature(files, "distributor")
        if mutate:
            document = E.fromstring(files["signature1.xml"])
            mutate(document)
            files["signature1.xml"] = E.tostring(document)
        path = self.root / "shape.wgt"
        with zipfile.ZipFile(path, "w") as archive:
            for name, data in files.items():
                archive.writestr(name, data)
        return path

    def verify(self, mutate=None, profile=None):
        return verify_package(
            self.package(mutate), profile or self.profile, "MiniHub001"
        )

    def test_sha512_properties_and_two_certificates_verify(self):
        members, version = self.verify()
        self.assertEqual(version, "1.0.0")
        self.assertIn("index.html", members)

    def test_properties_digest_rejects_tampering(self):
        def mutate(document):
            document.xpath('//*[@Id="Identifier"]')[0][0].text = "changed"

        with self.assertRaisesRegex(Refused, "digest mismatch: #SignedProperties"):
            self.verify(mutate)

    def test_missing_or_duplicate_object_is_refused(self):
        for duplicate in (False, True):
            with self.subTest(duplicate=duplicate):

                def mutate(document):
                    obj = document.xpath('//*[@Id="SignedProperties"]')[0]
                    if duplicate:
                        document.append(E.fromstring(E.tostring(obj)))
                    else:
                        document.remove(obj)

                with self.assertRaisesRegex(Refused, "Ambiguous signature object"):
                    self.verify(mutate)

    def test_xml_attributes_in_properties_are_refused(self):
        def mutate(document):
            document.xpath('//*[@Id="Identifier"]')[0].set(
                "{http://www.w3.org/XML/1998/namespace}lang", "en"
            )

        with self.assertRaisesRegex(Refused, "Unsupported XML attributes"):
            self.verify(mutate)

    def test_sha512_signature_value_is_actually_verified(self):
        def mutate(document):
            document.find("{" + DS + "}SignatureValue").text = base64.b64encode(
                b"invalid"
            ).decode()

        with self.assertRaises(Refused):
            self.verify(mutate)

    def test_pin_is_for_first_certificate_not_any_certificate(self):
        with self.assertRaisesRegex(Refused, "Signing identity"):
            self.verify(
                profile=dict(self.profile, distributor_cert_sha256=sha(self.certs[1]))
            )

        def mutate(document):
            data = document.find(".//{" + DS + "}X509Data")
            data.insert(0, data[-1])

        with self.assertRaisesRegex(Refused, "Signing identity"):
            self.verify(mutate)


if __name__ == "__main__":
    unittest.main()
