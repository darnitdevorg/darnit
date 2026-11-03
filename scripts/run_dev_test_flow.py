#!/usr/bin/env python3
"""Run end-to-end developer testing and regression tracking for Darnit.

Flow brainstormed in the October 27, 2026 Darnit Community Meeting
(local and automated testing agenda by Mike Lieberman and Jaydeep Pokhariya).

1. Optional clean install and installation time recording (--clean).
2. Generating dedicated test projects with known expected outcomes:
   - failing-empty: minimal repo intentionally failing documentation and license controls.
   - partially-compliant: repo with basic docs/license but missing security policies.
   - passing-reference: well-formed reference repo with clean baseline structure.
3. Running Darnit audit against each project and recording execution duration.
4. Comparing control-level PASS/FAIL verdicts against expected ground truth.
5. Tracking regressions in a structured JSON and Markdown report with commit SHA.

Usage:
    uv run python scripts/run_dev_test_flow.py [--dest PATH] [--report-file PATH] [--clean] [--mode audit|harness] [--verbose]

Exit Codes:
    0 = All test projects met expected compliance criteria, no regressions
    1 = Regression detected or verification failed
"""

from __future__ import annotations

import argparse
import json
import logging
import subprocess
import sys
import tempfile
import time
from dataclasses import asdict, dataclass
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("run_dev_test_flow")

REPO_ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(REPO_ROOT))

from scripts.setup_dev_projects import (  # noqa: E402
    create_failing_empty_project,
    create_partially_compliant_project,
    create_passing_reference_project,
    safe_rmtree,
)


@dataclass
class ProjectTestResult:
    project_name: str
    duration_seconds: float
    total_controls: int
    passes: int
    failures: int
    warnings: int
    errors: int
    pending: int
    checks: list[dict[str, Any]]
    passed_expectations: bool
    notes: list[str]


@dataclass
class DevFlowReport:
    commit_sha: str
    timestamp: str
    python_version: str
    platform: str
    install_duration_seconds: float | None
    total_test_duration_seconds: float
    all_passed: bool
    projects: list[ProjectTestResult]


def get_git_commit_sha(repo_root: Path) -> str:
    """Retrieve current commit SHA."""
    try:
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=repo_root,
            capture_output=True,
            text=True,
            check=True,
        )
        return res.stdout.strip()
    except Exception:
        return "unknown"


def run_audit(project_path: Path, mode: str = "audit") -> tuple[dict[str, Any], float]:
    """Execute darnit audit or harness in JSON mode against project_path and measure duration."""
    start = time.perf_counter()
    if mode == "harness":
        cmd = [
            "uv",
            "run",
            "darnit",
            "harness",
            "--framework",
            "openssf-baseline",
            "--format",
            "json",
            str(project_path),
        ]
    else:
        cmd = [
            "uv",
            "run",
            "darnit",
            "-q",
            "audit",
            "--no-fail",
            "--output",
            "json",
            "--framework",
            "openssf-baseline",
            str(project_path),
        ]
    res = subprocess.run(
        cmd,
        cwd=REPO_ROOT,
        capture_output=True,
        text=True,
        encoding="utf-8",
    )
    duration = time.perf_counter() - start
    if res.returncode != 0 and not res.stdout.strip():
        raise RuntimeError(f"{mode.capitalize()} command failed (exit {res.returncode}): {res.stderr}")

    try:
        data = json.loads(res.stdout)
    except json.JSONDecodeError as err:
        raise RuntimeError(f"Failed to parse {mode} JSON output: {err}\nOutput was:\n{res.stdout[:500]}") from err

    return data, duration


