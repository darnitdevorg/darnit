"""``darnit-amber verify`` and ``darnit-amber rerun`` (issue #677, steps C and D)."""

from __future__ import annotations

import base64
import hashlib
import json
from datetime import datetime
from pathlib import Path
from typing import Any

from .identity import pae as _pae
from .identity import verify_identity_signature, verify_with
from .publish import verify_publication
from .run import TSA_URL, RunError, _canonical, execute


def read_bundle(store: Any, bundle_id: str) -> dict[str, Any]:
    if hasattr(store, "read"):
        raw = store.read(bundle_id)
    else:  # local-fs store: files under its root
        root = Path(store._root)
        raw = (root / f"{bundle_id}.intoto.json").read_bytes()
    return json.loads(raw)


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
    for index, sig in enumerate(env.get("signatures") or []):
        for t in sig.get("timestamps") or []:
            item: dict[str, Any] = {"type": t.get("type"), "signature": index}
            try:
                signature = base64.b64decode(sig["sig"])
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


def _trusted_time(stamps: list[dict[str, Any]], index: int) -> datetime | None:
    """The earliest time a trusted timestamp proves signature ``index`` existed."""
    times = [
        datetime.fromisoformat(t["time"])
        for t in stamps
        if t.get("signature") == index and t.get("covers_signature") and t.get("tsa_chain") == "ok"
    ]
    return min(times) if times else None


def _verify_identities(env: dict[str, Any], stamps: list[dict[str, Any]]) -> list[dict[str, Any]]:
    """Every certificate-bearing signature on the envelope, checked against Sigstore's Fulcio roots."""
    out = []
    for index, sig in enumerate(env.get("signatures", [])):
        if not sig.get("certificate"):
            continue
        try:
            out.append(
                verify_identity_signature(env, sig, _trusted_time(stamps, index), _trusted_root().get_fulcio_certs())
            )
        except Exception as e:  # noqa: BLE001 - reported, never fatal
            out.append({"ok": False, "error": f"{type(e).__name__}: {e}"})
    return out


def _key_fingerprint(pubkey: Path) -> str:
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_public_key(pubkey.read_bytes())
    der = key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)
    return "sha256:" + hashlib.sha256(der).hexdigest()


def _verify_envelope(env: dict[str, Any], pubkey: Path | None) -> tuple[str, bool]:
    """The key-signature check of one envelope: what to report, and whether it passed.

    A certificate-signed envelope is checked by ``_verify_identities``; a
    key-signed one needs ``--pubkey``, and without it the check fails rather
    than being skipped, so ``verified`` can never be true for a bundle whose
    signature nobody checked.
    """
    signatures = env.get("signatures") or []
    if any(s.get("certificate") for s in signatures):
        return "see identity", True
    if pubkey is None:
        return "not checked: key-signed bundle and no --pubkey", False
    from cryptography.hazmat.primitives import serialization

    key = serialization.load_pem_public_key(pubkey.read_bytes())
    payload = base64.b64decode(env["payload"])
    pae = _pae(env["payloadType"], payload)
    for sig in signatures:
        try:
            verify_with(key, base64.b64decode(sig["sig"]), pae)
            return "ok", True
        except Exception:  # noqa: BLE001 - try the next signature
            continue
    return "no Witness signature verifies with the given public key", False


