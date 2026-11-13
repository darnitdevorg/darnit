"""Console script ``darnit-amber``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from darnit.stores.errors import StoreError

from .claim import claim
from .rerun import rerun, verify
from .run import TSA_URL, RunError, default_store, run

# What a bad entry, a bad regex, a missing file or a store problem raise: reported, not traced back.
_REPORTED = (RunError, StoreError, OSError, KeyError, ValueError, TypeError)


def _make_store(a: argparse.Namespace):  # noqa: ANN202
    from darnit.stores.defaults.local_fs import LocalFsAttestationStore

    out = a.out or default_store()
    out.mkdir(parents=True, exist_ok=True)
    return LocalFsAttestationStore(root=out)


def _add_verify_args(q: argparse.ArgumentParser) -> None:
    q.add_argument("--pubkey", type=Path, help="PEM public key the bundle must be signed with")
    q.add_argument("--claimer-pubkey", type=Path, help="for a bundle derived by claim: the claimer's PEM public key")


def _consent(yes: bool):  # noqa: ANN202
    def ask(command: str) -> bool:
        print(f"rerun will execute, on this machine, with your environment:\n  {command}", file=sys.stderr)
        if yes:
            return True
        if not sys.stdin.isatty():
            print("pass --yes to confirm (stdin is not a terminal)", file=sys.stderr)
            return False
        # The prompt goes to stderr like the rest of the dialogue: stdout carries only the JSON report.
        print("run it? [y/N] ", end="", file=sys.stderr, flush=True)
        return sys.stdin.readline().strip().lower() in ("y", "yes")

    return ask


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
    r.add_argument("--tsa", default=TSA_URL, help="RFC 3161 timestamp authority (default: Sigstore's)")
    r.add_argument("--no-timestamp", action="store_true", help="do not countersign with a timestamp authority")
    r.add_argument("--claims", type=Path, help="corpus entry (yaml or json): claims and run.command")
    r.add_argument(
        "--allow-dirty",
        action="store_true",
        help="run on a checkout with uncommitted changes; the bundle then records no commit and cannot be rerun",
    )
    r.add_argument(
        "--out", type=Path, default=None, help=f"store directory (default: {default_store()}, never the checkout)"
    )
    for name, help_ in (
        ("verify", "check a stored bundle: id, statement signature, outputs vs Witness, timestamps, signer"),
        ("rerun", "verify a stored bundle, then re-execute its experiment and compare outputs"),
        ("claim", "attach a paper claim to a stored run, measured from its stored outputs"),
    ):
        q = sub.add_parser(name, help=help_)
        q.add_argument("bundle_id")
        q.add_argument("--out", type=Path, default=None)
        if name == "verify":
            _add_verify_args(q)
        elif name == "rerun":
            _add_verify_args(q)
            q.add_argument("--yes", action="store_true", help="execute the bundle's command without asking")
            q.add_argument(
                "--artifact", help="path or URL to clone when the bundle names a local artifact (local/<name>)"
            )
            q.add_argument("--key", type=Path, help="signing key for this rerun (default: the generated one)")
            q.add_argument("--tsa", default=TSA_URL)
            q.add_argument("--no-timestamp", action="store_true")
        else:
            q.add_argument("--id", required=True, help="claim id, e.g. figure6a-queries-per-sec")
            q.add_argument("--file", required=True, help="output file of the run holding the value")
            q.add_argument("--regex", required=True, help="regex over that file; group 1 is the value")
            q.add_argument("--threshold", help="the paper's number, e.g. '>= 70' or '== falsified'")
            q.add_argument("--tolerance", help="a finite decimal >= 0; kept as written, never rounded through a float")
            q.add_argument("--scale", help="multiply the value, e.g. 100 for a fraction in percent (a decimal)")
            q.add_argument("--unit")
            q.add_argument("--source", help="where the threshold comes from, e.g. 'Table 3, row 2'")
            q.add_argument("--expected", choices=["REPRODUCED", "NOT_REPRODUCED", "NOT_COMPARABLE"])
            q.add_argument("--not-comparable", metavar="REASON", help="record the value but do not judge it")
            q.add_argument("--key", type=Path, help="key that signs the derived bundle (default: the generated one)")
            q.add_argument("--tsa", default=TSA_URL)
            q.add_argument("--no-timestamp", action="store_true")
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
                result = verify(store, a.bundle_id, a.pubkey, claimer_pubkey=a.claimer_pubkey)
            elif a.cmd == "rerun":
                result = rerun(
                    store,
                    a.bundle_id,
                    a.key,
                    None if a.no_timestamp else a.tsa,
                    pubkey=a.pubkey,
                    consent=_consent(a.yes),
                    artifact=a.artifact,
                    claimer_pubkey=a.claimer_pubkey,
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
                result = claim(store, a.bundle_id, spec, a.key, None if a.no_timestamp else a.tsa)
        except _REPORTED as e:
            print(f"darnit-amber: {e}", file=sys.stderr)
            return 1
        print(json.dumps(result, indent=2))
        return 0 if result.get("verified", not result.get("drift")) else 2

    try:
        store = _make_store(a)
        if command and a.cmd != "run":
            raise RunError("a command after -- only makes sense with run")
        bundle = run(
            a.artifact,
            a.ref,
            a.key,
            a.claims,
            store,
            command or None,
            None if a.no_timestamp else a.tsa,
            a.allow_dirty,
        )
    except _REPORTED as e:
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
