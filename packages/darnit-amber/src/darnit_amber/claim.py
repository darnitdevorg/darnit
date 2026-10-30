"""``darnit-amber claim``: attach a paper claim to a stored run and measure it from the stored outputs."""

from __future__ import annotations

import copy
import hashlib
import tempfile
from pathlib import Path
from typing import Any

from .rerun import read_bundle
from .run import RunError, _canonical, _claims, measure_claim, overall_verdict, read_blob, write_blob


def claim(store: Any, bundle_id: str, spec: dict[str, Any]) -> dict[str, Any]:
    """A new bundle derived from ``bundle_id`` with ``spec`` measured against its stored outputs."""
    first = read_bundle(store, bundle_id)
    new = copy.deepcopy(first)
    pred = new["statement"]["predicate"]
    exp = pred.get("experiment")
    if not exp:
        raise RunError("bundle has no experiment")
    path = spec["measure"]["file"]
    out = next((o for o in exp["outputs"] if o["path"] == path), None)
    if out is None:
        raise RunError(f"{path} is not an output of this run; outputs: {[o['path'] for o in exp['outputs']]}")
    if not out.get("stored"):
        raise RunError(f"{path} was not stored with the bundle (too large or not captured)")
    c = _claims({"claims": [spec]})[0]
    with tempfile.TemporaryDirectory(prefix="amber-claim-") as tmp:
        f = Path(tmp) / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_bytes(read_blob(store, bundle_id, path))
        measure_claim(c, Path(tmp))
    c["matches_expected"] = (c["verdict"] == c["expected_verdict"]) if c.get("expected_verdict") else None
    pred["claims"] = [x for x in pred.get("claims") or [] if x["id"] != c["id"]] + [c]
    pred["verdict"] = overall_verdict(pred["claims"])
    pred["derived_from"] = bundle_id
    new["id"] = hashlib.sha256(_canonical(new["statement"])).hexdigest()
    store.write(new["id"], _canonical(new), "application/vnd.in-toto+json")
    for o in exp["outputs"]:
        if o.get("stored"):
            write_blob(store, new["id"], o["path"], read_blob(store, bundle_id, o["path"]))
    return {"id": new["id"], "derived_from": bundle_id, "verdict": pred["verdict"], "claim": c}
