"""``darnit-amber verify`` and ``darnit-amber rerun`` (issue #677, steps C and D)."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from .run import TSA_URL, RunError, _canonical, execute


def read_bundle(store: Any, bundle_id: str) -> dict[str, Any]:
    if hasattr(store, "read"):
        raw = store.read(bundle_id)
    else:  # local-fs store: files under its root
        root = Path(store._root)
        raw = (root / f"{bundle_id}.intoto.json").read_bytes()
    return json.loads(raw)


def _pae(payload_type: str, payload: bytes) -> bytes:
    return b"DSSEv1 %d %s %d " % (len(payload_type), payload_type.encode(), len(payload)) + payload


def _der_len(n: int) -> bytes:
    if n < 0x80:
        return bytes([n])
    b = n.to_bytes((n.bit_length() + 7) // 8, "big")
    return bytes([0x80 | len(b)]) + b


def _wrap_token(token: bytes) -> bytes:
    """A bare TimeStampToken as a TimeStampResp (status granted), which rfc3161-client can decode."""
    body = b"\x30\x03\x02\x01\x00" + token
    return b"\x30" + _der_len(len(body)) + body


_DIGEST_OIDS = {
    "2.16.840.1.101.3.4.2.1": "sha256",
    "2.16.840.1.101.3.4.2.2": "sha384",
    "2.16.840.1.101.3.4.2.3": "sha512",
}


_TRUST_ROOT: Any = None


def _trusted_root() -> Any:
    """Sigstore's trusted root: refreshed through TUF when the network allows, else the copy sigstore ships."""
    global _TRUST_ROOT
    if _TRUST_ROOT is None:
        from sigstore.models import ClientTrustConfig

        try:
            _TRUST_ROOT = ClientTrustConfig.production().trusted_root
        except Exception:  # noqa: BLE001 - offline: the bundled root is still authentic, only possibly stale
            _TRUST_ROOT = ClientTrustConfig.production(offline=True).trusted_root
    return _TRUST_ROOT


def _tsa_chain(response: Any, signature: bytes) -> str:
    """Check the token's signer against Sigstore's timestamp authorities, as sigstore-python does."""
    from rfc3161_client import VerifierBuilder
    from rfc3161_client.errors import VerificationError as Rfc3161VerificationError

    for authority in _trusted_root().get_timestamp_authorities():
        certificates = authority.certificates(allow_expired=True)
        if len(certificates) < 2:
            continue
        builder = VerifierBuilder().tsa_certificate(certificates[0]).add_root_certificate(certificates[-1])
        for certificate in certificates[1:-1]:
            builder = builder.add_intermediate_certificate(certificate)
        try:
            builder.build().verify_message(response, signature)
        except Rfc3161VerificationError:
            continue
        when = response.tst_info.gen_time
        if authority.validity_period_start <= when and (
            not authority.validity_period_end or when < authority.validity_period_end
        ):
            return "ok"
        return "signer matched but outside the authority's validity period"
    return "no trusted timestamp authority signed this token"


def _timestamps(env: dict[str, Any]) -> list[dict[str, Any]]:
    """Witness's RFC 3161 countersignatures on the envelope: when the signature existed.

    Each token's message imprint must be the hash of the signature it covers,
    and its signer must chain to a timestamp authority in Sigstore's trusted root.
    """
    import rfc3161_client

    out: list[dict[str, Any]] = []
    for sig in env.get("signatures", []):
        signature = base64.b64decode(sig["sig"])
        for t in sig.get("timestamps") or []:
            item: dict[str, Any] = {"type": t.get("type")}
            try:
                response = rfc3161_client.decode_timestamp_response(_wrap_token(base64.b64decode(t["data"])))
                info = response.tst_info
                imprint = info.message_imprint
                algo = _DIGEST_OIDS.get(imprint.hash_algorithm.dotted_string)
                covers = algo is not None and imprint.message == hashlib.new(algo, signature).digest()
                item.update(
                    {
                        "time": info.gen_time.isoformat(),
                        "serial": str(info.serial_number),
                        "covers_signature": covers,
                        "tsa_chain": _tsa_chain(response, signature) if covers else "skipped (imprint mismatch)",
                    }
                )
            except Exception as e:  # noqa: BLE001 - reported, never fatal
                item["error"] = f"{type(e).__name__}: {e}"
            out.append(item)
    return out


