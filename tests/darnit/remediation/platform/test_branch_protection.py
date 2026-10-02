"""Branch-protection planner: read first, minimal change, never weaken (feature 043 T016; R3, SC-001)."""

from __future__ import annotations

import pytest

from darnit.remediation.plan import digest
from darnit.remediation.platform import FieldChange, PlatformRequirement, plan
from darnit.remediation.platform.targets import protection_get_to_put
from tests.darnit.remediation.platform.conftest import (
    REPO_PATH,
    _base,
    _err,
    _protection,
    satisfied,
    stricter,
)

REPOSITORY = "github.com/o/r"
PROTECTION = f"{REPO_PATH}/branches/main/protection"
MANDATORY_PUT_KEYS = {"required_status_checks", "enforce_admins", "required_pull_request_reviews", "restrictions"}


def bp(branch: str | None = None, **require) -> PlatformRequirement:
    return PlatformRequirement(target="branch_protection", require=require, branch=branch)


AC_03_01 = bp(require_pull_request=True)
AC_03_02 = bp(prevent_deletion=True)
QA_07_01 = bp(require_approvals=1)
BASELINE = [AC_03_01, AC_03_02, QA_07_01]


def only(plans):
    assert len(plans) == 1, plans
    return plans[0]


@pytest.mark.unit
class TestUnprotected:
    def test_one_put_that_sets_only_the_required_fields(self, gh_platform) -> None:
        gh = gh_platform("unprotected")

        change_set = only(plan(REPOSITORY, BASELINE)).change_set

        assert [(op.method, op.endpoint) for op in change_set.operations] == [("PUT", PROTECTION)]
        body = change_set.operations[0].body
        assert set(body) == MANDATORY_PUT_KEYS
        assert body["required_pull_request_reviews"] == {"required_approving_review_count": 1}
        assert body["enforce_admins"] is False
        assert body["required_status_checks"] is None
        assert body["restrictions"] is None
        assert change_set.satisfied_by is None
        assert gh.writes == []

    def test_preview_lists_what_protecting_the_branch_changes(self, gh_platform) -> None:
        gh_platform("unprotected")

        changes = only(plan(REPOSITORY, BASELINE)).change_set.operations[0].changes

        assert {c.field for c in changes} == {
            "protected",
            "allow_deletions",
            "allow_force_pushes",
            "required_pull_request_reviews",
        }


@pytest.mark.unit
class TestStricterExistingProtection:
    def test_only_allow_deletions_changes(self, gh_platform) -> None:
        gh = gh_platform("stricter")

        change_set = only(plan(REPOSITORY, BASELINE)).change_set

        assert [(op.method, op.endpoint) for op in change_set.operations] == [("PUT", PROTECTION)]
        assert change_set.operations[0].changes == [FieldChange(field="allow_deletions", before=True, after=False)]
        assert gh.writes == []

    def test_put_body_preserves_every_other_value(self, gh_platform) -> None:
        gh_platform("stricter")
        current = stricter()[PROTECTION]["body"]

        body = only(plan(REPOSITORY, BASELINE)).change_set.operations[0].body

        assert body == {**protection_get_to_put(current), "allow_deletions": False}
        assert body["required_status_checks"]["checks"] == [
            {"context": "ci/build", "app_id": 15368},
            {"context": "ci/test", "app_id": 15368},
        ]
        assert body["restrictions"] == {"users": ["octocat"], "teams": ["release-managers"], "apps": ["deploy-bot"]}
        reviews = body["required_pull_request_reviews"]
        assert reviews["required_approving_review_count"] == 2
        assert reviews["require_code_owner_reviews"] is True
        assert reviews["dismiss_stale_reviews"] is True
        assert body["required_linear_history"] is True
        assert body["required_conversation_resolution"] is True
        assert body["enforce_admins"] is True


