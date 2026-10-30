"""``--identity``: sign with a short-lived Sigstore (Fulcio) certificate instead of a key, and verify it.

The researcher logs in once per run (GitHub, Google, ...); Fulcio issues a
certificate valid for ten minutes bound to that identity; Witness signs with
it and puts the certificate and its chain in the envelope. ``verify`` checks
the signature with the certificate's key, the chain against the Fulcio
certificates in Sigstore's trusted root, and that the signing time (the RFC
3161 timestamp) falls inside the certificate's validity window. Fulcio
records every certificate it issues in a public transparency log, so the
identity becomes public; see the README.
"""

from __future__ import annotations

import base64
import hashlib
import os
from datetime import datetime
from typing import Any

from cryptography import x509
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa
from cryptography.x509.oid import ExtensionOID, ObjectIdentifier

FULCIO_URL = "https://fulcio.sigstore.dev"
OIDC_ISSUER = "https://oauth2.sigstore.dev/auth"
OIDC_CLIENT_ID = "sigstore"
TOKEN_ENV = "SIGSTORE_ID_TOKEN"  # a raw OIDC token (audience "sigstore"), e.g. from CI

_ISSUER_V1 = ObjectIdentifier("1.3.6.1.4.1.57264.1.1")  # raw string
_ISSUER_V2 = ObjectIdentifier("1.3.6.1.4.1.57264.1.8")  # DER UTF8String


def identity_token() -> str:
    """An OIDC token for Fulcio: ``$SIGSTORE_ID_TOKEN``, else the CI's ambient token, else a login.

    The login is out-of-band (a URL to open anywhere, a code to paste back), so it works on a
    machine with no browser. The token is a secret: callers must not log it or put it in argv.
    """
    raw = os.environ.get(TOKEN_ENV)
    if raw:
        return raw.strip()
    from sigstore.oidc import Issuer, detect_credential

    ambient = detect_credential(OIDC_CLIENT_ID)
    if ambient:
        return ambient
    return str(Issuer(OIDC_ISSUER).identity_token(client_id=OIDC_CLIENT_ID, force_oob=True))


def pae(payload_type: str, payload: bytes) -> bytes:
    """DSSE pre-authentication encoding: what a DSSE signature actually signs."""
    return b"DSSEv1 %d %s %d " % (len(payload_type), payload_type.encode(), len(payload)) + payload


def _der_utf8(raw: bytes) -> str:
    """The string inside a DER UTF8String (tag 0x0c); older Fulcio wrote the raw string."""
    if len(raw) >= 2 and raw[0] == 0x0C:
        n, i = raw[1], 2
        if n & 0x80:
            k = n & 0x7F
            n, i = int.from_bytes(raw[2 : 2 + k], "big"), 2 + k
        return raw[i : i + n].decode()
    return raw.decode()


def certificate_identity(cert: x509.Certificate) -> dict[str, Any]:
    """Who the certificate names: subject alternative names, OIDC issuer, and the certificate's digest."""
    subjects: list[str] = []
    try:
        san = cert.extensions.get_extension_for_oid(ExtensionOID.SUBJECT_ALTERNATIVE_NAME).value
        subjects = [n.value for n in san if isinstance(n, (x509.RFC822Name, x509.UniformResourceIdentifier))]
    except x509.ExtensionNotFound:
        pass
    issuer = None
    for oid in (_ISSUER_V2, _ISSUER_V1):
        try:
            issuer = _der_utf8(cert.extensions.get_extension_for_oid(oid).value.value)  # type: ignore[attr-defined]
            break
        except x509.ExtensionNotFound:
            continue
    der = cert.public_bytes(serialization.Encoding.DER)
    return {
        "subject": subjects[0] if subjects else cert.subject.rfc4514_string() or None,
        "issuer": issuer,
        "certificate_sha256": hashlib.sha256(der).hexdigest(),
        "not_before": cert.not_valid_before_utc.isoformat(),
        "not_after": cert.not_valid_after_utc.isoformat(),
    }


