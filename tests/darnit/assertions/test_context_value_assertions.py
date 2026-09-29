"""Applicability-changing project data is an assertion (feature 040, US3, T043, FR-013a).

A context value read from the audited repository's ``.project/`` that makes a
control not applicable is a not-applicable claim for that control, with origin
``context_value:<key>``. Values that came from detection are not.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from darnit.trust.assertions import DEFAULT_ASSERTER, context_value_assertions

LOCATION = ".project/darnit.yaml:context.has_releases"
RELEASE_CONTROLS = ("OSPS-BR-06.01", "OSPS-SA-03.01")
_CI_VARS = ("GITHUB_ACTIONS", "GITLAB_CI", "CI", "JENKINS_URL", "TF_BUILD", "BUILDKITE", "CIRCLECI", "TRAVIS")


@pytest.mark.unit
class TestContextValueAssertions:
    def test_repository_value_that_makes_controls_not_applicable_is_an_assertion_per_control(self) -> None:
        when = {"A": {"has_releases": True}, "B": {"has_releases": True, "platform": "github"}, "C": {"x": 1}}

        claims = context_value_assertions(
            when,
            context={"has_releases": False, "platform": "github", "x": 1},
            detected={"platform": "github"},
            repository_values={"has_releases": LOCATION},
        )

        assert [c.control_id for c in claims] == ["A", "B"]
        for claim in claims:
            assert claim.origin == "context_value:has_releases"
            assert claim.claim == "not_applicable"
            assert claim.reason is None
            assert claim.asserted_by == DEFAULT_ASSERTER
            assert claim.location == LOCATION
            assert claim.value is False

    def test_detected_value_is_not_an_assertion(self) -> None:
        claims = context_value_assertions(
            {"A": {"platform": "github"}},
            context={"platform": "gitlab"},
            detected={"platform": "gitlab"},
            repository_values={},
        )

        assert claims == []

    def test_control_not_applicable_by_detection_anyway_is_not_an_assertion(self) -> None:
        claims = context_value_assertions(
            {"A": {"has_releases": True, "platform": "github"}},
            context={"has_releases": False, "platform": "gitlab"},
            detected={"platform": "gitlab"},
            repository_values={"has_releases": LOCATION},
        )

        assert claims == []

    def test_repository_value_that_keeps_a_control_applicable_is_not_an_assertion(self) -> None:
        claims = context_value_assertions(
            {"A": {"has_releases": True}},
            context={"has_releases": True},
            detected={},
            repository_values={"has_releases": LOCATION},
        )

        assert claims == []

    def test_repository_value_overriding_a_detected_value_is_an_assertion(self) -> None:
        claims = context_value_assertions(
            {"A": {"platform": "github"}},
            context={"platform": "gitlab"},
            detected={"platform": "github"},
            repository_values={"platform": ".project/darnit.yaml:context.platform"},
        )

        assert [(c.control_id, c.origin) for c in claims] == [("A", "context_value:platform")]


def _repo(tmp_path: Path, *, confirmed: bool = True) -> Path:
    """A repository stating ``has_releases: false``.

    Feature 042 (FR-006): only a value confirmed in the repository is
    repository data a claim can be implied from (was: any stored value); the
    confirmation record here is the project's own statement.
    """
    import yaml

    from darnit.config.context_keys import value_digest

    path = tmp_path / "repo"
    (path / ".project").mkdir(parents=True)
    (path / ".project" / "project.yaml").write_text("name: repo\n", encoding="utf-8")
    data: dict = {"context": {"has_releases": False}}
    if confirmed:
        data["confirmations"] = {
            "has_releases": {
                "value_digest": value_digest("has_releases", False),
                "confirmed_by": "maintainer",
                "confirmed_at": "2026-09-01T00:00:00Z",
                "last_validated": "2026-09-01T00:00:00Z",
            }
        }
    (path / ".project" / "darnit.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    subprocess.run(["git", "init", "--initial-branch=main", "-q"], cwd=path, check=True)
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/example/repo.git"], cwd=path, check=True)
    return path


def _audit(repo: Path, **kwargs: object) -> dict[str, dict]:
    from darnit.config import load_controls_from_framework, load_framework_config
    from darnit.tools.audit import _get_framework_config_path, run_sieve_audit

    framework = load_framework_config(_get_framework_config_path("openssf-baseline"))
    controls = [c for c in load_controls_from_framework(framework) if c.control_id in RELEASE_CONTROLS]
    results, _ = run_sieve_audit(
        owner="example",
        repo="repo",
        local_path=str(repo),
        default_branch="main",
        level=3,
        controls=controls,
        framework_name="openssf-baseline",
        **kwargs,
    )
    return {r["id"]: r for r in results}


@pytest.mark.integration
class TestAuditedContextValues:
    @pytest.fixture(autouse=True)
    def _outside_ci(self, monkeypatch: pytest.MonkeyPatch) -> None:
        for var in _CI_VARS:
            monkeypatch.delenv(var, raising=False)

    def test_untrusted_repository_gets_pending_for_each_affected_control(self, tmp_path: Path) -> None:
        results = _audit(_repo(tmp_path))

        for control_id in RELEASE_CONTROLS:
            result = results[control_id]
            assert result["assertion"]["origin"] == "context_value:has_releases"
            assert result["assertion"]["outcome"] == "pending"
            assert result["assertion"]["location"] == LOCATION
            assert result["status"] != "N/A"

    def test_trusted_repository_with_unobtainable_evidence_is_pending(self, tmp_path: Path) -> None:
        """No reason is needed for a context value, but release evidence cannot be read here."""
        from darnit.config.operator.loader import LoadedOperatorConfig
        from darnit.config.operator.schema import OperatorConfig

        operator = LoadedOperatorConfig(
            config=OperatorConfig.model_validate(
                {"schema_version": 1, "trust": {"repos": ["github.com/example/repo"]}}
            ),
            source="test",
            digest=None,
            permission_check="ok",
            strict=False,
        )
        results = _audit(_repo(tmp_path), operator_config=operator, target="github.com/example/repo")

        for control_id in RELEASE_CONTROLS:
            assert results[control_id]["assertion"]["outcome"] == "pending"
            assert results[control_id]["status"] != "N/A"

    def test_unconfirmed_stored_value_implies_no_claim(self, tmp_path: Path) -> None:
        """Feature 042 (FR-006): an unconfirmed stored value is a candidate and has no effect."""
        results = _audit(_repo(tmp_path, confirmed=False))

        for control_id in RELEASE_CONTROLS:
            assert "assertion" not in results[control_id]
            assert results[control_id]["status"] != "N/A"

    def test_claims_ignored_when_user_config_is_not_applied(self, tmp_path: Path) -> None:
        results = _audit(_repo(tmp_path), apply_user_config=False)

        for control_id in RELEASE_CONTROLS:
            assert "assertion" not in results[control_id]
            assert results[control_id]["status"] != "N/A"
