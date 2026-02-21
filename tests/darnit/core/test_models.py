"""Tests for darnit.core.models module."""

import pytest

from darnit.core.models import (
    AuditResult,
    CheckResult,
    CheckStatus,
    RemediationResult,
)


class TestCheckResult:
    """Tests for CheckResult dataclass."""

    @pytest.mark.unit
    def test_basic_creation(self):
        """Test basic CheckResult creation."""
        result = CheckResult(
            control_id="OSPS-AC-01.01",
            status=CheckStatus.PASS,
            message="Control satisfied"
        )
        assert result.control_id == "OSPS-AC-01.01"
        assert result.status == CheckStatus.PASS
        assert result.message == "Control satisfied"
        assert result.level == 1  # default
        assert result.source == "builtin"  # default

    @pytest.mark.unit
    def test_custom_level(self):
        """Test CheckResult with custom level."""
        result = CheckResult(
            control_id="OSPS-AC-03.02",
            status=CheckStatus.FAIL,
            message="Missing branch protection",
            level=3
        )
        assert result.level == 3

    @pytest.mark.unit
    def test_with_details(self):
        """Test CheckResult with details."""
        result = CheckResult(
            control_id="OSPS-VM-01.01",
            status=CheckStatus.PASS,
            message="Security policy found",
            details={"file": "SECURITY.md", "has_email": True}
        )
        assert result.details["file"] == "SECURITY.md"
        assert result.details["has_email"] is True

    @pytest.mark.unit
    def test_to_dict(self):
        """Test CheckResult.to_dict() output format."""
        result = CheckResult(
            control_id="OSPS-AC-01.01",
            status=CheckStatus.PASS,
            message="Control satisfied",
            level=2,
            source="sieve"
        )
        d = result.to_dict()
        assert d["id"] == "OSPS-AC-01.01"
        assert d["status"] == "PASS"  # Uppercase
        assert d["details"] == "Control satisfied"
        assert d["level"] == 2
        assert d["source"] == "sieve"


class TestRemediationResult:
    """Tests for RemediationResult dataclass."""

    @pytest.mark.unit
    def test_successful_remediation(self):
        """Test successful remediation result."""
        result = RemediationResult(
            control_id="OSPS-VM-02.01",
            success=True,
            message="Created SECURITY.md",
            changes_made=["Created SECURITY.md"]
        )
        assert result.success is True
        assert len(result.changes_made) == 1
        assert result.requires_manual_action is False

    @pytest.mark.unit
    def test_manual_action_required(self):
        """Test remediation requiring manual action."""
        result = RemediationResult(
            control_id="OSPS-GV-01.01",
            success=False,
            message="Cannot automate governance structure",
            requires_manual_action=True,
            manual_steps=["Define governance roles", "Document in GOVERNANCE.md"]
        )
        assert result.success is False
        assert result.requires_manual_action is True
        assert len(result.manual_steps) == 2


class TestAuditResult:
    """Tests for AuditResult dataclass."""

    @pytest.mark.unit
    def test_basic_creation(self):
        """Test basic AuditResult creation."""
        result = AuditResult(
            owner="testorg",
            repo="testrepo",
            local_path="/path/to/repo",
            level=3,
            default_branch="main",
            all_results=[]
        )
        assert result.owner == "testorg"
        assert result.repo == "testrepo"
        assert result.level == 3
        assert result.all_results == []

    @pytest.mark.unit
    def test_with_summary(self):
        """Test AuditResult with summary."""
        result = AuditResult(
            owner="testorg",
            repo="testrepo",
            local_path="/path/to/repo",
            level=1,
            default_branch="main",
            all_results=[
                {"id": "OSPS-AC-01.01", "status": "PASS"},
                {"id": "OSPS-AC-02.01", "status": "FAIL"},
            ],
            summary={"PASS": 1, "FAIL": 1, "total": 2}
        )
        assert result.summary["PASS"] == 1
        assert result.summary["FAIL"] == 1
        assert result.summary["total"] == 2

    @pytest.mark.unit
    def test_with_compliance(self):
        """Test AuditResult with level compliance."""
        result = AuditResult(
            owner="testorg",
            repo="testrepo",
            local_path="/path/to/repo",
            level=3,
            default_branch="main",
            all_results=[],
            level_compliance={1: True, 2: True, 3: False}
        )
        assert result.level_compliance[1] is True
        assert result.level_compliance[3] is False

    @pytest.mark.unit
    def test_default_values(self):
        """Test AuditResult default values."""
        result = AuditResult(
            owner="test",
            repo="test",
            local_path="/test",
            level=1,
            default_branch="main",
            all_results=[]
        )
        assert result.summary is None
        assert result.level_compliance is None
        assert result.config_was_created is False
        assert result.config_was_updated is False
        assert result.config_changes == []
        assert result.skipped_controls == {}
        assert result.commit is None
        assert result.ref is None
