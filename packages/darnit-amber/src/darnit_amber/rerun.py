"""``darnit-amber verify`` and ``darnit-amber rerun`` (issue #677, steps C and D)."""

from __future__ import annotations

import base64
import hashlib
import json
from collections.abc import Callable
from datetime import datetime
from pathlib import Path
from typing import Any

from .identity import pae as _pae
from .identity import signature_chain, verify_identity_signature, verify_with
from .publish import verify_publication
from .run import STATEMENT_TYPE, TSA_URL, RunError, _canonical, _is_url, execute, read_blob, wrap_command


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


def _every_signature_timestamped(env: dict[str, Any], stamps: list[dict[str, Any]]) -> bool:
    """Each signature on the envelope has a trusted timestamp covering it; none is enough for an envelope with no signature."""
    signatures = env.get("signatures") or []
    return bool(signatures) and all(_trusted_time(stamps, i) is not None for i in range(len(signatures)))


def _load_pubkey(pubkey: Path) -> Any:
    from cryptography.hazmat.primitives import serialization

    return serialization.load_pem_public_key(pubkey.read_bytes())


def _spki_der(key: Any) -> bytes:
    from cryptography.hazmat.primitives import serialization

    return key.public_bytes(serialization.Encoding.DER, serialization.PublicFormat.SubjectPublicKeyInfo)


def _key_fingerprint(pubkey: Path) -> str:
    return "sha256:" + hashlib.sha256(_spki_der(_load_pubkey(pubkey))).hexdigest()


class _Expected:
    """What the caller says the signer is: a public key, or a Fulcio identity and issuer."""

    def __init__(self, pubkey: Path | None, identity: str | None, issuer: str | None) -> None:
        self.pubkey = pubkey
        self.key = _load_pubkey(pubkey) if pubkey else None
        self.identity = identity
        self.issuer = issuer


def _check_envelope(
    env: dict[str, Any], stamps: list[dict[str, Any]], signer: dict[str, Any], expected: _Expected
) -> dict[str, Any]:
    """One DSSE envelope against the signer the statement names and the signer the caller expects.

    ``ok`` requires: a signature that verifies (with ``--pubkey`` for a
    key-signed envelope, with its certificate for a Fulcio one), the
    statement's own description of the signer to match it (key fingerprint,
    or identity and issuer and, where recorded, the certificate digest), and
    the caller's expectation to match it: ``--pubkey`` must be the signing
    key, also when the envelope carries a certificate; an identity-signed
    envelope needs ``--expect-identity`` and ``--expect-issuer``.
    """
    result: dict[str, Any] = {"method": signer.get("method"), "signature": None, "ok": False}
    signatures = env.get("signatures") or []
    try:
        payload = base64.b64decode(env["payload"])
        data = _pae(env["payloadType"], payload)
    except Exception as e:  # noqa: BLE001
        result["signature"] = f"invalid envelope: {type(e).__name__}"
        return result
    cert_sigs = [(i, s) for i, s in enumerate(signatures) if s.get("certificate")]
    if signer.get("method") == "key":
        if cert_sigs:
            result["signature"] = "the statement says key-signed, the envelope carries a certificate"
            return result
        if expected.key is None:
            result["signature"] = "not checked: key-signed and no --pubkey"
            return result
        if _key_fingerprint(expected.pubkey) != signer.get("key_fingerprint"):  # type: ignore[arg-type]
            result["signature"] = "--pubkey is not the key the statement names"
            return result
        for sig in signatures:
            try:
                verify_with(expected.key, base64.b64decode(sig["sig"]), data)
                result["signature"] = "ok"
                result["ok"] = True
                return result
            except Exception:  # noqa: BLE001 - try the next signature
                continue
        result["signature"] = "no signature verifies with --pubkey"
        return result
    if signer.get("method") != "identity":
        result["signature"] = f"unknown signing method {signer.get('method')!r}"
        return result
    if not cert_sigs:
        result["signature"] = "the statement says identity-signed, the envelope carries no certificate"
        return result
    index, sig = cert_sigs[0]
    who = verify_identity_signature(env, sig, _trusted_time(stamps, index), _trusted_root().get_fulcio_certs())
    result.update(who)
    if not who["ok"]:
        return result
    leaf = signature_chain(sig)[0]
    problems = []
    if who["subject"] != signer.get("identity") or who["issuer"] != signer.get("issuer"):
        problems.append("the certificate names a different identity or issuer than the statement")
    recorded = signer.get("certificate_sha256")
    if recorded and who["certificate_sha256"] != recorded:
        problems.append("the certificate is not the one the statement names")
    if expected.key is not None and _spki_der(expected.key) != _spki_der(leaf.public_key()):
        problems.append("--pubkey is not the key in the certificate")
    if expected.identity is None or expected.issuer is None:
        problems.append("no expected identity: pass --expect-identity and --expect-issuer")
    elif who["subject"] != expected.identity or who["issuer"] != expected.issuer:
        problems.append(f"the certificate names {who['subject']} from {who['issuer']}, not the expected identity")
    result["signature"] = "ok" if not problems else "; ".join(problems)
    result["ok"] = not problems
    return result


