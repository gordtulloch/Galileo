# SPDX-License-Identifier: GPL-3.0-or-later
# Copyright (C) 2025-2026 Gord Tulloch

"""Connect Link TLS certificate (LINK-010, LINK-260).

A self-signed EC P-256 certificate is generated on first use. The private key lives in the secret
store, never in a file or the database; the (public) certificate PEM is a setting. Peers pin the
SHA-256 fingerprint, which the Options page also shows. A user-supplied pair replaces it.
"""

from __future__ import annotations

import datetime
import ssl
import tempfile
from pathlib import Path

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec
from cryptography.x509.oid import NameOID

from galileo.connect_link.secrets_store import SecretStore

_NS = "connect_link"
_KEY_SECRET = "tls_private_key"  # noqa: S105 -- the secret store entry name, not a secret
_VALID_DAYS = 3650


class CertificateError(Exception):
    """A certificate or key that cannot be used."""


def fingerprint_of(cert_pem: str) -> str:
    """SHA-256 of the certificate's DER form, lower-case hex."""
    cert = x509.load_pem_x509_certificate(cert_pem.encode("ascii"))
    return cert.fingerprint(hashes.SHA256()).hex()


class CertificateStore:
    def __init__(self, secrets: SecretStore, node_name: str = "galileo") -> None:
        self._secrets = secrets
        self._node_name = node_name

    # -- settings access (kept lazy so import never touches the database) --------------
    @staticmethod
    def _get_cert() -> str:
        from galileo import settings_store
        return str(settings_store.get_setting(_NS, "tls_cert", "") or "")

    @staticmethod
    def _set_cert(pem: str) -> None:
        from galileo import settings_store
        if not settings_store.set_setting(_NS, "tls_cert", pem):
            raise CertificateError("could not save the certificate (no database)")

    def ensure(self) -> str:
        """The certificate PEM, generating and storing a new pair if there is none."""
        cert_pem, key_pem = self._get_cert(), self._secrets.get(_KEY_SECRET)
        if cert_pem and key_pem:
            return cert_pem
        return self._generate()

    def fingerprint(self) -> str:
        return fingerprint_of(self.ensure())

    def _generate(self) -> str:
        key = ec.generate_private_key(ec.SECP256R1())
        name = x509.Name([x509.NameAttribute(NameOID.COMMON_NAME, self._node_name)])
        now = datetime.datetime.now(datetime.UTC)
        cert = (
            x509.CertificateBuilder()
            .subject_name(name).issuer_name(name).public_key(key.public_key())
            .serial_number(x509.random_serial_number())
            .not_valid_before(now - datetime.timedelta(days=1))
            .not_valid_after(now + datetime.timedelta(days=_VALID_DAYS))
            .add_extension(x509.BasicConstraints(ca=False, path_length=None), critical=True)
            .sign(key, hashes.SHA256())
        )
        return self._store(cert.public_bytes(serialization.Encoding.PEM).decode("ascii"), key)

    def _store(self, cert_pem: str, key) -> str:
        key_pem = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8, serialization.NoEncryption(),
        ).decode("ascii")
        self._secrets.set(_KEY_SECRET, key_pem)
        self._set_cert(cert_pem)
        return cert_pem

    def install_user_pair(self, cert_pem: str, key_pem: str) -> str:
        """Replace the certificate with the user's own; refuses a key that does not match it."""
        try:
            cert = x509.load_pem_x509_certificate(cert_pem.encode("ascii"))
            key = serialization.load_pem_private_key(key_pem.encode("ascii"), password=None)
        except Exception as exc:
            raise CertificateError(f"could not read the certificate and key: {exc}") from exc
        spki = serialization.PublicFormat.SubjectPublicKeyInfo
        pem = serialization.Encoding.PEM
        if cert.public_key().public_bytes(pem, spki) != key.public_key().public_bytes(pem, spki):
            raise CertificateError("the private key does not match the certificate")
        return self._store(cert_pem, key)

    def ssl_context(self) -> ssl.SSLContext:
        """A server context (TLS 1.2+). Python cannot load a key from memory, so the key is written
        encrypted under a throwaway password to a private temporary folder, loaded, and deleted."""
        import secrets as _secrets
        cert_pem = self.ensure()
        key_pem = self._secrets.get(_KEY_SECRET)
        if not key_pem:
            raise CertificateError("the TLS private key is missing from the secret store")
        key = serialization.load_pem_private_key(key_pem.encode("ascii"), password=None)
        password = _secrets.token_hex(16)
        enc = key.private_bytes(
            serialization.Encoding.PEM, serialization.PrivateFormat.PKCS8,
            serialization.BestAvailableEncryption(password.encode("ascii")),
        )
        ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
        ctx.minimum_version = ssl.TLSVersion.TLSv1_2
        with tempfile.TemporaryDirectory(prefix="galileo-link-") as tmp:
            cert_path, key_path = Path(tmp) / "c.pem", Path(tmp) / "k.pem"
            cert_path.write_text(cert_pem, encoding="ascii")
            key_path.write_bytes(enc)
            ctx.load_cert_chain(str(cert_path), str(key_path), password=password)
        return ctx
