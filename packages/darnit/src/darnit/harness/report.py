"""Harness report models: Markdown + JSON output.

Feature 026 T016-T017. Contract report-format.md.

Feature 027 additions:
- `PendingFeedbackEntry.resolution_trail`: which resolvers were offered a
  question that ultimately remained pending.
- `AnsweredFeedbackEntry` (new): captures each answered feedback question so
  provenance is recoverable from the report alone (SC-006).
- `HarnessReport.resolvers_used`: names of QuestionResolvers configured for
  the run.
- `HarnessReport.answered_feedback`: list of answered feedback questions,
  each carrying `origin`, `authority`, and `resolution_trail`.
"""

from __future__ import annotations

from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field

from darnit.harness.question_resolvers import ResolutionTrailEntry


class HarnessSummary(BaseModel):
    """Aggregate counts across all controls in the audit."""

    total: int
    # ``pass`` is a Python keyword; alias for JSON.
    pass_: int = Field(alias="pass")
    fail: int
    warn: int
    n_a: int
    error: int

    model_config = ConfigDict(populate_by_name=True)


class PendingFeedbackEntry(BaseModel):
    """One unanswered feedback question captured in the report.

    Feature 027 addition: `resolution_trail` records which resolvers were
    offered this question before it was left pending (all skipped/errored).
    Empty when no resolvers were configured or the AnswerSource chain didn't
    forward this question.
    """

    control_id: str
    context_key: str
    question: str
    resolution_trail: list[ResolutionTrailEntry] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class AnsweredFeedbackEntry(BaseModel):
    """One ANSWERED feedback question captured in the report.

    Feature 027 addition. Distinct model from PendingFeedbackEntry because
    the schemas differ: answered entries carry `answer`, `origin`, and
    `authority` fields that are meaningless for still-pending questions.
    An auditor reading the report can iterate `answered_feedback` to see
    how every user-judgment value was obtained (SC-006).
    """

    control_id: str
    context_key: str
    question: str
    answer: str
    origin: str
    authority: Literal["asserted"] = "asserted"
    resolution_trail: list[ResolutionTrailEntry] = Field(default_factory=list)

    model_config = ConfigDict(extra="forbid")


