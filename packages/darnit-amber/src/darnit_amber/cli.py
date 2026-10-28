"""Console script ``darnit-amber``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .rerun import rerun, verify
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
    r = sub.add_parser(
        "run",
        help="run the Amber audit and the experiment under Witness; write a run bundle",
        epilog="darnit-amber run --key k.pem -- ./run_experiment.sh   (inside the artifact checkout; outputs are inferred)",
    )
    r.add_argument("artifact", nargs="?", default=".", help="local path or git URL of the artifact (default: .)")
    r.add_argument("--ref", help="commit, branch or tag to check out (URL artifacts only)")
    r.add_argument("--key", type=Path, required=True, help="signing key for witness (Sigstore keyless comes later)")
    r.add_argument("--claims", type=Path, help="corpus entry (yaml or json): claims and run.command")
    r.add_argument("--store", choices=["local-fs", "s3"], default="local-fs", help="attestation store backend")
    r.add_argument("--out", type=Path, default=Path("amber-runs"), help="local-fs: store directory")
    r.add_argument("--bucket", help="s3: bucket name")
    r.add_argument("--prefix", default="amber/runs", help="s3: key prefix")
    r.add_argument("--endpoint-url", help="s3: endpoint for S3-compatible services")
    for name, help_ in (
        ("verify", "check a stored bundle: id, outputs vs Witness products, signatures"),
        ("rerun", "re-execute a stored bundle's experiment and compare outputs"),
    ):
        q = sub.add_parser(name, help=help_)
        q.add_argument("bundle_id")
        q.add_argument("--store", choices=["local-fs", "s3"], default="local-fs")
        q.add_argument("--out", type=Path, default=Path("amber-runs"))
        q.add_argument("--bucket")
        q.add_argument("--prefix", default="amber/runs")
        q.add_argument("--endpoint-url")
        if name == "verify":
            q.add_argument("--pubkey", type=Path, help="PEM public key of the Witness signer")
        else:
            q.add_argument("--key", type=Path, required=True, help="signing key for this rerun")
    argv = sys.argv[1:] if argv is None else list(argv)
    command: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, command = argv[:i], argv[i + 1 :]
    a = p.parse_args(argv)

    if a.cmd in ("verify", "rerun"):
        try:
            store = _make_store(a)
            result = verify(store, a.bundle_id, a.pubkey) if a.cmd == "verify" else rerun(store, a.bundle_id, a.key)
        except (RunError, FileNotFoundError, KeyError) as e:
            print(f"darnit-amber: {e}", file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2))
        return 0 if result.get("verified", not result.get("drift")) else 2

    try:
        store = _make_store(a)
        if command and a.cmd != "run":
            raise RunError("a command after -- only makes sense with run")
        bundle = run(a.artifact, a.ref, a.key, a.claims, store, command or None)
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
        "verdict": pred.get("verdict"),
        "claims": [
            {
                k: x.get(k)
                for k in ("id", "measured", "threshold", "verdict", "expected_verdict", "matches_expected", "reason")
            }
            for x in pred["claims"]
        ],
        "experiment": {"exit_code": exp.get("exit_code"), "outputs": exp.get("outputs")} if exp else None,
    }
    print(json.dumps(summary, indent=2))
    return 0


if __name__ == "__main__":
    sys.exit(main())