def signature_chain(sig: dict[str, Any]) -> list[x509.Certificate]:
    """The certificates Witness put in a DSSE signature: leaf first, then intermediates (PEM, base64 in JSON)."""
    out = []
    for field in ("certificate", *(["intermediates"] if sig.get("intermediates") else [])):
        values = sig.get(field)
        for v in values if isinstance(values, list) else [values]:
            if v:
                out.extend(x509.load_pem_x509_certificates(base64.b64decode(v)))
    return out


def verify_with(key: Any, signature: bytes, data: bytes) -> None:
    """Raise unless ``signature`` over ``data`` verifies with ``key`` (ECDSA P-256/SHA-256, RSA PKCS#1 v1.5, Ed25519)."""
    if isinstance(key, ec.EllipticCurvePublicKey):
        key.verify(signature, data, ec.ECDSA(hashes.SHA256()))
    elif isinstance(key, rsa.RSAPublicKey):
        key.verify(signature, data, padding.PKCS1v15(), hashes.SHA256())
    elif isinstance(key, ed25519.Ed25519PublicKey):
        key.verify(signature, data)
    else:
        raise ValueError(f"unsupported key type {type(key).__name__}")


def _chain_to_trusted(
    leaf: x509.Certificate, candidates: list[x509.Certificate], anchors: list[x509.Certificate], when: datetime
) -> str:
    """Path validation of ``leaf`` to one of ``anchors`` at ``when``, as sigstore-python does it.

    OpenSSL in strict mode builds the path and enforces the CA constraints
    (basicConstraints, keyUsage, path length, key identifiers); ``candidates``
    (the envelope's intermediates) are untrusted and can only link, never
    anchor. A leaf is also required to carry the code-signing EKU, which is
    what Fulcio issues; a certificate that is not a CA can never issue one.
    """
    from cryptography.x509.oid import ExtendedKeyUsageOID, ExtensionOID
    from OpenSSL.crypto import X509, X509Store, X509StoreContext, X509StoreContextError, X509StoreFlags

    try:
        eku = leaf.extensions.get_extension_for_oid(ExtensionOID.EXTENDED_KEY_USAGE).value
    except x509.ExtensionNotFound:
        return "leaf certificate has no extended key usage"
    if ExtendedKeyUsageOID.CODE_SIGNING not in eku:
        return "leaf certificate is not a code-signing certificate"
    store = X509Store()
    store.set_flags(X509StoreFlags.X509_STRICT)
    for anchor in anchors:
        store.add_cert(X509.from_cryptography(anchor))
    store.set_time(when)
    context = X509StoreContext(
        store, X509.from_cryptography(leaf), chain=[X509.from_cryptography(c) for c in candidates]
    )
    try:
        verified = context.get_verified_chain()
    except X509StoreContextError as e:
        return f"no valid path to a Fulcio certificate in Sigstore's trusted root: {e}"
    if len(verified) < 2:
        return "leaf certificate is itself a trust anchor"
    return "ok"


def verify_identity_signature(
    env: dict[str, Any], sig: dict[str, Any], when: datetime | None, anchors: list[x509.Certificate]
) -> dict[str, Any]:
    """Check one certificate-bearing DSSE signature. ``when`` is the trusted time the signature existed."""
    chain = signature_chain(sig)
    leaf, intermediates = chain[0], chain[1:]
    result: dict[str, Any] = {**certificate_identity(leaf), "signature": None, "chain": None, "signed_at": None}
    try:
        data = pae(env["payloadType"], base64.b64decode(env["payload"]))
        verify_with(leaf.public_key(), base64.b64decode(sig["sig"]), data)
        result["signature"] = "ok"
    except Exception as e:  # noqa: BLE001
        result["signature"] = f"invalid: {type(e).__name__}"
    if when is None:
        result["chain"] = "skipped (no trusted timestamp to place the signature inside the certificate's window)"
    else:
        result["signed_at"] = when.isoformat()
        result["chain"] = _chain_to_trusted(leaf, intermediates, anchors, when)
    result["ok"] = result["signature"] == "ok" and result["chain"] == "ok"
    return result
