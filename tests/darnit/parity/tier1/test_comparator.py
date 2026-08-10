"""Tests for the Tier 1 comparator (feature 028 T006).

Covers:
  - T1-9 mechanical enumeration: all 36 (mcp_status, harness_status) pairs
    classified per the T1-8 canonical drift table.
  - AuditResult factories (from_mcp_json + from_harness_report) shape.
  - FR-004: format_failure_table produces fixed-width Markdown with no ANSI.
  - FR-013: format_summary_line shape.
  - FR-015 / MC4: determinism -- run compare() twice, assert byte-identical
    output.
"""

from __future__ import annotations

from tests.darnit.parity.tier1.comparator import (
    STATUSES,
    AuditResult,
    Control,
    DriftEntry,
    ParityReport,
    compare,
)


def _make_mcp(controls: list[Control]) -> AuditResult:
    return AuditResult(controls=tuple(controls), source="mcp_tool")


def _make_harness(controls: list[Control]) -> AuditResult:
    return AuditResult(controls=tuple(controls), source="harness")


class TestAllowedDriftTable:
    """T1-9: enumerate every (mcp, harness) status pair and verify
    the comparator's classification matches the T1-8 table."""

    def test_all_36_pairs_classified_correctly(self) -> None:
        for m_status in STATUSES:
            for h_status in STATUSES:
                mcp = _make_mcp([Control(id="X", status=m_status)])
                harness = _make_harness([Control(id="X", status=h_status)])
                report = compare(mcp, harness, "test_fixture")

                if m_status == h_status:
                    # Agreement -- no drift entry.
                    assert report.total_controls == 1
                    assert report.agreements == 1
                    assert len(report.drifts) == 0
                    assert report.is_green, f"({m_status}, {h_status}) should be green"
                    continue

                # Divergence -- exactly one drift.
                assert report.total_controls == 1
                assert report.agreements == 0
                assert len(report.drifts) == 1
                drift = report.drifts[0]
                assert drift.control_id == "X"
                assert drift.mcp_status == m_status
                assert drift.harness_status == h_status

                # Classification: PENDING_LLM (MCP) -> non-PENDING_LLM
                # (harness) is the sole allowed drift.
                if m_status == "PENDING_LLM" and h_status != "PENDING_LLM":
                    assert drift.is_allowed_drift is True
                    assert report.is_green, f"PENDING_LLM->{h_status} must be green"
                else:
                    assert drift.is_allowed_drift is False
                    assert not report.is_green, f"({m_status}, {h_status}) must NOT be green"


class TestAuditResultFactories:
    def test_from_mcp_json_extracts_fields(self) -> None:
        payload = {
            "results": [
                {
                    "id": "OSPS-GV-01.01",
                    "status": "PASS",
                    "authority": "dispositive",
                    "level": 1,
                },
                {
                    "id": "OSPS-BR-06.01",
                    "status": "FAIL",
                    "authority": "dispositive",
                    "level": 2,
                },
            ],
        }
        result = AuditResult.from_mcp_json(payload)
        assert result.source == "mcp_tool"
        assert len(result.controls) == 2
        assert result.controls[0].id == "OSPS-GV-01.01"
        assert result.controls[0].status == "PASS"
        assert result.controls[0].authority == "dispositive"
        assert result.controls[0].level == 1

    def test_from_harness_report_equivalent_shape(self) -> None:
        """A HarnessReport-shaped input and an MCP-shaped input should
        produce equivalent Control values (modulo source)."""

        class _FakeReport:
            controls = [
                {"id": "X", "status": "PASS", "authority": "dispositive", "level": 1},
            ]

        harness = AuditResult.from_harness_report(_FakeReport())
        mcp = AuditResult.from_mcp_json(
            {"results": [{"id": "X", "status": "PASS", "authority": "dispositive", "level": 1}]},
        )
        assert harness.controls == mcp.controls
        assert harness.source == "harness"
        assert mcp.source == "mcp_tool"


class TestFormatting:
    def test_format_failure_table_no_ansi_no_escapes(self) -> None:
        """FR-004: fixed-width Markdown; no ANSI escape sequences."""
        report = ParityReport(
            fixture_name="test",
            total_controls=1,
            agreements=0,
            drifts=(
                DriftEntry(
                    fixture_name="test",
                    control_id="X",
                    mcp_status="PASS",
                    harness_status="FAIL",
                ),
            ),
        )
        table = report.format_failure_table()
        assert "\033" not in table, f"ANSI escape present: {table!r}"
        assert "|" in table
        assert "X" in table
        assert "PASS" in table
        assert "FAIL" in table

    def test_format_summary_line_shape(self) -> None:
        """FR-013: recognizable evidence-line shape."""
        report = ParityReport(
            fixture_name="mixed_repo",
            total_controls=10,
            agreements=8,
            drifts=(
                DriftEntry(
                    fixture_name="mixed_repo",
                    control_id="A",
                    mcp_status="PENDING_LLM",
                    harness_status="WARN",
                ),
                DriftEntry(
                    fixture_name="mixed_repo",
                    control_id="B",
                    mcp_status="PASS",
                    harness_status="FAIL",
                ),
            ),
        )
        line = report.format_summary_line()
        assert line.startswith("[tier1] mixed_repo:")
        assert "10 controls compared" in line
        assert "8 agreed" in line
        assert "1 diverged" in line
        assert "1 allowed-drift" in line

    def test_format_failure_table_on_green_report(self) -> None:
        report = ParityReport(
            fixture_name="test",
            total_controls=1,
            agreements=1,
            drifts=(),
        )
        assert "No disallowed drifts." == report.format_failure_table()


class TestDeterminism:
    """MC4 / FR-15: repeated runs on identical inputs produce
    byte-identical outputs. Guards against dict-iteration-order or
    time-dependent regressions."""

    def test_compare_output_is_deterministic(self) -> None:
        mcp = _make_mcp(
            [
                Control(id="Z", status="PASS"),
                Control(id="A", status="FAIL"),
                Control(id="M", status="WARN"),
            ]
        )
        harness = _make_harness(
            [
                Control(id="M", status="PASS"),
                Control(id="A", status="FAIL"),
                Control(id="Z", status="PASS"),
            ]
        )
        report1 = compare(mcp, harness, "det_test")
        report2 = compare(mcp, harness, "det_test")

        assert report1.format_summary_line() == report2.format_summary_line()
        assert report1.format_failure_table() == report2.format_failure_table()
        assert report1.drifts == report2.drifts
