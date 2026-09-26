"""Trust decisions for a run (feature 040, FR-016, FR-016a)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from darnit.config.operator.schema import OperatorConfig
from darnit.trust.decision import decide_trust, target_from_owner_repo
from darnit.trust.identity import IdentitySource

OWN = "github.com/example/own"


def _operator(repos: list[str] | None = None, **trust: object) -> OperatorConfig:
    return OperatorConfig.model_validate({"schema_version": 1, "trust": {"repos": repos or [OWN], **trust}})


def _remote(repo: Path, name: str, url: str) -> None:
    subprocess.run(["git", "remote", "add", name, url], cwd=repo, check=True, capture_output=True)


@pytest.mark.unit
class TestLocalRuns:
    def test_listed_operator_target_is_trusted(self, temp_git_repo: Path) -> None:
        decision = decide_trust("https://github.com/Example/Own.git", _operator(), temp_git_repo, env={})

        assert decision.trusted is True
        assert decision.reason == "listed; local run"
        assert decision.repository.canonical == OWN
        assert decision.repository.source is IdentitySource.OPERATOR_TARGET
        assert decision.ci_facts == {}

    def test_unlisted_operator_target_is_untrusted(self, temp_git_repo: Path) -> None:
        decision = decide_trust("github.com/example/other", _operator(), temp_git_repo, env={})

        assert decision.trusted is False
        assert decision.reason == "not listed"

    def test_operator_listed_case_insensitive_host(self, temp_git_repo: Path) -> None:
        operator = _operator(["git.example.com/team/own"], case_insensitive_hosts=["git.example.com"])
        decision = decide_trust("git.example.com/Team/Own", operator, temp_git_repo, env={})

        assert decision.trusted is True

    def test_checkout_remote_alone_is_never_trusted(self, temp_git_repo: Path) -> None:
        _remote(temp_git_repo, "origin", "git@github.com:example/own.git")
        decision = decide_trust(None, _operator(), temp_git_repo, env={})

        assert decision.trusted is False
        assert decision.reason == "identity from checkout only"
        assert decision.repository.canonical == OWN
        assert decision.repository.source is IdentitySource.CHECKOUT_HINT

    def test_upstream_remote_is_not_preferred_over_origin(self, temp_git_repo: Path) -> None:
        _remote(temp_git_repo, "origin", "https://github.com/someone/own.git")
        _remote(temp_git_repo, "upstream", "https://github.com/example/own.git")
        decision = decide_trust(None, _operator(), temp_git_repo, env={})

        assert decision.repository.canonical == "github.com/someone/own"
        assert decision.trusted is False

    def test_no_identity_at_all_is_untrusted(self, temp_git_repo: Path) -> None:
        decision = decide_trust(None, _operator(), temp_git_repo, env={})

        assert decision.trusted is False
        assert decision.repository is None
        assert decision.reason == "no repository identity"

    def test_unparseable_target_is_untrusted(self, temp_git_repo: Path) -> None:
        decision = decide_trust("not a repository", _operator(), temp_git_repo, env={})

        assert decision.trusted is False
        assert decision.repository is None

    def test_target_and_origin_mismatch_is_reported(self, temp_git_repo: Path) -> None:
        _remote(temp_git_repo, "origin", "https://github.com/example/different.git")
        decision = decide_trust(OWN, _operator(), temp_git_repo, env={})

        assert decision.trusted is True
        assert any("github.com/example/different" in w for w in decision.warnings)

    def test_matching_origin_is_not_reported(self, temp_git_repo: Path) -> None:
        _remote(temp_git_repo, "origin", "git@github.com:Example/Own.git")

        assert decide_trust(OWN, _operator(), temp_git_repo, env={}).warnings == ()

    def test_unparseable_trust_entries_are_ignored(self, temp_git_repo: Path) -> None:
        decision = decide_trust(OWN, _operator(["nonsense", OWN]), temp_git_repo, env={})

        assert decision.trusted is True


@pytest.mark.unit
class TestCiTarget:
    def test_operator_target_must_match_ci_repository(self, temp_git_repo: Path, tmp_path: Path) -> None:
        env = {
            "GITLAB_CI": "true",
            "CI_PIPELINE_SOURCE": "push",
            "CI_COMMIT_BRANCH": "main",
            "CI_DEFAULT_BRANCH": "main",
            "CI_SERVER_HOST": "gitlab.com",
            "CI_PROJECT_PATH": "example/own",
            "CI_COMMIT_SHA": "0" * 40,
        }
        operator = _operator(["gitlab.com/example/own", OWN], ci=[{"event": "push-default-branch"}])
        decision = decide_trust(OWN, operator, temp_git_repo, env=env)

        assert decision.trusted is False
        assert decision.reason == "ci: target does not match CI repository"


@pytest.mark.unit
def test_report_shape(temp_git_repo: Path) -> None:
    report = decide_trust(OWN, _operator(), temp_git_repo, env={}).report()

    assert report == {
        "repository": OWN,
        "identity_source": "operator_target",
        "trusted": True,
        "reason": "listed; local run",
        "ci_facts": {},
        "warnings": [],
    }


@pytest.mark.unit
@pytest.mark.parametrize(
    ("owner", "repo", "host", "expected"),
    [
        ("example", "own", None, "github.com/example/own"),
        ("Group/Sub", "proj", "gitlab.com", "gitlab.com/Group/Sub/proj"),
        (None, "own", None, None),
        ("example", None, None, None),
    ],
)
def test_target_from_owner_repo(owner: str | None, repo: str | None, host: str | None, expected: str | None) -> None:
    assert target_from_owner_repo(owner, repo, host) == expected
