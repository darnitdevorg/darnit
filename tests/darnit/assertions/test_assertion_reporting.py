"""Every driver path reports assertion-backed results the same way (feature 040, US2, T041).

Until claims can be honored (US3), every claim is ``pending`` and the control
is evaluated normally; a claim never removes a control from the audit.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from darnit.cli import main as cli_main
from darnit.tools.audit import format_results_markdown, run_sieve_audit

CONTROL = "OSPS-DO-01.01"


@pytest.fixture(autouse=True)
def _quiet_cli(monkeypatch: pytest.MonkeyPatch) -> None:
    monkeypatch.setattr("darnit.cli.configure_logging", lambda level: None)


def _repo(tmp_path: Path, *, readme: bool) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    if readme:
        (path / "README.md").write_text("# repo\n", encoding="utf-8")
    subprocess.run(["git", "init", "--initial-branch=main", "-q"], cwd=path, check=True)
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/example/repo.git"], cwd=path, check=True)
    (path / ".project").mkdir()
    (path / ".project" / "darnit.yaml").write_text(
        f"controls:\n  {CONTROL}:\n    status: n/a\n    reason: docs live elsewhere\n    asserted_by: '@alice'\n",
        encoding="utf-8",
    )
    return path


def _result(results: list[dict]) -> dict:
    return next(r for r in results if r["id"] == CONTROL)


def _expected_assertion() -> dict:
    return {
        "outcome": "pending",
        "origin": "explicit_claim",
        "reason": "docs live elsewhere",
        "asserted_by": "@alice",
        "location": f".project/darnit.yaml:controls.{CONTROL}",
        "confirmation": None,
        "contradiction": None,
    }


def _run_sieve(repo: Path) -> list[dict]:
    results, _ = run_sieve_audit(
        owner="example",
        repo="repo",
        local_path=str(repo),
        default_branch="main",
        level=1,
        tags=["domain=DO"],
        framework_name="openssf-baseline",
    )
    return results


def _cli(repo: Path, capsys: pytest.CaptureFixture[str]) -> list[dict]:
    cli_main(["audit", str(repo), "-f", "openssf-baseline", "--include", CONTROL, "-o", "json", "--no-fail"])
    return json.loads(capsys.readouterr().out)["results"]


def _mcp_baseline(repo: Path) -> list[dict]:
    from darnit_baseline.tools import audit_openssf_baseline

    output = audit_openssf_baseline(local_path=str(repo), level=1, tags="domain=DO", output_format="json")
    return json.loads(output)["results"]


def _harness(repo: Path) -> list[dict]:
    from darnit.core.llm_step import LLMJudgment, MockLLMStep
    from darnit.harness.driver import HarnessRun

    run = HarnessRun(
        local_path=str(repo),
        framework_name="openssf-baseline",
        level=1,
        llm_step=MockLLMStep(LLMJudgment(outcome="inconclusive", confidence=0.0, reasoning="mock")),
        per_call_timeout_s=10,
        total_run_timeout_s=120,
    )
    return json.loads(asyncio.new_event_loop().run_until_complete(run.run()).to_json())["controls"]


def _mcp_builtin(repo: Path) -> list[dict]:
    from darnit.server.tools.builtin_audit import builtin_audit

    output = asyncio.new_event_loop().run_until_complete(
        builtin_audit(
            local_path=str(repo), level=1, output_format="json", tags="domain=DO", _framework_name="openssf-baseline"
        )
    )
    return json.loads(output)["results"]


@pytest.mark.integration
@pytest.mark.parametrize("driver", ["sieve", "cli", "mcp_baseline", "mcp_builtin", "harness"])
def test_claim_is_reported_pending_and_control_evaluated(
    driver: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    repo = _repo(tmp_path, readme=False)
    results = {
        "sieve": lambda: _run_sieve(repo),
        "cli": lambda: _cli(repo, capsys),
        "mcp_baseline": lambda: _mcp_baseline(repo),
        "mcp_builtin": lambda: _mcp_builtin(repo),
        "harness": lambda: _harness(repo),
    }[driver]()

    result = _result(results)
    assert result["status"] == "FAIL"
    assert result["assertion"] == _expected_assertion()


@pytest.mark.integration
def test_evaluated_control_keeps_its_status(tmp_path: Path) -> None:
    # Feature 041: a README's presence no longer concludes DO-01.01; the
    # control awaits a model judgment, and the pending claim does not replace
    # that status.
    result = _result(_run_sieve(_repo(tmp_path, readme=True)))

    assert result["status"] == "PENDING"
    assert result["pending"] == {"kind": "llm_judgment"}
    assert result["assertion"]["outcome"] == "pending"


@pytest.mark.integration
def test_unclaimed_controls_carry_no_assertion(tmp_path: Path) -> None:
    results = _run_sieve(_repo(tmp_path, readme=True))

    assert all("assertion" not in r for r in results if r["id"] != CONTROL)


@pytest.mark.unit
def test_markdown_names_the_claim() -> None:
    results = [
        {
            "id": CONTROL,
            "status": "FAIL",
            "details": "no README",
            "level": 1,
            "assertion": _expected_assertion(),
        }
    ]
    summary = {"PASS": 0, "FAIL": 1, "WARN": 0, "N/A": 0, "ERROR": 0, "PENDING": 0, "total": 1}

    md = format_results_markdown("example", "repo", results, summary, {1: False}, 1)

    assert "Asserted not applicable" in md
    assert "@alice" in md
    assert "docs live elsewhere" in md
    assert "pending" in md


@pytest.mark.unit
def test_markdown_shows_each_outcome_with_its_evidence() -> None:
    confirmation = {"confirmed_by": "alice", "confirmed_at": "2026-09-01T00:00:00Z", "expires_at": "2027-02-28T00:00:00Z"}
    contradiction = {
        "evidence_source": "context.has_releases detection (detect_pipeline:file_exists)",
        "observed_at": "2026-09-01T00:00:00Z",
        "summary": "has_releases detected as True, which contradicts the not-applicable claim",
    }
    results = [
        {"id": "A", "status": "N/A", "details": "", "level": 1, "assertion": {
            **_expected_assertion(), "outcome": "honored", "confirmation": confirmation}},
        {"id": "B", "status": "FAIL", "details": "", "level": 1, "assertion": {
            **_expected_assertion(), "outcome": "contradicted", "contradiction": contradiction}},
        {"id": "C", "status": "PASS", "details": "", "level": 1, "assertion": _expected_assertion()},
    ]
    summary = {"PASS": 1, "FAIL": 1, "WARN": 0, "N/A": 1, "ERROR": 0, "PENDING": 0, "total": 3}

    md = format_results_markdown("example", "repo", results, summary, {1: False}, 1)

    assert "Asserted not applicable, honored" in md
    assert "Confirmed* by alice" in md
    assert "contradicted by evidence" in md
    assert "has_releases detected as True" in md
    assert "pending confirmation" in md
    assert "1 not-applicable claim(s) pending confirmation" in md


@pytest.mark.integration
def test_claims_about_unknown_controls_are_reported(tmp_path: Path) -> None:
    from darnit.config.operator.loader import resolve_operator_config
    from darnit.tools.audit import _format_audit_metadata_markdown, audit_report_metadata

    repo = _repo(tmp_path, readme=True)
    (repo / ".project" / "darnit.yaml").write_text(
        "controls:\n  OSPS-XX-99.99:\n    status: n/a\n    reason: x\n", encoding="utf-8"
    )

    metadata = audit_report_metadata(resolve_operator_config(repo), str(repo), None, "openssf-baseline")

    assert metadata["unknown_assertions"] == [
        {
            "control_id": "OSPS-XX-99.99",
            "location": ".project/darnit.yaml:controls.OSPS-XX-99.99",
            "asserted_by": "repository content",
            "reason": "x",
        }
    ]
    assert "OSPS-XX-99.99" in "\n".join(_format_audit_metadata_markdown(metadata))
