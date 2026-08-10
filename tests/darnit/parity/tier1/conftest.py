"""Tier 1 conftest: fixture auto-discovery + prepared-fixture helper (T012).

Auto-discovers `tests/darnit/parity/fixtures/<name>/.baseline.toml` and
parametrizes `fixture_dir`. Provides `prepared_fixture`, `mcp_tool_result`,
and `harness_result` pytest fixtures that materialize a git-initialized
copy of the fixture and run both audit paths against it.

HC1 fix: fixtures are copied to `tmp_path` and git-initialized before
either path is invoked, because `HarnessRun._initial_audit` ->
`prepare_audit` -> `detect_repo_from_git` requires a git repo.
"""

from __future__ import annotations

import asyncio
import json
import shutil
import subprocess
from pathlib import Path

import pytest

from darnit.core.llm_step import LLMJudgment, MockLLMStep
from darnit.harness.driver import HarnessRun
from darnit_baseline.tools import audit_openssf_baseline
from tests.darnit.parity.tier1.comparator import AuditResult

FIXTURES_DIR = Path(__file__).parent.parent / "fixtures"


@pytest.fixture(autouse=True)
def _ensure_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """The harness's credential check requires ANTHROPIC_API_KEY; set a
    dummy value so tests that don't exercise missing-key paths run cleanly."""
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")


def _discover_fixtures() -> list[Path]:
    if not FIXTURES_DIR.exists():
        return []
    return sorted(p for p in FIXTURES_DIR.iterdir() if p.is_dir() and (p / ".baseline.toml").exists())


def pytest_generate_tests(metafunc: pytest.Metafunc) -> None:
    """Auto-discover fixtures for any test that requests `fixture_dir`."""
    if "fixture_dir" in metafunc.fixturenames:
        fixtures = _discover_fixtures()
        metafunc.parametrize(
            "fixture_dir",
            fixtures,
            ids=[f.name for f in fixtures],
        )


@pytest.fixture
def prepared_fixture(
    fixture_dir: Path,
    tmp_path: Path,
) -> Path:
    """Copy the fixture into tmp_path and git-init it (HC1).

    HarnessRun and audit_openssf_baseline both call prepare_audit which
    requires the target directory to be a git repo. Static fixture dirs
    under tests/darnit/parity/fixtures/ are NOT git-initialized, so we
    copy them to a tmp_path and initialize there.
    """
    dest = tmp_path / fixture_dir.name
    shutil.copytree(fixture_dir, dest)
    subprocess.run(
        ["git", "init", "--initial-branch=main", "-q"],
        cwd=dest,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=test",
            "-c",
            "user.email=test@example.com",
            "commit",
            "--allow-empty",
            "-q",
            "-m",
            "init",
        ],
        cwd=dest,
        check=True,
        capture_output=True,
    )
    subprocess.run(
        [
            "git",
            "remote",
            "add",
            "origin",
            "https://github.com/fake-owner/fake-repo.git",
        ],
        cwd=dest,
        check=True,
        capture_output=True,
    )
    return dest


@pytest.fixture
def mcp_tool_result(prepared_fixture: Path) -> AuditResult:
    """Invoke audit_openssf_baseline directly; return normalized AuditResult."""
    raw = audit_openssf_baseline(
        local_path=str(prepared_fixture),
        level=3,
        output_format="json",
        auto_init_config=False,
        attest=False,
        prefer_upstream=False,
    )
    payload = json.loads(raw)
    return AuditResult.from_mcp_json(payload)


@pytest.fixture
def harness_result(prepared_fixture: Path) -> AuditResult:
    """Run HarnessRun with MockLLMStep=inconclusive; return normalized AuditResult."""
    mock = MockLLMStep(
        LLMJudgment(
            outcome="inconclusive",
            confidence=0.0,
            reasoning="tier1-mock: no LLM decision",
        )
    )
    run = HarnessRun(
        local_path=str(prepared_fixture),
        level=3,
        llm_step=mock,
        per_call_timeout_s=5,
        total_run_timeout_s=30,
    )
    report = asyncio.new_event_loop().run_until_complete(run.run())
    return AuditResult.from_harness_report(report)
