"""Tests for context storage abstraction layer.

Tests the unified interface for loading and saving context values
with provenance tracking.
"""

from pathlib import Path
from unittest.mock import MagicMock, patch

import yaml

from darnit.config.context_schema import ContextValue
from darnit.config.context_storage import (
    _run_detect_pipeline,
    get_context_definitions,
    get_context_value,
    get_pending_context,
    get_raw_value,
    is_context_confirmed,
    load_context,
    save_context_value,
    save_context_values,
)


class TestLoadContext:
    """Tests for load_context function."""

    def test_empty_repo(self, tmp_path: Path) -> None:
        """Test loading from repo with no config."""
        result = load_context(str(tmp_path))
        assert result == {}

    def test_load_legacy_context(self, tmp_path: Path) -> None:
        """Test loading context from x-openssf-baseline format."""
        # Create .project/ directory structure
        project_dir = tmp_path / ".project"
        project_dir.mkdir()
        config_path = project_dir / "project.yaml"
        config_path.write_text("""
name: test-project
""")
        ext_path = project_dir / "darnit.yaml"
        ext_path.write_text("""
context:
  has_releases: true
  has_subprojects: false
  is_library: true
  ci_provider: github
""")
        result = load_context(str(tmp_path))

        # Should organize by category
        assert "build" in result
        assert "has_releases" in result["build"]
        assert result["build"]["has_releases"].value is True

        assert "project" in result
        assert "has_subprojects" in result["project"]
        assert result["project"]["has_subprojects"].value is False
        assert "is_library" in result["project"]
        assert result["project"]["is_library"].value is True

        assert "ci" in result
        assert "provider" in result["ci"]
        assert result["ci"]["provider"].value == "github"

    def test_context_values_have_provenance(self, tmp_path: Path) -> None:
        """Test that loaded values have correct provenance tracking."""
        project_dir = tmp_path / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("name: test-project\n")
        (project_dir / "darnit.yaml").write_text("""
context:
  has_releases: true
""")
        result = load_context(str(tmp_path))

        ctx_value = result["build"]["has_releases"]
        assert isinstance(ctx_value, ContextValue)
        assert ctx_value.source == "user_confirmed"
        assert ctx_value.confidence == 1.0


class TestGetContextValue:
    """Tests for get_context_value function."""

    def test_get_existing_value(self, tmp_path: Path) -> None:
        """Test getting an existing context value."""
        project_dir = tmp_path / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("name: test-project\n")
        (project_dir / "darnit.yaml").write_text("""
context:
  has_releases: true
""")
        value = get_context_value(str(tmp_path), "has_releases")
        assert value is not None
        assert value.value is True

    def test_get_missing_value(self, tmp_path: Path) -> None:
        """Test getting a missing context value."""
        value = get_context_value(str(tmp_path), "nonexistent")
        assert value is None

    def test_get_value_with_category(self, tmp_path: Path) -> None:
        """Test getting a value from specific category."""
        project_dir = tmp_path / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("name: test-project\n")
        (project_dir / "darnit.yaml").write_text("""
context:
  has_releases: true
  is_library: true
""")
        # Search in build category
        build_value = get_context_value(str(tmp_path), "has_releases", category="build")
        assert build_value is not None

        # Search wrong category
        wrong_cat = get_context_value(str(tmp_path), "has_releases", category="project")
        assert wrong_cat is None


class TestGetRawValue:
    """Tests for get_raw_value function."""

    def test_get_raw_value(self, tmp_path: Path) -> None:
        """Test getting raw value without provenance."""
        project_dir = tmp_path / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("name: test-project\n")
        (project_dir / "darnit.yaml").write_text("""
context:
  ci_provider: gitlab
""")
        value = get_raw_value(str(tmp_path), "provider")
        assert value == "gitlab"

    def test_get_raw_value_default(self, tmp_path: Path) -> None:
        """Test default value when not found."""
        value = get_raw_value(str(tmp_path), "missing", default="default_value")
        assert value == "default_value"


class TestIsContextConfirmed:
    """Tests for is_context_confirmed function."""

    def test_confirmed_context(self, tmp_path: Path) -> None:
        """Test checking confirmed context."""
        project_dir = tmp_path / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("name: test-project\n")
        (project_dir / "darnit.yaml").write_text("""
context:
  has_releases: false
""")
        assert is_context_confirmed(str(tmp_path), "has_releases") is True
        assert is_context_confirmed(str(tmp_path), "is_library") is False


