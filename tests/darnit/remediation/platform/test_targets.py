"""Repository visibility and private vulnerability reporting targets (feature 043 T018; R2, R14)."""

from __future__ import annotations

import pytest

from darnit.remediation.platform import PlatformRequirement, PlatformTarget, plan
from tests.darnit.remediation.platform.conftest import REPO_PATH

REPOSITORY = "github.com/o/r"
PUBLIC = PlatformRequirement(target="repository", require={"visibility": "public"})
PVR = PlatformRequirement(target="vulnerability_reporting", require={"enabled": True})


@pytest.mark.unit
class TestRepositoryVisibility:
    def test_private_repo_gets_a_patch_with_only_visibility(self, gh_platform) -> None:
        gh = gh_platform("private_repo")

        [result] = plan(REPOSITORY, [PUBLIC])
        change_set = result.change_set

        [op] = change_set.operations
        assert (op.method, op.endpoint, op.body) == ("PATCH", REPO_PATH, {"visibility": "public"})
        assert [(c.field, c.before, c.after) for c in op.changes] == [("visibility", "private", "public")]
        assert change_set.target.impact == "high_impact"
        assert any("publicly readable" in note for note in change_set.impact_notes)
        assert any("fork" in note for note in change_set.impact_notes)
        assert gh.writes == []

    def test_public_repo_needs_nothing(self, gh_platform) -> None:
        gh_platform("unprotected")

        [result] = plan(REPOSITORY, [PUBLIC])

        assert result.change_set.operations == []
        assert result.change_set.satisfied_by == "already"
        assert result.change_set.impact_notes == []


@pytest.mark.unit
class TestVulnerabilityReporting:
    def test_disabled_gets_a_put(self, gh_platform) -> None:
        gh_platform("pvr_disabled")

        [result] = plan(REPOSITORY, [PVR])

        [op] = result.change_set.operations
        assert (op.method, op.endpoint, op.body) == ("PUT", f"{REPO_PATH}/private-vulnerability-reporting", None)
        assert [(c.field, c.before, c.after) for c in op.changes] == [("enabled", False, True)]
        assert result.change_set.target.impact == "platform"

    def test_enabled_needs_nothing(self, gh_platform) -> None:
        gh_platform("satisfied")

        [result] = plan(REPOSITORY, [PVR])

        assert result.change_set.operations == []
        assert result.change_set.satisfied_by == "already"

    def test_read_failure_is_an_error(self, gh_platform) -> None:
        gh_platform("read_failure")

        [result] = plan(REPOSITORY, [PVR])

        assert result.change_set is None
        assert result.error.error_class == "unavailable"


@pytest.mark.unit
class TestRequirementValidation:
    @pytest.mark.parametrize(
        ("target", "require"),
        [
            ("repository", {"visibility": "private"}),
            ("repository", {"archived": True}),
            ("vulnerability_reporting", {"enabled": False}),
            ("branch_protection", {"require_approvals": 0}),
            ("branch_protection", {"prevent_deletion": False}),
            ("branch_protection", {"require_status_checks": "ci"}),
            ("branch_protection", {"allow_force_pushes": False}),
            ("branch_protection", {}),
            ("org_settings", {"two_factor": True}),
        ],
    )
    def test_unknown_or_weakening_requirements_are_rejected(self, target: str, require: dict) -> None:
        with pytest.raises(ValueError):
            PlatformRequirement(target=target, require=require)

    def test_impact_is_fixed_by_kind(self) -> None:
        assert PlatformTarget.for_kind("repository", "o", "r").impact == "high_impact"
        assert PlatformTarget.for_kind("branch_protection", "o", "r", "main").impact == "platform"
        with pytest.raises(ValueError):
            PlatformTarget(kind="repository", impact="platform", owner="o", repo="r")
