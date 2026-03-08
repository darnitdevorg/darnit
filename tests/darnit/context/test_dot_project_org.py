"""Tests for org-level .project repository resolver."""

from unittest.mock import MagicMock, patch

import pytest

from darnit.context.dot_project_org import OrgProjectResolver, clear_cache


class TestOrgProjectResolver:
    """Test the OrgProjectResolver class."""

    def setup_method(self):
        """Clear cache before each test."""
        clear_cache()

    @pytest.mark.unit
    def test_resolve_returns_none_for_empty_owner(self):
        """Resolve returns None when owner is empty."""
        resolver = OrgProjectResolver()
        assert resolver.resolve("") is None

    @pytest.mark.unit
    def test_resolve_returns_none_when_gh_unavailable(self):
        """Resolve returns None when gh CLI is not available."""
        resolver = OrgProjectResolver()
        resolver._gh_available = False
        assert resolver.resolve("some-org") is None

    @pytest.mark.unit
    def test_resolve_caches_results(self):
        """Subsequent calls for the same owner return cached result."""
        resolver = OrgProjectResolver()
        resolver._gh_available = False

        # First call
        result1 = resolver.resolve("test-org")
        # Second call should use cache
        result2 = resolver.resolve("test-org")

        assert result1 is None
        assert result2 is None

    @pytest.mark.unit
    def test_resolve_returns_none_when_repo_not_found(self):
        """Resolve returns None when .project repo doesn't exist."""
        resolver = OrgProjectResolver()
        resolver._gh_available = True

        with patch.object(resolver, "_repo_exists", return_value=False):
            assert resolver.resolve("nonexistent-org") is None

    @pytest.mark.unit
    def test_resolve_fetches_and_parses_project_yaml(self):
        """Resolve fetches project.yaml from org .project repo and parses it."""
        resolver = OrgProjectResolver()
        resolver._gh_available = True

        project_yaml = """
name: org-project
repositories:
  - https://github.com/test-org/repo1
security:
  policy:
    path: SECURITY.md
"""

        with (
            patch.object(resolver, "_repo_exists", return_value=True),
            patch.object(
                resolver,
                "_fetch_file_content",
                side_effect=lambda owner, path: project_yaml
                if path == "project.yaml"
                else None,
            ),
        ):
            config = resolver.resolve("test-org")

        assert config is not None
        assert config.name == "org-project"
        assert config.security is not None
        assert config.security.policy.path == "SECURITY.md"

    @pytest.mark.unit
    def test_resolve_fetches_maintainers_yaml(self):
        """Resolve also fetches maintainers.yaml from org .project repo."""
        resolver = OrgProjectResolver()
        resolver._gh_available = True

        project_yaml = """
name: org-project
repositories:
  - https://github.com/test-org/repo1
"""
        maintainers_yaml = """
- alice
- bob
"""

        def fetch_file(owner, path):
            if path == "project.yaml":
                return project_yaml
            if path == "maintainers.yaml":
                return maintainers_yaml
            return None

        with (
            patch.object(resolver, "_repo_exists", return_value=True),
            patch.object(resolver, "_fetch_file_content", side_effect=fetch_file),
        ):
            config = resolver.resolve("test-org")

        assert config is not None
        assert "alice" in config.maintainers
        assert "bob" in config.maintainers

    @pytest.mark.unit
    def test_resolve_returns_none_when_no_project_yaml(self):
        """Resolve returns None when project.yaml not found in org repo."""
        resolver = OrgProjectResolver()
        resolver._gh_available = True

        with (
            patch.object(resolver, "_repo_exists", return_value=True),
            patch.object(resolver, "_fetch_file_content", return_value=None),
        ):
            config = resolver.resolve("test-org")

        assert config is None

    @pytest.mark.unit
    def test_is_gh_available_detects_missing_cli(self):
        """_is_gh_available returns False when gh is not installed."""
        resolver = OrgProjectResolver()

        with patch("subprocess.run", side_effect=FileNotFoundError):
            assert resolver._is_gh_available() is False
            assert resolver._gh_available is False

    @pytest.mark.unit
    def test_is_gh_available_detects_unauthenticated(self):
        """_is_gh_available returns False when gh is not authenticated."""
        resolver = OrgProjectResolver()
        mock_result = MagicMock()
        mock_result.returncode = 1

        with patch("subprocess.run", return_value=mock_result):
            assert resolver._is_gh_available() is False

    @pytest.mark.unit
    def test_clear_cache_resets_state(self):
        """clear_cache() removes all cached entries."""
        resolver = OrgProjectResolver()
        resolver._gh_available = False
        resolver.resolve("org1")  # Cache a None entry

        clear_cache()

        # After clear, the resolver should try to fetch again
        # (but will still fail since gh is unavailable)
        resolver2 = OrgProjectResolver()
        resolver2._gh_available = False
        result = resolver2.resolve("org1")
        assert result is None