class TestSaveContextValue:
    """Tests for save_context_value function."""

    def test_save_new_value(self, tmp_path: Path) -> None:
        """Test saving a new context value."""
        # Initialize git repo for detection
        (tmp_path / ".git").mkdir()

        config_path = save_context_value(str(tmp_path), "has_releases", True)

        assert Path(config_path).exists()

        # Verify it was saved
        value = get_raw_value(str(tmp_path), "has_releases")
        assert value is True

    def test_save_updates_existing(self, tmp_path: Path) -> None:
        """Test that saving updates existing config."""
        (tmp_path / ".git").mkdir()
        project_dir = tmp_path / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("name: existing-project\n")
        (project_dir / "darnit.yaml").write_text("""
context:
  has_releases: false
""")

        save_context_value(str(tmp_path), "has_releases", True)

        # Verify update
        value = get_raw_value(str(tmp_path), "has_releases")
        assert value is True

        # Verify name preserved in project.yaml
        with open(project_dir / "project.yaml") as f:
            data = yaml.safe_load(f)
        assert data["name"] == "existing-project"

    def test_save_unknown_key_succeeds(self, tmp_path: Path) -> None:
        """Test that saving unknown key succeeds (dynamically extending CNCF format)."""
        (tmp_path / ".git").mkdir()

        save_context_value(str(tmp_path), "unknown_key", "value")

        # Verify it was loaded back
        ctx = load_context(str(tmp_path))
        assert "custom" in ctx
        assert ctx["custom"]["unknown_key"].value == "value"


class TestSaveContextValues:
    """Tests for save_context_values function."""

    def test_save_multiple_values(self, tmp_path: Path) -> None:
        """Test saving multiple values at once."""
        (tmp_path / ".git").mkdir()

        save_context_values(
            str(tmp_path),
            {
                "has_releases": True,
                "is_library": False,
                "ci_provider": "github",
            },
        )

        assert get_raw_value(str(tmp_path), "has_releases") is True
        assert get_raw_value(str(tmp_path), "is_library") is False
        assert get_raw_value(str(tmp_path), "provider") == "github"


class TestGetContextDefinitions:
    """Tests for get_context_definitions function."""

    def test_loads_from_framework(self) -> None:
        """Test loading definitions from framework TOML."""
        # Use the actual repo path (current working directory should work)
        definitions = get_context_definitions(".")

        # Should have definitions from openssf-baseline.toml
        assert len(definitions) > 0

        # Check specific definitions exist
        assert "maintainers" in definitions
        assert "security_contact" in definitions
        assert "ci_provider" in definitions

    def test_definition_structure(self) -> None:
        """Test that definitions have correct structure."""
        definitions = get_context_definitions(".")

        if "maintainers" in definitions:
            maintainers = definitions["maintainers"]
            assert maintainers.type == "list_or_path"
            assert "maintainer" in maintainers.prompt.lower()
            assert len(maintainers.affects) > 0


class TestGetPendingContext:
    """Tests for get_pending_context function."""

    def test_returns_pending_for_empty_config(self, tmp_path: Path) -> None:
        """Test that all context is pending when no config exists."""
        (tmp_path / ".git").mkdir()

        # Note: This will try to load framework config which may not work
        # in a temp directory without proper setup
        pending = get_pending_context(str(tmp_path))

        # Should return empty list if framework can't be loaded
        # (which is expected in temp dir)
        assert isinstance(pending, list)

    def test_excludes_confirmed_context(self, tmp_path: Path) -> None:
        """Test that confirmed context is excluded from pending."""
        (tmp_path / ".git").mkdir()
        project_dir = tmp_path / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("name: test-project\n")
        (project_dir / "darnit.yaml").write_text("""
context:
  has_releases: true
  ci_provider: github
""")

        pending = get_pending_context(str(tmp_path))

        # has_releases and ci_provider should not be in pending
        pending_keys = [p.key for p in pending]
        assert "has_releases" not in pending_keys
        assert "ci_provider" not in pending_keys


