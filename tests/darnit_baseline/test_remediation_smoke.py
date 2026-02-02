"""Smoke tests for remediation functions.

These tests verify that all remediation functions can be imported and called
without import errors or immediate crashes. This catches issues like missing
imports (Path, file_exists, etc.) that would only surface at runtime.
"""

import os
import tempfile
from pathlib import Path

import pytest


class TestRemediationImports:
    """Test that all remediation functions can be imported."""

    @pytest.mark.unit
    def test_import_actions_module(self):
        """Test that the actions module can be imported."""
        from darnit_baseline.remediation import actions
        assert actions is not None

    @pytest.mark.unit
    def test_import_all_action_functions(self):
        """Test that all action functions can be imported."""
        from darnit_baseline.remediation.actions import (
            configure_dco_enforcement,
            create_bug_report_template,
            create_codeowners,
            create_contributing_guide,
            create_dependabot_config,
            create_governance_doc,
            create_maintainers_doc,
            create_security_policy,
            create_support_doc,
            ensure_vex_policy,
        )
        # Verify they're all callable
        assert callable(create_security_policy)
        assert callable(ensure_vex_policy)
        assert callable(create_contributing_guide)
        assert callable(create_codeowners)
        assert callable(create_maintainers_doc)
        assert callable(create_governance_doc)
        assert callable(create_dependabot_config)
        assert callable(create_support_doc)
        assert callable(create_bug_report_template)
        assert callable(configure_dco_enforcement)

    @pytest.mark.unit
    def test_import_orchestrator(self):
        """Test that the orchestrator can be imported."""
        from darnit_baseline.remediation.orchestrator import (
            _apply_remediation,
            remediate_audit_findings,
        )
        assert callable(remediate_audit_findings)
        assert callable(_apply_remediation)

    @pytest.mark.unit
    def test_import_registry(self):
        """Test that the registry can be imported and has expected categories."""
        from darnit_baseline.remediation.registry import REMEDIATION_REGISTRY

        expected_categories = [
            "branch_protection",
            "status_checks",
            "security_policy",
            "vex_policy",
            "codeowners",
            "maintainers",
            "governance",
            "contributing",
            "dco_enforcement",
            "bug_report_template",
            "dependabot",
            "support_doc",
        ]

        for category in expected_categories:
            assert category in REMEDIATION_REGISTRY, f"Missing category: {category}"
            assert "function" in REMEDIATION_REGISTRY[category]
            assert "controls" in REMEDIATION_REGISTRY[category]

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


class TestRemediationFunctionExecution:
    """Test that remediation functions can be executed without crashes."""

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
    def test_create_security_policy_executes(self, temp_repo):
        """Test create_security_policy runs without import errors."""
        from darnit_baseline.remediation.actions import create_security_policy

        result = create_security_policy(
            owner="test-owner",
            repo="test-repo",
            local_path=temp_repo,
        )
        # Should return a string (success or info message)
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.unit
    def test_ensure_vex_policy_executes(self, temp_repo):
        """Test ensure_vex_policy runs without import errors."""
        from darnit_baseline.remediation.actions import ensure_vex_policy

        result = ensure_vex_policy(local_path=temp_repo)
        # Should return a string
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.unit
    def test_create_contributing_guide_executes(self, temp_repo):
        """Test create_contributing_guide runs without import errors."""
        from darnit_baseline.remediation.actions import create_contributing_guide

        result = create_contributing_guide(
            owner="test-owner",
            repo="test-repo",
            local_path=temp_repo,
        )
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.unit
    def test_create_codeowners_executes(self, temp_repo):
        """Test create_codeowners runs without import errors."""
        from darnit_baseline.remediation.actions import create_codeowners

        result = create_codeowners(
            owner="test-owner",
            repo="test-repo",
            local_path=temp_repo,
        )
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.unit
    def test_create_maintainers_doc_executes(self, temp_repo):
        """Test create_maintainers_doc runs without import errors."""
        from darnit_baseline.remediation.actions import create_maintainers_doc

        result = create_maintainers_doc(
            owner="test-owner",
            repo="test-repo",
            local_path=temp_repo,
        )
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.unit
    def test_create_governance_doc_executes(self, temp_repo):
        """Test create_governance_doc runs without import errors."""
        from darnit_baseline.remediation.actions import create_governance_doc

        result = create_governance_doc(
            owner="test-owner",
            repo="test-repo",
            local_path=temp_repo,
        )
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.unit
    def test_create_dependabot_config_executes(self, temp_repo):
        """Test create_dependabot_config runs without import errors."""
        from darnit_baseline.remediation.actions import create_dependabot_config

        result = create_dependabot_config(
            owner="test-owner",
            repo="test-repo",
            local_path=temp_repo,
        )
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.unit
    def test_create_support_doc_executes(self, temp_repo):
        """Test create_support_doc runs without import errors."""
        from darnit_baseline.remediation.actions import create_support_doc

        result = create_support_doc(
            owner="test-owner",
            repo="test-repo",
            local_path=temp_repo,
        )
        assert isinstance(result, str)
        assert len(result) > 0

    @pytest.mark.unit
    def test_create_bug_report_template_executes(self, temp_repo):
        """Test create_bug_report_template runs without import errors."""
        from darnit_baseline.remediation.actions import create_bug_report_template

        result = create_bug_report_template(
            owner="test-owner",
            repo="test-repo",
            local_path=temp_repo,
        )
        assert isinstance(result, str)
        assert len(result) > 0


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
        from darnit_baseline.remediation.orchestrator import _apply_remediation
        from darnit_baseline.remediation.registry import REMEDIATION_REGISTRY

        # Test each category that doesn't require GitHub API
        for category, info in REMEDIATION_REGISTRY.items():
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


