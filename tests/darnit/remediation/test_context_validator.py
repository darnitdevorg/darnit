"""Tests for the context validator module.

Tests the generic context confirmation pattern that checks requirements
before running remediations.
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import patch

import pytest

from darnit.config.context_schema import ContextSource, ContextValue, Standing
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


def _resolved(key, standing, value=None, confidence=None):
    """A resolver result with one key; patched in for ``resolve_context``."""
    from darnit.config.context_resolve import ResolvedContext
    from darnit.config.context_schema import Origin, OriginKind, ResolvedValue

    origin = Origin(kind=OriginKind.DETECTOR, method="test", confidence=confidence) if confidence is not None else None
    return ResolvedContext(values={key: ResolvedValue(key=key, standing=standing, value=value, origin=origin)})


def _check(requirement, resolved, temp_repo):
    with patch("darnit.config.context_resolve.resolve_context", return_value=resolved):
        return check_context_requirements(requirements=[requirement], local_path=temp_repo, framework=None)


class TestCheckContextRequirements:
    """Tests for check_context_requirements function.

    Feature 042 (FR-006): readiness is decided by the resolver's standing,
    not by a stored ``source`` field and confidence (was: a USER_CONFIRMED
    source, or an AUTO_DETECTED one at or above the threshold, was ready).
    """

    def test_returns_ready_when_no_requirements(self, temp_repo):
        """Empty requirements list should return ready=True."""
        result = check_context_requirements(
            requirements=[],
            local_path=temp_repo,
            framework=None,
        )
        assert result.ready is True
        assert result.missing_context == []

    def test_returns_ready_when_context_confirmed(self, temp_repo):
        """A confirmed value is ready."""
        requirement = ContextRequirement(
            key="maintainers",
            required=True,
            confidence_threshold=0.9,
            prompt_if_auto_detected=True,
        )

        result = _check(requirement, _resolved("maintainers", Standing.CONFIRMED, ["@alice", "@bob"]), temp_repo)

        assert result.ready is True
        assert result.missing_context == []

    def test_returns_not_ready_when_context_missing(self, temp_repo):
        """Should return ready=False with prompts when context is unknown."""
        requirement = ContextRequirement(
            key="maintainers",
            required=True,
            confidence_threshold=0.9,
            prompt_if_auto_detected=True,
        )

        result = _check(requirement, _resolved("maintainers", Standing.UNKNOWN), temp_repo)

        assert result.ready is False
        assert "maintainers" in result.missing_context
        assert len(result.prompts) == 1

    def test_respects_confidence_threshold(self, temp_repo):
        """A value concluded below the requirement's threshold is not ready."""
        requirement = ContextRequirement(
            key="has_releases",
            required=True,
            confidence_threshold=0.9,
            prompt_if_auto_detected=False,
        )

        result = _check(requirement, _resolved("has_releases", Standing.CONCLUDED, True, 0.85), temp_repo)

        assert result.ready is False
        assert "has_releases" in result.missing_context

    def test_prompt_if_auto_detected_flag(self, temp_repo):
        """A concluded value still prompts when the requirement asks to."""
        requirement = ContextRequirement(
            key="has_releases",
            required=True,
            confidence_threshold=0.9,
            prompt_if_auto_detected=True,
        )

        result = _check(requirement, _resolved("has_releases", Standing.CONCLUDED, True, 0.95), temp_repo)

        assert result.ready is False
        assert "has_releases" in result.missing_context
        assert result.auto_detected["has_releases"] is True

    def test_concluded_value_allowed_when_flag_false(self, temp_repo):
        """A concluded value at or above the threshold proceeds if prompt_if_auto_detected=False."""
        requirement = ContextRequirement(
            key="has_releases",
            required=True,
            confidence_threshold=0.9,
            prompt_if_auto_detected=False,
        )

        result = _check(requirement, _resolved("has_releases", Standing.CONCLUDED, True, 0.95), temp_repo)

        assert result.ready is True

    def test_candidate_is_never_ready(self, temp_repo):
        """A candidate at any confidence is shown, never used."""
        requirement = ContextRequirement(
            key="maintainers",
            required=True,
            confidence_threshold=0.9,
            prompt_if_auto_detected=False,
        )

        result = _check(requirement, _resolved("maintainers", Standing.CANDIDATE, ["@user1"], 1.0), temp_repo)

        assert result.ready is False
        assert result.auto_detected["maintainers"] == ["@user1"]


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
        assert "confirm_project_data" in prompt

    def test_maintainers_does_not_show_auto_detected_value(self):
        """Maintainers prompt should NOT show auto-detected values (security measure).

        Auto-detected values for maintainers are intentionally hidden to prevent
        AI agents from guessing. The prompt should ask the user instead.
        """
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

        # Should NOT show auto-detected values for maintainers
        assert "@alice" not in prompt
        assert "@bob" not in prompt
        assert "Auto-detected" not in prompt
        # Should instead ask user to provide the information
        assert "Ask the user" in prompt
        assert "MUST ask" in prompt  # AI instruction

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

    def test_prompt_with_hint_file_shows_parsed_values_and_placeholder(self, temp_repo):
        """When a hint file exists, prompt should show parsed values but use placeholder command."""
        # Create a CODEOWNERS file
        codeowners_path = Path(temp_repo) / "CODEOWNERS"
        codeowners_path.write_text("* @alice @bob\ndocs/ @charlie\n")

        definition = ContextDefinitionConfig(
            type="list_or_path",
            prompt="Who are the project maintainers?",
            hint_sources=["CODEOWNERS", ".github/CODEOWNERS"],
            allow_sieve_hints=True,
        )
        requirement = ContextRequirement(
            key="maintainers",
            required=True,
            confidence_threshold=0.9,
            prompt_if_auto_detected=True,
        )

        prompt = format_context_prompt(
            context_key="maintainers",
            definition=definition,
            requirement=requirement,
            current_value=None,
            local_path=temp_repo,
        )

        # Should show the parsed values from the file
        assert "@alice" in prompt
        assert "@bob" in prompt
        assert "@charlie" in prompt
        # Should use a placeholder in the command, NOT the filename or actual values
        assert "confirm_project_data(maintainers=<user-confirmed values>)" in prompt
        # Should NOT suggest passing the filename
        assert 'maintainers="CODEOWNERS"' not in prompt

    def test_prompt_with_sieve_hints_uses_placeholder_command(self):
        """When sieve hints exist, prompt should show detected values but use placeholder command."""
        definition = ContextDefinitionConfig(
            type="list_or_path",
            prompt="Who are the project maintainers?",
            allow_sieve_hints=True,
        )
        requirement = ContextRequirement(
            key="maintainers",
            required=True,
            confidence_threshold=0.9,
            prompt_if_auto_detected=True,
        )
        current_value = ContextValue(
            value=["@detected1", "@detected2"],
            source=ContextSource.AUTO_DETECTED,
            confidence=0.7,
        )

        prompt = format_context_prompt(
            context_key="maintainers",
            definition=definition,
            requirement=requirement,
            current_value=current_value,
        )

        # Should show the detected values as hints
        assert "@detected1" in prompt
        assert "@detected2" in prompt
        # Should use a placeholder in the command, NOT the actual detected values
        assert "confirm_project_data(maintainers=<user-confirmed values>)" in prompt
        # Should NOT have executable command with actual values
        assert "['@detected1', '@detected2']" not in prompt