class TestLoadContextWithNewFields:
    """Tests for load_context with new governance and security fields."""

    def test_load_governance_category(self, tmp_path: Path) -> None:
        """Test loading context with governance category."""
        project_dir = tmp_path / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("name: test-project\n")
        (project_dir / "darnit.yaml").write_text("""
context:
  maintainers:
    - "@alice"
    - "@bob"
  governance_model: democracy
""")
        result = load_context(str(tmp_path))

        assert "governance" in result
        assert "maintainers" in result["governance"]
        assert result["governance"]["maintainers"].value == ["@alice", "@bob"]
        assert "governance_model" in result["governance"]
        assert result["governance"]["governance_model"].value == "democracy"

    def test_load_security_category(self, tmp_path: Path) -> None:
        """Test loading context with security category."""
        project_dir = tmp_path / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("name: test-project\n")
        (project_dir / "darnit.yaml").write_text("""
context:
  security_contact: security@example.org
""")
        result = load_context(str(tmp_path))

        assert "security" in result
        assert "security_contact" in result["security"]
        assert result["security"]["security_contact"].value == "security@example.org"

    def test_load_maintainers_as_path(self, tmp_path: Path) -> None:
        """Test loading maintainers as a file path reference."""
        project_dir = tmp_path / ".project"
        project_dir.mkdir()
        (project_dir / "project.yaml").write_text("name: test-project\n")
        (project_dir / "darnit.yaml").write_text("""
context:
  maintainers: MAINTAINERS.md
""")
        result = load_context(str(tmp_path))

        assert "governance" in result
        assert result["governance"]["maintainers"].value == "MAINTAINERS.md"


class TestSaveNewContextFields:
    """Tests for saving new governance and security context fields."""

    def test_save_maintainers_list(self, tmp_path: Path) -> None:
        """Test saving maintainers as a list."""
        (tmp_path / ".git").mkdir()

        save_context_value(str(tmp_path), "maintainers", ["@user1", "@user2"])

        result = get_raw_value(str(tmp_path), "maintainers")
        assert result == ["@user1", "@user2"]

    def test_save_maintainers_path(self, tmp_path: Path) -> None:
        """Test saving maintainers as a file path."""
        (tmp_path / ".git").mkdir()

        save_context_value(str(tmp_path), "maintainers", "MAINTAINERS.md")

        result = get_raw_value(str(tmp_path), "maintainers")
        assert result == "MAINTAINERS.md"

    def test_save_security_contact(self, tmp_path: Path) -> None:
        """Test saving security contact."""
        (tmp_path / ".git").mkdir()

        save_context_value(str(tmp_path), "security_contact", "security@example.com")

        result = get_raw_value(str(tmp_path), "security_contact")
        assert result == "security@example.com"

    def test_save_governance_model(self, tmp_path: Path) -> None:
        """Test saving governance model."""
        (tmp_path / ".git").mkdir()

        save_context_value(str(tmp_path), "governance_model", "bdfl")

        result = get_raw_value(str(tmp_path), "governance_model")
        assert result == "bdfl"

    def test_maintainers_round_trip(self, tmp_path: Path) -> None:
        """Test that maintainers survive save → load_context round-trip."""
        (tmp_path / ".git").mkdir()
        maintainers = ["@alice", "@bob", "@charlie"]

        save_context_value(str(tmp_path), "maintainers", maintainers)

        # Load via load_context and verify category + value
        context = load_context(str(tmp_path))
        assert "governance" in context
        assert "maintainers" in context["governance"]
        assert context["governance"]["maintainers"].value == maintainers

        # Also verify via get_context_value (searches all categories)
        cv = get_context_value(str(tmp_path), "maintainers")
        assert cv is not None
        assert cv.value == maintainers


class TestRunDetectPipelineHasReleases:
    """Tests for has_releases detect pipeline (FR-2)."""

    def _make_invocation(self, **kwargs):
        from darnit.config.framework_schema import HandlerInvocation

        return HandlerInvocation(**kwargs)

    def test_detects_changelog(self, tmp_path: Path) -> None:
        """has_releases detected when CHANGELOG.md exists."""
        (tmp_path / "CHANGELOG.md").write_text("# Changelog\n## v1.0.0\n")
        pipeline = [
            self._make_invocation(
                handler="file_exists", files=["CHANGELOG.md", "CHANGELOG", "CHANGES.md", "CHANGES"], value_if_pass=True
            ),
        ]
        result = _run_detect_pipeline("has_releases", pipeline, str(tmp_path), "owner", "repo")
        assert result is not None
        assert result.value is True
        assert "file_exists" in result.detection_method

    def test_detects_changes_file(self, tmp_path: Path) -> None:
        """has_releases detected when CHANGES file exists."""
        (tmp_path / "CHANGES").write_text("Changes\n")
        pipeline = [
            self._make_invocation(
                handler="file_exists", files=["CHANGELOG.md", "CHANGELOG", "CHANGES.md", "CHANGES"], value_if_pass=True
            ),
        ]
        result = _run_detect_pipeline("has_releases", pipeline, str(tmp_path), "owner", "repo")
        assert result is not None
        assert result.value is True

    def test_detects_release_workflow(self, tmp_path: Path) -> None:
        """has_releases detected when release workflow exists."""
        workflows = tmp_path / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "release.yml").write_text("on: release\n")
        pipeline = [
            self._make_invocation(handler="file_exists", files=[".github/workflows/release*"], value_if_pass=True),
        ]
        result = _run_detect_pipeline("has_releases", pipeline, str(tmp_path), "owner", "repo")
        assert result is not None
        assert result.value is True

    def test_no_evidence_returns_none(self, tmp_path: Path) -> None:
        """has_releases returns None when no release evidence exists."""
        pipeline = [
            self._make_invocation(handler="file_exists", files=[".github/workflows/release*"], value_if_pass=True),
            self._make_invocation(handler="file_exists", files=["CHANGELOG.md", "CHANGELOG"], value_if_pass=True),
        ]
        result = _run_detect_pipeline("has_releases", pipeline, str(tmp_path), "owner", "repo")
        assert result is None


