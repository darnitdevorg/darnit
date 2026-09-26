"""GitHub Actions trust rules (feature 040, research R4)."""

from __future__ import annotations

import json
import subprocess
from pathlib import Path

import pytest

from darnit.config.operator.schema import OperatorConfig
from darnit.trust.ci import detect_ci_run
from darnit.trust.decision import decide_trust

REPO = "github.com/example/project"


def _head(repo: Path) -> str:
    return subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=repo, capture_output=True, text=True, check=True
    ).stdout.strip()


def _operator(
    *, rule: bool = True, rule_repos: list[str] | None = None, repos: list[str] | None = None
) -> OperatorConfig:
    trust: dict = {"repos": [REPO] if repos is None else repos}
    if rule:
        trust["ci"] = [{"event": "push-default-branch", "repos": rule_repos or []}]
    return OperatorConfig.model_validate({"schema_version": 1, "trust": trust})


def _env(tmp_path: Path, event: str, payload: dict, **overrides: str) -> dict[str, str]:
    path = tmp_path / "event.json"
    path.write_text(json.dumps(payload), encoding="utf-8")
    env = {
        "GITHUB_ACTIONS": "true",
        "GITHUB_EVENT_NAME": event,
        "GITHUB_EVENT_PATH": str(path),
        "GITHUB_SERVER_URL": "https://github.com",
        "GITHUB_REPOSITORY": "Example/Project",
        "GITHUB_REF": "refs/heads/main",
        "GITHUB_REF_TYPE": "branch",
        "GITHUB_SHA": "0" * 40,
    }
    env.update(overrides)
    return env


def _push_payload(default_branch: str = "main") -> dict:
    return {"repository": {"id": 1, "full_name": "Example/Project", "default_branch": default_branch}}


def _pr_payload(head_repo: dict | None, base_id: int = 1) -> dict:
    return {
        "repository": {"id": base_id, "full_name": "Example/Project", "default_branch": "main"},
        "pull_request": {
            "head": {"repo": head_repo, "sha": "1" * 40},
            "base": {"repo": {"id": base_id, "full_name": "Example/Project"}},
        },
    }


@pytest.mark.unit
class TestDefaultBranchPush:
    def test_trusted_when_rule_configured_and_head_matches(self, temp_git_repo: Path, tmp_path: Path) -> None:
        env = _env(tmp_path, "push", _push_payload(), GITHUB_SHA=_head(temp_git_repo))
        decision = decide_trust(None, _operator(), temp_git_repo, env=env)

        assert decision.trusted is True
        assert decision.reason == "ci: push to default branch"
        assert decision.repository.canonical == REPO
        assert decision.repository.source.value == "ci_metadata"
        assert decision.ci_facts["platform"] == "github-actions"
        assert decision.ci_facts["event"] == "push"
        assert decision.ci_facts["default_branch"] == "main"

    def test_untrusted_without_rule(self, temp_git_repo: Path, tmp_path: Path) -> None:
        env = _env(tmp_path, "push", _push_payload(), GITHUB_SHA=_head(temp_git_repo))
        decision = decide_trust(None, _operator(rule=False), temp_git_repo, env=env)

        assert decision.trusted is False
        assert decision.reason.startswith("ci: no trust rule")

    def test_rule_repos_narrow_the_rule(self, temp_git_repo: Path, tmp_path: Path) -> None:
        env = _env(tmp_path, "push", _push_payload(), GITHUB_SHA=_head(temp_git_repo))
        operator = _operator(rule_repos=["github.com/example/other"], repos=[REPO, "github.com/example/other"])

        assert decide_trust(None, operator, temp_git_repo, env=env).trusted is False

    def test_untrusted_when_not_listed(self, temp_git_repo: Path, tmp_path: Path) -> None:
        env = _env(tmp_path, "push", _push_payload(), GITHUB_SHA=_head(temp_git_repo))
        decision = decide_trust(None, _operator(repos=["github.com/example/other"]), temp_git_repo, env=env)

        assert decision.trusted is False
        assert decision.reason == "not listed"

    def test_untrusted_when_head_differs_from_ci_commit(self, temp_git_repo: Path, tmp_path: Path) -> None:
        env = _env(tmp_path, "push", _push_payload(), GITHUB_SHA="f" * 40)
        decision = decide_trust(None, _operator(), temp_git_repo, env=env)

        assert decision.trusted is False
        assert decision.reason == "ci: head does not match CI commit"

    def test_untrusted_when_head_cannot_be_read(self, tmp_path: Path) -> None:
        checkout = tmp_path / "not-a-repo"
        checkout.mkdir()
        env = _env(tmp_path, "push", _push_payload())
        decision = decide_trust(None, _operator(), checkout, env=env)

        assert decision.trusted is False
        assert decision.reason == "ci: head does not match CI commit"

    def test_push_to_other_branch_is_untrusted(self, temp_git_repo: Path, tmp_path: Path) -> None:
        env = _env(tmp_path, "push", _push_payload(), GITHUB_REF="refs/heads/feature", GITHUB_SHA=_head(temp_git_repo))
        decision = decide_trust(None, _operator(), temp_git_repo, env=env)

        assert decision.trusted is False
        assert decision.reason == "ci: push to non-default branch"

    def test_tag_push_is_untrusted(self, temp_git_repo: Path, tmp_path: Path) -> None:
        env = _env(
            tmp_path,
            "push",
            _push_payload(),
            GITHUB_REF="refs/tags/main",
            GITHUB_REF_TYPE="tag",
            GITHUB_SHA=_head(temp_git_repo),
        )

        assert decide_trust(None, _operator(), temp_git_repo, env=env).trusted is False

    def test_default_branch_comes_from_payload(self, temp_git_repo: Path, tmp_path: Path) -> None:
        env = _env(tmp_path, "push", _push_payload(default_branch="develop"), GITHUB_SHA=_head(temp_git_repo))

        assert decide_trust(None, _operator(), temp_git_repo, env=env).trusted is False

    def test_missing_payload_is_untrusted(self, temp_git_repo: Path, tmp_path: Path) -> None:
        env = _env(tmp_path, "push", _push_payload(), GITHUB_SHA=_head(temp_git_repo))
        env["GITHUB_EVENT_PATH"] = str(tmp_path / "missing.json")

        assert decide_trust(None, _operator(), temp_git_repo, env=env).trusted is False

    def test_ci_identity_is_canonicalized_with_server_host(self, tmp_path: Path) -> None:
        env = _env(
            tmp_path, "push", _push_payload(), GITHUB_SERVER_URL="https://GHE.Example.com", GITHUB_REPOSITORY="Org/Repo"
        )
        run = detect_ci_run(env, case_insensitive_hosts=["ghe.example.com"])

        assert run is not None
        assert run.repository == "ghe.example.com/org/repo"