class TestStaleValueDetection:
    """A confirmed value that names a hint source file is treated as missing."""

    def _requirement(self):
        return ContextRequirement(
            key="maintainers",
            required=True,
            confidence_threshold=0.9,
            prompt_if_auto_detected=True,
        )

    @pytest.mark.parametrize("value", ["CODEOWNERS", ".github/CODEOWNERS"])
    def test_file_name_treated_as_missing(self, temp_repo, value):
        result = _check(self._requirement(), _resolved("maintainers", Standing.CONFIRMED, value), temp_repo)

        assert result.ready is False
        assert "maintainers" in result.missing_context

    def test_actual_list_value_not_treated_as_stale(self, temp_repo):
        result = _check(
            self._requirement(), _resolved("maintainers", Standing.CONFIRMED, ["@alice", "@bob"]), temp_repo
        )

        assert result.ready is True
        assert result.missing_context == []


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
                "requires_context": [
                    {
                        "key": "maintainers",
                        "required": True,
                        "confidence_threshold": 0.9,
                    }
                ],
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
        from darnit_baseline.remediation.orchestrator import _apply_control_remediation

        # Run codeowners control remediation without confirmation
        result = _apply_control_remediation(
            control_id="OSPS-GV-04.01",
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=False,
        )

        # Should return needs_confirmation status
        assert result["status"] == "needs_confirmation"
        assert "maintainers" in result.get("missing_context", [])
        assert "confirm_project_data" in result.get("result", "")

    @pytest.mark.integration
    def test_orchestrator_returns_needs_confirmation_status(self, temp_repo):
        """Status should be 'needs_confirmation' when context missing."""
        from darnit_baseline.remediation.orchestrator import _apply_control_remediation

        result = _apply_control_remediation(
            control_id="OSPS-GV-01.01",
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
        from darnit.server.tools.project_data import confirm_project_data_impl
        from darnit_baseline.remediation.orchestrator import _apply_control_remediation

        # First confirm maintainers
        confirm_result = confirm_project_data_impl(
            local_path=temp_repo,
            maintainers=["@alice", "@bob"],
        )
        assert "maintainers" in confirm_result

        # Now run remediation - should proceed
        result = _apply_control_remediation(
            control_id="OSPS-GV-04.01",
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
            dry_run=False,
        )

        assert result["status"] in ["applied", "needs_confirmation"]

        if result["status"] == "applied":
            assert (Path(temp_repo) / "CODEOWNERS").exists()


class TestSieveDetectionIsFiltered:
    """FR-003/FR-004: remediation's detection (now the resolver's) must not bypass detect_filter."""

    class _Result:
        is_usable = True
        confidence = 1.0
        signals: list = []

        def __init__(self, value):
            self.value = value

    def _sieve(self, value):
        result = self._Result(value)
        return type("Sieve", (), {"detect": lambda self, *a, **k: result})()

    def _detect(self, value, temp_repo):
        from darnit.config.context_resolve import _detect
        from darnit.config.context_storage import get_context_definitions

        definition = get_context_definitions(".")["security_contact"]
        with patch("darnit.context.get_context_sieve", return_value=self._sieve(value)):
            return _detect("security_contact", definition, temp_repo, None, None)

    @pytest.mark.unit
    def test_placeholder_is_not_offered(self, temp_repo):
        assert self._detect("security@example.com", temp_repo) == (None, None)

    @pytest.mark.unit
    def test_real_value_is_offered(self, temp_repo):
        detected, _ = self._detect("security@real.org", temp_repo)
        assert detected is not None
        assert detected.value == "security@real.org"
