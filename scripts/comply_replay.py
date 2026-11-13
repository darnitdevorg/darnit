#!/usr/bin/env python3
"""Replay the comply flow on reference repositories, with no model (#655, #639).

For each reference in scripts/comply_replay.toml: clone it at a fixed commit,
audit, confirm the recorded answers, plan and apply remediation, audit again,
and compare the result with scripts/comply_replay_expected.json: every
control's status before and after, its remediation outcome, and the files
remediation wrote. Any difference fails the run, a better result as much as a
worse one, so a change in what darnit concludes or fixes shows in the change
that causes it. If the difference is intended, record it with --record and
commit the expected file with the change.

The run is deterministic. No model runs, and no platform token is passed, so
every platform read fails the same way wherever the replay runs; platform
checks are measured by the corpus recordings instead. Tools come from the
project environment first (zizmor is pinned in the dev dependency group), and
a reference whose record names another zizmor version is not replayed.

Only the clone reaches GitHub. The run uses a throwaway HOME whose operator
configuration trusts the clone, and remediation names a repository identity
that does not exist. File changes land in the temporary clone, which is never
pushed.

    uv run python scripts/comply_replay.py                 # every reference
    uv run python scripts/comply_replay.py wtf-frontend    # one reference
    uv run python scripts/comply_replay.py --record        # record the measured result
    uv run python scripts/comply_replay.py --keep          # keep the clones and reports
    uv run python scripts/comply_replay.py --platform      # also read the platform

--platform reads the platform with GH_TOKEN, or `gh auth token` when it is
unset. What it reads depends on the token and on live settings, so that run is
reported only: it is not compared with the record and cannot be recorded.

Exit codes: 0 = the same as the record, 1 = a difference, 2 = a step failed.
"""

from __future__ import annotations

import argparse
import collections
import json
import os
import re
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
BIN = Path(sys.executable).parent
# Never passed to the replay unless --platform: each lets gh read the platform.
PLATFORM_ENV = (
    "GH_TOKEN",
    "GITHUB_TOKEN",
    "GH_ENTERPRISE_TOKEN",
    "GITHUB_ENTERPRISE_TOKEN",
    "GH_CONFIG_DIR",
    "GH_HOST",
)
OUTCOME = re.compile(r"^### (\S+): ([a-z_]+)\s*$", re.MULTILINE)

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


def _base_env(platform: bool) -> dict:
    env = {k: v for k, v in os.environ.items() if not k.startswith(("DARNIT_", "XDG_")) and k not in PLATFORM_ENV}
    env["PATH"] = f"{BIN}{os.pathsep}{env.get('PATH', '')}"
    if platform and (token := _token()):
        env["GH_TOKEN"] = token
    return env


def _zizmor_version(env: dict) -> str:
    try:
        out = subprocess.run(["zizmor", "--version"], env=env, capture_output=True, text=True, check=True)
    except (OSError, subprocess.CalledProcessError):
        return "missing"
    return out.stdout.split()[-1] if out.stdout.split() else "unknown"


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


def replay(name: str, ref: dict, root: Path, base_env: dict) -> dict:
    """Audit, confirm, remediate, audit again; return each control's result and the files written."""
    work = root / name
    checkout = work / "repo"
    work.mkdir()
    real = f"https://github.com/{ref['owner']}/{ref['repo']}.git"
    nowhere = f"https://github.com/{NOWHERE_OWNER}/{ref['repo']}.git"

    env = dict(base_env)
    env["HOME"] = str(
        _home(work, [f"github.com/{ref['owner']}/{ref['repo']}", f"github.com/{NOWHERE_OWNER}/{ref['repo']}"])
    )
    darnit = BIN / "darnit"

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
    outcomes = dict(OUTCOME.findall(json.loads((work / "remediation.json").read_text())["applied"]))

    after = _audit(darnit, checkout, ref, env, work / "after.json")

    controls = {}
    for cid in sorted(set(before) | set(after)):
        entry = {"before": before.get(cid, "-"), "after": after.get(cid, "-")}
        if cid in outcomes:
            entry["outcome"] = outcomes[cid]
        controls[cid] = entry
    return {
        "controls": controls,
        "files": sorted(line[3:] for line in changed),
        "seconds": round(time.monotonic() - started, 1),
    }


def _count(controls: dict, side: str, status: str) -> int:
    return sum(c[side] == status for c in controls.values())


def _fmt(entry: dict) -> str:
    outcome = f" ({entry['outcome']})" if "outcome" in entry else ""
    return f"{entry['before']} > {entry['after']}{outcome}"


