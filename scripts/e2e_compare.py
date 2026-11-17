#!/usr/bin/env python3
"""Compare darnit at two refs, end to end, on a reference repository.

    uv run python scripts/e2e_compare.py compare BASE HEAD [--phases 1,2,4]
    uv run python scripts/e2e_compare.py build REF
    uv run python scripts/e2e_compare.py prune         # remove the builds' worktrees

BASE and HEAD are git refs in this checkout, or pr/NUMBER for a pull request on
the remote (--remote, default upstream). HEAD is tested merged into BASE, which
is what would land. Each side is built in its own worktree and venv, and every
phase runs on a fresh copy of the reference repository at its pinned commit
(scripts/comply_replay.toml), with darnit in a throwaway HOME.

Phases (docs/design/e2e-verification.md, Layer 2):

  1  Deterministic audit. Compares each control's level, status and
     concluded_by. Platform reads use GH_TOKEN, or `gh auth token`, unless
     --no-platform; the token is used for reads only.
  2  MCP tool surface of every framework registered on either side: tool
     names, descriptions and schemas, as an agent sees them.
  4  Headless /darnit:darnit-comply through the local Claude Code login. The
     agent gets the reference's recorded answers, approves every file change
     and no platform change, and cannot confirm a PASS candidate, open a PR or
     change settings. The darnit server gets no token and its copy has no
     remote. Compares the final deterministic audit, the remediation outcomes
     and the files written; lists tool errors and permission denials. Costs
     model usage for two runs (about USD 4 each on wtf-frontend).

Nothing is written outside --root (default ~/.local/share/darnit-e2e-runs) and
the builds' worktrees. The report is compare.md in the run directory, for the
PR's Testing section.

Exit codes: 0 = no differences, 1 = differences, 2 = a step failed.
"""

from __future__ import annotations

import argparse
import concurrent.futures
import json
import os
import re
import shutil
import subprocess
import sys
import time
import tomllib
from collections import Counter
from pathlib import Path

CHECKOUT = Path(__file__).resolve().parent.parent
REFERENCES = CHECKOUT / "scripts" / "comply_replay.toml"
DEFAULT_ROOT = Path.home() / ".local" / "share" / "darnit-e2e-runs"
PHASES = {"1", "2", "4"}
SERVER = "darnit"
# The agent may not confirm its own PASS candidates or reach the platform.
DISALLOWED = ["confirm_pass_candidate", "create_remediation_pr", "enable_branch_protection", "create_test_repository"]
TOKEN_ENV = ("GH_TOKEN", "GITHUB_TOKEN", "GH_ENTERPRISE_TOKEN", "GITHUB_ENTERPRISE_TOKEN", "GH_CONFIG_DIR", "GH_HOST")
# Under CI, darnit takes trust from the CI run, not the operator configuration.
CI_ENV_PREFIXES = ("CI_", "GITHUB_", "GITLAB_", "RUNNER_")
CI_ENV = ("CI", "JENKINS_URL", "TF_BUILD", "BUILDKITE", "CIRCLECI", "TRAVIS", "TEAMCITY_VERSION")
OUTCOME = re.compile(r"^### (\S+): ([a-z_]+)\s*$", re.MULTILINE)
SPILLED = re.compile(r"Output has been saved to (\S+\.txt)")
SPILL_SIZE = re.compile(r"result \(([\d,]+) characters\)")

SURFACE = r"""
import asyncio, json
from darnit.config.merger import list_available_frameworks, resolve_framework_path
from darnit.server.factory import create_server
out = {}
for name in list_available_frameworks():
    path = resolve_framework_path(name)
    tools = asyncio.run(create_server(path).list_tools())
    out[name] = {t.name: t.model_dump(mode="json", exclude_none=True) for t in tools}
print(json.dumps(out))
"""

PROMPT = """/darnit:darnit-comply {framework}

This is an unattended test run. No person is available, so do not ask questions; use these facts instead.
- The repository is {identity}: owner "{owner}", repo "{repo}", local_path "{path}". The checkout has no remote.
- The person's answers to project data questions are exactly these: {answers}. Confirm them with \
confirm_project_data when the procedure asks. Do not confirm any other value; name every value you were \
asked for and do not have in the final report.
- In the remediation plan, the person approves every file change and no platform change set.
- You cannot edit files in this run: skip step 6 and say so.
- The person does not want a PR.
- PASS candidates stay unconfirmed: report them as awaiting the person's confirmation.
End with the step 9 report."""