def evaluate_project_results(
    project_name: str,
    project_path: Path,
    audit_data: dict[str, Any],
    duration: float,
) -> ProjectTestResult:
    """Evaluate audit results against expected verdicts for the project."""
    summary = audit_data.get("summary", {})
    results = audit_data.get("results") or audit_data.get("controls") or []
    by_id = {r.get("id"): r for r in results if isinstance(r, dict) and r.get("id")}

    notes: list[str] = []
    checks: list[dict[str, Any]] = []
    passed = True

    # Check for broken evaluation
    broken_evals = [r.get("id") for r in results if isinstance(r, dict) and r.get("error_class") == "evaluation"]
    if broken_evals:
        notes.append(f"Broken evaluation error_class on: {', '.join(filter(None, broken_evals))}")
        passed = False

    # Read ground truth expectations
    expected_file = project_path / "expected_verdicts.json"
    fail_count = summary.get("fail", 0)
    error_count = summary.get("error", 0)

    if expected_file.exists():
        expected_spec = json.loads(expected_file.read_text(encoding="utf-8"))
        expected_map: dict[str, Any] = expected_spec.get("expected", {})

        for control_id, exp_status in expected_map.items():
            actual_entry = by_id.get(control_id)
            actual_status = actual_entry.get("status") if actual_entry else "MISSING"

            matched = False
            if isinstance(exp_status, list):
                matched = actual_status in exp_status
            elif exp_status == "NOT_PASS":
                matched = actual_status in ("FAIL", "WARN", "PENDING")
            else:
                matched = actual_status == exp_status

            checks.append(
                {
                    "control_id": control_id,
                    "expected": ", ".join(exp_status) if isinstance(exp_status, list) else exp_status,
                    "actual": actual_status,
                    "matched": matched,
                }
            )
            if not matched:
                passed = False
                exp_desc = "/".join(exp_status) if isinstance(exp_status, list) else exp_status
                notes.append(f"{control_id}: expected {exp_desc}, got {actual_status}")

        # Enforce bounds from expected_spec
        max_failures = expected_spec.get("max_failures")
        if max_failures is not None and fail_count > max_failures:
            notes.append(f"Failures ({fail_count}) exceeded max_failures ({max_failures})")
            passed = False

        min_failures = expected_spec.get("min_failures")
        if min_failures is not None and fail_count < min_failures:
            notes.append(f"Failures ({fail_count}) below min_failures ({min_failures})")
            passed = False

        max_errors = expected_spec.get("max_errors")
        if max_errors is not None and error_count > max_errors:
            notes.append(f"Errors ({error_count}) exceeded max_errors ({max_errors})")
            passed = False
    else:
        # Fallback assertions if no expected_verdicts.json
        if project_name == "failing-empty" and fail_count == 0:
            notes.append("Expected failing-empty to have failures, got 0")
            passed = False
        elif project_name == "partially-compliant" and fail_count == 0:
            notes.append("Expected partially-compliant to have some failures, got 0")
            passed = False
        elif project_name == "passing-reference" and fail_count > 0:
            notes.append(f"Expected passing-reference to have 0 failures, got {fail_count}")
            passed = False

    return ProjectTestResult(
        project_name=project_name,
        duration_seconds=duration,
        total_controls=summary.get("total", len(results)),
        passes=summary.get("pass", 0),
        failures=fail_count,
        warnings=summary.get("warn", 0),
        errors=error_count,
        pending=summary.get("pending", 0),
        checks=checks,
        passed_expectations=passed,
        notes=notes,
    )


def render_markdown_report(report: DevFlowReport) -> str:
    """Render human-readable Markdown regression tracking report."""
    lines = [
        "# Darnit Developer Testing & Regression Report",
        "",
        f"- **Commit SHA**: `{report.commit_sha}`",
        f"- **Timestamp**: {report.timestamp}",
        f"- **Platform**: {report.platform} (Python {report.python_version})",
        f"- **Overall Status**: **{'PASSED' if report.all_passed else 'FAILED'}**",
        f"- **Total Test Duration**: {report.total_test_duration_seconds:.2f}s",
    ]
    if report.install_duration_seconds is not None:
        lines.append(f"- **Environment Sync Time**: {report.install_duration_seconds:.2f}s")
    lines.append("")

    lines.append("## Projects Summary")
    lines.append("")
    lines.append("| Project | Verdict | Pass | Fail | Warn | Error | Pending | Duration |")
    lines.append("|---|---|---|---|---|---|---|---|")
    for p in report.projects:
        status_badge = "PASS" if p.passed_expectations else "FAIL"
        lines.append(
            f"| `{p.project_name}` | {status_badge} | {p.passes} | {p.failures} | "
            f"{p.warnings} | {p.errors} | {p.pending} | {p.duration_seconds:.2f}s |"
        )
    lines.append("")

    lines.append("## Control Assertions")
    lines.append("")
    lines.append("| Project | Control | Expected | Actual | Matched |")
    lines.append("|---|---|---|---|---|")
    for p in report.projects:
        for c in p.checks:
            matched_str = "yes" if c["matched"] else "**NO**"
            lines.append(
                f"| `{p.project_name}` | `{c['control_id']}` | {c['expected']} | {c['actual']} | {matched_str} |"
            )
    lines.append("")

    if not report.all_passed:
        lines.append("## Regressions & Discrepancies")
        lines.append("")
        for p in report.projects:
            if p.notes:
                lines.append(f"### {p.project_name}")
                for note in p.notes:
                    lines.append(f"- {note}")
                lines.append("")

    return "\n".join(lines)


