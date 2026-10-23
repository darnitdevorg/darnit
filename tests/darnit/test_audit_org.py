"""Tests for the org repository helpers behind list_org_repos and audit_org."""

from __future__ import annotations

import json
from unittest.mock import MagicMock, patch

from darnit.tools.audit_org import (
    clone_repo,
    enumerate_org_repos,
)


class TestEnumerateOrgRepos:
    """Tests for enumerate_org_repos."""

    @patch("darnit.tools.audit_org.subprocess.run")
    def test_success(self, mock_run):
        """Returns list of repo names."""
        # gh auth status
        mock_run.side_effect = [
            MagicMock(returncode=0),  # auth check
            MagicMock(
                returncode=0,
                stdout=json.dumps([
                    {"name": "repo-a", "isArchived": False},
                    {"name": "repo-b", "isArchived": False},
                ]),
            ),
        ]
        repos, error = enumerate_org_repos("my-org")
        assert error is None
        assert repos == ["repo-a", "repo-b"]

    @patch("darnit.tools.audit_org.subprocess.run")
    def test_filters_archived_by_default(self, mock_run):
        """Archived repos are excluded by default."""
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(
                returncode=0,
                stdout=json.dumps([
                    {"name": "active", "isArchived": False},
                    {"name": "archived", "isArchived": True},
                ]),
            ),
        ]
        repos, error = enumerate_org_repos("my-org")
        assert error is None
        assert repos == ["active"]

    @patch("darnit.tools.audit_org.subprocess.run")
    def test_include_archived(self, mock_run):
        """Archived repos included when requested."""
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(
                returncode=0,
                stdout=json.dumps([
                    {"name": "active", "isArchived": False},
                    {"name": "archived", "isArchived": True},
                ]),
            ),
        ]
        repos, error = enumerate_org_repos("my-org", include_archived=True)
        assert error is None
        assert repos == ["active", "archived"]

    @patch("darnit.tools.audit_org.subprocess.run")
    def test_repo_name_filter(self, mock_run):
        """Only requested repos are returned."""
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(
                returncode=0,
                stdout=json.dumps([
                    {"name": "repo-a", "isArchived": False},
                    {"name": "repo-b", "isArchived": False},
                    {"name": "repo-c", "isArchived": False},
                ]),
            ),
        ]
        repos, error = enumerate_org_repos("my-org", repos=["repo-a", "repo-c"])
        assert error is None
        assert repos == ["repo-a", "repo-c"]

    @patch("darnit.tools.audit_org.subprocess.run")
    def test_repo_filter_warns_missing(self, mock_run, caplog):
        """Warns about repos not found in the org."""
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(
                returncode=0,
                stdout=json.dumps([
                    {"name": "repo-a", "isArchived": False},
                ]),
            ),
        ]
        repos, error = enumerate_org_repos("my-org", repos=["repo-a", "missing"])
        assert error is None
        assert repos == ["repo-a"]
        assert "missing" in caplog.text

    @patch("darnit.tools.audit_org.subprocess.run")
    def test_gh_not_authenticated(self, mock_run):
        """Returns error when gh is not authenticated."""
        mock_run.return_value = MagicMock(returncode=1)
        repos, error = enumerate_org_repos("my-org")
        assert repos == []
        assert "not authenticated" in error

    @patch("darnit.tools.audit_org.subprocess.run")
    def test_gh_not_installed(self, mock_run):
        """Returns error when gh is not installed."""
        mock_run.side_effect = FileNotFoundError()
        repos, error = enumerate_org_repos("my-org")
        assert repos == []
        assert "not found" in error

    def test_empty_owner(self):
        """Returns error for empty owner."""
        repos, error = enumerate_org_repos("")
        assert repos == []
        assert "owner is required" in error

    @patch("darnit.tools.audit_org.subprocess.run")
    def test_empty_org(self, mock_run):
        """Returns empty list for org with no repos."""
        mock_run.side_effect = [
            MagicMock(returncode=0),
            MagicMock(returncode=0, stdout="[]"),
        ]
        repos, error = enumerate_org_repos("empty-org")
        assert error is None
        assert repos == []


class TestCloneRepo:
    """Tests for clone_repo."""

    @patch("darnit.tools.audit_org.subprocess.run")
    def test_success(self, mock_run, tmp_path):
        """Returns True on successful clone."""
        mock_run.return_value = MagicMock(returncode=0)
        assert clone_repo("org", "repo", str(tmp_path / "repo")) is True
        mock_run.assert_called_once()
        args = mock_run.call_args[0][0]
        assert "gh" in args
        assert "--depth" in args

    @patch("darnit.tools.audit_org.subprocess.run")
    def test_failure(self, mock_run, tmp_path):
        """Returns False on clone failure."""
        mock_run.return_value = MagicMock(returncode=1, stderr="not found")
        assert clone_repo("org", "repo", str(tmp_path / "repo")) is False

    @patch("darnit.tools.audit_org.subprocess.run")
    def test_timeout(self, mock_run, tmp_path):
        """Returns False on timeout."""
        import subprocess
        mock_run.side_effect = subprocess.TimeoutExpired("gh", 120)
        assert clone_repo("org", "repo", str(tmp_path / "repo")) is False


class TestAuditSingleRepo:
    """Tests for _audit_single_repo, which the audit_org tool calls."""

    @patch("darnit.tools.audit_org.enumerate_org_repos")
    @patch("darnit.tools.audit_org.clone_repo")
    @patch("darnit.tools.audit_org.run_sieve_audit", create=True)
    def test_clone_failure_continues(self, mock_audit, mock_clone, mock_enum):
        """Clone failure produces ERROR entry and audit continues."""
        from darnit.tools.audit_org import _audit_single_repo

        mock_clone.return_value = False

        result = _audit_single_repo("org", "bad-repo", 1, None)
        assert result["status"] == "ERROR"
        assert "clone" in result["error"].lower()

    @patch("darnit.tools.audit_org.enumerate_org_repos")
    @patch("darnit.tools.audit_org.clone_repo")
    def test_audit_failure_continues(self, mock_clone, mock_enum):
        """Audit exception produces ERROR entry."""
        from darnit.tools.audit_org import _audit_single_repo

        mock_clone.return_value = True

        with patch("darnit.tools.audit.run_sieve_audit") as mock_audit:
            mock_audit.side_effect = RuntimeError("Audit exploded")
            result = _audit_single_repo("org", "bad-repo", 1, None)

        assert result["status"] == "ERROR"
        assert "exploded" in result["error"].lower()
