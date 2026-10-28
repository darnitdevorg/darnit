"""``darnit-amber verify`` and ``darnit-amber rerun`` (issue #677, steps C and D)."""

from __future__ import annotations

import base64
import hashlib
import json
from pathlib import Path
from typing import Any

from .run import RunError, _canonical, execute


def read_bundle(store: Any, bundle_id: str) -> dict[str, Any]:
    if hasattr(store, "read"):
        raw = store.read(bundle_id)
    else:  # local-fs store: files under its root
        root = Path(store._root)
        raw = (root / f"{bundle_id}.intoto.json").read_bytes()
    return json.loads(raw)


def _pae(payload_type: str, payload: bytes) -> bytes:
    return b"DSSEv1 %d %s %d " % (len(payload_type), payload_type.encode(), len(payload)) + payload


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
    checks["verified"] = all(v is True for k, v in checks.items() if isinstance(v, bool))
    return {"id": bundle_id, "subject": stmt["subject"][0], **checks}


def rerun(store: Any, bundle_id: str, key: Path) -> dict[str, Any]:
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
    }
    new = execute(artifact, commit, key, entry, store, rerun_of=bundle_id)
    mine = {o["path"]: o["sha256"] for o in new["statement"]["predicate"]["experiment"]["outputs"]}
    comparison = [
        {
            "path": o["path"],
            "first": o["sha256"],
            "rerun": mine.get(o["path"]),
            "result": "identical" if mine.get(o["path"]) == o["sha256"] else "changed",
        }
        for o in exp["outputs"]
    ]
    new["statement"]["predicate"]["reruns"] = {"of": bundle_id, "outputs": comparison}
    # the id covers the comparison too: recompute and store
    new["id"] = hashlib.sha256(_canonical(new["statement"])).hexdigest()
    store.write(new["id"], _canonical(new), "application/vnd.in-toto+json")
    return {
        "id": new["id"],
        "rerun_of": bundle_id,
        "exit_code": new["statement"]["predicate"]["experiment"]["exit_code"],
        "outputs": comparison,
        "drift": any(c["result"] == "changed" for c in comparison),
    }
