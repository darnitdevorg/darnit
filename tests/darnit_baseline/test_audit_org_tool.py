"""Tests for the audit_org and list_org_repos tool handlers."""

from __future__ import annotations

import json
from unittest.mock import patch

from darnit_baseline.tools import audit_org, list_org_repos


class TestListOrgRepos:
    """Tests for list_org_repos tool handler."""

    @patch("darnit.tools.audit_org.enumerate_org_repos")
    def test_returns_repo_list(self, mock_enum):
        """Returns JSON with repo names and count."""
        mock_enum.return_value = (["repo-a", "repo-b"], None)
        result = json.loads(list_org_repos(owner="my-org"))
        assert result["owner"] == "my-org"
        assert result["repos"] == ["repo-a", "repo-b"]
        assert result["count"] == 2

    @patch("darnit.tools.audit_org.enumerate_org_repos")
    def test_returns_error(self, mock_enum):
        """Returns JSON error when enumeration fails."""
        mock_enum.return_value = ([], "gh CLI not found")
        result = json.loads(list_org_repos(owner="my-org"))
        assert result["error"] == "gh CLI not found"
        assert result["repos"] == []
        assert result["count"] == 0

    @patch("darnit.tools.audit_org.enumerate_org_repos")
    def test_passes_include_archived(self, mock_enum):
        """include_archived flag is forwarded."""
        mock_enum.return_value = ([], None)
        list_org_repos(owner="my-org", include_archived=True)
        mock_enum.assert_called_once_with("my-org", include_archived=True)


class TestAuditOrgTool:
    """Tests for audit_org tool handler."""

    @patch("darnit.tools.audit_org._audit_single_repo")
    def test_delegates_to_audit_single_repo(self, mock_audit):
        """Tool handler delegates to _audit_single_repo."""
        mock_audit.return_value = {
            "repo": "my-repo",
            "status": "OK",
            "error": None,
            "results": [],
            "summary": {"PASS": 0, "FAIL": 0, "WARN": 0, "N/A": 0, "total": 0},
        }
        result = audit_org(owner="my-org", repo="my-repo", level=1)
        mock_audit.assert_called_once_with("my-org", "my-repo", 1, None)
        assert "my-repo" in result

    @patch("darnit.tools.audit_org._audit_single_repo")
    def test_normalizes_string_tags(self, mock_audit):
        """String tags are normalized to list."""
        mock_audit.return_value = {
            "repo": "my-repo",
            "status": "OK",
            "error": None,
            "results": [],
            "summary": {},
        }
        audit_org(owner="my-org", repo="my-repo", tags="domain=AC")
        assert mock_audit.call_args[0][3] == ["domain=AC"]

    @patch("darnit.tools.audit_org._audit_single_repo")
    def test_error_result(self, mock_audit):
        """Error result returns error markdown."""
        mock_audit.return_value = {
            "repo": "bad-repo",
            "status": "ERROR",
            "error": "Clone failed",
            "results": [],
            "summary": {},
        }
        result = audit_org(owner="my-org", repo="bad-repo")
        assert "Error" in result
        assert "Clone failed" in result

    @patch("darnit.tools.audit_org._audit_single_repo")
    def test_json_output(self, mock_audit):
        """JSON output returns valid JSON."""
        mock_audit.return_value = {
            "repo": "my-repo",
            "status": "OK",
            "error": None,
            "results": [],
            "summary": {},
        }
        result = audit_org(
            owner="my-org", repo="my-repo", output_format="json"
        )
        data = json.loads(result)
        assert data["repo"] == "my-repo"
        assert data["status"] == "OK"
