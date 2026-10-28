"""Console script ``darnit-amber``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .run import RunError, run


def _make_store(a: argparse.Namespace):  # noqa: ANN202
    if a.store == "s3":
        if not a.bucket:
            raise RunError("--bucket is required with --store s3")
        from .s3_store import S3AttestationStore

        return S3AttestationStore(bucket=a.bucket, prefix=a.prefix, endpoint_url=a.endpoint_url)
    from darnit.stores.defaults.local_fs import LocalFsAttestationStore

    a.out.mkdir(parents=True, exist_ok=True)
    return LocalFsAttestationStore(root=a.out)


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="darnit-amber", description="Amber reproducibility runs")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the Amber audit and the corpus experiment under Witness; write a run bundle")
    r.add_argument("artifact", help="local path or git URL of the artifact")
    r.add_argument("--ref", help="commit, branch or tag to check out (URL artifacts only)")
    r.add_argument("--key", type=Path, required=True, help="signing key for witness (Sigstore keyless comes later)")
    r.add_argument("--claims", type=Path, help="corpus entry (yaml or json): claims and run.command")
    r.add_argument("--store", choices=["local-fs", "s3"], default="local-fs", help="attestation store backend")
    r.add_argument("--out", type=Path, default=Path("amber-runs"), help="local-fs: store directory")
    r.add_argument("--bucket", help="s3: bucket name")
    r.add_argument("--prefix", default="amber/runs", help="s3: key prefix")
    r.add_argument("--endpoint-url", help="s3: endpoint for S3-compatible services")
    a = p.parse_args(argv)

    try:
        store = _make_store(a)
        bundle = run(a.artifact, a.ref, a.key, a.claims, store)
    except RunError as e:
        print(f"darnit-amber: {e}", file=sys.stderr)
        return 1
    pred = bundle["statement"]["predicate"]
    statuses: dict[str, int] = {}
    for x in pred["audit"]["results"]:
        statuses[x["status"]] = statuses.get(x["status"], 0) + 1
    exp = pred.get("experiment") or {}
    summary = {
        "id": bundle["id"],
        "subject": bundle["statement"]["subject"][0],
        "corpus_entry": pred.get("corpus_entry"),
        "audit": statuses,
        "claims": len(pred["claims"]),
        "experiment": {"exit_code": exp.get("exit_code"), "outputs": exp.get("outputs")} if exp else None,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
