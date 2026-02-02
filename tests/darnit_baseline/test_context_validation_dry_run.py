"""Tests for context validation behavior in dry_run mode.

CRITICAL: These tests verify that context validation (prompting for maintainers, etc.)
happens REGARDLESS of dry_run mode. This prevents a regression where dry_run=True
would bypass the context check and create files with guessed/auto-detected maintainers.

The bug this prevents:
- remediate_audit_findings() defaults to dry_run=True
- If context validation only happens when dry_run=False, users never see the prompt
- Result: Files get created with wrong maintainer information

These tests explicitly verify that:
1. dry_run=True still returns "needs_confirmation" when context is missing
2. dry_run=False still returns "needs_confirmation" when context is missing
3. All categories that require context (codeowners, maintainers, governance) prompt correctly
4. After confirmation, both dry_run modes proceed correctly
"""

import os
import tempfile
from pathlib import Path

import pytest


@pytest.fixture
def temp_repo():
    """Create a temporary directory that looks like a git repo."""
    with tempfile.TemporaryDirectory() as tmpdir:
        os.system(f"cd {tmpdir} && git init -q")
        os.system(f"cd {tmpdir} && git config user.email 'test@test.com'")
        os.system(f"cd {tmpdir} && git config user.name 'Test'")
        (Path(tmpdir) / "README.md").write_text("# Test")
        os.system(f"cd {tmpdir} && git add . && git commit -q -m 'init'")
        yield tmpdir


class TestContextValidationInDryRunMode:
    """CRITICAL: Verify context validation happens when dry_run=True.

    This is the main regression test. The bug was that dry_run=True would
    bypass context validation entirely.
    """

    @pytest.mark.unit
    def test_maintainers_needs_confirmation_in_dry_run_true(self, temp_repo):
        """dry_run=True MUST still return needs_confirmation for maintainers."""
        from darnit_baseline.remediation.orchestrator import _apply_remediation

        result = _apply_remediation(
            category="maintainers",
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=True,  # This is the default in tools.py
        )

        # CRITICAL: Must return needs_confirmation, NOT skip the check
        assert result["status"] == "needs_confirmation", \
            f"dry_run=True bypassed context validation! Got status: {result['status']}"
        assert result["category"] == "maintainers"
        assert "maintainers" in result.get("missing_context", [])
        assert "confirm_project_context" in result.get("result", "")

    @pytest.mark.unit
    def test_codeowners_needs_confirmation_in_dry_run_true(self, temp_repo):
        """dry_run=True MUST still return needs_confirmation for codeowners."""
        from darnit_baseline.remediation.orchestrator import _apply_remediation

        result = _apply_remediation(
            category="codeowners",
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=True,
        )

        assert result["status"] == "needs_confirmation", \
            f"dry_run=True bypassed context validation! Got status: {result['status']}"
        assert result["category"] == "codeowners"
        assert "maintainers" in result.get("missing_context", [])

    @pytest.mark.unit
    def test_governance_needs_confirmation_in_dry_run_true(self, temp_repo):
        """dry_run=True MUST still return needs_confirmation for governance."""
        from darnit_baseline.remediation.orchestrator import _apply_remediation

        result = _apply_remediation(
            category="governance",
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=True,
        )

        assert result["status"] == "needs_confirmation", \
            f"dry_run=True bypassed context validation! Got status: {result['status']}"
        assert result["category"] == "governance"
        assert "maintainers" in result.get("missing_context", [])


class TestContextValidationInDryRunFalse:
    """Verify context validation also happens when dry_run=False."""

    @pytest.mark.unit
    def test_maintainers_needs_confirmation_in_dry_run_false(self, temp_repo):
        """dry_run=False must return needs_confirmation for maintainers."""
        from darnit_baseline.remediation.orchestrator import _apply_remediation

        result = _apply_remediation(
            category="maintainers",
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=False,
        )

        assert result["status"] == "needs_confirmation"
        assert result["category"] == "maintainers"
        assert "maintainers" in result.get("missing_context", [])

    @pytest.mark.unit
    def test_codeowners_needs_confirmation_in_dry_run_false(self, temp_repo):
        """dry_run=False must return needs_confirmation for codeowners."""
        from darnit_baseline.remediation.orchestrator import _apply_remediation

        result = _apply_remediation(
            category="codeowners",
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=False,
        )

        assert result["status"] == "needs_confirmation"
        assert result["category"] == "codeowners"

    @pytest.mark.unit
    def test_governance_needs_confirmation_in_dry_run_false(self, temp_repo):
        """dry_run=False must return needs_confirmation for governance."""
        from darnit_baseline.remediation.orchestrator import _apply_remediation

        result = _apply_remediation(
            category="governance",
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=False,
        )

        assert result["status"] == "needs_confirmation"
        assert result["category"] == "governance"