class StepFailed(Exception):
    pass


def log(msg: str) -> None:
    print(msg, file=sys.stderr, flush=True)


def sh(cmd: list[str], check: bool = True, **kw) -> subprocess.CompletedProcess:
    r = subprocess.run(cmd, text=True, capture_output=True, **kw)
    if check and r.returncode:
        shown = " ".join(a if len(a) < 80 else a[:20] + "..." for a in cmd[:4])
        raise StepFailed(f"{shown} exited {r.returncode}: {(r.stderr or r.stdout).strip()[-800:]}")
    return r


# --- refs and builds ---------------------------------------------------------


def resolve(ref: str, remote: str) -> str:
    """Return the commit a ref names; pr/NUMBER is fetched from the remote."""
    if m := re.fullmatch(r"pr/(\d+)", ref):
        sh(["git", "-C", str(CHECKOUT), "fetch", "-q", remote, f"pull/{m[1]}/head"])
        ref = "FETCH_HEAD"
    return sh(["git", "-C", str(CHECKOUT), "rev-parse", "--verify", f"{ref}^{{commit}}"]).stdout.strip()


def build(root: Path, base: str, head: str | None = None) -> Path:
    """A worktree with a venv at base, or at head merged into base. Reused when present."""
    key = base[:12] if head is None else f"{base[:12]}+{head[:12]}"
    path = root / "builds" / key
    ready = path / ".e2e-ready"
    if ready.exists():
        return path
    if path.exists():
        sh(["git", "-C", str(CHECKOUT), "worktree", "remove", "--force", str(path)], check=False)
        shutil.rmtree(path, ignore_errors=True)
    path.parent.mkdir(parents=True, exist_ok=True)
    # A worktree whose directory was deleted by hand stays registered until pruned.
    sh(["git", "-C", str(CHECKOUT), "worktree", "prune"], check=False)
    log(f"build {key}")
    sh(["git", "-C", str(CHECKOUT), "worktree", "add", "-q", "--detach", str(path), base])
    if head is not None:
        merge = sh(
            [
                "git",
                "-C",
                str(path),
                "-c",
                "user.name=e2e",
                "-c",
                "user.email=e2e@invalid",
                "merge",
                "-q",
                "--no-ff",
                "--no-edit",
                head,
            ],
            check=False,
        )
        if merge.returncode:
            raise StepFailed(f"{head[:12]} does not merge cleanly into {base[:12]}: {merge.stdout.strip()[-400:]}")
    env = {k: v for k, v in os.environ.items() if k not in ("VIRTUAL_ENV", "UV_PROJECT_ENVIRONMENT")}
    sh(["uv", "sync", "-q", "--all-extras", "--frozen"], cwd=path, env=env)
    ready.write_text(sh(["git", "-C", str(path), "rev-parse", "HEAD"]).stdout)
    return path


# --- reference copies and darnit environment ---------------------------------


def references() -> dict:
    return tomllib.loads(REFERENCES.read_text(encoding="utf-8"))["references"]


def cache(root: Path, ref: dict) -> Path:
    """A local clone of the reference that holds its pinned commit. Run before any copy."""
    path = root / "cache" / f"{ref['owner']}__{ref['repo']}"
    if not path.exists():
        path.parent.mkdir(parents=True, exist_ok=True)
        sh(["git", "clone", "-q", ref["url"], str(path)])
    if sh(["git", "-C", str(path), "cat-file", "-e", f"{ref['commit']}^{{commit}}"], check=False).returncode:
        sh(["git", "-C", str(path), "fetch", "-q", "origin"])
    return path


def copy(root: Path, ref: dict, dest: Path) -> Path:
    """A fresh clone of the reference at its pinned commit, with no remote."""
    sh(["git", "clone", "-q", str(cache(root, ref)), str(dest)])
    sh(["git", "-C", str(dest), "checkout", "-q", "-b", "e2e", ref["commit"]])
    sh(["git", "-C", str(dest), "remote", "remove", "origin"])
    return dest


