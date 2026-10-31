"""Tests for developer testing scripts and E2E regression tracking flow."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from scripts.clean_and_install_dev import clean_artifacts
from scripts.run_dev_test_flow import (
    DevFlowReport,
    ProjectTestResult,
    evaluate_project_results,
    render_markdown_report,
)
from scripts.setup_dev_projects import (
    safe_rmtree,
    setup_all_projects,
)


@pytest.mark.unit
def test_setup_dev_projects_creates_valid_repos(tmp_path: Path) -> None:
    """Verify setup_all_projects creates git repos with required configuration and files."""
    dest = tmp_path / "projects"
    projects = setup_all_projects(dest)

    assert set(projects.keys()) == {"failing-empty", "partially-compliant", "passing-reference"}

    for name, p_path in projects.items():
        assert p_path.exists()
        assert (p_path / ".git").is_dir()
        assert (p_path / ".mcp.json").exists()
        assert (p_path / "CLAUDE.md").exists()
        assert (p_path / "expected_verdicts.json").exists()

        # Check git commit succeeded
        res = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=p_path,
            capture_output=True,
            text=True,
            check=True,
        )
        assert len(res.stdout.strip()) == 40


@pytest.mark.unit
def test_clean_artifacts_removes_caches_safely(tmp_path: Path) -> None:
    """Verify clean_artifacts removes cache and build directories without collateral damage."""
    dummy_repo = tmp_path / "repo"
    dummy_repo.mkdir()

    (dummy_repo / "dist").mkdir()
    (dummy_repo / ".pytest_cache").mkdir()
    (dummy_repo / ".ruff_cache").mkdir()
    src_dir = dummy_repo / "src" / "__pycache__"
    src_dir.mkdir(parents=True)
    (src_dir / "app.cpython-312.pyc").write_text("bytecode")

    source_file = dummy_repo / "src" / "app.py"
    source_file.write_text("print('clean')")

    clean_artifacts(dummy_repo, recreate_venv=False)

    assert not (dummy_repo / "dist").exists()
    assert not (dummy_repo / ".pytest_cache").exists()
    assert not (dummy_repo / ".ruff_cache").exists()
    assert not src_dir.exists()
    assert source_file.exists()


@pytest.mark.unit
def test_evaluate_project_results(tmp_path: Path) -> None:
    """Verify evaluation against expected verdicts, bounds, and error handling."""
    proj_dir = tmp_path / "test_proj"
    proj_dir.mkdir()
    expected_spec = {
        "expected": {
            "OSPS-DO-01.01": "FAIL",
            "OSPS-LE-03.01": "PASS",
        },
        "max_failures": 2,
        "max_errors": 1,
    }
    (proj_dir / "expected_verdicts.json").write_text(json.dumps(expected_spec), encoding="utf-8")

    # 1. Matching case
    audit_data_match = {
        "summary": {"total": 10, "pass": 6, "fail": 2, "warn": 2, "error": 0, "pending": 0},
        "results": [
            {"id": "OSPS-DO-01.01", "status": "FAIL", "error_class": None},
            {"id": "OSPS-LE-03.01", "status": "PASS", "error_class": None},
        ],
    }
    res_match = evaluate_project_results("test_proj", proj_dir, audit_data_match, duration=1.23)
    assert res_match.passed_expectations is True
    assert len(res_match.notes) == 0
    assert all(c["matched"] for c in res_match.checks)

    # 2. Mismatch case
    audit_data_mismatch = {
        "summary": {"total": 10, "pass": 7, "fail": 1, "warn": 2, "error": 0, "pending": 0},
        "results": [
            {"id": "OSPS-DO-01.01", "status": "PASS", "error_class": None},
            {"id": "OSPS-LE-03.01", "status": "PASS", "error_class": None},
        ],
    }
    res_mismatch = evaluate_project_results("test_proj", proj_dir, audit_data_mismatch, duration=1.0)
    assert res_mismatch.passed_expectations is False
    assert any("OSPS-DO-01.01" in n for n in res_mismatch.notes)

    # 3. Error bound exceed case
    audit_data_errors = {
        "summary": {"total": 10, "pass": 6, "fail": 2, "warn": 0, "error": 5, "pending": 0},
        "results": [
            {"id": "OSPS-DO-01.01", "status": "FAIL", "error_class": None},
            {"id": "OSPS-LE-03.01", "status": "PASS", "error_class": None},
        ],
    }
    res_errors = evaluate_project_results("test_proj", proj_dir, audit_data_errors, duration=1.0)
    assert res_errors.passed_expectations is False
    assert any("Errors (5) exceeded max_errors" in n for n in res_errors.notes)


@pytest.mark.unit
def test_render_markdown_report() -> None:
    """Verify Markdown report generation format."""
    report = DevFlowReport(
        commit_sha="abcdef1234567890",
        timestamp="2026-10-30T12:00:00Z",
        python_version="3.12.0",
        platform="linux",
        install_duration_seconds=5.42,
        total_test_duration_seconds=15.30,
        all_passed=True,
        projects=[
            ProjectTestResult(
                project_name="failing-empty",
                duration_seconds=3.10,
                total_controls=26,
                passes=3,
                failures=12,
                warnings=5,
                errors=6,
                pending=0,
                checks=[{"control_id": "OSPS-DO-01.01", "expected": "FAIL", "actual": "FAIL", "matched": True}],
                passed_expectations=True,
                notes=[],
            )
        ],
    )

    md = render_markdown_report(report)
    assert "# Darnit Developer Testing & Regression Report" in md
    assert "`abcdef1234567890`" in md
    assert "PASSED" in md
    assert "| `failing-empty` |" in md


@pytest.mark.unit
def test_safe_rmtree_removes_readonly_files(tmp_path: Path) -> None:
    """Verify safe_rmtree cleans up read-only files without raising PermissionError."""
    import stat

    target = tmp_path / "readonly_dir"
    target.mkdir()
    ro_file = target / "readonly.txt"
    ro_file.write_text("locked")
    ro_file.chmod(stat.S_IREAD)

    assert target.exists()
    safe_rmtree(target)
    assert not target.exists()


@pytest.mark.unit
def test_evaluate_project_results_harness_format(tmp_path: Path) -> None:
    """Verify evaluation handles real harness report schema with controls and HarnessSummary."""
    proj_dir = tmp_path / "harness_proj"
    proj_dir.mkdir()
    expected_spec = {
        "expected": {
            "OSPS-DO-01.01": "FAIL",
            "OSPS-LE-03.01": "PASS",
        },
        "max_failures": 3,
    }
    (proj_dir / "expected_verdicts.json").write_text(json.dumps(expected_spec), encoding="utf-8")

    # Real HarnessReport schema: controls with "id" and "status", HarnessSummary without "pending"
    harness_data = {
        "summary": {"total": 5, "pass": 2, "fail": 2, "warn": 1, "n_a": 0, "error": 0},
        "controls": [
            {"id": "OSPS-DO-01.01", "status": "FAIL", "error_class": None},
            {"id": "OSPS-LE-03.01", "status": "PASS", "error_class": None},
        ],
    }

    result = evaluate_project_results("harness_proj", proj_dir, harness_data, duration=2.5)
    assert result.project_name == "harness_proj"
    assert result.failures == 2
    assert result.passes == 2
    assert result.passed_expectations is True
