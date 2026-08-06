"""Fixtures for tests/darnit/harness/.

Feature 026 T020. Provides:
- `mock_llm_step`: a MockLLMStep returning a canned LLMJudgment
- `minimal_llm_repo_tree(tmp_path)`: copies the fixture repo + git-inits it
- `harness_run_factory`: constructs a HarnessRun with the mock LLM injected
- Env-var isolation: every test starts with ANTHROPIC_API_KEY set so the
  credential check passes; tests that want to exercise missing-key
  behavior monkeypatch it away explicitly
"""

from __future__ import annotations

import shutil
import subprocess
from collections.abc import Callable
from pathlib import Path

import pytest

from darnit.core.llm_step import LLMJudgment, MockLLMStep
from darnit.harness.answer_sources import AnswerResolver
from darnit.harness.driver import HarnessRun

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _ensure_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: set a fake ANTHROPIC_API_KEY so credential check passes.

    Tests that explicitly need the missing-key case monkeypatch.delenv().
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")


@pytest.fixture
def mock_llm_step() -> MockLLMStep:
    """Canned LLMJudgment: yes / high confidence / plausible reasoning."""
    judgment = LLMJudgment(
        outcome="yes",
        confidence=0.95,
        reasoning="mock: found security@example.com in README",
        raw_response={"provider": "mock"},
    )
    return MockLLMStep(judgment)


@pytest.fixture
def minimal_llm_repo_tree(tmp_path: Path) -> Path:
    """Copy the minimal_llm_repo fixture into tmp_path and git-init it.

    Mirrors feature 024's copy pattern so detect_repo_from_git succeeds.
    """
    src = FIXTURES_DIR / "minimal_llm_repo"
    dest = tmp_path / "minimal_llm_repo"
    if dest.exists():
        shutil.rmtree(dest)
    shutil.copytree(src, dest)
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
def harness_run_factory(
    mock_llm_step: MockLLMStep,
) -> Callable[..., HarnessRun]:
    """Return a factory constructing a HarnessRun with the mock LLM injected.

    Callers pass `local_path` and any optional overrides.
    """

    def _factory(
        local_path: str,
        *,
        answer_resolver: AnswerResolver | None = None,
        level: int = 1,
    ) -> HarnessRun:
        return HarnessRun(
            local_path=local_path,
            level=level,
            answer_resolver=answer_resolver or AnswerResolver(),
            llm_step=mock_llm_step,
            per_call_timeout_s=10,
            total_run_timeout_s=60,
        )

    return _factory