def _statement_signer(pred: dict[str, Any]) -> dict[str, Any]:
    """Who signed the statement: the claimer of a derived bundle, else the run's signer."""
    return pred.get("claim_signer") or pred.get("signing") or {}


def _witness_signer(signing: dict[str, Any], name: str) -> dict[str, Any]:
    out = {k: v for k, v in signing.items() if k != "certificates_sha256"}
    cert = (signing.get("certificates_sha256") or {}).get(name)
    if cert:
        out["certificate_sha256"] = cert
    return out


def verify(
    store: Any,
    bundle_id: str,
    pubkey: Path | None,
    online: bool = True,
    expect_identity: str | None = None,
    expect_issuer: str | None = None,
) -> dict[str, Any]:
    """Every check a bundle must pass; ``verified`` is true only when all of them do."""
    bundle = read_bundle(store, bundle_id)
    stmt = bundle["statement"]
    pred = stmt["predicate"]
    expected = _Expected(pubkey, expect_identity, expect_issuer)
    recomputed = hashlib.sha256(_canonical(stmt)).hexdigest()
    checks: dict[str, Any] = {"id_matches_statement": recomputed == bundle["id"] == bundle_id}
    envs = bundle.get("witness_envelopes") or {}
    stmt_env = bundle.get("statement_envelope") or {}

    # The statement is signed: the payload the researcher signed is the statement the id hashes.
    checks["statement_signed"] = bool(stmt_env) and stmt_env.get("payloadType") == STATEMENT_TYPE
    try:
        checks["statement_signed"] = checks["statement_signed"] and base64.b64decode(stmt_env["payload"]) == _canonical(
            stmt
        )
    except Exception:  # noqa: BLE001
        checks["statement_signed"] = False

    # The statement names every envelope by digest: a bundle cannot drop or swap one.
    expected_envs = pred.get("witness_envelopes_sha256") or {}
    checks["envelopes_match_statement"] = (
        bool(expected_envs)
        and set(expected_envs) == set(envs)
        and all(hashlib.sha256(_canonical(envs[name])).hexdigest() == digest for name, digest in expected_envs.items())
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
        cmd = run.get("cmd") or []
        checks["command_matches_witness"] = (
            bool(w) and len(cmd) == 4 and cmd[:3] == ["sh", "-c", wrap_command(exp["command"])]
        )
        # Stored outputs are what the statement says they are: a store can be written to by others.
        stored_ok = True
        for o in exp["outputs"]:
            if not o.get("stored"):
                continue
            try:
                stored_ok = (
                    stored_ok and hashlib.sha256(read_blob(store, bundle_id, o["path"])).hexdigest() == o["sha256"]
                )
            except Exception:  # noqa: BLE001 - missing or unreadable: not what the statement says
                stored_ok = False
        checks["stored_outputs_match"] = stored_ok

    signing = pred.get("signing") or {}
    all_envs = {"statement": stmt_env, **envs}
    checks["timestamps"] = {name: _timestamps(env) for name, env in all_envs.items()}
    checks["timestamps_trusted"] = bool(all_envs) and all(
        _every_signature_timestamped(env, checks["timestamps"][name]) for name, env in all_envs.items()
    )
    checks["signatures"] = {
        "statement": _check_envelope(stmt_env, checks["timestamps"]["statement"], _statement_signer(pred), expected),
        **{
            name: _check_envelope(env, checks["timestamps"][name], _witness_signer(signing, name), expected)
            for name, env in envs.items()
        },
    }
    checks["signatures_verified"] = bool(envs) and all(s["ok"] for s in checks["signatures"].values())

    publication = bundle.get("publication")
    if publication:
        checks["publication"] = {}
        for name, record in publication.items():
            try:
                checks["publication"][name] = verify_publication(all_envs[name], record, _trusted_root(), online=online)
            except Exception as e:  # noqa: BLE001 - reported, never fatal
                checks["publication"][name] = {"ok": False, "error": f"{type(e).__name__}: {e}"}
        checks["published"] = all(p.get("ok") for p in checks["publication"].values())
    checks["signing"] = signing
    if pred.get("claim_signer"):
        checks["claim_signer"] = pred["claim_signer"]
    checks["verified"] = all(v is True for k, v in checks.items() if isinstance(v, bool))
    subject = (stmt.get("subject") or [{}])[0]
    return {"id": bundle_id, "subject": subject, "verdict": pred.get("verdict"), **checks}


def failed_checks(report: dict[str, Any]) -> list[str]:
    return [k for k, v in report.items() if v is False and k != "verified"]


def rerun(
    store: Any,
    bundle_id: str,
    key: Path | None,
    tsa: str | None = TSA_URL,
    identity: bool = False,
    publish: str | None = None,
    pubkey: Path | None = None,
    expect_identity: str | None = None,
    expect_issuer: str | None = None,
    online: bool = True,
    consent: Callable[[str], bool] | None = None,
) -> dict[str, Any]:
    """Verify the bundle, get consent for its command, then run it again at the recorded commit in a fresh clone.

    The command runs on this machine with this user's environment (no
    container yet: darnit #677 step B), so nothing in it is executed before
    it verified and ``consent`` saw it.
    """
    report = verify(store, bundle_id, pubkey, online, expect_identity, expect_issuer)
    if not report["verified"]:
        raise RunError(
            f"bundle {bundle_id} does not verify ({', '.join(failed_checks(report))}); rerun executes nothing from it"
        )
    first = read_bundle(store, bundle_id)
    stmt = first["statement"]
    pred = stmt["predicate"]
    exp = pred.get("experiment")
    if not exp:
        raise RunError("bundle has no experiment to rerun")
    artifact = stmt["subject"][0]["name"]
    commit = stmt["subject"][0]["digest"].get("gitCommit")
    if not commit:
        raise RunError("bundle records no commit (run with --allow-dirty), so there is nothing to rerun at")
    if not _is_url(artifact) and not Path(artifact).is_dir():
        raise RunError(f"the bundle's artifact {artifact} is a local path that does not exist here")
    if consent is None or not consent(exp["command"]):
        raise RunError("rerun not confirmed")
    entry = {
        "id": pred.get("corpus_entry"),
        "run": {"command": exp["command"], "outputs": [o["path"] for o in exp["outputs"]]},
        "claims": [
            {k: v for k, v in c.items() if k not in ("measured", "verdict", "reason")} for c in pred.get("claims") or []
        ],
    }
    new = execute(
        artifact,
        commit,
        key,
        entry,
        store,
        rerun_of=first,
        tsa=tsa,
        identity=identity,
        publish=publish,
        clone_local=True,
    )
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
