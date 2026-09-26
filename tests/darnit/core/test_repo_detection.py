"""Tests for canonical repo identity detection in darnit.core.utils."""

from pathlib import Path
from unittest.mock import patch

from darnit.core.utils import (
    _parse_github_url,
    detect_checkout_identity,
    detect_owner_repo,
    detect_repo_from_git,
)
from darnit.trust.identity import IdentitySource


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

    def test_origin_preferred_over_upstream(self, temp_git_repo: Path):
        """Default: origin remote checked first (feature 040, research R3)."""

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
        assert result["owner"] == "fork-user"
        assert result["source"] == "origin"

    def test_upstream_fallback_when_no_origin(self, temp_git_repo: Path):
        """No origin remote -> falls back to upstream."""

        def fake_remote(name, cwd):
            if name == "upstream":
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
        assert result["source"] == "upstream"

    def test_prefer_upstream_true_is_explicit_opt_in(self, temp_git_repo: Path):
        """prefer_upstream=True checks upstream first."""

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
                str(temp_git_repo), prefer_upstream=True
            )

        assert result is not None
        assert result["owner"] == "upstream-org"
        assert result["source"] == "upstream"

    def test_identity_keeps_host(self, temp_git_repo: Path):
        """The canonical identity of the remote keeps its host."""

        def fake_remote(name, cwd):
            if name == "origin":
                return "git@gitlab.example.com:Team/Sub/Proj.git"
            return None

        with (
            patch("darnit.core.utils._get_remote_url", side_effect=fake_remote),
            patch("darnit.core.utils._gh_enrich", return_value={}),
        ):
            result = detect_repo_from_git(str(temp_git_repo))

        assert result is not None
        assert result["identity"] == "gitlab.example.com/Team/Sub/Proj"

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
            detect_owner_repo(str(temp_git_repo), prefer_upstream=True)
            mock.assert_called_once_with(
                str(temp_git_repo),
                prefer_upstream=True,
                owner=None,
                repo=None,
            )


class TestDetectCheckoutIdentity:
    """Checkout remotes give a hint only, from origin only (feature 040)."""

    def test_origin_is_a_checkout_hint(self, temp_git_repo: Path):
        with patch(
            "darnit.core.utils._get_remote_url",
            side_effect=lambda name, cwd: "https://github.com/Org/Repo.git" if name == "origin" else None,
        ):
            identity = detect_checkout_identity(str(temp_git_repo))

        assert identity is not None
        assert identity.canonical == "github.com/org/repo"
        assert identity.source is IdentitySource.CHECKOUT_HINT
        assert identity.trusted_eligible is False

    def test_upstream_is_never_used(self, temp_git_repo: Path):
        with patch(
            "darnit.core.utils._get_remote_url",
            side_effect=lambda name, cwd: "https://github.com/org/repo.git" if name == "upstream" else None,
        ):
            assert detect_checkout_identity(str(temp_git_repo)) is None