def identity(ref: dict) -> str:
    return f"github.com/{ref['owner']}/{ref['repo']}"


def darnit_home(path: Path, ref: dict) -> dict:
    """Environment entries for a throwaway darnit HOME that trusts the reference."""
    config = path / ".config" / "darnit" / "config.toml"
    config.parent.mkdir(parents=True)
    config.write_text(
        f'schema_version = 1\n\n[trust]\nrepos = ["{identity(ref)}"]\n\n'
        '[remediation]\nplatform = "manual"\nhigh_impact = "manual"\n',
        encoding="utf-8",
    )
    config.chmod(0o600)
    (path / "gh").mkdir()
    return {
        "HOME": str(path),
        "XDG_CONFIG_HOME": str(path / ".config"),
        "XDG_DATA_HOME": str(path / ".local" / "share"),
        "XDG_CACHE_HOME": str(path / ".cache"),
        "GH_CONFIG_DIR": str(path / "gh"),
    }


def clean_env() -> dict:
    """The caller's environment without darnit, XDG, CI or platform-token variables.

    Tokens are removed, never set empty: zizmor refuses an empty GH_TOKEN (#752).
    """
    return {
        k: v
        for k, v in os.environ.items()
        if not k.startswith(("DARNIT_", "XDG_", *CI_ENV_PREFIXES))
        and k not in TOKEN_ENV
        and k not in CI_ENV
        and k not in ("VIRTUAL_ENV",)
    }


def platform_token() -> str | None:
    if os.environ.get("GH_TOKEN"):
        return os.environ["GH_TOKEN"]
    try:
        r = subprocess.run(["gh", "auth", "token"], text=True, capture_output=True)
    except OSError:
        return None
    if r.returncode:
        return None
    return r.stdout.strip() or None


def audit(build_path: Path, checkout: Path, ref: dict, env: dict, out: Path) -> dict:
    r = sh(
        [
            str(build_path / ".venv" / "bin" / "darnit"),
            "audit",
            str(checkout),
            "-f",
            ref["framework"],
            "-o",
            "json",
            "--no-fail",
            "--repo",
            identity(ref),
        ],
        env=env,
        cwd=checkout,
        check=False,
    )
    out.write_text(r.stdout)
    try:
        results = json.loads(r.stdout)["results"]
    except (json.JSONDecodeError, KeyError) as exc:
        raise StepFailed(f"audit of {checkout} gave no results: {r.stderr.strip()[-800:]}") from exc
    return {
        c["id"]: {"level": c.get("level"), "status": c.get("status"), "concluded_by": c.get("concluded_by")}
        for c in results
    }


def changed_files(checkout: Path, commit: str) -> list[str]:
    status = sh(["git", "-C", str(checkout), "status", "--porcelain", "--untracked-files=all"]).stdout
    committed = sh(["git", "-C", str(checkout), "diff", "--name-only", f"{commit}..HEAD"]).stdout
    return sorted({line[3:] for line in status.splitlines()} | set(committed.split()))


# --- phases ------------------------------------------------------------------


def phase_audit(side: Path, build_path: Path, root: Path, ref: dict, token: str | None) -> dict:
    work = side / "phase1"
    work.mkdir(parents=True)
    checkout = copy(root, ref, work / "repo")
    env = {**clean_env(), **darnit_home(work / "home", ref)}
    if token:
        env["GH_TOKEN"] = token
    controls = audit(build_path, checkout, ref, env, work / "audit.json")
    files = changed_files(checkout, ref["commit"])
    if files:
        raise StepFailed(f"the audit changed files in its copy: {files}")
    return {"controls": controls}


def phase_surface(side: Path, build_path: Path, ref: dict) -> dict:
    work = side / "phase2"
    work.mkdir(parents=True)
    env = {**clean_env(), **darnit_home(work / "home", ref)}
    r = sh([str(build_path / ".venv" / "bin" / "python"), "-c", SURFACE], env=env, cwd=work)
    surface = json.loads(r.stdout)
    (work / "surface.json").write_text(json.dumps(surface, indent=1, sort_keys=True))
    return {"frameworks": surface}


