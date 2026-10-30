"""``--publish``: record each Witness envelope in Rekor, Sigstore's public transparency log, and check it.

Only the DSSE envelope goes to Rekor (the statement's hashes, command and
environment, and the signature with its certificate or public key); the
experiment's outputs stay in the researcher's store. Rekor answers with a
log index, an inclusion proof and a signed checkpoint, which the bundle
keeps under ``publication`` so that ``verify`` can check inclusion
offline; online, it also re-fetches the entry by index. Anyone can look
the entry up, so the envelope and the signer identity become public.
"""

from __future__ import annotations

import base64
import hashlib
import json
from typing import Any

from cryptography.hazmat.primitives import serialization

REKOR_URL = "https://rekor.sigstore.dev"


def _dsse_envelope(env: dict[str, Any]) -> str:
    """The envelope as DSSE proper: Witness's certificate and timestamp fields are not part of the format."""
    return json.dumps(
        {
            "payload": env["payload"],
            "payloadType": env["payloadType"],
            "signatures": [{"keyid": s.get("keyid", ""), "sig": s["sig"]} for s in env["signatures"]],
        },
        separators=(",", ":"),
    )


def _verifiers(env: dict[str, Any], key_path: Any) -> list[str]:
    """Base64 PEM of what verifies each signature: the Fulcio certificate, or the signing key's public half."""
    out = []
    for sig in env["signatures"]:
        if sig.get("certificate"):
            out.append(sig["certificate"])  # already base64 PEM
            continue
        if key_path is None:
            raise ValueError("a key-signed envelope needs the key to derive the verifier")
        private = serialization.load_pem_private_key(key_path.read_bytes(), password=None)
        pem = private.public_key().public_bytes(
            serialization.Encoding.PEM, serialization.PublicFormat.SubjectPublicKeyInfo
        )
        out.append(base64.b64encode(pem).decode())
    return out


def publish_envelope(env: dict[str, Any], key_path: Any, rekor_url: str = REKOR_URL) -> dict[str, Any]:
    """POST the envelope as a Rekor ``dsse`` entry; return what the bundle keeps."""
    from sigstore._internal.rekor.client import RekorClient

    proposed = {
        "apiVersion": "0.0.1",
        "kind": "dsse",
        "spec": {"proposedContent": {"envelope": _dsse_envelope(env), "verifiers": _verifiers(env, key_path)}},
    }
    client = RekorClient(rekor_url)
    resp = client.log.entries.session.post(client.log.entries.url, json=proposed)
    resp.raise_for_status()
    response = resp.json()  # {uuid: {body, integratedTime, logID, logIndex, verification}}
    ((uuid, entry),) = response.items()
    return {
        "log": rekor_url,
        "uuid": uuid,
        "log_index": entry["logIndex"],
        "integrated_time": entry["integratedTime"],
        "response": response,  # verbatim, so verify can rebuild and check the proof offline
    }


def _entry_body(record: dict[str, Any]) -> dict[str, Any]:
    ((_uuid, entry),) = record["response"].items()
    return json.loads(base64.b64decode(entry["body"]))


def verify_publication(
    env: dict[str, Any], record: dict[str, Any], trusted_root: Any, online: bool = True
) -> dict[str, Any]:
    """Is this envelope the one in the log, and is the log's proof of inclusion good?"""
    from sigstore.models import TransparencyLogEntry

    result: dict[str, Any] = {
        "log": record.get("log"),
        "log_index": record.get("log_index"),
        "integrated_time": None,
        "entry_matches_envelope": None,
        "inclusion": None,
        "online": None,
    }
    try:
        from datetime import UTC, datetime

        result["integrated_time"] = datetime.fromtimestamp(int(record["integrated_time"]), UTC).isoformat()
    except Exception:  # noqa: BLE001
        pass
    try:
        body = _entry_body(record)
        spec = body["spec"]
        payload_hash = hashlib.sha256(base64.b64decode(env["payload"])).hexdigest()
        sigs = {s["sig"] for s in env["signatures"]}
        logged = {s["signature"] for s in spec.get("signatures", [])}
        result["entry_matches_envelope"] = (
            body.get("kind") == "dsse"
            and spec["payloadHash"]["value"] == payload_hash
            and bool(sigs)
            and sigs == logged
        )
    except Exception as e:  # noqa: BLE001
        result["entry_matches_envelope"] = False
        result["error"] = f"{type(e).__name__}: {e}"
        return result
    if not result["entry_matches_envelope"]:
        result["ok"] = False  # a proof of inclusion for some other entry says nothing about this envelope
        return result
    try:
        from sigstore._internal.trust import KeyringPurpose

        entry = TransparencyLogEntry._from_v1_response(record["response"])
        entry._verify(trusted_root.rekor_keyring(KeyringPurpose.VERIFY))
        result["inclusion"] = "ok"
    except Exception as e:  # noqa: BLE001
        result["inclusion"] = f"invalid: {type(e).__name__}: {e}"
    if online:
        try:
            from sigstore._internal.rekor.client import RekorClient

            fetched = RekorClient(record["log"]).log.entries.get(log_index=int(record["log_index"]))
            ((_u, stored),) = record["response"].items()
            same = fetched._inner.canonicalized_body == base64.b64decode(stored["body"])
            result["online"] = "ok" if same else "the log holds a different entry at this index"
        except Exception as e:  # noqa: BLE001
            result["online"] = f"skipped: {type(e).__name__}: {e}"
    result["ok"] = result["entry_matches_envelope"] is True and result["inclusion"] == "ok"
    return result
