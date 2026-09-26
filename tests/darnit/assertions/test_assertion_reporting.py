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


def _repo(tmp_path: Path, *, readme: bool, claim_file: str) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    if readme:
        (path / "README.md").write_text("# repo\n", encoding="utf-8")
    subprocess.run(["git", "init", "--initial-branch=main", "-q"], cwd=path, check=True)
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/example/repo.git"], cwd=path, check=True)
    if claim_file == "project":
        (path / ".project").mkdir()
        (path / ".project" / "darnit.yaml").write_text(
            f"controls:\n  {CONTROL}:\n    status: n/a\n    reason: docs live elsewhere\n    asserted_by: '@alice'\n",
            encoding="utf-8",
        )
    else:
        (path / ".baseline.toml").write_text(
            f'[controls."{CONTROL}"]\nstatus = "n/a"\nreason = "docs live elsewhere"\n', encoding="utf-8"
        )
    return path


def _result(results: list[dict]) -> dict:
    return next(r for r in results if r["id"] == CONTROL)


def _expected_assertion(claim_file: str) -> dict:
    location = ".project/darnit.yaml" if claim_file == "project" else ".baseline.toml"
    return {
        "outcome": "pending",
        "origin": "explicit_claim",
        "reason": "docs live elsewhere",
        "asserted_by": "@alice" if claim_file == "project" else "repository content",
        "location": f"{location}:controls.{CONTROL}",
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
@pytest.mark.parametrize("claim_file", ["project", "baseline"])
@pytest.mark.parametrize("driver", ["sieve", "cli", "mcp_baseline", "mcp_builtin", "harness"])
def test_claim_is_reported_pending_and_control_evaluated(
    driver: str,
    claim_file: str,
    tmp_path: Path,
    capsys: pytest.CaptureFixture[str],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")
    repo = _repo(tmp_path, readme=False, claim_file=claim_file)
    results = {
        "sieve": lambda: _run_sieve(repo),
        "cli": lambda: _cli(repo, capsys),
        "mcp_baseline": lambda: _mcp_baseline(repo),
        "mcp_builtin": lambda: _mcp_builtin(repo),
        "harness": lambda: _harness(repo),
    }[driver]()

    result = _result(results)
    assert result["status"] == "FAIL"
    assert result["assertion"] == _expected_assertion(claim_file)


@pytest.mark.integration
def test_passing_control_keeps_its_status(tmp_path: Path) -> None:
    result = _result(_run_sieve(_repo(tmp_path, readme=True, claim_file="project")))

    assert result["status"] == "PASS"
    assert result["assertion"]["outcome"] == "pending"


@pytest.mark.integration
def test_unclaimed_controls_carry_no_assertion(tmp_path: Path) -> None:
    results = _run_sieve(_repo(tmp_path, readme=True, claim_file="project"))

    assert all("assertion" not in r for r in results if r["id"] != CONTROL)


@pytest.mark.unit
def test_markdown_names_the_claim() -> None:
    results = [
        {
            "id": CONTROL,
            "status": "FAIL",
            "details": "no README",
            "level": 1,
            "assertion": _expected_assertion("project"),
        }
    ]
    summary = {"PASS": 0, "FAIL": 1, "WARN": 0, "N/A": 0, "ERROR": 0, "PENDING_LLM": 0, "total": 1}

    md = format_results_markdown("example", "repo", results, summary, {1: False}, 1)

    assert "Asserted not applicable" in md
    assert "@alice" in md
    assert "docs live elsewhere" in md
    assert "pending" in md