def _tool_text(text: str) -> str:
    """An MCP tool's text: its JSON envelope ({"result": "..."}) decoded when it has one."""
    try:
        decoded = json.loads(text)
    except json.JSONDecodeError:
        return text
    if isinstance(decoded, dict) and isinstance(decoded.get("result"), str):
        return decoded["result"]
    return text


def parse_transcript(lines) -> dict:
    """Tool calls, tool errors, permission denials, remediation outcomes and run facts from stream-json."""
    calls, errors, spilled, outcomes, facts, uses = Counter(), [], [], {}, {}, {}
    for line in lines:
        try:
            event = json.loads(line)
        except json.JSONDecodeError:
            continue
        kind = event.get("type")
        if kind == "system" and event.get("subtype") == "init":
            facts["model"] = event.get("model")
            facts["mcp_servers"] = [f"{s.get('name')}:{s.get('status')}" for s in event.get("mcp_servers") or []]
        elif kind == "assistant":
            for c in event["message"].get("content") or []:
                if c.get("type") == "tool_use":
                    calls[c["name"]] += 1
                    uses[c["id"]] = c["name"]
        elif kind == "user" and isinstance(event["message"].get("content"), list):
            for c in event["message"]["content"]:
                if c.get("type") != "tool_result":
                    continue
                content = c.get("content")
                text = (
                    content
                    if isinstance(content, str)
                    else " ".join(x.get("text", "") for x in content or [] if isinstance(x, dict))
                )
                tool = uses.get(c.get("tool_use_id"))
                if spill := SPILLED.search(text):
                    # Too large for the agent: Claude Code saved it to a file and gave the agent the path.
                    size = SPILL_SIZE.search(text)
                    spilled.append({"tool": tool, "characters": int(size[1].replace(",", "")) if size else None})
                    if Path(spill[1]).is_file():
                        text = Path(spill[1]).read_text(encoding="utf-8", errors="replace")
                elif c.get("is_error"):
                    errors.append({"tool": tool, "error": text[:400]})
                if (tool or "").startswith("mcp__") and "# Remediation Applied" in text:
                    outcomes.update(OUTCOME.findall(_tool_text(text)))
        elif kind == "result":
            facts.update(
                turns=event.get("num_turns"),
                cost_usd=event.get("total_cost_usd"),
                is_error=event.get("is_error"),
                subtype=event.get("subtype"),
                denials=[d.get("tool_name") for d in event.get("permission_denials") or []],
                report=event.get("result") or "",
            )
    return {"tool_calls": dict(calls), "tool_errors": errors, "spilled": spilled, "outcomes": outcomes, **facts}