def differences(measured: dict, recorded: dict) -> list[str]:
    """Every way the measured result differs from the recorded one."""
    out = []
    rec, now = recorded.get("controls", {}), measured["controls"]
    for cid in sorted(set(rec) | set(now)):
        if rec.get(cid) == now.get(cid):
            continue
        if cid not in rec:
            out.append(f"{cid}: not recorded; now {_fmt(now[cid])}")
        elif cid not in now:
            out.append(f"{cid}: recorded {_fmt(rec[cid])}; now absent")
        else:
            out.append(f"{cid}: recorded {_fmt(rec[cid])}; now {_fmt(now[cid])}")
    rec_files, now_files = set(recorded.get("files", [])), set(measured["files"])
    out += [f"no longer written: {f}" for f in sorted(rec_files - now_files)]
    out += [f"now written: {f}" for f in sorted(now_files - rec_files)]
    return out


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__.split("\n\n")[0])
    parser.add_argument("names", nargs="*", help="references to replay (default: all)")
    parser.add_argument("--record", action="store_true", help="write the measured result as the expected one")
    parser.add_argument("--keep", action="store_true", help="keep the clones and reports")
    parser.add_argument("--platform", action="store_true", help="read the platform with a token (report only)")
    args = parser.parse_args()
    if args.record and args.platform:
        parser.error("a --platform run depends on the token and live settings, so it cannot be recorded")

    references = tomllib.loads(REFERENCES.read_text())["references"]
    expected = json.loads(EXPECTED.read_text()) if EXPECTED.exists() else {}
    names = args.names or list(references)
    unknown = [n for n in names if n not in references]
    if unknown:
        parser.error(f"unknown reference(s): {', '.join(unknown)}")

    base_env = _base_env(args.platform)
    zizmor = _zizmor_version(base_env)
    print(f"zizmor {zizmor}; platform reads: {'token' if 'GH_TOKEN' in base_env else 'none'}")

    root = Path(tempfile.mkdtemp(prefix="darnit-replay-"))
    results, status = {}, 0
    try:
        for name in names:
            recorded_zizmor = expected.get(name, {}).get("zizmor")
            if not args.record and recorded_zizmor and recorded_zizmor != zizmor:
                print(
                    f"{name}: recorded with zizmor {recorded_zizmor}, found {zizmor}; "
                    "run from the project environment (uv sync) or re-record",
                    file=sys.stderr,
                )
                status = 2
                continue
            try:
                results[name] = replay(name, references[name], root, base_env)
            except StepFailed as exc:
                print(f"{name}: {exc}", file=sys.stderr)
                status = 2
    finally:
        if args.keep:
            print(f"clones and reports: {root}")
        else:
            shutil.rmtree(root, ignore_errors=True)

    print(f"\n{'reference':20} {'FAIL before':>12} {'PASS before':>12} {'PASS after':>11} {'files':>6} {'time':>7}")
    for name, r in results.items():
        c = r["controls"]
        print(
            f"{name:20} {_count(c, 'before', 'FAIL'):>12} {_count(c, 'before', 'PASS'):>12} "
            f"{_count(c, 'after', 'PASS'):>11} {len(r['files']):>6} {r['seconds']:>6}s"
        )
        for side in ("before", "after"):
            print(f"{'':20} {side:6} {dict(sorted(collections.Counter(e[side] for e in c.values()).items()))}")
        for cid, entry in c.items():
            if entry["before"] != entry["after"] or "outcome" in entry:
                print(f"{'':20}   {cid:24} {_fmt(entry)}")
        if args.platform or args.record:
            continue
        if name not in expected:
            print(f"{name}: no recorded result; record one with --record", file=sys.stderr)
            status = max(status, 1)
            continue
        diffs = differences(r, expected[name])
        if diffs:
            print(f"{name}: differs from the record:", file=sys.stderr)
            for d in diffs:
                print(f"  {d}", file=sys.stderr)
            print(
                f"{name}: if the difference is intended, run --record and commit {EXPECTED.name} with the change",
                file=sys.stderr,
            )
            status = max(status, 1)
        else:
            print(f"{name}: the same as the record")

    if args.record and results:
        expected.update(
            {n: {"zizmor": zizmor, "controls": r["controls"], "files": r["files"]} for n, r in results.items()}
        )
        EXPECTED.write_text(json.dumps(expected, indent=2, sort_keys=True) + "\n")
        print(f"recorded {', '.join(results)} in {EXPECTED.name}")
    return status


if __name__ == "__main__":
    sys.exit(main())
