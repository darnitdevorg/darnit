"""Render a per-class detail file (``findings/<slug>.md``).

Each :class:`FindingGroup` gets its own Markdown file listing the
mitigation guidance, representative code examples, and a full instance
table.
"""

from __future__ import annotations

from typing import Any

from ..discovery_models import CandidateFinding, FindingGroup
from .common import STRIDE_HEADINGS, severity_band

# ---------------------------------------------------------------------------
# Mitigation helpers
# ---------------------------------------------------------------------------

_MITIGATED_STATUSES = frozenset({"mitigated", "accepted", "false_positive"})


def _finding_status(
    finding: CandidateFinding,
    sidecar_matches: dict[str, Any],
) -> str:
    """Return the display status for a single finding."""
    fp = finding.fingerprint
    if fp and fp in sidecar_matches:
        entry = sidecar_matches[fp]
        status = getattr(entry, "status", None) or entry.get("status", "")  # type: ignore[union-attr]
        return str(status).capitalize()
    return "Unmitigated"


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------


def _render_metadata(group: FindingGroup) -> list[str]:
    md: list[str] = []
    stride_heading = STRIDE_HEADINGS.get(group.stride_category, "Unknown")
    top_finding = max(
        group.findings,
        key=lambda f: f.severity * f.confidence,
    )
    band = severity_band(top_finding.severity, top_finding.confidence)

    md.append(f"**STRIDE category:** {stride_heading}")
    md.append(f"**Rule ID:** `{group.query_id}`")
    md.append(f"**Max severity:** {band}")
    md.append("")
    return md


def _render_mitigation(group: FindingGroup) -> list[str]:
    md: list[str] = ["## Mitigation", ""]
    hint = group.mitigation_hint.strip() if group.mitigation_hint else ""
    md.append(hint or "No specific guidance available.")
    md.append("")
    return md


def _render_representative_examples(group: FindingGroup) -> list[str]:
    md: list[str] = ["## Representative Examples", ""]

    # Pick up to 3 highest-severity findings for code examples.
    sorted_findings = sorted(
        group.findings,
        key=lambda f: f.severity * f.confidence,
        reverse=True,
    )
    examples = sorted_findings[:3]

    for finding in examples:
        loc = f"{finding.primary_location.file}:{finding.primary_location.line}"
        md.append("<details>")
        md.append(f"<summary><code>{loc}</code></summary>")
        md.append("")
        md.append("```")
        snippet = finding.code_snippet
        for offset, line in enumerate(snippet.lines):
            line_no = snippet.start_line + offset
            prefix = ">>> " if line_no == snippet.marker_line else "    "
            md.append(f"{prefix}{line_no:4d} | {line}")
        md.append("```")
        md.append("")
        md.append(f"*{finding.rationale}*")
        md.append("")
        md.append("</details>")
        md.append("")

    return md


def _render_all_instances(
    group: FindingGroup,
    sidecar_matches: dict[str, Any],
) -> list[str]:
    md: list[str] = ["## All Instances", ""]

    md.append("| # | File | Line | Severity | Confidence | Status |")
    md.append("|---|------|------|----------|------------|--------|")
    for idx, finding in enumerate(group.findings, start=1):
        band = severity_band(finding.severity, finding.confidence)
        status = _finding_status(finding, sidecar_matches)
        md.append(
            f"| {idx} "
            f"| `{finding.primary_location.file}` "
            f"| {finding.primary_location.line} "
            f"| {band} "
            f"| {finding.confidence:.2f} "
            f"| {status} |"
        )

    md.append("")
    md.append(f"*{len(group.findings)} instances total.*")
    md.append("")
    return md


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def render_group_file(
    group: FindingGroup,
    sidecar_matches: dict[str, Any],
) -> str:
    """Render a detail file for a single :class:`FindingGroup`.

    Parameters
    ----------
    group:
        The finding group to render.
    sidecar_matches:
        Mapping of finding fingerprint to mitigation entry (or dict with a
        ``status`` key).  Empty dict means nothing is mitigated.

    Returns
    -------
    str
        Complete Markdown content for ``findings/<slug>.md``.
    """
    md: list[str] = [f"# {group.class_name}", ""]
    md.extend(_render_metadata(group))
    md.extend(_render_mitigation(group))
    md.extend(_render_representative_examples(group))
    md.extend(_render_all_instances(group, sidecar_matches))
    return "\n".join(md) + "\n"
