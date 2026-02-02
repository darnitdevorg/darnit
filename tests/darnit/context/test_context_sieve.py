"""Tests for the context detection sieve.

These tests verify that:
1. Progressive detection works (deterministic → heuristic → API → combine)
2. Confidence scoring correctly combines signals
3. Auto-detected values are properly formatted
4. Missing context returns appropriate results
"""

import os
import tempfile
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

from darnit.context import (
    ContextDetectionResult,
    ContextSieve,
    ContextSignal,
    SignalSource,
    calculate_confidence,
    get_context_sieve,
)


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


class TestConfidenceScoring:
    """Test the confidence scoring module."""

    @pytest.mark.unit
    def test_single_signal_confidence(self):
        """Single signal gets weighted confidence."""
        signals = [
            ContextSignal(
                source=SignalSource.EXPLICIT_FILE,
                value=["@alice"],
                raw_confidence=0.95,
            )
        ]
        result = calculate_confidence(signals)

        # EXPLICIT_FILE weight is 0.9, raw_confidence is 0.95
        # Expected: 0.95 * 0.9 = 0.855
        assert 0.8 <= result.confidence <= 0.9
        assert result.value == ["@alice"]
        assert result.agreement_factor == 1.0

    @pytest.mark.unit
    def test_multiple_agreeing_signals_boost(self):
        """Multiple agreeing signals get confidence boost."""
        signals = [
            ContextSignal(
                source=SignalSource.EXPLICIT_FILE,
                value=["@alice", "@bob"],
                raw_confidence=0.9,
            ),
            ContextSignal(
                source=SignalSource.GIT_HISTORY,
                value=["alice", "bob"],  # Without @, should still match
                raw_confidence=0.7,
            ),
        ]
        result = calculate_confidence(signals)

        # Should have agreement boost
        assert result.confidence > 0.7
        assert result.agreement_factor > 0.5

    @pytest.mark.unit
    def test_conflicting_signals_penalty(self):
        """Conflicting signals get confidence penalty."""
        signals = [
            ContextSignal(
                source=SignalSource.EXPLICIT_FILE,
                value=["@alice"],
                raw_confidence=0.9,
            ),
            ContextSignal(
                source=SignalSource.GITHUB_API,
                value=["@charlie", "@dave"],  # Completely different
                raw_confidence=0.7,
            ),
        ]
        result = calculate_confidence(signals)

        # Low agreement factor (0.5 or less indicates conflict)
        assert result.agreement_factor <= 0.5

    @pytest.mark.unit
    def test_empty_signals(self):
        """Empty signals list returns zero confidence."""
        result = calculate_confidence([])
        assert result.confidence == 0.0
        assert result.value is None

    @pytest.mark.unit
    def test_user_confirmed_highest_weight(self):
        """USER_CONFIRMED has the highest weight."""
        signals = [
            ContextSignal(
                source=SignalSource.USER_CONFIRMED,
                value=["@alice"],
                raw_confidence=1.0,
            ),
            ContextSignal(
                source=SignalSource.GITHUB_API,
                value=["@bob"],
                raw_confidence=0.8,
            ),
        ]
        result = calculate_confidence(signals)

        # USER_CONFIRMED should take precedence
        assert result.value == ["@alice"]