class TestRunDetectPipelinePlatform:
    """Tests for platform detect pipeline (FR-3)."""

    def _make_invocation(self, **kwargs):
        from darnit.config.framework_schema import HandlerInvocation

        return HandlerInvocation(**kwargs)

    @patch("darnit.sieve.builtin_handlers.subprocess.run")
    def test_detects_github_from_remote(self, mock_run, tmp_path: Path) -> None:
        """platform detected as 'github' when remote contains github.com."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="https://github.com/owner/repo.git\n",
            stderr="",
        )
        pipeline = [
            self._make_invocation(
                handler="exec",
                command=["git", "remote", "get-url", "origin"],
                pass_exit_codes=[0],
                expr='output.stdout.contains("github.com")',
                value_if_pass="github",
            ),
        ]
        result = _run_detect_pipeline("platform", pipeline, str(tmp_path), "owner", "repo")
        assert result is not None
        assert result.value == "github"

    @patch("darnit.sieve.builtin_handlers.subprocess.run")
    def test_detects_gitlab_from_remote(self, mock_run, tmp_path: Path) -> None:
        """platform detected as 'gitlab' when remote contains gitlab.com."""
        mock_run.return_value = MagicMock(
            returncode=0,
            stdout="https://gitlab.com/owner/repo.git\n",
            stderr="",
        )
        pipeline = [
            self._make_invocation(
                handler="exec",
                command=["git", "remote", "get-url", "origin"],
                pass_exit_codes=[0],
                expr='output.stdout.contains("github.com")',
                value_if_pass="github",
            ),
            self._make_invocation(
                handler="exec",
                command=["git", "remote", "get-url", "origin"],
                pass_exit_codes=[0],
                expr='output.stdout.contains("gitlab.com")',
                value_if_pass="gitlab",
            ),
        ]
        result = _run_detect_pipeline("platform", pipeline, str(tmp_path), "owner", "repo")
        assert result is not None
        assert result.value == "gitlab"

    def test_falls_back_to_github_dir(self, tmp_path: Path) -> None:
        """platform detected as 'github' from .github/ directory when no remote."""
        (tmp_path / ".github").mkdir()
        pipeline = [
            self._make_invocation(handler="file_exists", files=[".github"], value_if_pass="github"),
        ]
        result = _run_detect_pipeline("platform", pipeline, str(tmp_path), "owner", "repo")
        assert result is not None
        assert result.value == "github"

    @patch("darnit.sieve.builtin_handlers.subprocess.run")
    def test_no_remote_no_github_dir_returns_none(self, mock_run, tmp_path: Path) -> None:
        """platform returns None when no remote and no .github/ directory."""
        mock_run.return_value = MagicMock(returncode=1, stdout="", stderr="")
        pipeline = [
            self._make_invocation(
                handler="exec",
                command=["sh", "-c", "git remote get-url origin 2>/dev/null | grep -q github.com"],
                pass_exit_codes=[0],
                value_if_pass="github",
            ),
            self._make_invocation(
                handler="exec",
                command=["sh", "-c", "git remote get-url origin 2>/dev/null | grep -q gitlab.com"],
                pass_exit_codes=[0],
                value_if_pass="gitlab",
            ),
            self._make_invocation(handler="file_exists", files=[".github"], value_if_pass="github"),
        ]
        result = _run_detect_pipeline("platform", pipeline, str(tmp_path), "owner", "repo")
        assert result is None
