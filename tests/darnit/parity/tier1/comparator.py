"""Comparator for Tier 1 audit parity (feature 028 T004).

Diffs two `AuditResult` instances (one from the direct MCP tool call, one
from the harness) and produces a `ParityReport` with a drift table.

The single allowed drift class is: MCP tool leaves a control PENDING_LLM,
harness resolves it via its LLM continuation loop to any non-PENDING_LLM
status. Any other divergence is a hard failure.

See:
  - specs/028-audit-parity-tests/data-model.md sections 3-5
  - specs/028-audit-parity-tests/contracts/tier1-parity-invariant.md
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from darnit.harness.report import HarnessReport

Status = Literal["PASS", "FAIL", "WARN", "N/A", "ERROR", "PENDING_LLM"]
STATUSES: tuple[Status, ...] = (
    "PASS",
    "FAIL",
    "WARN",
    "N/A",
    "ERROR",
    "PENDING_LLM",
)


@dataclass(frozen=True)
class Control:
    id: str
    status: Status
    authority: Literal["dispositive", "suggestive", "asserted"] | None = None
    level: int | None = None


@dataclass(frozen=True)
class AuditResult:
    """Normalized shape both paths reduce to for comparison."""

    controls: tuple[Control, ...]
    source: Literal["mcp_tool", "harness"]

    @classmethod
    def from_mcp_json(cls, payload: dict[str, Any]) -> AuditResult:
        """Parse audit_openssf_baseline(output_format='json') output."""
        results = payload.get("results", [])
        return cls(
            controls=tuple(
                Control(
                    id=str(r.get("id", "")),
                    status=r.get("status", "ERROR"),
                    authority=r.get("authority"),
                    level=r.get("level"),
                )
                for r in results
            ),
            source="mcp_tool",
        )

    @classmethod
    def from_harness_report(cls, report: HarnessReport) -> AuditResult:
        """Reduce a HarnessReport (feature 026) to the same shape."""
        return cls(
            controls=tuple(
                Control(
                    id=str(c.get("id", "")),
                    status=c.get("status", "ERROR"),
                    authority=c.get("authority"),
                    level=c.get("level"),
                )
                for c in report.controls
            ),
            source="harness",
        )

    def filter_to(self, control_ids: tuple[str, ...] | list[str]) -> AuditResult:
        """Return a copy containing only the controls whose id is in the set.

        Neither audit path today applies `audit_profiles` from a fixture's
        `.baseline.toml` automatically, so both paths run every OpenSSF
        Baseline control. This helper narrows to the fixture-declared
        `control_ids` so a fixture can assert parity over its subset without
        the noise of unrelated controls.

        If `control_ids` is empty, returns self (no filtering).
        """
        if not control_ids:
            return self
        allowed = set(control_ids)
        return AuditResult(
            controls=tuple(c for c in self.controls if c.id in allowed),
            source=self.source,
        )


@dataclass(frozen=True)
class DriftEntry:
    """One divergence between the MCP tool and harness paths.

    Statuses that AGREE do not produce a DriftEntry; only divergences do.
    A separate flag distinguishes disallowed (hard failure) from allowed
    (evidence-only) drift.
    """

    fixture_name: str
    control_id: str
    mcp_status: str
    harness_status: str
    note: str = ""  # e.g. "missing on harness side", "missing on mcp side"

    @property
    def is_allowed_drift(self) -> bool:
        """T1-8 canonical table: only PENDING_LLM (MCP) -> non-PENDING_LLM
        (harness) is allowed. Everything else is disallowed."""
        if self.mcp_status == "PENDING_LLM" and self.harness_status != "PENDING_LLM":
            return True
        return False


@dataclass(frozen=True)
class ParityReport:
    fixture_name: str
    total_controls: int
    agreements: int
    drifts: tuple[DriftEntry, ...]

    @property
    def disallowed_drifts(self) -> tuple[DriftEntry, ...]:
        return tuple(d for d in self.drifts if not d.is_allowed_drift)

    @property
    def allowed_drifts(self) -> tuple[DriftEntry, ...]:
        return tuple(d for d in self.drifts if d.is_allowed_drift)

    @property
    def is_green(self) -> bool:
        return len(self.disallowed_drifts) == 0

    def format_summary_line(self) -> str:
        """FR-013 evidence line, emitted on every run."""
        return (
            f"[tier1] {self.fixture_name}: "
            f"{self.total_controls} controls compared, "
            f"{self.agreements} agreed, "
            f"{len(self.disallowed_drifts)} diverged, "
            f"{len(self.allowed_drifts)} allowed-drift"
        )

    def format_failure_table(self) -> str:
        """FR-004: fixed-width Markdown table (no ANSI) for pytest messages.

        Called when disallowed_drifts is non-empty. If called on a green
        report, produces "No disallowed drifts."
        """
        disallowed = self.disallowed_drifts
        if not disallowed:
            return "No disallowed drifts."

        headers = ["control_id", "mcp_status", "harness_status", "note"]
        rows = [[d.control_id, d.mcp_status, d.harness_status, d.note] for d in disallowed]

        # Compute column widths (max of header and any row value).
        widths = [max(len(headers[i]), *(len(row[i]) for row in rows)) for i in range(len(headers))]

        def _fmt_row(row: list[str]) -> str:
            cells = [row[i].ljust(widths[i]) for i in range(len(row))]
            return "| " + " | ".join(cells) + " |"

        separator = "| " + " | ".join("-" * w for w in widths) + " |"
        lines = [
            f"Fixture: {self.fixture_name}",
            f"Disallowed drifts: {len(disallowed)}",
            "",
            _fmt_row(headers),
            separator,
            *[_fmt_row(row) for row in rows],
        ]
        return "\n".join(lines)


def compare(
    mcp: AuditResult,
    harness: AuditResult,
    fixture_name: str,
) -> ParityReport:
    """Diff two AuditResults per the T1-8 allowed-drift table.

    - Statuses that agree: no DriftEntry produced.
    - Controls present on one side but not the other: DriftEntry with
      note='missing on <side>'; treated as disallowed (T1-3).
    - Status divergences: DriftEntry; classification via is_allowed_drift.
    """
    mcp_by_id = {c.id: c for c in mcp.controls}
    harness_by_id = {c.id: c for c in harness.controls}

    all_ids = sorted(set(mcp_by_id) | set(harness_by_id))
    drifts: list[DriftEntry] = []
    agreements = 0

    for cid in all_ids:
        m = mcp_by_id.get(cid)
        h = harness_by_id.get(cid)

        if m is None and h is not None:
            drifts.append(
                DriftEntry(
                    fixture_name=fixture_name,
                    control_id=cid,
                    mcp_status="<MISSING>",
                    harness_status=h.status,
                    note="missing on mcp side",
                )
            )
            continue
        if h is None and m is not None:
            drifts.append(
                DriftEntry(
                    fixture_name=fixture_name,
                    control_id=cid,
                    mcp_status=m.status,
                    harness_status="<MISSING>",
                    note="missing on harness side",
                )
            )
            continue

        # Both present.
        assert m is not None and h is not None
        if m.status == h.status:
            agreements += 1
        else:
            drifts.append(
                DriftEntry(
                    fixture_name=fixture_name,
                    control_id=cid,
                    mcp_status=m.status,
                    harness_status=h.status,
                )
            )

    return ParityReport(
        fixture_name=fixture_name,
        total_controls=len(all_ids),
        agreements=agreements,
        drifts=tuple(drifts),
    )


__all__ = (
    "Control",
    "AuditResult",
    "DriftEntry",
    "ParityReport",
    "Status",
    "STATUSES",
    "compare",
)