def verify(store: Any, bundle_id: str, pubkey: Path | None, online: bool = True) -> dict[str, Any]:
    bundle = read_bundle(store, bundle_id)
    stmt = bundle["statement"]
    pred = stmt["predicate"]
    recomputed = hashlib.sha256(_canonical(stmt)).hexdigest()
    checks: dict[str, Any] = {"id_matches_statement": recomputed == bundle["id"] == bundle_id}
    envs = bundle.get("witness_envelopes") or {}

    # The statement names every envelope by digest: a bundle cannot drop or swap one.
    expected = pred.get("witness_envelopes_sha256") or {}
    checks["envelopes_match_statement"] = (
        bool(expected)
        and set(expected) == set(envs)
        and all(hashlib.sha256(_canonical(envs[name])).hexdigest() == digest for name, digest in expected.items())
    )

    exp = pred.get("experiment")
    if exp:
        w = json.loads(base64.b64decode(envs["experiment"]["payload"])) if "experiment" in envs else {}
        attestations = {a["type"]: a["attestation"] for a in (w.get("predicate") or {}).get("attestations") or []}
        prod = next((v for k, v in attestations.items() if k.endswith("/product/v0.1")), {})
        run = next((v for k, v in attestations.items() if k.endswith("/command-run/v0.1")), {})
        checks["outputs_match_witness_products"] = bool(w) and all(
            (prod.get(o["path"]) or {}).get("digest", {}).get("sha256") == o["sha256"] for o in exp["outputs"]
        )
        checks["command_matches_witness"] = bool(w) and run.get("cmd") == ["sh", "-c", exp["command"]]

    signatures = {name: _verify_envelope(env, pubkey) for name, env in envs.items()}
    checks["signatures"] = {name: text for name, (text, _ok) in signatures.items()}
    checks["timestamps"] = {name: _timestamps(env) for name, env in envs.items()}
    stamped = [t for ts in checks["timestamps"].values() for t in ts]
    checks["timestamp_covers_signature"] = bool(stamped) and all(t.get("covers_signature") for t in stamped)
    checks["timestamp_authority_trusted"] = bool(stamped) and all(t.get("tsa_chain") == "ok" for t in stamped)

    signing = pred.get("signing") or {}
    identities = {name: _verify_identities(env, checks["timestamps"][name]) for name, env in envs.items()}
    if any(identities.values()):
        checks["identity"] = identities
        recorded = signing.get("certificates_sha256") or {}
        checks["identity_verified"] = all(
            ids and all(i.get("ok") and i.get("certificate_sha256") == recorded.get(name) for i in ids)
            for name, ids in identities.items()
        )
    checks["signatures_verified"] = bool(envs) and all(ok for _text, ok in signatures.values())
    if pubkey is not None and signing.get("method") == "key":
        checks["signer_matches_statement"] = _key_fingerprint(pubkey) == signing.get("key_fingerprint")

    publication = pred.get("publication")
    if publication:
        checks["publication"] = {}
        for name, record in publication.items():
            try:
                checks["publication"][name] = verify_publication(envs[name], record, _trusted_root(), online=online)
            except Exception as e:  # noqa: BLE001 - reported, never fatal
                checks["publication"][name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        checks["published"] = all(p.get("ok") for p in checks["publication"].values())
    checks["signing"] = signing
    checks["verified"] = all(v is True for k, v in checks.items() if isinstance(v, bool))
    subject = (stmt.get("subject") or [{}])[0]
    return {"id": bundle_id, "subject": subject, **checks}


def rerun(
    store: Any,
    bundle_id: str,
    key: Path | None,
    tsa: str | None = TSA_URL,
    identity: bool = False,
    publish: str | None = None,
) -> dict[str, Any]:
    first = read_bundle(store, bundle_id)
    stmt = first["statement"]
    pred = stmt["predicate"]
    exp = pred.get("experiment")
    if not exp:
        raise RunError("bundle has no experiment to rerun")
    artifact = stmt["subject"][0]["name"]
    commit = stmt["subject"][0]["digest"].get("gitCommit")
    entry = {
        "id": pred.get("corpus_entry"),
        "run": {"command": exp["command"], "outputs": [o["path"] for o in exp["outputs"]]},
        "claims": [
            {k: v for k, v in c.items() if k not in ("measured", "verdict", "reason")} for c in pred.get("claims") or []
        ],
    }
    new = execute(artifact, commit, key, entry, store, rerun_of=first, tsa=tsa, identity=identity, publish=publish)
    new_pred = new["statement"]["predicate"]
    comparison = new_pred["reruns"]
    return {
        "id": new["id"],
        "rerun_of": bundle_id,
        "exit_code": new_pred["experiment"]["exit_code"],
        "verdict": new_pred.get("verdict"),
        "outputs": comparison["outputs"],
        "claims": comparison["claims"],
        "drift": comparison["drift"],
    }
