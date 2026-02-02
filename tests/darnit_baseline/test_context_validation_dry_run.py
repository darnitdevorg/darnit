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


class TestFileReferenceRecommendation:
    """CRITICAL: Verify that file references are recommended when governance files exist.

    This prevents data duplication - instead of storing maintainer lists in .project/,
    we should reference existing files like CODEOWNERS.
    """

    @pytest.fixture
    def temp_repo_with_codeowners(self):
        """Create a temp repo that has a CODEOWNERS file."""
        with tempfile.TemporaryDirectory() as tmpdir:
            os.system(f"cd {tmpdir} && git init -q")
            os.system(f"cd {tmpdir} && git config user.email 'test@test.com'")
            os.system(f"cd {tmpdir} && git config user.name 'Test'")
            (Path(tmpdir) / "README.md").write_text("# Test")
            (Path(tmpdir) / "CODEOWNERS").write_text("* @existingowner\n")
            os.system(f"cd {tmpdir} && git add . && git commit -q -m 'init'")
            yield tmpdir

    @pytest.mark.unit
    def test_prompt_recommends_file_reference_when_codeowners_exists(
        self, temp_repo_with_codeowners
    ):
        """When CODEOWNERS exists, prompt should recommend referencing it."""
        from darnit_baseline.remediation.orchestrator import remediate_audit_findings

        result = remediate_audit_findings(
            local_path=temp_repo_with_codeowners,
            categories=["governance"],
            dry_run=True,
        )

        # Should reference the existing file as authoritative source
        assert "CODEOWNERS" in result
        assert 'maintainers="CODEOWNERS"' in result
        # Should indicate it's an authoritative source
        assert "authoritative" in result.lower()

    @pytest.mark.unit
    def test_file_reference_stored_as_string_not_list(self, temp_repo_with_codeowners):
        """When user confirms with file path, it should be stored as string, not list."""
        from darnit.config.loader import load_project_config
        from darnit_baseline.tools import confirm_project_context

        # Confirm maintainers by referencing CODEOWNERS
        confirm_project_context(
            local_path=temp_repo_with_codeowners,
            maintainers="CODEOWNERS",
        )

        # Load the config and check what's stored
        config = load_project_config(temp_repo_with_codeowners)
        assert config is not None
        assert config.x_openssf_baseline is not None
        assert config.x_openssf_baseline.context is not None

        # Should be stored as string (file reference), not list
        maintainers = config.x_openssf_baseline.context.maintainers
        assert isinstance(maintainers, str), \
            f"maintainers should be string (file ref), got {type(maintainers)}: {maintainers}"
        assert maintainers == "CODEOWNERS"


class TestPreflightContextCheck:
    """CRITICAL: Verify pre-flight check blocks remediation until context is confirmed.

    This prevents the AI from bypassing the prompt flow by ensuring ALL context
    requirements are checked BEFORE any remediation starts.
    """

    @pytest.mark.unit
    def test_preflight_blocks_multiple_categories(self, temp_repo):
        """Pre-flight should aggregate context needs across multiple categories."""
        from darnit_baseline.remediation.orchestrator import remediate_audit_findings

        # Request multiple categories that need maintainers
        result = remediate_audit_findings(
            local_path=temp_repo,
            categories=["codeowners", "governance"],
            dry_run=True,
        )

        # Should return early with context prompt (not "Would Apply")
        assert "Context Confirmation Required" in result
        # Should NOT have "Would Apply" section - remediation blocked
        assert "Would Apply (0 remediations)" not in result or "Would Apply (0" in result

    @pytest.mark.unit
    def test_preflight_allows_after_confirmation(self, temp_repo):
        """After confirming context, remediation should proceed."""
        from darnit.server.tools.project_context import confirm_project_context_impl
        from darnit_baseline.remediation.orchestrator import remediate_audit_findings

        # First, confirm maintainers
        confirm_project_context_impl(
            local_path=temp_repo,
            maintainers=["@testuser"],
        )

        # Now request remediation
        result = remediate_audit_findings(
            local_path=temp_repo,
            categories=["codeowners"],
            dry_run=True,
        )

        # Should now show "Would Apply" (not "Context Confirmation Required")
        assert "Would Apply" in result
        assert "Context Confirmation Required" not in result


class TestExplicitWarningAgainstDirectEdits:
    """CRITICAL: Verify prompts include explicit warnings against direct file editing.

    This prevents AI agents from bypassing the proper tool flow by directly
    editing .project/ files instead of using confirm_project_context().
    """

    @pytest.mark.unit
    def test_preflight_prompt_warns_against_direct_edits(self, temp_repo):
        """Pre-flight prompt MUST include warning about not editing files directly."""
        from darnit_baseline.remediation.orchestrator import remediate_audit_findings

        result = remediate_audit_findings(
            local_path=temp_repo,
            categories=["codeowners"],
            dry_run=True,
        )

        # CRITICAL: Must contain explicit warning
        assert "DO NOT" in result, \
            f"Pre-flight prompt missing 'DO NOT' warning: {result[:500]}"
        assert ".project/" in result or "project" in result.lower(), \
            f"Pre-flight prompt should mention .project/ files: {result[:500]}"
        assert "confirm_project_context" in result, \
            f"Pre-flight prompt should mention the tool to use: {result[:500]}"

    @pytest.mark.unit
    def test_context_prompt_warns_against_direct_edits(self, temp_repo):
        """Individual context prompts MUST include warning about not editing files directly."""
        from darnit_baseline.remediation.orchestrator import _apply_remediation

        result = _apply_remediation(
            category="maintainers",
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=True,
        )

        # Should be needs_confirmation with the prompt
        assert result["status"] == "needs_confirmation"
        prompt_text = result.get("result", "")

        # CRITICAL: Must contain explicit warning
        assert "DO NOT" in prompt_text, \
            f"Context prompt missing 'DO NOT' warning: {prompt_text[:500]}"
        assert "confirm_project_context" in prompt_text, \
            f"Context prompt should mention the tool to use: {prompt_text[:500]}"
