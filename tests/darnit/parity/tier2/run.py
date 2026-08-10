"""Tier 2 runner entrypoint (feature 028 T021).

Invoked from the manual-dispatch GitHub Actions workflow. For each fixture:

  1. Capture MCP tool JSON via direct Python call.
  2. Invoke the /darnit-audit skill via the Claude Agent SDK.
  3. Parse the skill's final assistant message.
  4. Run `diff()` and write per-fixture artifacts.
  5. Aggregate outcomes into an exit code per contract T2-13.

Exit codes:
  0 -- success (every fixture agrees)
  1 -- at least one fixture had a skill-vs-tool disagreement
  2 -- at least one fixture had unparseable skill output
  3 -- setup error (missing key, missing fixtures)
  4 -- rate limit exhausted (not automated; documented for follow-up)

`--dry-run` stubs the SDK client with a canned response so the runner
can be exercised offline (used by the config workflow test).
"""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import sys
from pathlib import Path

from tests.darnit.parity.tier1.comparator import AuditResult
from tests.darnit.parity.tier2.artifact_writer import write_fixture_artifacts
from tests.darnit.parity.tier2.claude_agent_sdk_client import (
    SetupError,
    SkillInvocationResult,
)
from tests.darnit.parity.tier2.diff import diff
from tests.darnit.parity.tier2.skill_markdown_parser import SkillReport

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"
DEFAULT_ARTIFACT_ROOT = Path("parity-artifacts")


def _discover_fixtures(fixture_glob: str) -> list[Path]:
    if not FIXTURES_DIR.exists():
        return []
    all_fixtures = sorted(p for p in FIXTURES_DIR.iterdir() if p.is_dir() and (p / ".baseline.toml").exists())
    if fixture_glob == "*":
        return all_fixtures
    import fnmatch

    return [p for p in all_fixtures if fnmatch.fnmatch(p.name, fixture_glob)]


def _run_mcp_tool(fixture_dir: Path) -> tuple[str, AuditResult]:
    """Invoke the MCP tool; return (raw_json_str, normalized_result)."""
    from darnit_baseline.tools import audit_openssf_baseline

    raw = audit_openssf_baseline(
        local_path=str(fixture_dir),
        level=3,
        output_format="json",
        auto_init_config=False,
        attest=False,
        prefer_upstream=False,
    )
    return raw, AuditResult.from_mcp_json(json.loads(raw))


async def _run_skill(
    fixture_dir: Path,
    dry_run: bool,
) -> SkillInvocationResult:
    if dry_run:
        # Stub: return a canned Markdown summary that the parser can extract.
        return SkillInvocationResult(
            final_message=("# Dry-Run Skill Output\n\nPassed: 0\nFailed: 0\nWarned: 0\n\nNo controls to summarize."),
            model="dry-run",
            turn_count=0,
            metadata={"dry_run": True},
        )
    from tests.darnit.parity.tier2.claude_agent_sdk_client import invoke_skill

    return await invoke_skill(fixture_dir=fixture_dir)


def _write_step_summary(text: str) -> None:
    """Append `text` to GITHUB_STEP_SUMMARY if set. No-op otherwise."""
    path = os.environ.get("GITHUB_STEP_SUMMARY")
    if not path:
        return
    with open(path, "a") as f:
        f.write(text + "\n")


def _preflight_summary(fixture_glob: str) -> None:
    """T2-7/T2-8: preflight audit line BEFORE consuming the API key."""
    actor = os.environ.get("GITHUB_ACTOR", "<local>")
    sha = os.environ.get("GITHUB_SHA", "<local>")
    line = f"Tier 2 parity preflight: actor={actor} sha={sha} fixture_glob={fixture_glob!r}"
    print(line, file=sys.stderr)
    _write_step_summary(line)


async def _run_one_fixture(
    fixture_dir: Path,
    artifact_root: Path,
    dry_run: bool,
) -> str:
    """Return the diff outcome string for this fixture."""
    mcp_raw, mcp_result = _run_mcp_tool(fixture_dir)
    skill_result = await _run_skill(fixture_dir, dry_run=dry_run)
    skill_report = SkillReport.parse(skill_result.final_message)
    diff_report = diff(mcp_result, skill_report, fixture_dir.name)

    write_fixture_artifacts(
        artifact_root=artifact_root,
        fixture_name=fixture_dir.name,
        mcp_json=mcp_raw,
        skill_markdown=skill_result.final_message,
        diff_md=diff_report.diff_markdown,
        metadata={
            "model": skill_result.model,
            "turn_count": skill_result.turn_count,
            "dry_run": dry_run,
        },
    )
    return diff_report.outcome


async def _main_async(args: argparse.Namespace) -> int:
    _preflight_summary(args.fixture_glob)

    artifact_root = Path(args.artifact_dir)
    fixtures = _discover_fixtures(args.fixture_glob)
    if not fixtures:
        print(
            f"Tier 2: no fixtures matched {args.fixture_glob!r} under {FIXTURES_DIR}",
            file=sys.stderr,
        )
        return 3  # setup error

    outcomes: dict[str, list[str]] = {
        "success": [],
        "per_control_disagree": [],
        "counts_disagree": [],
        "skill_unparseable": [],
    }

    for fixture_dir in fixtures:
        try:
            outcome = await _run_one_fixture(fixture_dir, artifact_root, args.dry_run)
        except SetupError as exc:
            print(f"Tier 2 setup error: {exc}", file=sys.stderr)
            _write_step_summary(f"setup_error: {exc}")
            return 3
        except Exception as exc:  # noqa: BLE001
            print(
                f"Tier 2 fixture {fixture_dir.name!r} raised {type(exc).__name__}: {exc}",
                file=sys.stderr,
            )
            outcomes.setdefault("errored", []).append(fixture_dir.name)
            continue
        outcomes[outcome].append(fixture_dir.name)

    summary = (
        f"Tier 2 parity check: {len(fixtures)} fixtures checked, "
        f"{len(outcomes['per_control_disagree']) + len(outcomes['counts_disagree'])} drifts, "
        f"{len(outcomes['skill_unparseable'])} unparseable"
    )
    print(summary, file=sys.stderr)
    _write_step_summary(summary)

    # Compute exit code per T2-13.
    if outcomes.get("errored"):
        return 3
    if outcomes["per_control_disagree"] or outcomes["counts_disagree"]:
        return 1
    if outcomes["skill_unparseable"]:
        return 2
    return 0


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description="Feature 028 Tier 2 parity runner")
    parser.add_argument(
        "--fixture-glob",
        default="*",
        help="Glob to filter which fixtures under tests/darnit/parity/fixtures/ are run",
    )
    parser.add_argument(
        "--artifact-dir",
        default=str(DEFAULT_ARTIFACT_ROOT),
        help="Where to write per-fixture artifact bundles",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Stub the SDK invocation with a canned response (no API call)",
    )
    args = parser.parse_args(argv)

    return asyncio.new_event_loop().run_until_complete(_main_async(args))


if __name__ == "__main__":
    sys.exit(main())