class TestContextValidationAfterConfirmation:
    """Verify remediation proceeds after context is confirmed."""

    @pytest.mark.unit
    def test_maintainers_proceeds_after_confirmation_dry_run_true(self, temp_repo):
        """After confirmation, dry_run=True should show preview (not needs_confirmation)."""
        from darnit.server.tools.project_context import confirm_project_context_impl
        from darnit_baseline.remediation.orchestrator import _apply_remediation

        # First confirm maintainers
        confirm_project_context_impl(
            local_path=temp_repo,
            maintainers=["@alice", "@bob"],
        )

        # Now try remediation
        result = _apply_remediation(
            category="maintainers",
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=True,
        )

        # Should NOT be needs_confirmation anymore
        assert result["status"] != "needs_confirmation", \
            f"Still prompting after confirmation! Status: {result['status']}"
        # Should be skipped (if file exists) or show preview
        assert result["status"] in ["skipped", "applied", "dry_run", "preview", "would_apply"]

    @pytest.mark.unit
    def test_maintainers_proceeds_after_confirmation_dry_run_false(self, temp_repo):
        """After confirmation, dry_run=False should create the file."""
        from darnit.server.tools.project_context import confirm_project_context_impl
        from darnit_baseline.remediation.orchestrator import _apply_remediation

        # First confirm maintainers
        confirm_project_context_impl(
            local_path=temp_repo,
            maintainers=["@alice", "@bob"],
        )

        # Now try remediation
        result = _apply_remediation(
            category="maintainers",
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=False,
        )

        # Should NOT be needs_confirmation anymore
        assert result["status"] != "needs_confirmation"
        # File should be created
        assert (Path(temp_repo) / "MAINTAINERS.md").exists()


class TestAllContextRequiringCategories:
    """Verify ALL categories that require context are properly tested."""

    CONTEXT_REQUIRING_CATEGORIES = ["codeowners", "maintainers", "governance"]

    @pytest.mark.unit
    def test_registry_has_context_requirements(self):
        """Verify registry defines context requirements for expected categories."""
        from darnit_baseline.remediation.registry import REMEDIATION_REGISTRY

        for category in self.CONTEXT_REQUIRING_CATEGORIES:
            assert category in REMEDIATION_REGISTRY, f"Missing category: {category}"
            info = REMEDIATION_REGISTRY[category]
            assert "requires_context" in info, \
                f"Category {category} missing requires_context in registry"
            assert len(info["requires_context"]) > 0, \
                f"Category {category} has empty requires_context"

    @pytest.mark.unit
    @pytest.mark.parametrize("category", CONTEXT_REQUIRING_CATEGORIES)
    def test_each_category_prompts_in_dry_run_true(self, temp_repo, category):
        """Parametrized test: each category must prompt in dry_run=True mode."""
        from darnit_baseline.remediation.orchestrator import _apply_remediation

        result = _apply_remediation(
            category=category,
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=True,
        )

        assert result["status"] == "needs_confirmation", \
            f"Category {category} with dry_run=True returned {result['status']} instead of needs_confirmation"

    @pytest.mark.unit
    @pytest.mark.parametrize("category", CONTEXT_REQUIRING_CATEGORIES)
    def test_each_category_prompts_in_dry_run_false(self, temp_repo, category):
        """Parametrized test: each category must prompt in dry_run=False mode."""
        from darnit_baseline.remediation.orchestrator import _apply_remediation

        result = _apply_remediation(
            category=category,
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=False,
        )

        assert result["status"] == "needs_confirmation", \
            f"Category {category} with dry_run=False returned {result['status']} instead of needs_confirmation"


class TestToolsDefaultBehavior:
    """Test that the MCP tool functions also respect context validation."""

    @pytest.mark.unit
    def test_remediate_audit_findings_default_dry_run_prompts(self, temp_repo):
        """remediate_audit_findings with default dry_run=True must show prompts."""
        from darnit_baseline.tools import remediate_audit_findings

        # This is what gets called via MCP - default is dry_run=True
        result = remediate_audit_findings(
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
            categories=["codeowners"],
            # dry_run defaults to True
        )

        # Result should mention confirmation is needed
        assert "confirm" in result.lower() or "needs_confirmation" in result.lower(), \
            f"Tool with default dry_run didn't prompt for confirmation: {result[:200]}"

    @pytest.mark.unit
    def test_remediate_audit_findings_explicit_dry_run_false_prompts(self, temp_repo):
        """remediate_audit_findings with dry_run=False must also show prompts."""
        from darnit_baseline.tools import remediate_audit_findings

        result = remediate_audit_findings(
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
            categories=["governance"],
            dry_run=False,
        )

        # Result should mention confirmation is needed
        assert "confirm" in result.lower() or "needs_confirmation" in result.lower(), \
            f"Tool with dry_run=False didn't prompt for confirmation: {result[:200]}"
