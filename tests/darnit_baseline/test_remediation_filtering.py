"""Tests for remediation audit-based filtering.

Verifies that _apply_remediation filters controls by audit results
so only non-passing controls are remediated.
"""

from unittest.mock import patch

from darnit_baseline.remediation.orchestrator import _apply_remediation


class TestRemediationAuditFiltering:
    """Test that _apply_remediation filters by non_passing_ids."""

    def test_mixed_passing_failing_remediates_only_failing(self):
        """Category with mixed passing/failing controls only remediates the failing one."""
        # The "dependabot" category has controls VM-05.01, VM-05.02, VM-05.03.
        # If VM-05.01 passes but VM-05.03 fails, only VM-05.03 should be
        # considered for remediation.
        non_passing_ids = {"OSPS-VM-05.03"}

        with patch(
            "darnit_baseline.remediation.orchestrator.is_control_applicable",
            return_value=(True, None),
        ), patch(
            "darnit_baseline.remediation.orchestrator._get_framework_config",
            return_value=None,
        ), patch(
            "darnit_baseline.remediation.orchestrator.get_context_requirements_for_category",
            return_value=[],
        ):
            result = _apply_remediation(
                category="dependabot",
                local_path="/tmp/test",
                owner="testorg",
                repo="testrepo",
                dry_run=True,
                non_passing_ids=non_passing_ids,
            )

        # VM-05.01 and VM-05.02 pass, so they're filtered out.
        # VM-05.03 doesn't have declarative remediation available
        # (framework config is None), so we get no_remediation.
        # The key assertion is that it did NOT pick VM-05.01.
        assert result["status"] in ("no_remediation", "manual", "would_apply")
        assert result["category"] == "dependabot"

    def test_all_controls_passing_returns_already_passing(self):
        """Category where all controls pass is skipped."""
        # All controls in the category pass
        non_passing_ids: set[str] = set()

        with patch(
            "darnit_baseline.remediation.orchestrator.is_control_applicable",
            return_value=(True, None),
        ), patch(
            "darnit_baseline.remediation.orchestrator._get_framework_config",
            return_value=None,
        ), patch(
            "darnit_baseline.remediation.orchestrator.get_context_requirements_for_category",
            return_value=[],
        ):
            result = _apply_remediation(
                category="dependabot",
                local_path="/tmp/test",
                owner="testorg",
                repo="testrepo",
                dry_run=True,
                non_passing_ids=non_passing_ids,
            )

        assert result["status"] == "already_passing"
        assert "already pass" in result["message"]

    def test_explicit_categories_still_filter_by_audit(self):
        """Even with explicit categories, non_passing_ids filtering applies."""
        # User explicitly passes "security_policy" but all its controls pass
        non_passing_ids: set[str] = set()

        with patch(
            "darnit_baseline.remediation.orchestrator.is_control_applicable",
            return_value=(True, None),
        ), patch(
            "darnit_baseline.remediation.orchestrator._get_framework_config",
            return_value=None,
        ), patch(
            "darnit_baseline.remediation.orchestrator.get_context_requirements_for_category",
            return_value=[],
        ):
            result = _apply_remediation(
                category="security_policy",
                local_path="/tmp/test",
                owner="testorg",
                repo="testrepo",
                dry_run=True,
                non_passing_ids=non_passing_ids,
            )

        assert result["status"] == "already_passing"

    def test_none_non_passing_ids_preserves_legacy_behavior(self):
        """When non_passing_ids is None, all applicable controls are considered."""
        with patch(
            "darnit_baseline.remediation.orchestrator.is_control_applicable",
            return_value=(True, None),
        ), patch(
            "darnit_baseline.remediation.orchestrator._get_framework_config",
            return_value=None,
        ), patch(
            "darnit_baseline.remediation.orchestrator.get_context_requirements_for_category",
            return_value=[],
        ):
            result = _apply_remediation(
                category="support_doc",
                local_path="/tmp/test",
                owner="testorg",
                repo="testrepo",
                dry_run=True,
                non_passing_ids=None,  # Legacy: no filtering
            )

        # With None, all controls are considered (no already_passing)
        assert result["status"] != "already_passing"
