"""Console script ``darnit-amber``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .claim import claim
from .publish import REKOR_URL
from .rerun import rerun, verify
from .run import TSA_URL, RunError, run


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
    r.add_argument("--key", type=Path, help="signing key (PEM); default: a key generated once under darnit's data dir")
    r.add_argument(
        "--identity",
        action="store_true",
        help="sign with a Sigstore certificate from a login instead of a key (the identity becomes public)",
    )
    r.add_argument(
        "--publish",
        action="store_true",
        help="record the signed envelopes in Rekor, Sigstore's public log (the envelope and signer become public)",
    )
    r.add_argument("--rekor", default=REKOR_URL, help=f"Rekor instance for --publish (default: {REKOR_URL})")
    r.add_argument("--tsa", default=TSA_URL, help="RFC 3161 timestamp authority (default: Sigstore's)")
    r.add_argument("--no-timestamp", action="store_true", help="do not countersign with a timestamp authority")
    r.add_argument("--claims", type=Path, help="corpus entry (yaml or json): claims and run.command")
    r.add_argument("--store", choices=["local-fs", "s3"], default="local-fs", help="attestation store backend")
    r.add_argument("--out", type=Path, default=Path("amber-runs"), help="local-fs: store directory")
    r.add_argument("--bucket", help="s3: bucket name")
    r.add_argument("--prefix", default="amber/runs", help="s3: key prefix")
    r.add_argument("--endpoint-url", help="s3: endpoint for S3-compatible services")
    for name, help_ in (
        ("verify", "check a stored bundle: id, outputs vs Witness products, signatures, timestamps, identity"),
        ("rerun", "re-execute a stored bundle's experiment and compare outputs"),
        ("claim", "attach a paper claim to a stored run, measured from its stored outputs"),
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
            q.add_argument("--offline", action="store_true", help="do not re-fetch published entries from Rekor")
        elif name == "rerun":
            q.add_argument("--key", type=Path, help="signing key for this rerun (default: the generated one)")
            q.add_argument("--identity", action="store_true")
            q.add_argument("--publish", action="store_true")
            q.add_argument("--rekor", default=REKOR_URL)
            q.add_argument("--tsa", default=TSA_URL)
            q.add_argument("--no-timestamp", action="store_true")
        else:
            q.add_argument("--id", required=True, help="claim id, e.g. figure6a-queries-per-sec")
            q.add_argument("--file", required=True, help="output file of the run holding the value")
            q.add_argument("--regex", required=True, help="regex over that file; group 1 is the value")
            q.add_argument("--threshold", help="the paper's number, e.g. '>= 70' or '== falsified'")
            q.add_argument("--tolerance", type=float)
            q.add_argument("--scale", type=float, help="multiply the value, e.g. 100 for a fraction in percent")
            q.add_argument("--unit")
            q.add_argument("--source", help="where the threshold comes from, e.g. 'Table 3, row 2'")
            q.add_argument("--expected", choices=["REPRODUCED", "NOT_REPRODUCED", "NOT_COMPARABLE"])
            q.add_argument("--not-comparable", metavar="REASON", help="record the value but do not judge it")
    argv = sys.argv[1:] if argv is None else list(argv)
    command: list[str] = []
    if "--" in argv:
        i = argv.index("--")
        argv, command = argv[:i], argv[i + 1 :]
    a = p.parse_args(argv)

    if a.cmd in ("verify", "rerun", "claim"):
        try:
            store = _make_store(a)
            if a.cmd == "verify":
                result = verify(store, a.bundle_id, a.pubkey, online=not a.offline)
            elif a.cmd == "rerun":
                result = rerun(
                    store,
                    a.bundle_id,
                    a.key,
                    None if a.no_timestamp else a.tsa,
                    a.identity,
                    a.rekor if a.publish else None,
                )
            else:
                spec = {
                    "id": a.id,
                    "threshold": a.threshold,
                    "tolerance": a.tolerance,
                    "unit": a.unit,
                    "source": a.source,
                    "expected_verdict": a.expected,
                    "measure": {
                        "file": a.file,
                        "regex": a.regex,
                        "scale": a.scale,
                        "comparable": False if a.not_comparable else None,
                        "reason": a.not_comparable,
                    },
                }
                result = claim(store, a.bundle_id, spec)
        except (RunError, FileNotFoundError, KeyError) as e:
            print(f"darnit-amber: {e}", file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2))
        return 0 if result.get("verified", not result.get("drift")) else 2

    try:
        store = _make_store(a)
        if command and a.cmd != "run":
            raise RunError("a command after -- only makes sense with run")
        if a.identity and a.key:
            raise RunError("--identity and --key are alternatives")
        bundle = run(
            a.artifact,
            a.ref,
            a.key,
            a.claims,
            store,
            command or None,
            None if a.no_timestamp else a.tsa,
            a.identity,
            a.rekor if a.publish else None,
        )
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
        "signing": pred.get("signing"),
        "publication": {
            n: {"log": p["log"], "log_index": p["log_index"]} for n, p in (pred.get("publication") or {}).items()
        }
        or None,
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
