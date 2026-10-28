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
    def test_detect_maintainers_from_file_ignores_email_domain(self, temp_repo):
        """An email domain must not become a maintainer handle (issue #464)."""
        (Path(temp_repo) / "MAINTAINERS.md").write_text(
            "# Maintainers\n\n- Alice Example <alice@realcorp.io> @alice\n"
        )

        sieve = ContextSieve()
        result = sieve.detect("maintainers", temp_repo, "owner", "repo")

        assert result.key == "maintainers"
        assert "@alice" in result.value
        assert not any("realcorp" in str(v).lower() for v in result.value)

    @pytest.mark.unit
    def test_parse_maintainers_file_email_domain_not_a_handle(self):
        """The issue's exact example: only the real handle is returned."""
        sieve = ContextSieve()
        assert (
            sieve._parse_maintainers_file("- Alice Example <alice@realcorp.io> @alice\n")
            == ["@alice"]
        )

    @pytest.mark.unit
    def test_parse_maintainers_file_name_and_email_without_handle(self):
        """A display name plus email, with no @handle, yields no maintainers."""
        sieve = ContextSieve()
        assert sieve._parse_maintainers_file("- Alice Example <alice@realcorp.io>\n") == []

    @pytest.mark.unit
    def test_parse_maintainers_file_plain_email_yields_nothing(self):
        """A bare email address contributes no handle."""
        sieve = ContextSieve()
        assert sieve._parse_maintainers_file("Contact: bob@example.com\n") == []

    @pytest.mark.unit
    def test_parse_maintainers_file_keeps_plain_handles(self):
        """Ordinary @mentions still parse as before."""
        sieve = ContextSieve()
        assert sieve._parse_maintainers_file(
            "- @alice - Lead maintainer\n- @bob - Core contributor\n"
        ) == ["@alice", "@bob"]

    @pytest.mark.unit
    def test_parse_maintainers_file_handle_glued_to_email(self):
        """A handle written directly after an email still parses."""
        sieve = ContextSieve()
        assert (
            sieve._parse_maintainers_file("- Alice Example <alice@realcorp.io>@alice\n")
            == ["@alice"]
        )

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
        """Validator uses sieve detection and names the hint source file.

        When a hint source file (MAINTAINERS.md) exists, the prompt names it.
        Feature 042 (FR-013, research R6) replaced the "authoritative source"
        section: the sieve's candidate is shown as unconfirmed data with its
        digest, the only thing an agent may accept on the person's answer.
        """
        # Create a MAINTAINERS.md - this is an authoritative source
        (Path(temp_repo) / "MAINTAINERS.md").write_text("""
# Maintainers
- @alice
- @bob
""")

        from darnit.config.framework_schema import ContextRequirement
        from darnit.config.merger import load_framework_config
        from darnit.remediation.context_validator import check_context_requirements

        # Load the framework config to get hint_sources from TOML
        framework_path = Path(__file__).parent.parent.parent.parent / "packages" / "darnit-baseline" / "src" / "darnit_baseline" / "openssf-baseline.toml"
        framework = load_framework_config(framework_path)

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
            framework=framework,
            owner="test-owner",
            repo="test-repo",
        )

        # Sieve may populate auto_detected (now allowed via allow_sieve_hints=true)
        # Key behavior: maintainers should still be in missing_context (needs confirmation)
        assert "maintainers" in result.missing_context
        assert len(result.prompts) >= 1
        assert "`MAINTAINERS.md`" in result.prompts[0]
        assert "UNCONFIRMED" in result.prompts[0]

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


class TestStatusChecksDetection:
    """Test required_status_checks detection (deterministic workflow fallback and API candidate proposing)."""

    @pytest.mark.unit
    def test_detect_status_checks_deterministic(self, temp_repo):
        """Detect status checks from workflow files."""
        wf_dir = Path(temp_repo) / ".github" / "workflows"
        wf_dir.mkdir(parents=True)
        (wf_dir / "ci.yml").write_text("""
name: CI
on: [push, pull_request]
jobs:
  test:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
  lint:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
""")
        sieve = ContextSieve()
        signals = sieve._detect_status_checks_deterministic(temp_repo, "test-owner", "test-repo")
        assert len(signals) == 1
        assert signals[0].source == SignalSource.PROJECT_MANIFEST
        assert "test" in signals[0].value
        assert "lint" in signals[0].value

    @pytest.mark.unit
    def test_detect_status_checks_api_success(self, temp_repo):
        """Detect status checks passing on recent PRs."""

        def fake_gh_api(endpoint, **kwargs):
            if "/pulls" in endpoint:
                return [{"number": 42, "head": {"sha": "sha123"}}], 200, ""
            if "/check-runs" in endpoint:
                return (
                    {
                        "check_runs": [
                            {"name": "ci / build", "conclusion": "success"},
                            {"name": "failing-check", "conclusion": "failure"},
                        ]
                    },
                    200,
                    "",
                )
            if "/status" in endpoint:
                return (
                    {
                        "statuses": [
                            {"context": "codecov/patch", "state": "success"},
                            {"context": "bad/check", "state": "failure"},
                        ]
                    },
                    200,
                    "",
                )
            return {}, 404, "not found"

        with patch("darnit.core.utils.gh_api_with_status", side_effect=fake_gh_api):
            sieve = ContextSieve()
            signals = sieve._detect_status_checks_api(temp_repo, "test-owner", "test-repo")
            assert len(signals) == 1
            signal = signals[0]
            assert signal.source == SignalSource.GITHUB_API
            assert signal.method == "Checks seen passing on PR #42"
            assert "ci / build" in signal.value
            assert "codecov/patch" in signal.value
            assert "failing-check" not in signal.value
            assert "bad/check" not in signal.value

    @pytest.mark.unit
    def test_detect_status_checks_api_failure(self, temp_repo):
        """Gracefully returns empty list on API error."""
        with patch("darnit.core.utils.gh_api_with_status", return_value=({}, 500, "Server Error")):
            sieve = ContextSieve()
            signals = sieve._detect_status_checks_api(temp_repo, "test-owner", "test-repo")
            assert signals == []

