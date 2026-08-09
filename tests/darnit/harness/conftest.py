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
from darnit.harness.question_resolvers import Answer, QuestionResolver

FIXTURES_DIR = Path(__file__).parent / "fixtures"


@pytest.fixture(autouse=True)
def _ensure_api_key(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: set a fake ANTHROPIC_API_KEY so credential check passes.

    Tests that explicitly need the missing-key case monkeypatch.delenv().
    """
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")


@pytest.fixture(autouse=True)
def _stub_framework_pending(monkeypatch: pytest.MonkeyPatch) -> None:
    """Default: stub `HarnessRun._enumerate_framework_pending` to `[]`.

    Feature 027 QuestionResolver tests (and other harness tests) assemble
    synthesized fake results and count how many end up answered/pending.
    Once PR #365 wired the framework's own `get_pending_context` into
    `_collect_unanswered`, running against a real .baseline.toml fixture
    starts emitting real per-key questions -- polluting those counts.
    Tests that want the enumerator active un-stub via `monkeypatch.undo()`
    or set `run._enumerate_framework_pending = <real fn>`.
    """
    monkeypatch.setattr(
        HarnessRun,
        "_enumerate_framework_pending",
        lambda self: [],
    )


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


# ---------------------------------------------------------------------------
# Feature 027: QuestionResolver fixtures
# ---------------------------------------------------------------------------


class _MockAnsweringResolver:
    """Returns a fixed Answer to every question."""

    def __init__(self, name: str = "mock_answering", value: str = "mock-answer") -> None:
        self.name = name
        self._value = value

    async def resolve(self, question: object) -> Answer | None:
        return Answer(value=self._value, origin=self.name)


class _MockSkippingResolver:
    """Returns None to every question."""

    def __init__(self, name: str = "mock_skipping") -> None:
        self.name = name

    async def resolve(self, question: object) -> Answer | None:
        return None


class _MockErroringResolver:
    """Raises RuntimeError on every resolve()."""

    def __init__(
        self,
        name: str = "mock_erroring",
        exception_message: str = "mock error",
    ) -> None:
        self.name = name
        self._msg = exception_message

    async def resolve(self, question: object) -> Answer | None:
        raise RuntimeError(self._msg)


@pytest.fixture
def mock_answering_resolver() -> QuestionResolver:
    return _MockAnsweringResolver()


@pytest.fixture
def mock_skipping_resolver() -> QuestionResolver:
    return _MockSkippingResolver()


@pytest.fixture
def mock_erroring_resolver() -> Callable[..., QuestionResolver]:
    def _factory(exception_message: str = "mock error") -> QuestionResolver:
        return _MockErroringResolver(exception_message=exception_message)

    return _factory
