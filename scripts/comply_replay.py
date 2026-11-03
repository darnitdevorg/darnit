#!/usr/bin/env python3
"""Replay the comply flow on reference repositories, with no model (#655, #639).

For each reference in scripts/comply_replay.toml: clone it at a fixed commit,
audit, confirm the recorded answers, plan and apply remediation, audit again,
and compare the PASS counts with scripts/comply_replay_expected.json. A count
below the recorded one fails the run, so a change that stops darnit fixing
things shows up before it merges.

Only reads reach GitHub. The run uses a throwaway HOME whose operator
configuration trusts the clone, and remediation names a repository identity
that does not exist, so any platform change it attempts is refused. File
changes land in the temporary clone, which is never pushed.

    uv run python scripts/comply_replay.py                 # every reference
    uv run python scripts/comply_replay.py wtf-frontend    # one reference
    uv run python scripts/comply_replay.py --record        # record the measured counts
    uv run python scripts/comply_replay.py --keep          # keep the clones and reports

The audits read the platform with GH_TOKEN, or `gh auth token` when it is unset.

Exit codes: 0 = no count dropped, 1 = a count dropped, 2 = a step failed.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import shutil
import subprocess
import sys
import tempfile
import time
import tomllib
from pathlib import Path

SCRIPTS = Path(__file__).resolve().parent
REFERENCES = SCRIPTS / "comply_replay.toml"
EXPECTED = SCRIPTS / "comply_replay_expected.json"
NOWHERE_OWNER = "darnit-replay-nonexistent"
COUNTED = ("pass_before", "pass_after")

# Runs in the throwaway HOME: confirm the answers, then plan and apply every
# planned remediation, approving each digest the plan shows.
REMEDIATE = r"""
import asyncio, inspect, json, re, sys
from darnit_baseline import tools

path, owner, repo, answers, out = sys.argv[1], sys.argv[2], sys.argv[3], json.loads(sys.argv[4]), sys.argv[5]

def run(fn, **kw):
    result = fn(**kw)
    return asyncio.run(result) if inspect.iscoroutine(result) else result

