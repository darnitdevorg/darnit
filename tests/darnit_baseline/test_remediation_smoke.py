"""Smoke tests for remediation functions.

These tests verify that the remediation orchestrator and TOML-based
remediation system can be imported and called without import errors
or immediate crashes.
"""

import os
import tempfile
from pathlib import Path

import pytest


class TestRemediationImports:
    """Test that remediation modules can be imported."""

    @pytest.mark.unit
    def test_import_orchestrator(self):
        """Test that the orchestrator can be imported."""
        from darnit_baseline.remediation.orchestrator import (
            REMEDIATION_CATEGORIES,
            _apply_remediation,
            remediate_audit_findings,
        )
        assert callable(remediate_audit_findings)
        assert callable(_apply_remediation)
        assert isinstance(REMEDIATION_CATEGORIES, dict)

    @pytest.mark.unit
    def test_import_categories_has_expected_keys(self):
        """Test that REMEDIATION_CATEGORIES has expected categories."""
        from darnit_baseline.remediation.orchestrator import REMEDIATION_CATEGORIES

        expected_categories = [
            "branch_protection",
            "security_policy",
            "codeowners",
            "governance",
            "contributing",
            "dco_enforcement",
            "bug_report_template",
            "dependabot",
            "support_doc",
        ]

        for category in expected_categories:
            assert category in REMEDIATION_CATEGORIES, f"Missing category: {category}"
            assert "description" in REMEDIATION_CATEGORIES[category]
            assert "controls" in REMEDIATION_CATEGORIES[category]

    @pytest.mark.unit
    def test_import_tools(self):
        """Test that the MCP tools can be imported."""
        from darnit_baseline.tools import (
            create_security_policy,
            enable_branch_protection,
            remediate_audit_findings,
        )
        assert callable(remediate_audit_findings)
        assert callable(create_security_policy)
        assert callable(enable_branch_protection)


class TestRemediationOrchestratorExecution:
    """Test that the remediation orchestrator works end-to-end."""

    @pytest.fixture
    def temp_repo(self):
        """Create a temporary directory that looks like a git repo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            # Initialize as a git repo
            os.system(f"cd {tmpdir} && git init -q")
            os.system(f"cd {tmpdir} && git config user.email 'test@test.com'")
            os.system(f"cd {tmpdir} && git config user.name 'Test'")
            # Create a dummy file and commit
            (Path(tmpdir) / "README.md").write_text("# Test")
            os.system(f"cd {tmpdir} && git add . && git commit -q -m 'init'")
            yield tmpdir

    @pytest.mark.unit
    def test_remediate_audit_findings_dry_run(self, temp_repo):
        """Test remediate_audit_findings in dry-run mode."""
        from darnit_baseline.remediation.orchestrator import remediate_audit_findings

        result = remediate_audit_findings(
            local_path=temp_repo,
            categories=["security_policy"],
            dry_run=True,
        )
        assert isinstance(result, str)
        assert "Preview" in result or "dry run" in result.lower() or "would" in result.lower()

    @pytest.mark.unit
    def test_remediate_all_categories_dry_run(self, temp_repo):
        """Test remediate_audit_findings with all categories in dry-run mode."""
        from darnit_baseline.remediation.orchestrator import remediate_audit_findings

        result = remediate_audit_findings(
            local_path=temp_repo,
            categories=["all"],
            dry_run=True,
        )
        assert isinstance(result, str)
        # Should not crash and should return something meaningful
        assert len(result) > 0

    @pytest.mark.unit
    def test_apply_single_remediation_dry_run(self, temp_repo):
        """Test _apply_remediation for each category."""
        from darnit_baseline.remediation.orchestrator import (
            REMEDIATION_CATEGORIES,
            _apply_remediation,
        )

        # Test each category that doesn't require GitHub API
        for category, info in REMEDIATION_CATEGORIES.items():
            if not info.get("requires_api", False):
                result = _apply_remediation(
                    category=category,
                    local_path=temp_repo,
                    owner="test-owner",
                    repo="test-repo",
                    dry_run=True,
                )
                assert isinstance(result, dict), f"Category {category} didn't return dict"
                assert "category" in result, f"Category {category} missing 'category' key"
                assert "status" in result, f"Category {category} missing 'status' key"


class TestGovernancePromptBehavior:
    """Test that governance remediation prompts for confirmation.

    Governance category requires maintainers context, so it should prompt
    before creating files like GOVERNANCE.md or MAINTAINERS.md.
    """

    @pytest.fixture
    def temp_repo(self):
        """Create a temporary directory that looks like a git repo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.system(f"cd {tmpdir} && git init -q")
            os.system(f"cd {tmpdir} && git config user.email 'test@test.com'")
            os.system(f"cd {tmpdir} && git config user.name 'Test'")
            (Path(tmpdir) / "README.md").write_text("# Test")
            os.system(f"cd {tmpdir} && git add . && git commit -q -m 'init'")
            yield tmpdir

    @pytest.mark.unit
    def test_orchestrator_returns_needs_confirmation_for_governance(self, temp_repo):
        """Test that _apply_remediation returns needs_confirmation status for governance."""
        from darnit_baseline.remediation.orchestrator import _apply_remediation

        result = _apply_remediation(
            category="governance",
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=False,
        )

        # Should return needs_confirmation status since maintainers aren't confirmed
        assert result["status"] == "needs_confirmation"
        assert result["category"] == "governance"
        assert "confirm_project_context" in result.get("result", "")

    @pytest.mark.unit
    def test_orchestrator_returns_applied_after_confirmation(self, temp_repo):
        """Test that _apply_remediation returns applied status after confirmation."""
        from darnit.server.tools.project_context import confirm_project_context_impl
        from darnit_baseline.remediation.orchestrator import _apply_remediation

        # First confirm maintainers
        confirm_project_context_impl(
            local_path=temp_repo,
            maintainers=["@alice", "@bob"],
        )

        result = _apply_remediation(
            category="governance",
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=False,
        )

        # Should return applied status since maintainers are confirmed
        assert result["status"] == "applied"
        assert result["category"] == "governance"


class TestCodeownersPromptBehavior:
    """Test that CODEOWNERS remediation prompts for confirmation."""

    @pytest.fixture
    def temp_repo(self):
        """Create a temporary directory that looks like a git repo."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.system(f"cd {tmpdir} && git init -q")
            os.system(f"cd {tmpdir} && git config user.email 'test@test.com'")
            os.system(f"cd {tmpdir} && git config user.name 'Test'")
            (Path(tmpdir) / "README.md").write_text("# Test")
            os.system(f"cd {tmpdir} && git add . && git commit -q -m 'init'")
            yield tmpdir

    @pytest.mark.unit
    def test_orchestrator_returns_needs_confirmation_for_codeowners(self, temp_repo):
        """Test that _apply_remediation returns needs_confirmation status for codeowners."""
        from darnit_baseline.remediation.orchestrator import _apply_remediation

        result = _apply_remediation(
            category="codeowners",
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=False,
        )

        # Should return needs_confirmation status since maintainers aren't confirmed
        assert result["status"] == "needs_confirmation"
        assert result["category"] == "codeowners"
        assert "confirm_project_context" in result.get("result", "")