class TestMaintainersPromptBehavior:
    """Test that maintainers remediation prompts for confirmation."""

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
    def test_maintainers_prompts_when_not_confirmed(self, temp_repo):
        """Test that create_maintainers_doc prompts for confirmation when not confirmed."""
        from darnit_baseline.remediation.actions import create_maintainers_doc

        result = create_maintainers_doc(
            owner="test-owner",
            repo="test-repo",
            local_path=temp_repo,
        )
        # Should return a prompt, not create a file
        assert "confirm_project_context" in result
        assert "maintainers" in result.lower()
        # File should NOT be created
        assert not (Path(temp_repo) / "MAINTAINERS.md").exists()

    @pytest.mark.unit
    def test_maintainers_creates_file_when_confirmed(self, temp_repo):
        """Test that create_maintainers_doc creates file when maintainers are confirmed."""
        from darnit.server.tools.project_context import confirm_project_context_impl
        from darnit_baseline.remediation.actions import create_maintainers_doc

        # First confirm maintainers
        confirm_result = confirm_project_context_impl(
            local_path=temp_repo,
            maintainers=["@alice", "@bob"],
        )
        assert "✅" in confirm_result

        # Now create maintainers doc
        result = create_maintainers_doc(
            owner="test-owner",
            repo="test-repo",
            local_path=temp_repo,
        )
        # Should create the file
        assert "✅" in result or "Created" in result
        assert (Path(temp_repo) / "MAINTAINERS.md").exists()

        # File should contain the confirmed maintainers
        content = (Path(temp_repo) / "MAINTAINERS.md").read_text()
        assert "@alice" in content
        assert "@bob" in content

    @pytest.mark.unit
    def test_orchestrator_returns_needs_confirmation_for_maintainers(self, temp_repo):
        """Test that _apply_remediation returns needs_confirmation status for maintainers."""
        from darnit_baseline.remediation.orchestrator import _apply_remediation

        result = _apply_remediation(
            category="maintainers",
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=False,  # Not a dry run, but should still prompt
        )

        # Should return needs_confirmation status since maintainers aren't confirmed
        assert result["status"] == "needs_confirmation"
        assert result["category"] == "maintainers"
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
            category="maintainers",
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=False,
        )

        # Should return applied status since maintainers are confirmed
        assert result["status"] == "applied"
        assert result["category"] == "maintainers"


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
    def test_codeowners_prompts_when_not_confirmed(self, temp_repo):
        """Test that create_codeowners prompts for confirmation when not confirmed."""
        from darnit_baseline.remediation.actions import create_codeowners

        result = create_codeowners(
            owner="test-owner",
            repo="test-repo",
            local_path=temp_repo,
        )
        # Should return a prompt, not create a file
        assert "confirm_project_context" in result
        assert "maintainers" in result.lower() or "codeowners" in result.lower()
        # File should NOT be created
        assert not (Path(temp_repo) / "CODEOWNERS").exists()
        assert not (Path(temp_repo) / ".github" / "CODEOWNERS").exists()

    @pytest.mark.unit
    def test_codeowners_creates_file_when_confirmed(self, temp_repo):
        """Test that create_codeowners creates file when maintainers are confirmed."""
        from darnit.server.tools.project_context import confirm_project_context_impl
        from darnit_baseline.remediation.actions import create_codeowners

        # First confirm maintainers
        confirm_result = confirm_project_context_impl(
            local_path=temp_repo,
            maintainers=["@alice", "@bob"],
        )
        assert "✅" in confirm_result

        # Now create CODEOWNERS
        result = create_codeowners(
            owner="test-owner",
            repo="test-repo",
            local_path=temp_repo,
        )
        # Should create the file
        assert "✅" in result or "Created" in result
        assert (Path(temp_repo) / "CODEOWNERS").exists()

        # File should contain the confirmed maintainers
        content = (Path(temp_repo) / "CODEOWNERS").read_text()
        assert "@alice" in content
        assert "@bob" in content

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


class TestGovernancePromptBehavior:
    """Test that GOVERNANCE.md remediation prompts for confirmation."""

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
    def test_governance_prompts_when_not_confirmed(self, temp_repo):
        """Test that create_governance_doc prompts for confirmation when not confirmed."""
        from darnit_baseline.remediation.actions import create_governance_doc

        result = create_governance_doc(
            owner="test-owner",
            repo="test-repo",
            local_path=temp_repo,
        )
        # Should return a prompt, not create a file
        assert "confirm_project_context" in result
        assert "maintainers" in result.lower()
        # File should NOT be created
        assert not (Path(temp_repo) / "GOVERNANCE.md").exists()

    @pytest.mark.unit
    def test_governance_creates_file_when_confirmed(self, temp_repo):
        """Test that create_governance_doc creates file when maintainers are confirmed."""
        from darnit.server.tools.project_context import confirm_project_context_impl
        from darnit_baseline.remediation.actions import create_governance_doc

        # First confirm maintainers
        confirm_result = confirm_project_context_impl(
            local_path=temp_repo,
            maintainers=["@alice", "@bob"],
        )
        assert "✅" in confirm_result

        # Now create GOVERNANCE.md
        result = create_governance_doc(
            owner="test-owner",
            repo="test-repo",
            local_path=temp_repo,
        )
        # Should create the file
        assert "✅" in result or "Created" in result
        assert (Path(temp_repo) / "GOVERNANCE.md").exists()

        # File should contain the confirmed maintainers
        content = (Path(temp_repo) / "GOVERNANCE.md").read_text()
        assert "@alice" in content
        assert "@bob" in content

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