def phase_comply(side: Path, build_path: Path, root: Path, ref: dict, model: str | None, timeout: int) -> dict:
    work = side / "phase4"
    work.mkdir(parents=True)
    checkout = copy(root, ref, work / "repo")
    home = darnit_home(work / "home", ref)
    mcp = work / "mcp.json"
    mcp.write_text(
        json.dumps(
            {
                "mcpServers": {
                    SERVER: {
                        "command": str(build_path / ".venv" / "bin" / "darnit"),
                        "args": ["serve", "--framework", ref["framework"]],
                        "env": home,
                    }
                }
            },
            indent=1,
        )
    )
    plugin = work / "plugin"
    (plugin / ".claude-plugin").mkdir(parents=True)
    (plugin / ".claude-plugin" / "plugin.json").write_text(
        json.dumps({"name": "darnit", "version": "0.0.0-e2e", "description": f"darnit skills from {build_path}"})
    )
    shutil.copytree(build_path / "packages" / "darnit" / "src" / "darnit" / "skills", plugin / "skills")
    prompt = PROMPT.format(
        framework=ref["framework"],
        identity=identity(ref),
        owner=ref["owner"],
        repo=ref["repo"],
        path=checkout,
        answers=json.dumps(ref.get("answers", {})),
    )
    tools = f"mcp__{SERVER}__"
    cmd = [
        "claude",
        "-p",
        prompt,
        "--setting-sources",
        "project",
        "--strict-mcp-config",
        "--mcp-config",
        str(mcp),
        "--plugin-dir",
        str(plugin),
        "--tools",
        "Read,Glob,Grep",
        "--allowedTools",
        f"{tools}*",
        "Read",
        "Glob",
        "Grep",
        "--disallowedTools",
        *[tools + t for t in DISALLOWED],
        "--output-format",
        "stream-json",
        "--verbose",
    ]
    if model:
        cmd += ["--model", model]
    # claude keeps the real HOME (it uses the local login); darnit gets its own through the MCP env.
    env = clean_env()
    started = time.monotonic()
    with (work / "transcript.jsonl").open("w") as out, (work / "claude.stderr").open("w") as err:
        try:
            rc = subprocess.run(
                cmd, cwd=checkout, stdout=out, stderr=err, text=True, env=env, timeout=timeout
            ).returncode
        except subprocess.TimeoutExpired:
            rc = "timeout"
    seconds = round(time.monotonic() - started)
    with (work / "transcript.jsonl").open() as fh:
        run = parse_transcript(fh)
    (work / "report.md").write_text(run.pop("report", ""))
    if rc != 0:
        raise StepFailed(f"claude exited {rc} after {seconds}s; see {work / 'claude.stderr'}")
    controls = audit(build_path, checkout, ref, {**clean_env(), **home}, work / "final-audit.json")
    return {"seconds": seconds, **run, "final": controls, "files": changed_files(checkout, ref["commit"])}


# --- comparison --------------------------------------------------------------


def diff_controls(base: dict, head: dict, fields=("level", "status", "concluded_by")) -> list[str]:
    out = []
    for cid in sorted(set(base) | set(head)):
        if cid not in head:
            out.append(f"{cid}: removed")
        elif cid not in base:
            out.append(f"{cid}: added ({head[cid].get('status')})")
        else:
            changes = [
                f"{f} {base[cid].get(f)} > {head[cid].get(f)}" for f in fields if base[cid].get(f) != head[cid].get(f)
            ]
            if changes:
                out.append(f"{cid}: {', '.join(changes)}")
    return out


def diff_surface(base: dict, head: dict) -> list[str]:
    out = []
    for fw in sorted(set(base) | set(head)):
        b, h = base.get(fw) or {}, head.get(fw) or {}
        if (base.get(fw) is None) != (head.get(fw) is None):
            out.append(f"{fw}: {'not registered' if head.get(fw) is None else 'registered'} in head")
        out += [f"{fw}: added {n}" for n in sorted(set(h) - set(b))]
        out += [f"{fw}: removed {n}" for n in sorted(set(b) - set(h))]
        for name in sorted(set(b) & set(h)):
            fields = sorted(k for k in set(b[name]) | set(h[name]) if b[name].get(k) != h[name].get(k))
            if fields:
                out.append(f"{fw}: changed {name} ({', '.join(fields)})")
    return out


def diff_mapping(base: dict, head: dict) -> list[str]:
    return [
        f"{k}: {base.get(k, '-')} > {head.get(k, '-')}"
        for k in sorted(set(base) | set(head))
        if base.get(k) != head.get(k)
    ]


def diff_files(base: list[str], head: list[str]) -> list[str]:
    return [f"no longer written: {f}" for f in sorted(set(base) - set(head))] + [
        f"now written: {f}" for f in sorted(set(head) - set(base))
    ]


def compare_comply(base: dict, head: dict) -> dict:
    return {
        "final_audit": diff_controls(base["final"], head["final"], fields=("status",)),
        "outcomes": diff_mapping(base["outcomes"], head["outcomes"]),
        "files": diff_files(base["files"], head["files"]),
        "head_tool_errors": head["tool_errors"],
        "head_denials": head.get("denials") or [],
    }


def counts(controls: dict) -> dict:
    return dict(sorted(Counter(c["status"] for c in controls.values()).items()))