class HarnessReport(BaseModel):
    """End-of-run report emitted by HarnessRun.run().

    Two serialization forms per contract report-format.md:
    - JSON: ``to_json()`` -> stable schema at version "1.0"
    - Markdown: ``to_markdown()`` -> issue-paste ready with section
      headings and per-control authority parenthetical

    Contract items RF-1..RF-8. `authority` is on every control result
    (RF-1 + feature 025 SC-006). API key never appears (RF-4). Empty
    sections render as "None." in Markdown (RF-7).
    """

    harness_version: str = "1.0"
    target: dict[str, Any]
    summary: HarnessSummary
    controls: list[dict[str, Any]]
    pending_feedback: list[PendingFeedbackEntry]
    answer_sources_used: list[str]
    llm_calls: dict[str, Any]
    # Feature 027 additions. Both default to empty so feature-026-era
    # constructions still validate.
    resolvers_used: list[str] = Field(default_factory=list)
    answered_feedback: list[AnsweredFeedbackEntry] = Field(default_factory=list)
    # exit_class NOT emitted in JSON body per RF-8; kept as an attribute
    # for the driver but excluded from serialization.
    exit_class: int = Field(default=0, exclude=True)

    model_config = ConfigDict(populate_by_name=True)

    # ------------------------------------------------------------------
    # JSON (RF-2, RF-3, RF-4, RF-5)
    # ------------------------------------------------------------------

    def to_json(self, *, indent: int | None = 2) -> str:
        """JSON output. Uses ``by_alias=True`` so ``pass`` (not ``pass_``) is emitted."""
        return self.model_dump_json(by_alias=True, indent=indent)

    # ------------------------------------------------------------------
    # Markdown (RF-1, RF-6, RF-7)
    # ------------------------------------------------------------------

    def to_markdown(self) -> str:
        """Markdown output. Sections in order per contract report-format.md."""
        lines: list[str] = []
        lines.append("# Darnit Harness Report")
        lines.append("")

        # Summary
        lines.append("## Summary")
        lines.append("")
        target = self.target
        lines.append(f"- Target: `{target.get('local_path', '')}`")
        if target.get("owner") and target.get("repo"):
            lines.append(f"- Repository: `{target['owner']}/{target['repo']}`")
        s = self.summary
        lines.append(f"- Total: {s.total}")
        lines.append(f"- Passed: {s.pass_}")
        lines.append(f"- Failed: {s.fail}")
        lines.append(f"- Warned: {s.warn}")
        lines.append(f"- N/A: {s.n_a}")
        lines.append(f"- Errored: {s.error}")
        lines.append("")

        # Failed controls (RF-7: empty section renders as "None.")
        lines.append("## Failed Controls")
        lines.append("")
        failed = [c for c in self.controls if c.get("status") == "FAIL"]
        if failed:
            for c in failed:
                lines.append(self._format_control_line(c))
        else:
            lines.append("None.")
        lines.append("")

        # Warned or Pending
        lines.append("## Warned or Pending Controls")
        lines.append("")
        warned = [c for c in self.controls if c.get("status") in ("WARN", "PENDING_LLM", "ERROR")]
        if warned:
            for c in warned:
                lines.append(self._format_control_line(c))
        else:
            lines.append("None.")
        lines.append("")

        # Passed
        lines.append("## Passed Controls")
        lines.append("")
        passed = [c for c in self.controls if c.get("status") == "PASS"]
        if passed:
            for c in passed:
                lines.append(self._format_control_line(c, compact=True))
        else:
            lines.append("None.")
        lines.append("")

        # Answer Sources (RF-5)
        lines.append("## Answer Sources")
        lines.append("")
        if self.answer_sources_used:
            for source_name in self.answer_sources_used:
                lines.append(f"- {source_name}")
        else:
            lines.append("None.")
        lines.append("")

        # Resolvers Used (feature 027; only if non-empty)
        if self.resolvers_used:
            lines.append("## Resolvers Used")
            lines.append("")
            for resolver_name in self.resolvers_used:
                lines.append(f"- {resolver_name}")
            lines.append("")

        # Answered Feedback (feature 027; only if non-empty)
        if self.answered_feedback:
            lines.append("## Answered Feedback")
            lines.append("")
            for entry in self.answered_feedback:
                lines.append(
                    f"- **{entry.control_id}** -- {entry.context_key}",
                )
                lines.append(f"  - Question: {entry.question}")
                lines.append(
                    f"  - Answered: `{entry.answer}` "
                    f"(origin: {entry.origin}, authority: {entry.authority})",
                )
                if entry.resolution_trail:
                    lines.append("  - Resolution trail:")
                    for trail_entry in entry.resolution_trail:
                        detail = (
                            f" -- {trail_entry.error_summary}"
                            if trail_entry.error_summary
                            else ""
                        )
                        lines.append(
                            f"    - `{trail_entry.resolver_name}`: "
                            f"{trail_entry.outcome}{detail}",
                        )
            lines.append("")

        # Pending Feedback (feature 027 -- render trails if present)
        if self.pending_feedback:
            lines.append("## Pending Feedback")
            lines.append("")
            for pending in self.pending_feedback:
                lines.append(
                    f"- **{pending.control_id}** -- {pending.context_key}",
                )
                lines.append(f"  - Question: {pending.question}")
                if pending.resolution_trail:
                    lines.append("  - Resolution trail:")
                    for trail_entry in pending.resolution_trail:
                        detail = (
                            f" -- {trail_entry.error_summary}"
                            if trail_entry.error_summary
                            else ""
                        )
                        lines.append(
                            f"    - `{trail_entry.resolver_name}`: "
                            f"{trail_entry.outcome}{detail}",
                        )
            lines.append("")

        # LLM Calls (RF-6)
        lines.append("## LLM Calls")
        lines.append("")
        llm = self.llm_calls
        lines.append(f"- Total: {llm.get('total', 0)}")
        lines.append(f"- Provider: {llm.get('provider', 'unknown')}")
        lines.append("")

        return "\n".join(lines)

    @staticmethod
    def _format_control_line(control: dict[str, Any], compact: bool = False) -> str:
        """Format a single control's line for Markdown output.

        Every mention includes the authority in parentheses per RF-1.
        """
        control_id = control.get("id", "unknown")
        status = control.get("status", "unknown")
        authority = control.get("authority", "unknown")
        if compact:
            return f"- {control_id} {status} ({authority})"
        message = control.get("details") or control.get("message") or ""
        # Truncate long messages so a Markdown list stays readable.
        if len(message) > 200:
            message = message[:200] + "..."
        return f"- {control_id} {status} ({authority}) -- {message}"


__all__ = [
    "HarnessSummary",
    "PendingFeedbackEntry",
    "AnsweredFeedbackEntry",
    "HarnessReport",
]