named = {"local_path": path, "owner": owner, "repo": repo}
confirmed = run(tools.confirm_project_data, **named, **answers)
plan = run(tools.remediate_audit_findings, **named, dry_run=True)
digests = sorted(set(re.findall(r"sha256:[0-9a-f]{64}", plan)))
applied = run(tools.remediate_audit_findings, **named, dry_run=False, approve=digests)
json.dump({"confirmed": confirmed, "plan": plan, "approved": len(digests), "applied": applied}, open(out, "w"))
"""


class StepFailed(Exception):
    pass


def _run(cmd: list[str], env: dict, cwd: Path | None = None, stdout=None) -> None:
    proc = subprocess.run(cmd, env=env, cwd=cwd, stdout=stdout or subprocess.PIPE, stderr=subprocess.PIPE, text=True)
    if proc.returncode != 0:
        raise StepFailed(f"{' '.join(cmd[:4])} ... exited {proc.returncode}: {proc.stderr.strip()[-500:]}")


def _token() -> str | None:
    if os.environ.get("GH_TOKEN"):
        return os.environ["GH_TOKEN"]
    try:
        out = subprocess.run(["gh", "auth", "token"], capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return None
    return out.stdout.strip() or None


def _home(root: Path, identities: list[str]) -> Path:
    """A HOME whose operator configuration trusts the replayed repository."""
    home = root / "home"
    config = home / ".config" / "darnit" / "config.toml"
    config.parent.mkdir(parents=True)
    repos = ", ".join(json.dumps(i) for i in identities)
    config.write_text(f"schema_version = 1\n\n[trust]\nrepos = [{repos}]\n", encoding="utf-8")
    config.chmod(0o600)
    return home


def _audit(darnit: Path, checkout: Path, ref: dict, env: dict, out: Path) -> dict:
    with out.open("w") as fh:
        _run(
            [
                str(darnit),
                "audit",
                str(checkout),
                "-o",
                "json",
                "-f",
                ref["framework"],
                "--no-fail",
                "--repo",
                f"github.com/{ref['owner']}/{ref['repo']}",
            ],
            env,
            cwd=checkout,
            stdout=fh,
        )
    return {r["id"]: r["status"] for r in json.loads(out.read_text())["results"]}


def replay(name: str, ref: dict, root: Path) -> dict:
    """Audit, confirm, remediate, audit again; return the counts and transitions."""
    work = root / name
    checkout = work / "repo"
    work.mkdir()
    real = f"https://github.com/{ref['owner']}/{ref['repo']}.git"
    nowhere = f"https://github.com/{NOWHERE_OWNER}/{ref['repo']}.git"

    env = {k: v for k, v in os.environ.items() if not k.startswith(("DARNIT_", "XDG_"))}
    env["HOME"] = str(
        _home(work, [f"github.com/{ref['owner']}/{ref['repo']}", f"github.com/{NOWHERE_OWNER}/{ref['repo']}"])
    )
    if token := _token():
        env["GH_TOKEN"] = token
    darnit = Path(sys.executable).parent / "darnit"

    started = time.monotonic()
    _run(["git", "clone", "-q", "--filter=blob:none", ref["url"], str(checkout)], env)
    _run(["git", "-C", str(checkout), "checkout", "-q", "-b", "replay", ref["commit"]], env)
    _run(["git", "-C", str(checkout), "remote", "set-url", "origin", real], env)

    before = _audit(darnit, checkout, ref, env, work / "before.json")

    _run(["git", "-C", str(checkout), "remote", "set-url", "origin", nowhere], env)
    _run(
        [
            sys.executable,
            "-c",
            REMEDIATE,
            str(checkout),
            NOWHERE_OWNER,
            ref["repo"],
            json.dumps(ref.get("answers", {})),
            str(work / "remediation.json"),
        ],
        env,
    )
    _run(["git", "-C", str(checkout), "remote", "set-url", "origin", real], env)
    changed = subprocess.run(
        ["git", "-C", str(checkout), "status", "--porcelain", "--untracked-files=all"],
        capture_output=True,
        text=True,
        env=env,
    ).stdout.splitlines()

    after = _audit(darnit, checkout, ref, env, work / "after.json")

    return {
        "pass_before": sum(s == "PASS" for s in before.values()),
        "fail_before": sum(s == "FAIL" for s in before.values()),
        "pass_after": sum(s == "PASS" for s in after.values()),
        "before": dict(collections.Counter(before.values())),
        "after": dict(collections.Counter(after.values())),
        "files_changed": len(changed),
        "transitions": {k: f"{before.get(k, '-')} > {after[k]}" for k in sorted(after) if before.get(k) != after[k]},
        "seconds": round(time.monotonic() - started, 1),
    }


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("names", nargs="*", help="references to replay (default: all)")
    parser.add_argument("--record", action="store_true", help="write the measured counts as the expected ones")
    parser.add_argument("--keep", action="store_true", help="keep the clones and reports")
    args = parser.parse_args()

    references = tomllib.loads(REFERENCES.read_text())["references"]
    expected = json.loads(EXPECTED.read_text()) if EXPECTED.exists() else {}
    names = args.names or list(references)
    unknown = [n for n in names if n not in references]
    if unknown:
        parser.error(f"unknown reference(s): {', '.join(unknown)}")

    root = Path(tempfile.mkdtemp(prefix="darnit-replay-"))
    results, status = {}, 0
    try:
        for name in names:
            try:
                results[name] = replay(name, references[name], root)
            except StepFailed as exc:
                print(f"{name}: {exc}", file=sys.stderr)
                status = 2
    finally:
        if args.keep:
            print(f"clones and reports: {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)

    print(
        f"\n{'reference':20} {'FAIL before':>12} {'PASS before':>12} {'PASS after':>11} {'recorded':>13} {'files':>6} {'time':>7}"
    )
    for name, r in results.items():
        rec = expected.get(name, {})
        recorded = f"{rec.get('pass_before', '-')} > {rec.get('pass_after', '-')}"
        print(
            f"{name:20} {r['fail_before']:>12} {r['pass_before']:>12} {r['pass_after']:>11} {recorded:>13} {r['files_changed']:>6} {r['seconds']:>6}s"
        )
        print(f"{'':20} before {r['before']}\n{'':20} after  {r['after']}")
        for control, change in r["transitions"].items():
            print(f"{'':20}   {control:24} {change}")
        dropped = [k for k in COUNTED if k in rec and r[k] < rec[k]]
        if dropped:
            print(f"{name}: dropped below the recorded count: {', '.join(dropped)}", file=sys.stderr)
            status = max(status, 1)
        elif any(k in rec and r[k] > rec[k] for k in COUNTED):
            print(f"{name}: above the recorded count; record it with --record")

    if args.record and results:
        expected.update({n: {k: r[k] for k in COUNTED} for n, r in results.items()})
        EXPECTED.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")
        print(f"recorded {', '.join(results)} in {EXPECTED.name}")
    return status


if __name__ == "__main__":
    sys.exit(main())
