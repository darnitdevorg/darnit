"""Console script ``darnit-amber``."""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .run import RunError, run


def main(argv: list[str] | None = None) -> int:
    p = argparse.ArgumentParser(prog="darnit-amber", description="Amber reproducibility runs")
    sub = p.add_subparsers(dest="cmd", required=True)
    r = sub.add_parser("run", help="run the Amber audit on an artifact under Witness and write a run bundle")
    r.add_argument("artifact", help="local path or git URL of the artifact")
    r.add_argument("--ref", help="branch or tag to clone (URL artifacts only)")
    r.add_argument("--key", type=Path, required=True, help="signing key for witness (Sigstore keyless comes later)")
    r.add_argument("--claims", type=Path, help="corpus claims file (yaml or json)")
    r.add_argument("--out", type=Path, default=Path("amber-runs"), help="local store directory")
    a = p.parse_args(argv)

    try:
        bundle = run(a.artifact, a.ref, a.key, a.claims, a.out)
    except RunError as e:
        print(f"darnit-amber: {e}", file=sys.stderr)
        return 1
    pred = bundle["statement"]["predicate"]
    statuses: dict[str, int] = {}
    for x in pred["audit"]["results"]:
        statuses[x["status"]] = statuses.get(x["status"], 0) + 1
    print(
        json.dumps(
            {
                "id": bundle["id"],
                "subject": bundle["statement"]["subject"][0],
                "audit": statuses,
                "claims": len(pred["claims"]),
                "outputs": len(pred["outputs"]),
            },
            indent=2,
        )
    )
    return 0


if __name__ == "__main__":
    sys.exit(main())