@pytest.mark.unit
class TestAlreadySatisfied:
    def test_classic_protection_satisfies(self, gh_platform) -> None:
        gh = gh_platform("satisfied")

        change_set = only(plan(REPOSITORY, BASELINE)).change_set

        assert change_set.operations == []
        assert change_set.satisfied_by == "already"
        assert gh.writes == []

    def test_ruleset_satisfies_without_classic_protection(self, gh_platform) -> None:
        gh = gh_platform("ruleset_only")

        change_set = only(plan(REPOSITORY, BASELINE)).change_set

        assert change_set.operations == []
        assert change_set.satisfied_by == "ruleset"
        assert gh.writes == []

    def test_partly_ruleset_partly_missing_notes_the_ruleset(self, gh_platform) -> None:
        gh_platform("ruleset_only")

        change_set = only(plan(REPOSITORY, [*BASELINE, bp(prevent_force_push=True)])).change_set

        body = change_set.operations[0].body
        assert body["required_pull_request_reviews"] is None, "a requirement the ruleset satisfies is not duplicated"
        assert any("ruleset" in note for note in change_set.impact_notes)


@pytest.mark.unit
class TestUnreadable:
    def test_unknown_protection_field_refuses_a_full_put(self, gh_platform) -> None:
        gh = gh_platform("unknown_field")

        result = only(plan(REPOSITORY, BASELINE))

        assert result.change_set is None
        assert result.error.error_class == "evaluation"
        assert "cannot preserve unknown protection setting future_setting" in result.error.cause
        assert gh.writes == []

    def test_unknown_field_does_not_block_a_granular_change(self, gh_platform) -> None:
        gh_platform("unknown_field")

        change_set = only(plan(REPOSITORY, [bp(require_approvals=3)])).change_set

        assert [op.method for op in change_set.operations] == ["PATCH"]

    def test_read_failure_is_an_error_with_its_cause(self, gh_platform) -> None:
        gh = gh_platform("read_failure")

        result = only(plan(REPOSITORY, BASELINE))

        assert result.change_set is None
        assert result.error.error_class == "unavailable"
        assert "502" in result.error.cause
        assert gh.writes == []

    def test_unreadable_default_branch_is_an_error(self, gh_platform) -> None:
        responses = satisfied()
        responses[REPO_PATH] = _err(403, "Resource not accessible by integration")
        gh = gh_platform(responses)

        result = only(plan(REPOSITORY, BASELINE))

        assert result.change_set is None
        assert result.error.error_class == "auth"
        assert "default branch" in result.error.cause
        assert gh.writes == []

    def test_missing_branch_is_an_error(self, gh_platform) -> None:
        responses = satisfied()
        responses[f"{REPO_PATH}/branches/main"] = _err(404, "Branch not found")
        gh_platform(responses)

        result = only(plan(REPOSITORY, BASELINE))

        assert result.change_set is None
        assert "Branch not found" in result.error.cause

    def test_unreadable_rules_are_an_error(self, gh_platform) -> None:
        responses = satisfied()
        responses[f"{REPO_PATH}/rules/branches/main"] = _err(502, "Bad Gateway")
        gh_platform(responses)

        assert only(plan(REPOSITORY, BASELINE)).error is not None


@pytest.mark.unit
class TestBranch:
    def test_default_branch_comes_from_the_platform(self, gh_platform) -> None:
        gh_platform("default_branch_release")

        change_set = only(plan(REPOSITORY, BASELINE)).change_set

        assert change_set.target.branch == "release"
        assert change_set.operations[0].endpoint == f"{REPO_PATH}/branches/release/protection"

    def test_a_named_branch_is_used_without_reading_the_default(self, gh_platform) -> None:
        gh = gh_platform("default_branch_release")

        change_set = only(plan(REPOSITORY, [bp(branch="main", require_pull_request=True)])).change_set

        assert change_set.target.branch == "main"
        assert REPO_PATH not in gh.calls

    def test_requirements_on_one_branch_merge_into_one_change_set(self, gh_platform) -> None:
        gh_platform("stricter")

        plans = plan(REPOSITORY, [bp(branch="main", prevent_deletion=True), AC_03_01, QA_07_01])

        change_set = only(plans).change_set
        assert {r.key for r in change_set.requirements} == {
            "prevent_deletion",
            "require_pull_request",
            "require_approvals",
        }


