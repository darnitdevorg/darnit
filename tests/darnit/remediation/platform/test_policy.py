"""Remediation policy for platform writes (feature 043 T019; FR-026, SC-002, R4)."""

from __future__ import annotations

from pathlib import Path

import pytest

from darnit.config.operator import loader
from darnit.config.operator.schema import RemediationSettings
from darnit.remediation.platform import FieldChange, PlatformRequirement, ResolvedPolicy, apply, resolve_policy
from darnit.remediation.platform.targets import normalize_protection_get
from tests.darnit.remediation.platform.conftest import REPO_PATH, _base, _protection, stricter

REPOSITORY = "github.com/o/r"
PROTECTION = f"{REPO_PATH}/branches/main/protection"
AC_03_02 = PlatformRequirement(target="branch_protection", require={"prevent_deletion": True})
BASELINE = [
    PlatformRequirement(target="branch_protection", require={"require_pull_request": True}),
    AC_03_02,
    PlatformRequirement(target="branch_protection", require={"require_approvals": 1}),
]
PUBLIC = PlatformRequirement(target="repository", require={"visibility": "public"})


def policy(platform: str = "prompt", high_impact: str = "prompt") -> ResolvedPolicy:
    return ResolvedPolicy(
        settings=RemediationSettings(platform=platform, high_impact=high_impact),
        operator_config_digest="sha256:" + "0" * 64,
        operator="alice",
    )


@pytest.mark.unit
class TestPrompt:
    def test_no_digest_needs_approval_and_writes_nothing(self, simulated_gh) -> None:
        gh = simulated_gh("stricter")

        [result] = apply(REPOSITORY, BASELINE, policy=policy())

        assert result.kind == "needs_approval"
        assert result.mode == "prompt"
        assert result.change_set.operations, "the outcome carries the previewed change"
        assert gh.writes == []

    def test_already_satisfied_needs_no_approval(self, simulated_gh) -> None:
        gh = simulated_gh("satisfied")

        [result] = apply(REPOSITORY, BASELINE, policy=policy())

        assert result.kind == "unchanged"
        assert result.reason == "already"
        assert gh.writes == []


@pytest.mark.unit
class TestManual:
    def test_manual_writes_nothing_and_gives_steps(self, simulated_gh) -> None:
        gh = simulated_gh("stricter")

        [result] = apply(REPOSITORY, BASELINE, policy=policy(platform="manual"))

        assert result.kind == "manual"
        assert result.steps and any("allow_deletions" in step or "deletion" in step.lower() for step in result.steps)
        assert gh.writes == []

    def test_manual_high_impact_only_governs_high_impact(self, simulated_gh) -> None:
        simulated_gh(_base(protection=_protection(allow_deletions=True), private=True))

        results = apply(REPOSITORY, [AC_03_02, PUBLIC], policy=policy(platform="auto", high_impact="manual"))

        kinds = {r.target.kind: r.kind for r in results}
        assert kinds == {"branch_protection": "applied", "repository": "manual"}


@pytest.mark.unit
class TestAuto:
    def test_auto_writes_without_a_digest_and_records_the_policy(self, simulated_gh) -> None:
        gh = simulated_gh("stricter")
        before = normalize_protection_get(stricter()[PROTECTION]["body"])

        [result] = apply(REPOSITORY, BASELINE, policy=policy(platform="auto"))

        assert result.kind == "applied"
        assert result.mode == "auto"
        assert result.approval is None
        assert [(w.method, w.endpoint) for w in gh.writes] == [("PUT", PROTECTION)]
        assert result.changed == [FieldChange(field="allow_deletions", before=True, after=False)]
        after = normalize_protection_get(gh.protection())
        assert after == {**before, "allow_deletions": {"enabled": False}}, (
            "every pre-existing setting is unchanged (SC-001)"
        )

    def test_auto_still_reads_first_and_skips_satisfied(self, simulated_gh) -> None:
        gh = simulated_gh("ruleset_only")

        [result] = apply(REPOSITORY, BASELINE, policy=policy(platform="auto"))

        assert result.kind == "unchanged"
        assert result.reason == "ruleset"
        assert gh.writes == []

    def test_auto_high_impact_records_impact_notes(self, simulated_gh) -> None:
        simulated_gh("private_repo")

        [result] = apply(REPOSITORY, [PUBLIC], policy=policy(high_impact="auto"))

        assert result.kind == "applied"
        assert result.change_set.impact_notes

    def test_high_impact_prompt_is_not_relaxed_by_platform_auto(self, simulated_gh) -> None:
        gh = simulated_gh("private_repo")

        [result] = apply(REPOSITORY, [PUBLIC], policy=policy(platform="auto"))

        assert result.kind == "needs_approval"
        assert gh.writes == []


