"""Tests for write-back routing classification."""

from __future__ import annotations

from darnit_baseline.remediation.routing import (
    classify_remediation_actions,
    classify_writeback,
    format_routing_report,
)


class TestClassifyWriteback:
    """Tests for classify_writeback."""

    def test_org_field_present_in_org_config(self):
        """Org-level field routes to 'org' when present in org config."""
        org_config = {"security": {"contact": "sec@example.com"}}
        assert classify_writeback("security.contact", org_config) == "org"

    def test_org_field_missing_from_org_config(self):
        """Org-level field routes to 'repo' when not in org config."""
        org_config = {"security": {}}
        assert classify_writeback("security.contact", org_config) == "repo"

    def test_always_repo_field(self):
        """Always-repo fields route to 'repo' regardless of org config."""
        org_config = {"security": {"contact": "sec@example.com"}}
        assert classify_writeback("SECURITY.md", org_config) == "repo"
        assert classify_writeback("CODEOWNERS", org_config) == "repo"

    def test_no_org_config(self):
        """Everything routes to 'repo' when no org config exists."""
        assert classify_writeback("security.contact", None) == "repo"
        assert classify_writeback("maintainers", None) == "repo"

    def test_unknown_field_routes_to_repo(self):
        """Unknown fields route to 'repo'."""
        org_config = {"security": {"contact": "sec@example.com"}}
        assert classify_writeback("unknown.field", org_config) == "repo"

    def test_maintainers_in_org_config(self):
        """Maintainers field routes to 'org' when present."""
        org_config = {"maintainers": ["@alice", "@bob"]}
        assert classify_writeback("maintainers", org_config) == "org"

    def test_governance_in_org_config(self):
        """Governance field routes to 'org' when present."""
        org_config = {"governance": {"codeowners": {"path": ".github/CODEOWNERS"}}}
        assert classify_writeback("governance.codeowners", org_config) == "org"

    def test_empty_org_field_routes_to_repo(self):
        """Org-level field with empty value routes to 'repo'."""
        org_config = {"maintainers": []}
        assert classify_writeback("maintainers", org_config) == "repo"


class TestClassifyRemediationActions:
    """Tests for classify_remediation_actions."""

    def test_classifies_actions(self):
        """Actions get routing labels."""
        actions = [
            {"field": "security.contact", "description": "Set security contact"},
            {"artifact": "SECURITY.md", "description": "Create SECURITY.md"},
        ]
        org_config = {"security": {"contact": "sec@example.com"}}
        result = classify_remediation_actions(actions, org_config)
        assert result[0]["routing"] == "org"
        assert result[1]["routing"] == "repo"


class TestFormatRoutingReport:
    """Tests for format_routing_report."""

    def test_format_with_mixed_routing(self):
        """Report includes both org and repo sections."""
        actions = [
            {"field": "security.contact", "description": "Set security contact", "routing": "org"},
            {"artifact": "SECURITY.md", "description": "Create SECURITY.md", "routing": "repo"},
        ]
        report = format_routing_report(actions, "my-org")
        assert "## Write-back Routing" in report
        assert "[org]" in report
        assert "[repo]" in report
        assert "my-org/.project" in report

    def test_format_empty_actions(self):
        """Empty actions produce empty report."""
        assert format_routing_report([], "my-org") == ""
