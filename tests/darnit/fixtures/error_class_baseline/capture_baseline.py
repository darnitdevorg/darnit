"""Capture the pre-feature output baseline for feature 036 SC-002 (task T001a).

Runs an audit against an all-deterministic fixture repo (two file-existence
controls, no network) and writes markdown / JSON / SARIF outputs to
tests/darnit/fixtures/error_class_baseline/.

MUST be run against unmodified `main` code. T027 diffs post-feature output
against these files; generating them from post-feature code would be circular.
"""

from __future__ import annotations

import json
import subprocess
import sys
import tempfile
from pathlib import Path

REPO_ROOT = Path(__file__).resolve().parents[0]
# Resolve the actual repo root by walking up to the dir containing pyproject.toml
_p = Path.cwd()
while _p != _p.parent and not (_p / "pyproject.toml").exists():
    _p = _p.parent
REPO_ROOT = _p

OUT_DIR = REPO_ROOT / "tests" / "darnit" / "fixtures" / "error_class_baseline"

# The two purely-deterministic controls the parity corpus already uses:
# README presence and LICENSE presence. No network, no LLM.
DETERMINISTIC_CONTROL_IDS = ["OSPS-DO-01.01", "OSPS-LE-03.01"]

FIXTURE_SRC = REPO_ROOT / "tests" / "darnit" / "parity" / "fixtures" / "mixed_repo"


def build_fixture(dest: Path) -> None:
    """Copy the mixed_repo fixture into a git repo at a stable path.

    A stable path matters: several formatters embed the repo path, so the
    baseline has to be reproducible. We use a fixed directory name under
    the system tempdir rather than a random mkdtemp suffix.
    """
    import shutil

    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(FIXTURE_SRC, dest)
    # Drop the parity harness config so it isn't mistaken for repo content.
    (dest / "parity.toml").unlink(missing_ok=True)

    subprocess.run(["git", "init", "-q"], cwd=dest, check=True)
    subprocess.run(
        ["git", "config", "user.email", "baseline@example.com"], cwd=dest, check=True
    )
    subprocess.run(["git", "config", "user.name", "Baseline"], cwd=dest, check=True)
    subprocess.run(["git", "add", "-A"], cwd=dest, check=True)
    subprocess.run(
        ["git", "commit", "-q", "-m", "baseline fixture"],
        cwd=dest,
        check=True,
        env={"GIT_COMMITTER_DATE": "2020-01-01T00:00:00Z", "PATH": "/usr/bin:/bin"},
    )


def scrub(text: str, fixture: Path) -> str:
    """Normalize machine- and run-varying fields out of formatter output.

    Two classes of variance, neither related to this feature:

    * The fixture's tempdir path (machine-dependent).
    * ``format_results_markdown``'s ``Generated At:`` wall-clock stamp
      (run-dependent). This is a genuine Tier 1 determinism gap in the
      markdown formatter -- audit reports can never be byte-for-byte
      reproducible while it embeds a timestamp. Out of scope for feature
      036; flagged as a follow-up on issue #418.
    * ``pass_history[].duration_ms`` (load-dependent). Reads 0 for these
      fast file-existence checks in practice, but nothing guarantees it,
      and a flaky baseline test is worse than no baseline test.
    """
    import re

    text = text.replace(str(fixture), "<FIXTURE>")
    text = re.sub(
        r"\*\*Generated At:\*\* \S+",
        "**Generated At:** <SCRUBBED-TIMESTAMP>",
        text,
    )
    text = re.sub(r'"duration_ms": \d+', '"duration_ms": "<SCRUBBED-DURATION>"', text)
    return text


def main() -> int:
    fixture = Path(tempfile.gettempdir()) / "darnit-036-baseline-fixture"
    build_fixture(fixture)

    from darnit.config.control_loader import load_controls_from_effective
    from darnit.config.merger import load_effective_config_by_name
    from darnit.filtering.filters import filter_controls
    from darnit.tools.audit import (
        calculate_compliance,
        format_results_markdown,
        run_sieve_audit,
    )

    config = load_effective_config_by_name("openssf-baseline", repo_path=fixture)
    all_controls = load_controls_from_effective(config)
    controls = filter_controls(
        all_controls, {}, set(DETERMINISTIC_CONTROL_IDS), None
    )
    print(f"filtered to {len(controls)} controls: {[c.control_id for c in controls]}")

    results, summary = run_sieve_audit(
        owner="baseline-owner",
        repo="baseline-repo",
        local_path=str(fixture),
        default_branch="main",
        level=1,
        controls=controls,
        apply_user_config=False,
        stop_on_llm=True,
    )

    # Sort for stability -- run_sieve_audit's ordering follows the registry.
    results = sorted(results, key=lambda r: r["id"])

    OUT_DIR.mkdir(parents=True, exist_ok=True)

    # --- markdown ---
    compliance = calculate_compliance(results, level=1)
    md = format_results_markdown(
        owner="baseline-owner",
        repo="baseline-repo",
        results=results,
        summary=summary,
        compliance=compliance,
        level=1,
        local_path=str(fixture),
        framework_name="openssf-baseline",
    )
    md = scrub(md, fixture)
    (OUT_DIR / "baseline.md").write_text(md, encoding="utf-8")

    # --- JSON (the CheckResult wire shape, which is what error_class lands in) ---
    scrubbed = json.loads(scrub(json.dumps(results), fixture))
    (OUT_DIR / "baseline.json").write_text(
        json.dumps(scrubbed, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    # --- SARIF ---
    from darnit_baseline.formatters.sarif import result_to_sarif_result

    sarif_results = [
        result_to_sarif_result(r, rule_index=i, repo="baseline-repo", local_path=str(fixture))
        for i, r in enumerate(results)
    ]
    sarif_scrubbed = json.loads(scrub(json.dumps(sarif_results), fixture))
    (OUT_DIR / "baseline.sarif").write_text(
        json.dumps(sarif_scrubbed, indent=2, sort_keys=True) + "\n", encoding="utf-8"
    )

    print(f"wrote baseline to {OUT_DIR}")
    for f in sorted(OUT_DIR.iterdir()):
        print(f"  {f.name}: {f.stat().st_size} bytes")
    print(f"\ncontrols captured: {[r['id'] for r in results]}")
    print(f"summary: {summary}")
    return 0


if __name__ == "__main__":
    sys.exit(main())