@pytest.mark.unit
class TestFailures:
    def test_read_only_token_errors_with_nothing_changed(self, simulated_gh) -> None:
        gh = simulated_gh("read_only_token")

        [result] = apply(REPOSITORY, BASELINE, policy=policy(platform="auto"))

        assert result.kind == "error"
        assert result.error.error_class == "auth"
        assert result.changed == []
        assert len(gh.writes) == 1

    def test_unreadable_state_writes_nothing(self, simulated_gh) -> None:
        gh = simulated_gh("read_failure")

        [result] = apply(REPOSITORY, BASELINE, policy=policy(platform="auto"))

        assert result.kind == "error"
        assert gh.writes == []

    def test_partial_write_lists_exactly_the_changed_field(self, simulated_gh) -> None:
        gh = simulated_gh(
            _base(protection=_protection(allow_deletions=True)),
            reject=(f"PUT {PROTECTION}",),
        )

        [result] = apply(
            REPOSITORY,
            [AC_03_02, PlatformRequirement(target="branch_protection", require={"require_approvals": 2})],
            policy=policy(platform="auto"),
        )

        assert [(w.method, w.endpoint) for w in gh.writes] == [
            ("PATCH", f"{PROTECTION}/required_pull_request_reviews"),
            ("PUT", PROTECTION),
        ]
        assert result.kind == "error"
        assert result.changed == [
            FieldChange(field="required_pull_request_reviews.required_approving_review_count", before=1, after=2)
        ]
        assert "allow_deletions" not in {c.field for c in result.changed}

    def test_non_github_repository_is_manual_with_no_platform_call(self, simulated_gh) -> None:
        gh = simulated_gh("stricter")

        results = apply("gitlab.com/o/r", [*BASELINE, PUBLIC], policy=policy(platform="auto", high_impact="auto"))

        assert {r.kind for r in results} == {"manual"}
        assert all(r.steps for r in results)
        assert gh.calls == []


@pytest.mark.unit
class TestPolicySource:
    def test_policy_comes_from_operator_configuration(self, tmp_path: Path) -> None:
        config = tmp_path / "operator" / "config.toml"
        config.parent.mkdir()
        config.write_text('schema_version = 1\n\n[remediation]\nplatform = "auto"\nhigh_impact = "manual"\n')
        config.chmod(0o600)
        loader.set_launch_options(config)
        repo = tmp_path / "repo"
        repo.mkdir()

        resolved = resolve_policy(repo)

        assert resolved.settings == RemediationSettings(platform="auto", high_impact="manual")
        assert resolved.operator_config_digest
        assert resolved.operator

    def test_a_remediation_table_in_the_audited_repository_is_ignored(self, tmp_path: Path) -> None:
        repo = tmp_path / "repo"
        (repo / ".project").mkdir(parents=True)
        (repo / ".baseline.toml").write_text('[remediation]\nplatform = "auto"\nhigh_impact = "auto"\n')
        (repo / ".project" / "darnit.yaml").write_text("remediation:\n  platform: auto\n  high_impact: auto\n")
        (repo / ".darnit.toml").write_text('schema_version = 1\n[remediation]\nplatform = "auto"\n')

        resolved = resolve_policy(repo)

        assert resolved.settings == RemediationSettings(platform="prompt", high_impact="prompt")