def render(meta: dict, results: dict, diffs: dict, failures: list[str]) -> str:
    lines = [
        "## End-to-end comparison",
        "",
        f"- base: `{meta['base']}`",
        f"- head: `{meta['head']}`, merged into base (`{meta['head_build']}`)",
        f"- reference: {meta['reference']} at `{meta['commit']}` ({meta['url']})",
        f"- phases: {', '.join(meta['phases'])}; platform reads in phase 1: {meta['platform']}",
        "",
    ]
    for failure in failures:
        lines.append(f"**Step failed:** {failure}")
    if "1" in diffs:
        b, h = results["base"]["1"]["controls"], results["head"]["1"]["controls"]
        lines += ["### Phase 1: deterministic audit", "", f"- base {counts(b)}", f"- head {counts(h)}"]
        lines += _listed(diffs["1"], "No control changed level, status or concluded_by.")
    if "2" in diffs:
        tools = {fw: len(t or {}) for fw, t in results["head"]["2"]["frameworks"].items()}
        lines += ["### Phase 2: MCP tool surface", "", f"- head tools: {tools}"]
        lines += _listed(diffs["2"], "No tool, description or schema changed.")
    if "4" in diffs:
        lines += ["### Phase 4: headless /darnit:darnit-comply", "", "| | base | head |", "|---|---|---|"]
        b, h = results["base"]["4"], results["head"]["4"]
        for label, key in (("model", "model"), ("turns", "turns"), ("seconds", "seconds"), ("cost (USD)", "cost_usd")):
            lines.append(f"| {label} | {b.get(key)} | {h.get(key)} |")
        lines.append(f"| tool calls | {sum(b['tool_calls'].values())} | {sum(h['tool_calls'].values())} |")
        lines.append(f"| tool errors | {len(b['tool_errors'])} | {len(h['tool_errors'])} |")
        lines.append(f"| outputs too large for the agent | {_spills(b)} | {_spills(h)} |")
        lines.append(f"| permission denials | {len(b.get('denials') or [])} | {len(h.get('denials') or [])} |")
        lines.append(f"| files written | {len(b['files'])} | {len(h['files'])} |")
        lines += ["", f"- final audit, base {counts(b['final'])}", f"- final audit, head {counts(h['final'])}"]
        d = diffs["4"]
        listed = (
            [f"final audit: {x}" for x in d["final_audit"]]
            + [f"outcome: {x}" for x in d["outcomes"]]
            + [f"files: {x}" for x in d["files"]]
            + [f"head tool error: {e['tool']}: {e['error'][:200]}" for e in d["head_tool_errors"]]
            + [f"head permission denial: {x}" for x in d["head_denials"]]
        )
        lines += _listed(
            listed,
            "Final audit, remediation outcomes and files written are the same; no tool errors or denials in head.",
        )
        lines.append("The agent's own judgments and wording vary between runs and are not compared.")
        lines.append("")
    return "\n".join(lines)


def _spills(run: dict) -> str:
    spilled = run.get("spilled") or []
    if not spilled:
        return "0"
    largest = max((s["characters"] or 0 for s in spilled), default=0)
    return f"{len(spilled)} (largest {largest:,} characters)"


def _listed(items: list[str], same: str) -> list[str]:
    if not items:
        return ["", same, ""]
    return ["", *[f"- {x}" for x in items], ""]


def differs(diffs: dict) -> bool:
    return any(v if not isinstance(v, dict) else any(v.values()) for v in diffs.values())


# --- commands ----------------------------------------------------------------


def cmd_build(args) -> int:
    try:
        path = build(args.root, resolve(args.ref, args.remote))
    except StepFailed as exc:
        log(str(exc))
        return 2
    print(path)
    return 0


def cmd_prune(args) -> int:
    """Remove every build's worktree; run directories and the reference cache stay."""
    builds = args.root / "builds"
    for path in sorted(builds.iterdir()) if builds.is_dir() else []:
        sh(["git", "-C", str(CHECKOUT), "worktree", "remove", "--force", str(path)], check=False)
        shutil.rmtree(path, ignore_errors=True)
        print(f"removed {path}")
    sh(["git", "-C", str(CHECKOUT), "worktree", "prune"], check=False)
    return 0


