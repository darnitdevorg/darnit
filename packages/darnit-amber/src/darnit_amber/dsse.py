"""DSSE helpers shared by ``verify`` and the signing paths: what a signature covers, and how to check one."""

from __future__ import annotations

from typing import Any

from cryptography.hazmat.primitives import hashes
from cryptography.hazmat.primitives.asymmetric import ec, ed25519, padding, rsa


def pae(payload_type: str, payload: bytes) -> bytes:
    """DSSE pre-authentication encoding: what a DSSE signature actually signs."""
    return b"DSSEv1 %d %s %d " % (len(payload_type), payload_type.encode(), len(payload)) + payload


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
