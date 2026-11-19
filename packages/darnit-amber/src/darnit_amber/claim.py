"""``darnit-amber claim``: attach a paper claim to a stored run and measure it from the stored outputs."""

from __future__ import annotations

import copy
import hashlib
from pathlib import Path
from typing import Any

from .rerun import read_bundle
from .run import (
    TSA_URL,
    RunError,
    _canonical,
    _claims,
    _store_bundle,
    default_key,
    key_fingerprint,
    measure_claim,
    overall_verdict,
    read_blob,
    read_output,
    safe_rel,
    sign_statement,
    write_blob,
)


def claim(
    store: Any, bundle_id: str, spec: dict[str, Any], key: Path | None = None, tsa: str | None = TSA_URL
) -> dict[str, Any]:
    """A new bundle derived from ``bundle_id`` with ``spec`` measured against its stored outputs.

    The derived statement is signed by whoever makes the claim (``key``, default
    the generated one) and recorded under ``claim_signer``; the Witness
    envelopes and their signer are the first bundle's, unchanged.
    """
    first = read_bundle(store, bundle_id)
    new = copy.deepcopy(first)
    pred = new["statement"]["predicate"]
    exp = pred.get("experiment")
    if not exp:
        raise RunError("bundle has no experiment")
    path = safe_rel(str((spec.get("measure") or {}).get("file") or ""))
    data = read_output(store, first, path)  # raises unless stored and matching the statement's digest
    c = _claims({"claims": [spec]})[0]
    measure_claim(c, lambda p: data if p == path else None)
    c["matches_expected"] = (c["verdict"] == c["expected_verdict"]) if c.get("expected_verdict") else None
    # Which signer stands behind each claim: the run's claims were in the statement the run's signer
    # signed (``signing``); this one is in the statement this claimer signs (``claim_signer``). A claim an
    # earlier claimer made keeps that claimer: ``prior_claimer`` with the signer it had and the bundle it
    # was signed in, since ``claim_signer`` now names someone else (review, Nov 13: Alice's claim pointed
    # at Bob). Only this claimer signs this statement, so every earlier claim is carried over on the
    # claimer's word; the bundles with the original signatures stay in the store along ``derived_from``.
    prior = pred.get("claim_signer")
    for x in pred.get("claims") or []:
        if x.get("signed_by") == "claim_signer" and prior:
            x["signed_by"] = "prior_claimer"
            x["signer"] = dict(prior)
            x["signed_in"] = bundle_id
        else:
            x.setdefault("signed_by", "signing")
    c["signed_by"] = "claim_signer"
    c.pop("signer", None)
    c.pop("signed_in", None)
    pred["claims"] = [x for x in pred.get("claims") or [] if x["id"] != c["id"]] + [c]
    pred["verdict"] = overall_verdict(pred["claims"])
    pred["derived_from"] = bundle_id
    key = key or default_key()
    pred["claim_signer"] = {"method": "key", "key_fingerprint": key_fingerprint(key), "timestamp_authority": tsa}
    new["id"] = hashlib.sha256(_canonical(new["statement"])).hexdigest()
    new["statement_envelope"] = sign_statement(new["statement"], key, tsa)
    new["publication"] = None
    _store_bundle(store, new)
    for o in exp["outputs"]:
        if o.get("stored"):
            write_blob(store, new["id"], o["path"], read_output(store, first, o["path"]))  # checked, not copied blind
    # The two Witness-hashed records travel with the run they belong to; verify reads them back by digest.
    for record in (exp.get("exit_status"), (pred.get("audit") or {}).get("report")):
        if record:
            data = read_blob(store, bundle_id, record["path"])
            if hashlib.sha256(data).hexdigest() != record["sha256"]:
                raise RunError(f"{record['path']} of {bundle_id} is not what its statement says; refusing to derive")
            write_blob(store, new["id"], record["path"], data)
    return {"id": new["id"], "derived_from": bundle_id, "verdict": pred["verdict"], "claim": c}