def cmd_compare(args) -> int:
    phases = sorted(set(args.phases.split(",")))
    if unknown := set(phases) - PHASES:
        log(f"unknown phases: {sorted(unknown)}; implemented: {sorted(PHASES)}")
        return 2
    if "4" in phases and not shutil.which("claude"):
        log("phase 4 needs the claude CLI on PATH")
        return 2
    ref = references()[args.reference]
    failures: list[str] = []
    results: dict = {"base": {}, "head": {}}
    try:
        base_sha, head_sha = resolve(args.base, args.remote), resolve(args.head, args.remote)
        builds = {"base": build(args.root, base_sha), "head": build(args.root, base_sha, head_sha)}
        cache(args.root, ref)
    except StepFailed as exc:
        log(str(exc))
        return 2
    run = args.root / f"compare-{base_sha[:8]}-{head_sha[:8]}-{time.strftime('%Y%m%dT%H%M%S')}"
    token = None if args.no_platform else platform_token()
    meta = {
        "base": base_sha,
        "head": head_sha,
        "head_build": (builds["head"] / ".e2e-ready").read_text().strip(),
        "reference": args.reference,
        "commit": ref["commit"],
        "url": ref["url"],
        "phases": phases,
        "platform": "yes" if token else "no",
    }
    log(f"run {run}")

    def side(name: str) -> dict:
        out, path = {}, run / name
        for phase in phases:
            try:
                if phase == "1":
                    out["1"] = phase_audit(path, builds[name], args.root, ref, token)
                elif phase == "2":
                    out["2"] = phase_surface(path, builds[name], ref)
                elif phase == "4":
                    log(f"{name}: phase 4 (headless comply)")
                    out["4"] = phase_comply(path, builds[name], args.root, ref, args.model, args.timeout)
            except StepFailed as exc:
                failures.append(f"{name} phase {phase}: {exc}")
        return out

    with concurrent.futures.ThreadPoolExecutor(max_workers=2) as pool:
        futures = {name: pool.submit(side, name) for name in ("base", "head")}
        for name, future in futures.items():
            results[name] = future.result()

    diffs: dict = {}
    for phase in phases:
        if phase not in results["base"] or phase not in results["head"]:
            continue
        b, h = results["base"][phase], results["head"][phase]
        if phase == "1":
            diffs["1"] = diff_controls(b["controls"], h["controls"])
        elif phase == "2":
            diffs["2"] = diff_surface(b["frameworks"], h["frameworks"])
        elif phase == "4":
            diffs["4"] = compare_comply(b, h)

    (run / "compare.json").write_text(
        json.dumps({"meta": meta, "results": results, "diffs": diffs, "failures": failures}, indent=1, default=str)
    )
    report = render(meta, results, diffs, failures)
    (run / "compare.md").write_text(report)
    print(report)
    log(f"report: {run / 'compare.md'}")
    if failures:
        return 2
    return 1 if differs(diffs) else 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    parser.add_argument(
        "--root", type=Path, default=DEFAULT_ROOT, help="builds, copies and reports (default: %(default)s)"
    )
    parser.add_argument("--remote", default="upstream", help="remote for pr/NUMBER refs (default: %(default)s)")
    sub = parser.add_subparsers(dest="command", required=True)
    b = sub.add_parser("build", help="worktree and venv for a ref")
    b.add_argument("ref")
    b.set_defaults(func=cmd_build)
    sub.add_parser("prune", help="remove every build's worktree").set_defaults(func=cmd_prune)
    c = sub.add_parser("compare", help="run the phases on base and head and compare")
    c.add_argument("base")
    c.add_argument("head")
    c.add_argument("--phases", default="1,2", help="comma-separated, from 1,2,4 (default: %(default)s)")
    c.add_argument("--reference", default="wtf-frontend", help="from scripts/comply_replay.toml")
    c.add_argument("--no-platform", action="store_true", help="phase 1 without a platform token")
    c.add_argument("--model", help="claude model for phase 4 (default: the CLI's)")
    c.add_argument("--timeout", type=int, default=3600, help="seconds per phase 4 run")
    c.set_defaults(func=cmd_compare)
    args = parser.parse_args(argv)
    args.root = args.root.expanduser().resolve()
    return args.func(args)


if __name__ == "__main__":
    sys.exit(main())
