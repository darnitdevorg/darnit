"""GitLab CI trust rules (feature 040, research R4)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from darnit.config.operator.schema import OperatorConfig
from darnit.trust.decision import decide_trust

REPO = "gitlab.com/group/sub/project"


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def _operator(*, rule: bool = True) -> OperatorConfig:
    trust: dict = {"repos": [REPO]}
    if rule:
        trust["ci"] = [{"event": "push-default-branch"}]
    return OperatorConfig.model_validate({"schema_version": 1, "trust": trust})


def _env(sha: str, **overrides: str) -> dict[str, str]:
    env = {
        "GITLAB_CI": "true",
        "CI_PIPELINE_SOURCE": "push",
        "CI_COMMIT_BRANCH": "main",
        "CI_DEFAULT_BRANCH": "main",
        "CI_SERVER_HOST": "gitlab.com",
        "CI_PROJECT_PATH": "Group/Sub/Project",
        "CI_COMMIT_SHA": sha,
    }
    env.update(overrides)
    return {k: v for k, v in env.items() if v is not None}


@pytest.mark.unit
class TestGitLab:
    def test_default_branch_push_is_trusted(self, temp_git_repo: Path) -> None:
        decision = decide_trust(None, _operator(), temp_git_repo, env=_env(_head(temp_git_repo)))

        assert decision.trusted is True
        assert decision.reason == "ci: push to default branch"
        assert decision.repository.canonical == REPO
        assert decision.ci_facts["platform"] == "gitlab-ci"
        assert decision.ci_facts["event"] == "push"

    def test_untrusted_without_rule(self, temp_git_repo: Path) -> None:
        decision = decide_trust(None, _operator(rule=False), temp_git_repo, env=_env(_head(temp_git_repo)))

        assert decision.trusted is False

    def test_other_branch_is_untrusted(self, temp_git_repo: Path) -> None:
        env = _env(_head(temp_git_repo), CI_COMMIT_BRANCH="feature")
        decision = decide_trust(None, _operator(), temp_git_repo, env=env)

        assert decision.trusted is False
        assert decision.reason == "ci: push to non-default branch"

    def test_merge_request_context_is_untrusted(self, temp_git_repo: Path) -> None:
        env = _env(_head(temp_git_repo), CI_MERGE_REQUEST_IID="7")
        decision = decide_trust(None, _operator(), temp_git_repo, env=env)

        assert decision.trusted is False
        assert decision.reason == "ci: merge request"

    def test_fork_merge_request_is_untrusted(self, temp_git_repo: Path) -> None:
        env = _env(
            _head(temp_git_repo),
            CI_PIPELINE_SOURCE="merge_request_event",
            CI_MERGE_REQUEST_IID="7",
            CI_MERGE_REQUEST_PROJECT_ID="1",
            CI_MERGE_REQUEST_SOURCE_PROJECT_ID="2",
        )
        decision = decide_trust(None, _operator(), temp_git_repo, env=env)

        assert decision.trusted is False
        assert decision.reason == "ci: fork merge request"
        assert decision.ci_facts["fork"] is True

    def test_head_must_match_ci_commit(self, temp_git_repo: Path) -> None:
        decision = decide_trust(None, _operator(), temp_git_repo, env=_env("a" * 40))

        assert decision.trusted is False
        assert decision.reason == "ci: head does not match CI commit"

    @pytest.mark.parametrize("source", ["schedule", "web", "pipeline", "trigger"])
    def test_other_sources_are_untrusted(self, source: str, temp_git_repo: Path) -> None:
        env = _env(_head(temp_git_repo), CI_PIPELINE_SOURCE=source)
        decision = decide_trust(None, _operator(), temp_git_repo, env=env)

        assert decision.trusted is False
        assert decision.reason == f"ci: untrusted event {source}"

    def test_missing_pipeline_source_is_unknown(self, temp_git_repo: Path) -> None:
        env = _env(_head(temp_git_repo))
        del env["CI_PIPELINE_SOURCE"]
        decision = decide_trust(None, _operator(), temp_git_repo, env=env)

        assert decision.trusted is False
        assert decision.reason == "ci: unknown event"
