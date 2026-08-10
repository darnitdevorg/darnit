"""Tier 1 MCP-vs-harness parity test (feature 028 T013).

Parametrized per fixture. For each fixture in the corpus, invokes both
audit paths and asserts they agree modulo the sole allowed drift class
(PENDING_LLM -> non-PENDING_LLM). Emits a summary line on every run
(FR-013) captured by capsys.
"""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from tests.darnit.parity.tier1.comparator import AuditResult, compare
from tests.darnit.parity.tier1.fixture_meta import load_parity_metadata


def test_parity(
    fixture_dir: Path,
    mcp_tool_result: AuditResult,
    harness_result: AuditResult,
    capsys: pytest.CaptureFixture[str],
) -> None:
    """Verify MCP tool and harness produce identical per-control status
    for the given fixture, modulo the allowed PENDING_LLM -> non-PENDING_LLM
    drift.

    Fixtures may declare `control_ids` in their `parity.toml` to filter
    which controls are compared. Neither audit path applies fixture-level
    `audit_profiles` automatically today, so this test-side filter is how
    a fixture narrows its scope.
    """
    meta = load_parity_metadata(fixture_dir)
    if meta is not None and meta.control_ids:
        mcp = mcp_tool_result.filter_to(meta.control_ids)
        harness = harness_result.filter_to(meta.control_ids)
    else:
        mcp = mcp_tool_result
        harness = harness_result

    report = compare(mcp, harness, fixture_name=fixture_dir.name)

    # FR-013 evidence: emit summary line to stdout unconditionally, so
    # even green runs produce a per-fixture record.
    summary = report.format_summary_line()
    print(summary)

    # MC2 fix: assert the summary line matches the FR-013 pattern.
    pattern = re.compile(
        rf"^\[tier1\] {re.escape(fixture_dir.name)}: "
        r"\d+ controls compared, \d+ agreed, \d+ diverged, \d+ allowed-drift$",
    )
    assert pattern.match(summary), f"FR-013 evidence line malformed: {summary!r}"

    if not report.is_green:
        # Emit the drift table into stdout as well for CI logs.
        table = report.format_failure_table()
        print(table)
        pytest.fail("MCP tool and harness disagree beyond allowed drift:\n" + table)
