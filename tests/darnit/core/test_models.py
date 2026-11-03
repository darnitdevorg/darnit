"""Tests for darnit.core.models module."""

import pytest

from darnit.core.models import (
    AuditResult,
    CheckResult,
    CheckStatus,
)


class TestCheckResult:
    """Tests for CheckResult dataclass."""

    @pytest.mark.unit
    def test_basic_creation(self):
        """Test basic CheckResult creation."""
        result = CheckResult(control_id="OSPS-AC-01.01", status=CheckStatus.PASS, message="Control satisfied")
        assert result.control_id == "OSPS-AC-01.01"
        assert result.status == CheckStatus.PASS
        assert result.message == "Control satisfied"
        assert result.level == 1  # default
        assert result.source == "builtin"  # default

    @pytest.mark.unit
    def test_to_dict(self):
        """Test CheckResult.to_dict() output format."""
        result = CheckResult(
            control_id="OSPS-AC-01.01", status=CheckStatus.PASS, message="Control satisfied", level=2, source="sieve"
        )
        d = result.to_dict()
        assert d["id"] == "OSPS-AC-01.01"
        assert d["status"] == "PASS"  # Uppercase
        assert d["details"] == "Control satisfied"
        assert d["level"] == 2
        assert d["source"] == "sieve"


class TestAuditResult:
    """Tests for AuditResult dataclass."""

    @pytest.mark.unit
    def test_default_values(self):
        """Test AuditResult default values."""
        result = AuditResult(
            owner="test", repo="test", local_path="/test", level=1, default_branch="main", all_results=[]
        )
        assert result.summary is None
        assert result.level_compliance is None
        assert result.config_was_created is False
        assert result.config_was_updated is False
        assert result.config_changes == []
        assert result.skipped_controls == {}
        assert result.commit is None
        assert result.ref is None