def _verify_envelope(env: dict[str, Any], pubkey: Path | None) -> str:
    """'unsigned-check' when no key; 'ok' or raises when a key is given."""
    if pubkey is None:
        return "skipped (no --pubkey)"
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_public_key(pubkey.read_bytes())
    payload = base64.b64decode(env["payload"])
    pae = _pae(env["payloadType"], payload)
    for sig in env["signatures"]:
        try:
            key.verify(base64.b64decode(sig["sig"]), pae)  # type: ignore[call-arg]
            return "ok"
        except Exception:  # noqa: BLE001
            continue
    raise RunError("no Witness signature verifies with the given public key")


def verify(store: Any, bundle_id: str, pubkey: Path | None) -> dict[str, Any]:
    bundle = read_bundle(store, bundle_id)
    stmt = bundle["statement"]
    recomputed = hashlib.sha256(_canonical(stmt)).hexdigest()
    checks: dict[str, Any] = {"id_matches_statement": recomputed == bundle["id"] == bundle_id}
    exp = stmt["predicate"].get("experiment")
    envs = bundle.get("witness_envelopes", {})
    if exp and "experiment" in envs:
        w = json.loads(base64.b64decode(envs["experiment"]["payload"]))
        prod = next(
            (a["attestation"] for a in w["predicate"]["attestations"] if a["type"].endswith("/product/v0.1")), {}
        )
        checks["outputs_match_witness_products"] = all(
            (prod.get(o["path"]) or {}).get("digest", {}).get("sha256") == o["sha256"] for o in exp["outputs"]
        )
    checks["signatures"] = {name: _verify_envelope(env, pubkey) for name, env in envs.items()}
    checks["timestamps"] = {name: _timestamps(env) for name, env in envs.items()}
    stamped = [t for ts in checks["timestamps"].values() for t in ts]
    checks["timestamp_covers_signature"] = bool(stamped) and all(t.get("covers_signature") for t in stamped)
    checks["timestamp_authority_trusted"] = bool(stamped) and all(t.get("tsa_chain") == "ok" for t in stamped)
    checks["signing"] = stmt["predicate"].get("signing")
    checks["verified"] = all(v is True for k, v in checks.items() if isinstance(v, bool))
    return {"id": bundle_id, "subject": stmt["subject"][0], **checks}


def rerun(store: Any, bundle_id: str, key: Path | None, tsa: str | None = TSA_URL) -> dict[str, Any]:
    first = read_bundle(store, bundle_id)
    stmt = first["statement"]
    pred = stmt["predicate"]
    exp = pred.get("experiment")
    if not exp:
        raise RunError("bundle has no experiment to rerun")
    artifact = stmt["subject"][0]["name"]
    commit = stmt["subject"][0]["digest"].get("gitCommit")
    first_claims = pred.get("claims") or []
    entry = {
        "id": pred.get("corpus_entry"),
        "run": {"command": exp["command"], "outputs": [o["path"] for o in exp["outputs"]]},
        "claims": [{k: v for k, v in c.items() if k not in ("measured", "verdict", "reason")} for c in first_claims],
    }
    new = execute(artifact, commit, key, entry, store, rerun_of=bundle_id, tsa=tsa)
    new_pred = new["statement"]["predicate"]
    mine = {o["path"]: o["sha256"] for o in new_pred["experiment"]["outputs"]}
    outputs = [
        {
            "path": o["path"],
            "first": o["sha256"],
            "rerun": mine.get(o["path"]),
            "result": "identical" if mine.get(o["path"]) == o["sha256"] else "changed",
        }
        for o in exp["outputs"]
    ]
    again = {c["id"]: c for c in new_pred.get("claims") or []}
    claims = [
        {
            "id": c["id"],
            "first": {"measured": c.get("measured"), "verdict": c.get("verdict")},
            "rerun": {
                "measured": again.get(c["id"], {}).get("measured"),
                "verdict": again.get(c["id"], {}).get("verdict"),
            },
            "result": "same" if again.get(c["id"], {}).get("verdict") == c.get("verdict") else "changed",
        }
        for c in first_claims
    ]
    measured = [c for c in claims if c["first"]["measured"] is not None]
    drift = any(c["result"] == "changed" for c in claims) or (
        not measured and any(o["result"] == "changed" for o in outputs)
    )
    new_pred["reruns"] = {"of": bundle_id, "outputs": outputs, "claims": claims, "drift": drift}
    # the id covers the comparison too: recompute and store
    new["id"] = hashlib.sha256(_canonical(new["statement"])).hexdigest()
    store.write(new["id"], _canonical(new), "application/vnd.in-toto+json")
    return {
        "id": new["id"],
        "rerun_of": bundle_id,
        "exit_code": new_pred["experiment"]["exit_code"],
        "verdict": new_pred.get("verdict"),
        "outputs": outputs,
        "claims": claims,
        "drift": drift,
    }