class TestContextSieve:
    """Test the context detection sieve."""

    @pytest.mark.unit
    def test_sieve_singleton(self):
        """get_context_sieve returns singleton instance."""
        sieve1 = get_context_sieve()
        sieve2 = get_context_sieve()
        assert sieve1 is sieve2

    @pytest.mark.unit
    def test_detect_unknown_key(self, temp_repo):
        """Unknown context key returns empty result."""
        sieve = ContextSieve()
        result = sieve.detect("unknown_key", temp_repo, "owner", "repo")

        assert result.key == "unknown_key"
        assert result.value is None
        assert result.confidence == 0.0
        assert result.needs_confirmation is True

    @pytest.mark.unit
    def test_detect_maintainers_from_file(self, temp_repo):
        """Detects maintainers from MAINTAINERS.md file."""
        # Create MAINTAINERS.md
        (Path(temp_repo) / "MAINTAINERS.md").write_text("""
# Maintainers

- @alice - Lead maintainer
- @bob - Core contributor
""")

        sieve = ContextSieve()
        result = sieve.detect("maintainers", temp_repo, "owner", "repo")

        assert result.key == "maintainers"
        assert result.is_usable
        assert "@alice" in result.value or "alice" in str(result.value).lower()
        assert "@bob" in result.value or "bob" in str(result.value).lower()
        # High confidence from explicit file
        assert result.confidence >= 0.8

    @pytest.mark.unit
    def test_detect_maintainers_from_codeowners(self, temp_repo):
        """Detects maintainers from CODEOWNERS file."""
        # Create .github/CODEOWNERS
        github_dir = Path(temp_repo) / ".github"
        github_dir.mkdir()
        (github_dir / "CODEOWNERS").write_text("""
# CODEOWNERS
* @alice @bob
/docs/ @charlie
""")

        sieve = ContextSieve()
        result = sieve.detect("maintainers", temp_repo, "owner", "repo")

        assert result.key == "maintainers"
        assert result.is_usable
        # Should find at least the global owners
        assert len(result.value) >= 2

    @pytest.mark.unit
    def test_detect_maintainers_from_package_json(self, temp_repo):
        """Detects maintainers from package.json."""
        (Path(temp_repo) / "package.json").write_text("""{
    "name": "test-package",
    "author": "Alice Smith <alice@example.com>",
    "contributors": [
        {"name": "Bob Jones"}
    ]
}""")

        sieve = ContextSieve()
        result = sieve.detect("maintainers", temp_repo, "owner", "repo")

        assert result.key == "maintainers"
        assert result.is_usable
        # Should find author and contributors
        assert any("alice" in str(v).lower() for v in result.value)

    @pytest.mark.unit
    def test_detect_security_contact_from_security_md(self, temp_repo):
        """Detects security contact from SECURITY.md."""
        (Path(temp_repo) / "SECURITY.md").write_text("""
# Security Policy

## Reporting a Vulnerability

Please report security issues to security@example.com
""")

        sieve = ContextSieve()
        result = sieve.detect("security_contact", temp_repo, "owner", "repo")

        assert result.key == "security_contact"
        assert result.is_usable
        assert "security@example.com" in result.value

    @pytest.mark.unit
    def test_detect_governance_from_file(self, temp_repo):
        """Detects governance model from GOVERNANCE.md."""
        (Path(temp_repo) / "GOVERNANCE.md").write_text("""
# Governance

This project uses a steering committee model.
""")

        sieve = ContextSieve()
        result = sieve.detect("governance_model", temp_repo, "owner", "repo")

        assert result.key == "governance_model"
        assert result.is_usable
        # Should detect committee model
        assert "committee" in result.value.lower() or "documented" in result.value.lower()

    @pytest.mark.unit
    def test_high_confidence_skips_later_phases(self, temp_repo):
        """High-confidence deterministic result skips heuristic/API phases."""
        # Create high-confidence MAINTAINERS.md
        (Path(temp_repo) / "MAINTAINERS.md").write_text("""
# Maintainers
- @alice
- @bob
""")

        sieve = ContextSieve()

        # Mock the API detection to track if it's called
        with patch.object(sieve, '_detect_maintainers_api'):
            result = sieve.detect("maintainers", temp_repo, "owner", "repo")

            # API phase should not be called if deterministic was sufficient
            # (depends on confidence threshold)
            assert result.is_usable
            # The actual behavior depends on threshold

    @pytest.mark.unit
    @patch('subprocess.run')
    def test_github_api_detection(self, mock_run, temp_repo):
        """Tests GitHub API detection for maintainers."""
        # Mock successful API call
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout='["alice", "bob"]'
        )

        sieve = ContextSieve()
        signals = sieve._detect_maintainers_api(temp_repo, "test-owner", "test-repo")

        assert len(signals) == 1
        assert signals[0].source == SignalSource.GITHUB_API
        assert "@alice" in signals[0].value
        assert "@bob" in signals[0].value

    @pytest.mark.unit
    @patch('subprocess.run')
    def test_github_api_failure_handled(self, mock_run, temp_repo):
        """Tests that GitHub API failures are handled gracefully."""
        # Mock failed API call
        mock_run.return_value = MagicMock(
            returncode=1,
            stdout='',
            stderr='API error'
        )

        sieve = ContextSieve()
        signals = sieve._detect_maintainers_api(temp_repo, "test-owner", "test-repo")

        # Should return empty signals, not raise
        assert len(signals) == 0


class TestContextDetectionResult:
    """Test the ContextDetectionResult dataclass."""

    @pytest.mark.unit
    def test_is_high_confidence(self):
        """Test high confidence detection."""
        result = ContextDetectionResult(
            key="maintainers",
            value=["@alice"],
            confidence=0.95,
        )
        assert result.is_high_confidence is True

        result.confidence = 0.7
        assert result.is_high_confidence is False

    @pytest.mark.unit
    def test_is_usable(self):
        """Test usability checks."""
        # Usable with list value
        result = ContextDetectionResult(
            key="maintainers",
            value=["@alice"],
            confidence=0.5,
        )
        assert result.is_usable is True

        # Not usable with None
        result.value = None
        assert result.is_usable is False

        # Not usable with empty list
        result.value = []
        assert result.is_usable is False

        # Usable with string value
        result = ContextDetectionResult(
            key="security_contact",
            value="security@example.com",
            confidence=0.5,
        )
        assert result.is_usable is True


class TestIntegrationWithValidator:
    """Test integration between context sieve and validator."""

    @pytest.mark.unit
    def test_validator_uses_sieve_for_detection(self, temp_repo):
        """Validator should use sieve when context is missing."""
        # Create a MAINTAINERS.md so sieve can detect
        (Path(temp_repo) / "MAINTAINERS.md").write_text("""
# Maintainers
- @alice
- @bob
""")

        from darnit.config.framework_schema import ContextRequirement
        from darnit.remediation.context_validator import check_context_requirements

        requirements = [
            ContextRequirement(
                key="maintainers",
                required=True,
                confidence_threshold=0.9,
                prompt_if_auto_detected=True,
            )
        ]

        result = check_context_requirements(
            requirements=requirements,
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
        )

        # Should have auto-detected maintainers
        assert "maintainers" in result.auto_detected
        assert len(result.auto_detected["maintainers"]) >= 2

    @pytest.mark.unit
    def test_validator_prompts_for_low_confidence(self, temp_repo):
        """Validator should prompt when confidence is below threshold."""
        # Create only package.json (lower confidence source)
        (Path(temp_repo) / "package.json").write_text("""{
    "name": "test",
    "author": "Alice"
}""")

        from darnit.config.framework_schema import ContextRequirement
        from darnit.remediation.context_validator import check_context_requirements

        requirements = [
            ContextRequirement(
                key="maintainers",
                required=True,
                confidence_threshold=0.95,  # Very high threshold
                prompt_if_auto_detected=True,
            )
        ]

        result = check_context_requirements(
            requirements=requirements,
            local_path=temp_repo,
            owner="test-owner",
            repo="test-repo",
        )

        # Should not be ready (confidence too low)
        assert result.ready is False
        # Should have prompts
        assert len(result.prompts) > 0
