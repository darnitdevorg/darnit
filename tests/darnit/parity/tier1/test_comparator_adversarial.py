"""Adversarial comparator tests (feature 028 T014).

Covers SC-001 (comparator catches a seeded PASS-vs-FAIL divergence),
SC-003 (N seeded divergences produce N table rows), and LC1 (all three
PENDING_LLM allowed-drift resolutions).
"""

from __future__ import annotations

from tests.darnit.parity.tier1.comparator import (
    AuditResult,
    Control,
    compare,
)


def _mcp(*controls: Control) -> AuditResult:
    return AuditResult(controls=tuple(controls), source="mcp_tool")


def _harness(*controls: Control) -> AuditResult:
    return AuditResult(controls=tuple(controls), source="harness")


class TestSC001CatchesDivergence:
    def test_pass_to_fail_divergence_flagged(self) -> None:
        """SC-001: hand-built PASS vs FAIL produces a disallowed drift."""
        mcp = _mcp(Control(id="X", status="PASS"))
        harness = _harness(Control(id="X", status="FAIL"))
        report = compare(mcp, harness, "sc001_test")

        assert not report.is_green
        assert len(report.disallowed_drifts) == 1
        assert report.disallowed_drifts[0].control_id == "X"
        assert report.disallowed_drifts[0].mcp_status == "PASS"
        assert report.disallowed_drifts[0].harness_status == "FAIL"


class TestSC003FailureMessageListsAllDrifts:
    def test_five_divergences_produce_five_rows(self) -> None:
        """SC-003: N seeded divergences -> N rows in the failure table."""
        mcp_controls = [Control(id=f"CTRL-{i:02d}", status="PASS") for i in range(5)]
        harness_controls = [Control(id=f"CTRL-{i:02d}", status="FAIL") for i in range(5)]
        report = compare(_mcp(*mcp_controls), _harness(*harness_controls), "sc003")

        assert len(report.disallowed_drifts) == 5

        table = report.format_failure_table()
        # Count table rows (excluding header + separator + preamble lines).
        # A "data row" starts with "| CTRL-".
        data_rows = [ln for ln in table.split("\n") if ln.startswith("| CTRL-")]
        assert len(data_rows) == 5, f"Expected 5 rows, got {len(data_rows)}"


class TestLC1AllowedDriftResolutions:
    """LC1: PENDING_LLM (MCP) -> non-PENDING_LLM (harness) is allowed for
    every non-PENDING_LLM value the harness might land on."""

    def test_pending_to_warn_is_allowed(self) -> None:
        mcp = _mcp(Control(id="X", status="PENDING_LLM"))
        harness = _harness(Control(id="X", status="WARN"))
        report = compare(mcp, harness, "lc1")
        assert report.is_green
        assert len(report.drifts) == 1
        assert report.drifts[0].is_allowed_drift

    def test_pending_to_pass_is_allowed(self) -> None:
        mcp = _mcp(Control(id="X", status="PENDING_LLM"))
        harness = _harness(Control(id="X", status="PASS"))
        report = compare(mcp, harness, "lc1")
        assert report.is_green
        assert len(report.drifts) == 1
        assert report.drifts[0].is_allowed_drift

    def test_pending_to_fail_is_allowed(self) -> None:
        mcp = _mcp(Control(id="X", status="PENDING_LLM"))
        harness = _harness(Control(id="X", status="FAIL"))
        report = compare(mcp, harness, "lc1")
        assert report.is_green
        assert len(report.drifts) == 1
        assert report.drifts[0].is_allowed_drift


class TestDisallowedReverseDrift:
    def test_reverse_drift_pending_llm_from_harness_disallowed(self) -> None:
        """Harness produced PENDING_LLM while MCP resolved to WARN. That's
        a bug: the harness's LLM continuation loop should resolve. Not
        the other way around."""
        mcp = _mcp(Control(id="X", status="WARN"))
        harness = _harness(Control(id="X", status="PENDING_LLM"))
        report = compare(mcp, harness, "reverse")
        assert not report.is_green
        assert len(report.disallowed_drifts) == 1


class TestMissingControlCase:
    """T1-3: control appears on one side but not the other -> hard fail."""

    def test_control_missing_on_harness_side_flagged(self) -> None:
        mcp = _mcp(
            Control(id="X", status="PASS"),
            Control(id="Y", status="PASS"),
        )
        harness = _harness(Control(id="X", status="PASS"))
        report = compare(mcp, harness, "missing")
        assert not report.is_green
        assert any("missing on harness side" in d.note for d in report.disallowed_drifts)

    def test_control_missing_on_mcp_side_flagged(self) -> None:
        mcp = _mcp(Control(id="X", status="PASS"))
        harness = _harness(
            Control(id="X", status="PASS"),
            Control(id="Z", status="FAIL"),
        )
        report = compare(mcp, harness, "missing")
        assert not report.is_green
        assert any("missing on mcp side" in d.note for d in report.disallowed_drifts)