@pytest.mark.unit
class TestGranularWrites:
    def test_review_count_is_raised_by_patch(self, gh_platform) -> None:
        gh_platform("satisfied")

        change_set = only(plan(REPOSITORY, [bp(require_approvals=2)])).change_set

        [op] = change_set.operations
        assert (op.method, op.endpoint) == ("PATCH", f"{PROTECTION}/required_pull_request_reviews")
        assert op.body == {"required_approving_review_count": 2}
        assert op.changes == [
            FieldChange(field="required_pull_request_reviews.required_approving_review_count", before=1, after=2)
        ]

    def test_review_count_is_never_lowered(self, gh_platform) -> None:
        gh_platform("stricter")

        change_set = only(plan(REPOSITORY, [bp(require_approvals=1)])).change_set

        assert change_set.operations == []
        assert change_set.satisfied_by == "already"

    def test_enforce_admins_only_when_off(self, gh_platform) -> None:
        gh_platform(_base(protection=_protection(enforce_admins=False)))

        [op] = only(plan(REPOSITORY, [bp(enforce_admins=True)])).change_set.operations

        assert (op.method, op.endpoint, op.body) == ("POST", f"{PROTECTION}/enforce_admins", None)
        assert op.changes == [FieldChange(field="enforce_admins", before=False, after=True)]

    def test_enforce_admins_already_on(self, gh_platform) -> None:
        gh_platform("satisfied")

        assert only(plan(REPOSITORY, [bp(enforce_admins=True)])).change_set.operations == []

    def test_status_checks_add_only_missing_contexts(self, gh_platform) -> None:
        gh_platform("stricter")

        [op] = only(plan(REPOSITORY, [bp(require_status_checks=["ci/test", "ci/lint"])])).change_set.operations

        assert (op.method, op.endpoint) == ("POST", f"{PROTECTION}/required_status_checks/contexts")
        assert op.body == {"contexts": ["ci/lint"]}
        assert op.changes == [
            FieldChange(
                field="required_status_checks.contexts",
                before=["ci/build", "ci/test"],
                after=["ci/build", "ci/lint", "ci/test"],
            )
        ]

    def test_status_checks_created_by_patch_when_none_configured(self, gh_platform) -> None:
        gh_platform(_base(protection=_protection()))

        [op] = only(plan(REPOSITORY, [bp(require_status_checks=["ci/build"])])).change_set.operations

        assert (op.method, op.endpoint, op.body) == (
            "PATCH",
            f"{PROTECTION}/required_status_checks",
            {"contexts": ["ci/build"]},
        )

    def test_full_put_comes_last_and_carries_the_granular_changes(self, gh_platform) -> None:
        gh_platform(_base(protection=_protection(allow_deletions=True)))

        operations = only(plan(REPOSITORY, [bp(require_approvals=2), AC_03_02])).change_set.operations

        assert [(op.method, op.endpoint) for op in operations] == [
            ("PATCH", f"{PROTECTION}/required_pull_request_reviews"),
            ("PUT", PROTECTION),
        ]
        put = operations[1]
        assert put.body["required_pull_request_reviews"]["required_approving_review_count"] == 2
        assert put.changes == [FieldChange(field="allow_deletions", before=True, after=False)]


@pytest.mark.unit
class TestDigest:
    def test_digest_binds_target_observed_state_and_operations(self, gh_platform) -> None:
        gh_platform("stricter")

        change_set = only(plan(REPOSITORY, BASELINE)).change_set

        assert change_set.digest == digest(
            {
                "target": change_set.target.model_dump(mode="json"),
                "observed_digest": change_set.observed_digest,
                "operations": [op.model_dump(mode="json") for op in change_set.operations],
            }
        )

    def test_same_state_same_digest(self, gh_platform) -> None:
        gh_platform("stricter")

        assert only(plan(REPOSITORY, BASELINE)).change_set.digest == only(plan(REPOSITORY, BASELINE)).change_set.digest

    def test_different_state_different_digest(self, gh_platform) -> None:
        gh_platform("stricter")
        first = only(plan(REPOSITORY, BASELINE)).change_set.digest
        responses = stricter()
        responses[PROTECTION]["body"]["required_linear_history"] = {"enabled": False}
        gh_platform(responses)

        assert only(plan(REPOSITORY, BASELINE)).change_set.digest != first
