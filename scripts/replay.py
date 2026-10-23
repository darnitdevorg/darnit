#!/usr/bin/env python3
"""Replay audit -> confirm -> remediate -> audit on a reference repository, with no model.

Usage: scripts/replay.py <clone_url> <commit> <answers.json> [--expected expected.json] [--record expected.json]

Clones the repository at the commit, audits it, confirms project data from the
answer file, remediates with every planned digest approved under a repository
name that does not exist (so no platform write can land), audits again, and
prints PASS before and after with the remediation outcome counts. File
remediations are applied to the clone and never pushed. HOME and the XDG
directories are redirected to a scratch directory, so nothing reaches the
operator's own configuration; GH_TOKEN, if set, is passed through for the
platform reads of the audits.

With --expected it fails when PASS after, or fixed, is below the recorded value
(a PR that lowers either must update the file). With --record it writes the
file. See #655 (Phase 0.1 and 0.2) and #639.
"""

from __future__ import annotations

import argparse
import json
import os
import re
import subprocess
import sys
import tempfile
from collections import Counter
from pathlib import Path

NONEXISTENT_OWNER = "darnit-replay-nonexistent"


def _owner_repo(clone_url: str) -> tuple[str, str]:
    m = re.search(r"[:/]([^/:]+)/([^/]+?)(?:\.git)?/?$", clone_url)
    if not m:
        sys.exit(f"cannot read owner/repo from {clone_url}")
    return m.group(1), m.group(2)


def _audit(path: str, owner: str, repo: str) -> dict[str, str]:
    from darnit_baseline.tools import audit_openssf_baseline

    data = json.loads(audit_openssf_baseline(local_path=path, owner=owner, repo=repo, output_format="json"))
    return {r["id"]: r["status"] for r in data["results"]}


def _outcomes(report: str) -> dict[str, int]:
    return {k: int(v) for k, v in re.findall(r"\| (\w+) \| (\d+) \|", report)}


def replay(clone_url: str, commit: str, answers: dict, work: Path) -> dict:
    from darnit_baseline.tools import confirm_project_data, remediate_audit_findings

    owner, repo = _owner_repo(clone_url)
    clone = work / "repo"
    subprocess.run(["git", "clone", "-q", clone_url, str(clone)], check=True)
    subprocess.run(["git", "-C", str(clone), "checkout", "-q", commit], check=True)
    path = str(clone)

    before = _audit(path, owner, repo)
    confirm_project_data(local_path=path, owner=NONEXISTENT_OWNER, repo=repo, **answers)
    preview = remediate_audit_findings(local_path=path, owner=NONEXISTENT_OWNER, repo=repo, dry_run=True)
    digests = sorted(set(re.findall(r"\b[0-9a-f]{64}\b", preview)))
    applied = remediate_audit_findings(local_path=path, owner=NONEXISTENT_OWNER, repo=repo, dry_run=False, approve=digests)
    after = _audit(path, owner, repo)
    planned = re.search(r"Would Apply \((\d+) remediations?\)", preview)

    counts = lambda m: dict(sorted(Counter(m.values()).items()))  # noqa: E731
    return {
        "repository": f"{owner}/{repo}",
        "commit": commit,
        "before": counts(before),
        "after": counts(after),
        "remediation": _outcomes(applied) | {"planned": int(planned.group(1)) if planned else 0},
        "changed": {k: f"{before[k]}->{after.get(k)}" for k in sorted(before) if before[k] != after.get(k)},
        "controls_after": dict(sorted(after.items())),
    }


def main() -> int:
    p = argparse.ArgumentParser(description=__doc__.split("\n")[0])
    p.add_argument("clone_url")
    p.add_argument("commit")
    p.add_argument("answers", type=Path)
    p.add_argument("--expected", type=Path)
    p.add_argument("--record", type=Path)
    p.add_argument("--output", type=Path, help="write the full result here (for recording from CI)")
    args = p.parse_args()

    with tempfile.TemporaryDirectory() as tmp:
        home = Path(tmp) / "home"
        home.mkdir()
        os.environ.update({"HOME": str(home), "XDG_CONFIG_HOME": str(home / "cfg"), "XDG_DATA_HOME": str(home / "data")})
        result = replay(args.clone_url, args.commit, json.loads(args.answers.read_text()), Path(tmp))

    print(json.dumps({k: v for k, v in result.items() if k != "controls_after"}, indent=2))
    passes = (result["before"].get("PASS", 0), result["after"].get("PASS", 0))
    print(f"PASS {passes[0]} -> {passes[1]}, fixed {result['remediation'].get('fixed', 0)}")

    if args.output:
        args.output.write_text(json.dumps(result, indent=2) + "\n")
    if args.record:
        args.record.write_text(json.dumps(result, indent=2) + "\n")
        print(f"recorded {args.record}")
    if args.expected:
        exp = json.loads(args.expected.read_text())
        failures = []
        for name, got, want in (
            ("PASS after", passes[1], exp["after"].get("PASS", 0)),
            ("fixed", result["remediation"].get("fixed", 0), exp["remediation"].get("fixed", 0)),
        ):
            if got < want:
                failures.append(f"{name}: {got} < recorded {want}")
        if result["remediation"].get("planned") != exp["remediation"].get("planned"):
            print(f"planned remediations: {result['remediation'].get('planned')} (recorded {exp['remediation'].get('planned')}); not gated, it varies with platform reads")
        moved = {k: (exp["controls_after"].get(k), v) for k, v in result["controls_after"].items() if exp["controls_after"].get(k) != v}
        if moved:
            print("controls whose final status differs from the record:", moved)
        if failures:
            print("REGRESSION: " + "; ".join(failures) + f". If intended, re-run with --record {args.expected}.")
            return 1
        print("matches the recorded expectations")
    return 0


if __name__ == "__main__":
    sys.exit(main())
