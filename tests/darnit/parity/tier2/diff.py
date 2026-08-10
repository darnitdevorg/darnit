"""Tier 2 diff: MCP tool JSON vs skill Markdown summary (feature 028 T020).

Compares the skill's user-facing summary against the raw tool output.
Any per-control status difference is a hard failure regardless of
authority level (FR-008 / T2-13). Unparseable skill output is a distinct
failure class from disagreement (FR-006a).
"""

from __future__ import annotations

from dataclasses import dataclass
from enum import IntEnum

from tests.darnit.parity.tier1.comparator import AuditResult
from tests.darnit.parity.tier2.skill_markdown_parser import SkillReport


class Tier2Outcome(IntEnum):
    """Contract T2-13 exit codes."""

    SUCCESS = 0
    PER_CONTROL_DISAGREE = 1
    SKILL_UNPARSEABLE = 2
    COUNTS_DISAGREE = 1  # combined with per-control under exit 1


@dataclass(frozen=True)
class Tier2DiffReport:
    fixture_name: str
    outcome: str  # "success" | "per_control_disagree" | "skill_unparseable" | "counts_disagree"
    disagreeing_controls: tuple[str, ...] = ()
    diff_markdown: str = ""

    @property
    def is_success(self) -> bool:
        return self.outcome == "success"


def diff(
    mcp_result: AuditResult,
    skill_report: SkillReport,
    fixture_name: str,
) -> Tier2DiffReport:
    """Compare tool JSON vs skill summary.

    Order of classification (most severe first):
      1. Skill output unparseable -> SKILL_UNPARSEABLE.
      2. Per-control status disagreement -> PER_CONTROL_DISAGREE.
      3. Summary-count disagreement (per-control agrees) -> COUNTS_DISAGREE.
      4. All-agree -> success.
    """
    if not skill_report.parseable:
        return Tier2DiffReport(
            fixture_name=fixture_name,
            outcome="skill_unparseable",
            diff_markdown=_format_unparseable_report(fixture_name, skill_report),
        )

    # Per-control comparison: for every skill claim, find the matching
    # tool control and compare status.
    mcp_by_id = {c.id: c for c in mcp_result.controls}
    disagreements: list[tuple[str, str, str]] = []  # (control_id, tool_status, skill_status)

    assert skill_report.controls is not None
    for claim in skill_report.controls:
        tool_ctrl = mcp_by_id.get(claim.id)
        if tool_ctrl is None:
            disagreements.append((claim.id, "<not in tool output>", claim.status))
            continue
        if tool_ctrl.status != claim.status:
            disagreements.append((claim.id, tool_ctrl.status, claim.status))

    if disagreements:
        return Tier2DiffReport(
            fixture_name=fixture_name,
            outcome="per_control_disagree",
            disagreeing_controls=tuple(d[0] for d in disagreements),
            diff_markdown=_format_per_control_report(fixture_name, disagreements),
        )

    # Counts comparison. Compute tool counts from AuditResult.
    assert skill_report.counts is not None
    tool_counts = _tool_counts(mcp_result)

    counts_differ = False
    for key in ("pass", "fail", "warn", "error"):
        if key in skill_report.counts and skill_report.counts[key] != tool_counts.get(key, 0):
            counts_differ = True

    if counts_differ:
        return Tier2DiffReport(
            fixture_name=fixture_name,
            outcome="counts_disagree",
            diff_markdown=_format_counts_report(
                fixture_name,
                tool_counts,
                skill_report.counts,
            ),
        )

    return Tier2DiffReport(
        fixture_name=fixture_name,
        outcome="success",
        diff_markdown=f"# Tier 2 parity: {fixture_name}\n\nSUCCESS: skill agrees with tool.\n",
    )


def _tool_counts(mcp_result: AuditResult) -> dict[str, int]:
    counts = {"pass": 0, "fail": 0, "warn": 0, "error": 0, "n_a": 0, "pending_llm": 0}
    for c in mcp_result.controls:
        key = c.status.lower().replace("/", "_")
        if key in counts:
            counts[key] += 1
    return counts


def _format_per_control_report(
    fixture_name: str,
    disagreements: list[tuple[str, str, str]],
) -> str:
    lines = [
        f"# Tier 2 parity: {fixture_name}",
        "",
        "FAIL: per-control status disagreement between skill summary and tool JSON.",
        "",
        "| control_id | tool_status | skill_status |",
        "| --- | --- | --- |",
    ]
    for cid, tool_s, skill_s in disagreements:
        lines.append(f"| {cid} | {tool_s} | {skill_s} |")
    lines.append("")
    lines.append(
        "See `mcp_tool_result.json` and `skill_final_message.md` in this directory for the raw artifacts.",
    )
    return "\n".join(lines)


def _format_counts_report(
    fixture_name: str,
    tool_counts: dict[str, int],
    skill_counts: dict[str, int],
) -> str:
    lines = [
        f"# Tier 2 parity: {fixture_name}",
        "",
        "FAIL: summary counts differ between skill summary and tool JSON.",
        "",
        "| status | tool_count | skill_count |",
        "| --- | --- | --- |",
    ]
    for key in ("pass", "fail", "warn", "error", "n_a", "pending_llm"):
        t = tool_counts.get(key, 0)
        s = skill_counts.get(key, "-")
        lines.append(f"| {key} | {t} | {s} |")
    return "\n".join(lines)


def _format_unparseable_report(
    fixture_name: str,
    skill_report: SkillReport,
) -> str:
    return (
        f"# Tier 2 parity: {fixture_name}\n\n"
        "FAIL: skill output could not be parsed. This is DISTINCT from a "
        "disagreement -- the parser did not find the expected shape in the "
        "skill's final message.\n\n"
        f"Parser notes: {list(skill_report.parse_notes) or ['(none)']}\n\n"
        "See `skill_final_message.md` in this directory for the raw output.\n"
    )


__all__ = ("Tier2Outcome", "Tier2DiffReport", "diff")