def run_flow(
    dest_dir: Path | None = None,
    clean_install: bool = False,
    report_file: Path | None = None,
    mode: str = "audit",
    verbose: bool = False,
) -> bool:
    """Execute the full dev test flow."""
    if verbose:
        logger.setLevel(logging.DEBUG)
        logging.getLogger().setLevel(logging.DEBUG)

    temp_dest: Path | None = None
    if dest_dir is None:
        temp_dest = Path(tempfile.mkdtemp(prefix="darnit-flow-"))
        target_dir = temp_dest
    else:
        target_dir = dest_dir
        target_dir.mkdir(parents=True, exist_ok=True)

    try:
        install_time: float | None = None
        if clean_install:
            from scripts.clean_and_install_dev import (
                clean_artifacts,
                sync_environment,
                verify_environment,
            )

            clean_artifacts(REPO_ROOT)
            install_time = sync_environment(REPO_ROOT)
            verify_environment(REPO_ROOT)

        commit_sha = get_git_commit_sha(REPO_ROOT)
        start_all = time.perf_counter()

        logger.info("Setting up dedicated test projects in %s...", target_dir)
        projects = {
            "failing-empty": create_failing_empty_project(target_dir),
            "partially-compliant": create_partially_compliant_project(target_dir),
            "passing-reference": create_passing_reference_project(target_dir),
        }

        project_results: list[ProjectTestResult] = []
        for name, path in projects.items():
            logger.info("Running baseline %s against %s...", mode, name)
            audit_data, duration = run_audit(path, mode=mode)
            res = evaluate_project_results(name, path, audit_data, duration)
            project_results.append(res)
            logger.info("  %s evaluated in %.2fs: %s", name, duration, "PASS" if res.passed_expectations else "FAIL")
            if verbose:
                for c in res.checks:
                    logger.debug(
                        "    [%s] %s: actual=%s expected=%s",
                        "OK" if c["matched"] else "FAIL",
                        c["control_id"],
                        c["actual"],
                        c["expected"],
                    )

        total_duration = time.perf_counter() - start_all
        all_passed = all(p.passed_expectations for p in project_results)

        report = DevFlowReport(
            commit_sha=commit_sha,
            timestamp=datetime.now(UTC).isoformat(),
            python_version=sys.version.split()[0],
            platform=sys.platform,
            install_duration_seconds=install_time,
            total_test_duration_seconds=total_duration,
            all_passed=all_passed,
            projects=project_results,
        )

        md_output = render_markdown_report(report)
        print("\n" + md_output)

        if report_file is not None:
            report_file.parent.mkdir(parents=True, exist_ok=True)
            if report_file.suffix == ".json":
                report_file.write_text(json.dumps(asdict(report), indent=2), encoding="utf-8")
            else:
                report_file.write_text(md_output, encoding="utf-8")
            logger.info("Report saved to %s", report_file)

        return all_passed
    finally:
        if temp_dest is not None:
            safe_rmtree(temp_dest)


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--dest", type=Path, default=None, help="Destination directory for test projects")
    parser.add_argument("--report-file", type=Path, default=None, help="Path to write report (Markdown or JSON)")
    parser.add_argument(
        "--clean",
        action="store_true",
        help="Clean build caches and run fresh uv sync before testing (opt-in)",
    )
    parser.add_argument(
        "--mode",
        choices=["audit", "harness"],
        default="audit",
        help="Execution mode: 'audit' (offline debug, default) or 'harness' (LLM in-band driver)",
    )
    parser.add_argument("--verbose", action="store_true", help="Verbose logging")
    args = parser.parse_args()

    success = run_flow(
        dest_dir=args.dest,
        clean_install=args.clean,
        report_file=args.report_file,
        mode=args.mode,
        verbose=args.verbose,
    )
    sys.exit(0 if success else 1)


if __name__ == "__main__":
    main()
