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


class TestRemediationResult:
    """Tests for RemediationResult dataclass."""

    @pytest.mark.unit
    def test_successful_remediation(self):
        """Test successful remediation result."""
        result = RemediationResult(
            control_id="OSPS-VM-02.01",
            success=True,
            message="Created SECURITY.md",
            changes_made=["Created SECURITY.md"],
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
            manual_steps=["Define governance roles", "Document in GOVERNANCE.md"],
        )
        assert result.success is False
        assert result.requires_manual_action is True
        assert len(result.manual_steps) == 2


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


import concurrent.futures
import time

from darnit.core.models import ExecutionContext


class TestExecutionContext:
    """Tests for ExecutionContext dataclass and functionality."""

    @pytest.fixture
    def ctx(self):
        return ExecutionContext(owner="test", repo="repo", local_path="/test")

    @pytest.mark.unit
    def test_cache_miss_and_hit(self, ctx):
        """Test that get_or_run_tool caches the result."""
        call_count = 0

        def dummy_tool():
            nonlocal call_count
            call_count += 1
            return {"data": "test"}

        # First call: cache miss, runs tool
        res1 = ctx.get_or_run_tool("my_tool", dummy_tool)
        assert res1 == {"data": "test"}
        assert call_count == 1

        # Second call: cache hit, doesn't run tool
        res2 = ctx.get_or_run_tool("my_tool", dummy_tool)
        assert res2 == {"data": "test"}
        assert call_count == 1

    @pytest.mark.unit
    def test_concurrent_tool_execution(self, ctx):
        """Test that concurrent calls to get_or_run_tool only execute the tool once."""
        call_count = 0

        def slow_tool():
            nonlocal call_count
            time.sleep(0.1)  # Simulate slow network/tool
            call_count += 1
            return {"data": "slow_result"}

        # Run 10 threads trying to hit the same tool simultaneously
        with concurrent.futures.ThreadPoolExecutor(max_workers=10) as executor:
            futures = [executor.submit(ctx.get_or_run_tool, "slow_tool", slow_tool) for _ in range(10)]
            results = [f.result() for f in futures]

        # Ensure all threads got the correct result
        for r in results:
            assert r == {"data": "slow_result"}

        # Ensure the underlying tool was only called EXACTLY once
        assert call_count == 1

    @pytest.mark.unit
    def test_check_result_caching(self, ctx):
        """Test caching CheckResults directly."""
        result = CheckResult(control_id="CTRL-1", status=CheckStatus.PASS, message="pass")

        assert ctx.get_cached_result("CTRL-1") is None
        ctx.cache_result(result)
        assert ctx.get_cached_result("CTRL-1") is result