@pytest.mark.unit
class TestPullRequests:
    @pytest.mark.parametrize("event", ["pull_request", "pull_request_target"])
    def test_fork_pull_request_is_untrusted(self, event: str, temp_git_repo: Path, tmp_path: Path) -> None:
        payload = _pr_payload({"id": 2, "full_name": "someone/project", "fork": True})
        env = _env(tmp_path, event, payload, GITHUB_REF="refs/pull/1/merge", GITHUB_SHA=_head(temp_git_repo))
        decision = decide_trust(None, _operator(), temp_git_repo, env=env)

        assert decision.trusted is False
        assert decision.reason == "ci: fork pull request"
        assert decision.ci_facts["fork"] is True
        assert decision.ci_facts["head_repository"] == "someone/project"

    def test_same_repository_pull_request_is_untrusted(self, temp_git_repo: Path, tmp_path: Path) -> None:
        # head.repo.fork is true for same-repository pull requests inside a
        # forked repository; fork detection must compare ids instead.
        payload = _pr_payload({"id": 1, "full_name": "Example/Project", "fork": True})
        env = _env(tmp_path, "pull_request", payload, GITHUB_SHA=_head(temp_git_repo))
        decision = decide_trust(None, _operator(), temp_git_repo, env=env)

        assert decision.trusted is False
        assert decision.reason == "ci: pull request"
        assert decision.ci_facts["fork"] is False

    def test_deleted_head_repository_counts_as_fork(self, temp_git_repo: Path, tmp_path: Path) -> None:
        env = _env(tmp_path, "pull_request", _pr_payload(None), GITHUB_SHA=_head(temp_git_repo))
        decision = decide_trust(None, _operator(), temp_git_repo, env=env)

        assert decision.reason == "ci: fork pull request"


@pytest.mark.unit
class TestOtherEvents:
    @pytest.mark.parametrize("event", ["workflow_run", "merge_group", "schedule", "workflow_dispatch"])
    def test_other_events_are_untrusted(self, event: str, temp_git_repo: Path, tmp_path: Path) -> None:
        env = _env(tmp_path, event, _push_payload(), GITHUB_SHA=_head(temp_git_repo))
        decision = decide_trust(None, _operator(), temp_git_repo, env=env)

        assert decision.trusted is False
        assert decision.reason == f"ci: untrusted event {event}"

    def test_missing_event_is_unknown(self, temp_git_repo: Path, tmp_path: Path) -> None:
        env = _env(tmp_path, "push", _push_payload(), GITHUB_SHA=_head(temp_git_repo))
        del env["GITHUB_EVENT_NAME"]
        decision = decide_trust(None, _operator(), temp_git_repo, env=env)

        assert decision.trusted is False
        assert decision.reason == "ci: unknown event"

    def test_unrecognized_ci_is_untrusted(self, temp_git_repo: Path) -> None:
        decision = decide_trust(REPO, _operator(), temp_git_repo, env={"CI": "true"})

        assert decision.trusted is False
        assert decision.reason == "ci: unknown event"
        assert decision.ci_facts["platform"] == "unknown"

    def test_not_in_ci_returns_none(self) -> None:
        assert detect_ci_run({}) is None
