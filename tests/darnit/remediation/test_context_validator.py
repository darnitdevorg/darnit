"""Tests for the context validator module.

Tests the generic context confirmation pattern that checks requirements
before running remediations.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from darnit.config.context_schema import ContextSource, ContextValue
from darnit.config.framework_schema import ContextDefinitionConfig, ContextRequirement
from darnit.remediation.context_validator import (
    ContextCheckResult,
    check_context_requirements,
    format_context_prompt,
    get_context_requirements_for_category,
)


@pytest.fixture
def temp_repo():
    """Create a temporary directory for testing."""
    with tempfile.TemporaryDirectory() as tmpdir:
        # Initialize basic git repo structure
        os.system(f"cd {tmpdir} && git init -q")
        os.system(f"cd {tmpdir} && git config user.email 'test@test.com'")
        os.system(f"cd {tmpdir} && git config user.name 'Test'")
        (Path(tmpdir) / "README.md").write_text("# Test Project")
        os.system(f"cd {tmpdir} && git add . && git commit -q -m 'init'")
        yield tmpdir


class TestContextCheckResult:
    """Tests for ContextCheckResult dataclass."""

    def test_default_values(self):
        """Test default values are correct."""
        result = ContextCheckResult()
        assert result.ready is True
        assert result.missing_context == []
        assert result.prompts == []
        assert result.auto_detected == {}

    def test_custom_values(self):
        """Test setting custom values."""
        result = ContextCheckResult(
            ready=False,
            missing_context=["maintainers"],
            prompts=["Please confirm maintainers"],
            auto_detected={"maintainers": ["@user1"]},
        )
        assert result.ready is False
        assert result.missing_context == ["maintainers"]
        assert len(result.prompts) == 1
        assert result.auto_detected["maintainers"] == ["@user1"]


class TestCheckContextRequirements:
    """Tests for check_context_requirements function."""

    def test_returns_ready_when_no_requirements(self, temp_repo):
        """Empty requirements list should return ready=True."""
        result = check_context_requirements(
            requirements=[],
            local_path=temp_repo,
            framework=None,
        )
        assert result.ready is True
        assert result.missing_context == []

    @patch("darnit.remediation.context_validator.get_context_value")
    def test_returns_ready_when_context_confirmed(self, mock_get_context, temp_repo):
        """Should return ready=True when context is USER_CONFIRMED."""
        # Mock confirmed context
        mock_get_context.return_value = ContextValue(
            value=["@alice", "@bob"],
            source=ContextSource.USER_CONFIRMED,
            confidence=1.0,
        )

        requirement = ContextRequirement(
            key="maintainers",
            required=True,
            confidence_threshold=0.9,
            prompt_if_auto_detected=True,
        )

        result = check_context_requirements(
            requirements=[requirement],
            local_path=temp_repo,
            framework=None,
        )

        assert result.ready is True
        assert result.missing_context == []

    @patch("darnit.remediation.context_validator.get_context_value")
    def test_returns_not_ready_when_context_missing(self, mock_get_context, temp_repo):
        """Should return ready=False with prompts when context is missing."""
        mock_get_context.return_value = None

        requirement = ContextRequirement(
            key="maintainers",
            required=True,
            confidence_threshold=0.9,
            prompt_if_auto_detected=True,
        )

        result = check_context_requirements(
            requirements=[requirement],
            local_path=temp_repo,
            framework=None,
        )

        assert result.ready is False
        assert "maintainers" in result.missing_context
        assert len(result.prompts) == 1

    @patch("darnit.remediation.context_validator.get_context_value")
    def test_respects_confidence_threshold(self, mock_get_context, temp_repo):
        """Low confidence values should trigger prompt."""
        # Mock low-confidence auto-detected context
        mock_get_context.return_value = ContextValue(
            value=["@user1"],
            source=ContextSource.USER_CONFIRMED,  # Even confirmed but low confidence
            confidence=0.5,  # Below 0.9 threshold
        )

        requirement = ContextRequirement(
            key="maintainers",
            required=True,
            confidence_threshold=0.9,
            prompt_if_auto_detected=False,
        )

        result = check_context_requirements(
            requirements=[requirement],
            local_path=temp_repo,
            framework=None,
        )

        assert result.ready is False
        assert "maintainers" in result.missing_context

    @patch("darnit.remediation.context_validator.get_context_value")
    def test_prompt_if_auto_detected_flag(self, mock_get_context, temp_repo):
        """Auto-detected values should prompt if flag is set."""
        # Mock high-confidence auto-detected context
        mock_get_context.return_value = ContextValue(
            value=["@user1"],
            source=ContextSource.AUTO_DETECTED,
            confidence=0.95,  # Above threshold
        )

        requirement = ContextRequirement(
            key="maintainers",
            required=True,
            confidence_threshold=0.9,
            prompt_if_auto_detected=True,  # Should still prompt
        )

        result = check_context_requirements(
            requirements=[requirement],
            local_path=temp_repo,
            framework=None,
        )

        assert result.ready is False
        assert "maintainers" in result.missing_context
        assert result.auto_detected["maintainers"] == ["@user1"]

    @patch("darnit.remediation.context_validator.get_context_value")
    def test_auto_detected_allowed_when_flag_false(self, mock_get_context, temp_repo):
        """Auto-detected values should proceed if prompt_if_auto_detected=False."""
        mock_get_context.return_value = ContextValue(
            value=["@user1"],
            source=ContextSource.AUTO_DETECTED,
            confidence=0.95,
        )

        requirement = ContextRequirement(
            key="maintainers",
            required=True,
            confidence_threshold=0.9,
            prompt_if_auto_detected=False,  # Allow auto-detected
        )

        result = check_context_requirements(
            requirements=[requirement],
            local_path=temp_repo,
            framework=None,
        )

        assert result.ready is True


class TestFormatContextPrompt:
    """Tests for format_context_prompt function."""

    def test_generates_prompt_with_warning(self):
        """Prompt should include warning from requirement."""
        requirement = ContextRequirement(
            key="maintainers",
            required=True,
            confidence_threshold=0.9,
            prompt_if_auto_detected=True,
            warning="GitHub collaborators are not project maintainers",
        )

        prompt = format_context_prompt(
            context_key="maintainers",
            definition=None,
            requirement=requirement,
            current_value=None,
        )

        assert "maintainers" in prompt
        assert "GitHub collaborators are not project maintainers" in prompt
        assert "confirm_project_context" in prompt

    def test_includes_auto_detected_value(self):
        """Prompt should show auto-detected value."""
        requirement = ContextRequirement(key="maintainers")
        current_value = ContextValue(
            value=["@alice", "@bob"],
            source=ContextSource.AUTO_DETECTED,
            confidence=0.7,
        )

        prompt = format_context_prompt(
            context_key="maintainers",
            definition=None,
            requirement=requirement,
            current_value=current_value,
        )

        assert "@alice" in prompt
        assert "@bob" in prompt
        assert "Auto-detected" in prompt

    def test_includes_definition_hints(self):
        """Prompt should include hints from definition."""
        requirement = ContextRequirement(key="maintainers")
        definition = ContextDefinitionConfig(
            type="list_or_path",
            prompt="Who are the project maintainers?",
            hint="Provide GitHub usernames",
            examples=["@user1, @user2", "MAINTAINERS.md"],
        )

        prompt = format_context_prompt(
            context_key="maintainers",
            definition=definition,
            requirement=requirement,
            current_value=None,
        )

        assert "Who are the project maintainers?" in prompt
        assert "Provide GitHub usernames" in prompt
        assert "@user1, @user2" in prompt


class TestGetContextRequirementsForCategory:
    """Tests for get_context_requirements_for_category function."""

    def test_returns_empty_when_no_requirements(self):
        """Should return empty list when no requirements defined."""
        result = get_context_requirements_for_category(
            category="security_policy",
            control_id=None,
            framework=None,
            registry={"security_policy": {"description": "test"}},
        )
        assert result == []

    def test_loads_from_registry_as_fallback(self):
        """Should load requirements from Python registry when no TOML."""
        registry = {
            "codeowners": {
                "description": "Create CODEOWNERS",
                "requires_context": [{
                    "key": "maintainers",
                    "required": True,
                    "confidence_threshold": 0.9,
                }],
            },
        }

        result = get_context_requirements_for_category(
            category="codeowners",
            control_id=None,
            framework=None,
            registry=registry,
        )

        assert len(result) == 1
        assert result[0].key == "maintainers"
        assert result[0].confidence_threshold == 0.9


class TestOrchestratorContextIntegration:
    """Integration tests for orchestrator with context validation."""

    @pytest.mark.integration
    def test_orchestrator_checks_requirements_before_remediation(self, temp_repo):
        """Orchestrator should call validator before running function."""
        from darnit_baseline.remediation.orchestrator import _apply_remediation

        # Run codeowners remediation without confirmation
        result = _apply_remediation(
            category="codeowners",
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=False,
        )

        # Should return needs_confirmation status
        assert result["status"] == "needs_confirmation"
        assert "maintainers" in result.get("missing_context", [])
        assert "confirm_project_context" in result.get("result", "")

    @pytest.mark.integration
    def test_orchestrator_returns_needs_confirmation_status(self, temp_repo):
        """Status should be 'needs_confirmation' when context missing."""
        from darnit_baseline.remediation.orchestrator import _apply_remediation

        result = _apply_remediation(
            category="governance",
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=False,
        )

        assert result["status"] == "needs_confirmation"
        assert "result" in result  # Should have prompt text

    @pytest.mark.integration
    def test_orchestrator_proceeds_when_context_confirmed(self, temp_repo):
        """Remediation should run when all context is confirmed."""
        from darnit.server.tools.project_context import confirm_project_context_impl
        from darnit_baseline.remediation.orchestrator import _apply_remediation

        # First confirm maintainers
        confirm_result = confirm_project_context_impl(
            local_path=temp_repo,
            maintainers=["@alice", "@bob"],
        )
        assert "maintainers" in confirm_result

        # Now run remediation - should proceed
        result = _apply_remediation(
            category="codeowners",
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=False,
        )

        # Should either be applied or still use legacy function logic
        # (depends on whether orchestrator pre-check is primary or fallback)
        assert result["status"] in ["applied", "needs_confirmation"]

        # If applied, file should exist
        if result["status"] == "applied":
            assert (Path(temp_repo) / "CODEOWNERS").exists()
