"""Tests for canonical repo identity detection in darnit.core.utils."""

from pathlib import Path
from unittest.mock import patch

from darnit.core.utils import (
    _parse_github_url,
    detect_owner_repo,
    detect_repo_from_git,
)


class TestParseGithubUrl:
    """Tests for _parse_github_url helper."""

    def test_https_url(self):
        assert _parse_github_url("https://github.com/kusari-oss/darnit.git") == (
            "kusari-oss",
            "darnit",
        )

    def test_https_url_no_dot_git(self):
        assert _parse_github_url("https://github.com/kusari-oss/darnit") == (
            "kusari-oss",
            "darnit",
        )

    def test_ssh_url(self):
        assert _parse_github_url("git@github.com:kusari-oss/darnit.git") == (
            "kusari-oss",
            "darnit",
        )

    def test_non_github_url_still_parses(self):
        # The parser extracts owner/repo from any git URL pattern
        assert _parse_github_url("https://gitlab.com/foo/bar.git") == ("foo", "bar")

    def test_invalid_url_returns_none(self):
        assert _parse_github_url("not-a-url") is None


class TestDetectRepoFromGit:
    """Tests for detect_repo_from_git()."""

    def test_explicit_owner_repo_short_circuits(self, temp_git_repo: Path):
        """Both owner and repo provided → no subprocess calls."""
        with patch("darnit.core.utils._get_remote_url") as mock_remote:
            result = detect_repo_from_git(
                str(temp_git_repo), owner="my-org", repo="my-repo"
            )
            mock_remote.assert_not_called()

        assert result is not None
        assert result["owner"] == "my-org"
        assert result["repo"] == "my-repo"
        assert result["source"] == "explicit"

    def test_upstream_preferred_over_origin(self, temp_git_repo: Path):
        """Default: upstream remote checked first."""

        def fake_remote(name, cwd):
            if name == "upstream":
                return "https://github.com/upstream-org/repo.git"
            if name == "origin":
                return "https://github.com/fork-user/repo.git"
            return None

        with (
            patch("darnit.core.utils._get_remote_url", side_effect=fake_remote),
            patch("darnit.core.utils._gh_enrich", return_value={}),
        ):
            result = detect_repo_from_git(str(temp_git_repo))

        assert result is not None
        assert result["owner"] == "upstream-org"
        assert result["source"] == "upstream"

    def test_origin_fallback_when_no_upstream(self, temp_git_repo: Path):
        """No upstream remote → falls back to origin."""

        def fake_remote(name, cwd):
            if name == "origin":
                return "https://github.com/my-user/my-repo.git"
            return None

        with (
            patch("darnit.core.utils._get_remote_url", side_effect=fake_remote),
            patch("darnit.core.utils._gh_enrich", return_value={}),
        ):
            result = detect_repo_from_git(str(temp_git_repo))

        assert result is not None
        assert result["owner"] == "my-user"
        assert result["repo"] == "my-repo"
        assert result["source"] == "origin"

    def test_prefer_upstream_false_reverses_order(self, temp_git_repo: Path):
        """prefer_upstream=False checks origin first."""

        def fake_remote(name, cwd):
            if name == "upstream":
                return "https://github.com/upstream-org/repo.git"
            if name == "origin":
                return "https://github.com/fork-user/repo.git"
            return None

        with (
            patch("darnit.core.utils._get_remote_url", side_effect=fake_remote),
            patch("darnit.core.utils._gh_enrich", return_value={}),
        ):
            result = detect_repo_from_git(
                str(temp_git_repo), prefer_upstream=False
            )

        assert result is not None
        assert result["owner"] == "fork-user"
        assert result["source"] == "origin"

    def test_source_field_present(self, temp_git_repo: Path):
        """Return dict includes source field."""

        def fake_remote(name, cwd):
            if name == "upstream":
                return "https://github.com/org/repo.git"
            return None

        with (
            patch("darnit.core.utils._get_remote_url", side_effect=fake_remote),
            patch("darnit.core.utils._gh_enrich", return_value={}),
        ):
            result = detect_repo_from_git(str(temp_git_repo))

        assert result is not None
        assert "source" in result
        assert result["source"] == "upstream"

    def test_returns_none_for_non_git_path(self, temp_dir: Path):
        """Non-git directory → None without exception."""
        result = detect_repo_from_git(str(temp_dir))
        assert result is None

    def test_returns_none_when_no_remotes(self, temp_git_repo: Path):
        """No remotes configured → None."""
        with patch("darnit.core.utils._get_remote_url", return_value=None):
            result = detect_repo_from_git(str(temp_git_repo))

        assert result is None

    def test_partial_owner_provided(self, temp_git_repo: Path):
        """Only owner provided → detect repo from remote."""

        def fake_remote(name, cwd):
            if name == "upstream":
                return "https://github.com/some-org/detected-repo.git"
            return None

        with (
            patch("darnit.core.utils._get_remote_url", side_effect=fake_remote),
            patch("darnit.core.utils._gh_enrich", return_value={}),
        ):
            result = detect_repo_from_git(
                str(temp_git_repo), owner="explicit-org"
            )

        assert result is not None
        assert result["owner"] == "explicit-org"
        assert result["repo"] == "detected-repo"

    def test_gh_enrichment_provides_metadata(self, temp_git_repo: Path):
        """gh CLI enriches with is_private, default_branch, url."""

        def fake_remote(name, cwd):
            if name == "upstream":
                return "https://github.com/org/repo.git"
            return None

        enrichment = {
            "url": "https://github.com/org/repo",
            "is_private": True,
            "default_branch": "develop",
        }

        with (
            patch("darnit.core.utils._get_remote_url", side_effect=fake_remote),
            patch("darnit.core.utils._gh_enrich", return_value=enrichment),
        ):
            result = detect_repo_from_git(str(temp_git_repo))

        assert result is not None
        assert result["is_private"] is True
        assert result["default_branch"] == "develop"
        assert result["url"] == "https://github.com/org/repo"


class TestDetectOwnerRepo:
    """Tests for detect_owner_repo() convenience wrapper."""

    def test_returns_tuple(self, temp_git_repo: Path):
        """Returns (owner, repo) tuple."""
        with patch(
            "darnit.core.utils.detect_repo_from_git",
            return_value={
                "owner": "org",
                "repo": "repo",
                "source": "upstream",
            },
        ):
            result = detect_owner_repo(str(temp_git_repo))

        assert result == ("org", "repo")
        assert isinstance(result, tuple)

    def test_returns_empty_owner_and_dirname_on_failure(self, temp_git_repo: Path):
        """Returns ("", dir_name) when detection fails."""
        with patch(
            "darnit.core.utils.detect_repo_from_git", return_value=None
        ):
            owner, repo = detect_owner_repo(str(temp_git_repo))

        assert owner == ""
        assert repo == temp_git_repo.name

    def test_passes_prefer_upstream(self, temp_git_repo: Path):
        """prefer_upstream parameter is forwarded."""
        with patch(
            "darnit.core.utils.detect_repo_from_git", return_value=None
        ) as mock:
            detect_owner_repo(str(temp_git_repo), prefer_upstream=False)
            mock.assert_called_once_with(
                str(temp_git_repo),
                prefer_upstream=False,
                owner=None,
                repo=None,
            )
