"""Render SUMMARY.md for the multi-file threat model output layout.

Produces the top-level summary document that links to per-class detail
files under ``findings/`` and to the companion ``data-flow.md`` and
``raw-findings.json`` artefacts.
"""

from __future__ import annotations

from datetime import datetime
from typing import Any

from ..discovery_models import (
    CandidateFinding,
    DiscoveryResult,
    FindingGroup,
    TrimmedOverflow,
)
from .common import (
    STRIDE_HEADINGS,
    VERIFICATION_PROMPT_CLOSE,
    VERIFICATION_PROMPT_OPEN,
    GeneratorOptions,
    repo_display_name,
    risk_counts,
    severity_band,
)

# ---------------------------------------------------------------------------
# Mitigation helpers
# ---------------------------------------------------------------------------

_MITIGATED_STATUSES = frozenset({"mitigated", "accepted", "false_positive"})


def _is_mitigated(fingerprint: str | None, sidecar_matches: dict[str, Any]) -> bool:
    """Return True if the finding is covered by an accepted sidecar entry."""
    if not fingerprint or fingerprint not in sidecar_matches:
        return False
    entry = sidecar_matches[fingerprint]
    status = getattr(entry, "status", None) or entry.get("status", "")  # type: ignore[union-attr]
    return status in _MITIGATED_STATUSES


def _mitigation_stance(group: FindingGroup, sidecar_matches: dict[str, Any]) -> str:
    """Return ``<mitigated>/<total>`` string for a group."""
    mitigated = sum(1 for f in group.findings if _is_mitigated(f.fingerprint, sidecar_matches))
    return f"{mitigated}/{len(group.findings)}"


def _has_unmitigated(group: FindingGroup, sidecar_matches: dict[str, Any]) -> bool:
    """Return True if at least one finding in the group is not mitigated."""
    return any(not _is_mitigated(f.fingerprint, sidecar_matches) for f in group.findings)


# ---------------------------------------------------------------------------
# Section renderers
# ---------------------------------------------------------------------------


def _render_executive_summary(
    result: DiscoveryResult,
    all_findings: list[CandidateFinding],
    repo_path: str,
) -> list[str]:
    md: list[str] = ["## Executive Summary", ""]

    display = repo_display_name(repo_path)
    scan_date = datetime.now().strftime("%Y-%m-%d %H:%M:%S")

    stats = result.file_scan_stats
    languages = ", ".join(sorted((stats.by_language or {}).keys())) if stats else "unknown"

    counts = risk_counts(all_findings)
    total = sum(counts.values())

    md.append("| Field | Value |")
    md.append("|-------|-------|")
    md.append(f"| Repository | `{display}` |")
    md.append(f"| Scan date | {scan_date} |")
    md.append(f"| Languages | {languages or 'none'} |")
    md.append(f"| Total findings | {total} |")
    md.append(f"| Critical | {counts['CRITICAL']} |")
    md.append(f"| High | {counts['HIGH']} |")
    md.append(f"| Medium | {counts['MEDIUM']} |")
    md.append(f"| Low | {counts['LOW']} |")
    md.append("")
    return md


def _render_top_risks(
    groups: list[FindingGroup],
    sidecar_matches: dict[str, Any],
    options: GeneratorOptions,
    overflow_hint: TrimmedOverflow | None,
) -> list[str]:
    md: list[str] = ["## Top Risks", ""]

    sorted_groups = sorted(groups, key=lambda g: g.max_severity_score, reverse=True)
    cap = options.top_risks_cap
    visible = sorted_groups[:cap]
    overflow_count = len(sorted_groups) - cap

    if not visible:
        md.append("No findings to report.")
        md.append("")
        return md

    md.append("| Class | STRIDE | Instances | Severity | Mitigation |")
    md.append("|-------|--------|-----------|----------|------------|")
    for group in visible:
        stride_heading = STRIDE_HEADINGS.get(group.stride_category, "Unknown")
        instance_count = len(group.findings)
        # Use the group's max_severity_score to determine the band; pick the
        # highest-severity finding's individual values for the band function.
        top_finding = max(
            group.findings,
            key=lambda f: f.severity * f.confidence,
        )
        band = severity_band(top_finding.severity, top_finding.confidence)
        stance = _mitigation_stance(group, sidecar_matches)
        link = f"[{group.class_name}](findings/{group.slug}.md)"
        md.append(f"| {link} | {stride_heading} | {instance_count} | {band} | {stance} |")

    if overflow_count > 0:
        md.append("")
        md.append(f"*...and {overflow_count} more classes — see [`findings/`](findings/) for full details.*")

    md.append("")
    return md


def _render_unmitigated(
    groups: list[FindingGroup],
    sidecar_matches: dict[str, Any],
) -> list[str]:
    md: list[str] = ["## Unmitigated Findings", ""]

    unmitigated_groups = [g for g in groups if _has_unmitigated(g, sidecar_matches)]

    if not unmitigated_groups:
        md.append("All findings have been mitigated, accepted, or marked as false positives.")
        md.append("")
        return md

    # Sort by max severity descending for consistent ordering.
    unmitigated_groups.sort(key=lambda g: g.max_severity_score, reverse=True)

    md.append("| Class | Instances | Max Severity | Detail |")
    md.append("|-------|-----------|--------------|--------|")
    for group in unmitigated_groups:
        unmitigated_count = sum(1 for f in group.findings if not _is_mitigated(f.fingerprint, sidecar_matches))
        top_finding = max(
            group.findings,
            key=lambda f: f.severity * f.confidence,
        )
        band = severity_band(top_finding.severity, top_finding.confidence)
        link = f"[{group.slug}.md](findings/{group.slug}.md)"
        md.append(f"| {group.class_name} | {unmitigated_count} | {band} | {link} |")

    md.append("")
    return md


def _render_companion_links() -> list[str]:
    md: list[str] = ["## Companion Artefacts", ""]
    md.append("- [Data Flow Diagram](data-flow.md)")
    md.append("- [Raw Findings (JSON)](raw-findings.json)")
    md.append("")
    return md


def _render_recommendations(
    groups: list[FindingGroup],
    sidecar_matches: dict[str, Any],
) -> list[str]:
    md: list[str] = ["## Recommendations Summary", ""]

    # Collect all individual findings from all groups.
    all_findings: list[CandidateFinding] = []
    for group in groups:
        for f in group.findings:
            if not _is_mitigated(f.fingerprint, sidecar_matches):
                all_findings.append(f)

    immediate = [f for f in all_findings if severity_band(f.severity, f.confidence) in ("CRITICAL", "HIGH")]
    short_term = [f for f in all_findings if severity_band(f.severity, f.confidence) == "MEDIUM"]

    md.append("### Immediate Actions (Critical / High)")
    md.append("")
    if immediate:
        for i, f in enumerate(immediate, start=1):
            md.append(f"{i}. **{f.title}** — `{f.primary_location.file}:{f.primary_location.line}`")
    else:
        md.append("No critical or high severity findings requiring immediate action.")
    md.append("")

    md.append("### Short-term Actions (Medium)")
    md.append("")
    if short_term:
        for i, f in enumerate(short_term, start=1):
            md.append(f"{i}. **{f.title}** — `{f.primary_location.file}:{f.primary_location.line}`")
    else:
        md.append("No medium severity findings.")
    md.append("")

    return md


def _render_verification_prompts() -> list[str]:
    md: list[str] = ["## Verification Prompts", ""]
    md.append(VERIFICATION_PROMPT_OPEN)
    md.append("")
    md.append(
        "**For the calling agent (Claude via MCP):** this summary was produced "
        "by the darnit tree-sitter discovery pipeline. Before committing, "
        "follow these steps:"
    )
    md.append("")
    md.append("1. Open each detail file under `findings/` and review the representative code snippets.")
    md.append(
        "2. For each finding class, ask: does the code at these locations "
        "plausibly exhibit the described threat? If not, remove the detail "
        "file and its entry from this summary."
    )
    md.append("3. Refine narrative with project-specific details where helpful.")
    md.append(
        "4. Preserve this `darnit:verification-prompt-block` section — it "
        "marks the draft as having gone through review."
    )
    md.append("")
    md.append(VERIFICATION_PROMPT_CLOSE)
    md.append("")
    return md


def _render_limitations(
    result: DiscoveryResult,
    overflow_hint: TrimmedOverflow | None,
) -> list[str]:
    md: list[str] = ["## Limitations", ""]
    stats = result.file_scan_stats

    if stats is not None:
        by_lang = ", ".join(f"{lang}={count}" for lang, count in sorted(stats.by_language.items()))
        md.append(f"- Scanned **{stats.in_scope_files}** in-scope files ({by_lang or 'none'}).")
        md.append(
            f"- Skipped **{stats.excluded_dir_count}** vendor/build directories "
            f"and **{stats.unsupported_file_count}** files in unsupported languages."
        )
        if stats.shallow_mode:
            md.append(
                f"- **Shallow analysis mode** was active (threshold: "
                f"{stats.shallow_threshold}). Some analyses were reduced or skipped."
            )

    md.append(f"- Opengrep taint analysis: {'available' if result.opengrep_available else 'not available'}.")
    if result.opengrep_degraded_reason:
        md.append(f"  - Reason: {result.opengrep_degraded_reason}")

    if overflow_hint is not None and overflow_hint.total > 0:
        md.append("")
        md.append(f"- **{overflow_hint.total}** additional candidate findings were trimmed to fit the finding cap.")

    md.append("")
    md.append(
        "*This is a threat-modeling aid, not an exhaustive vulnerability "
        "scan. Use Kusari Inspector or an equivalent SAST tool for deeper "
        "coverage.*"
    )
    md.append("")
    return md


# ---------------------------------------------------------------------------
# Public entry point
# ---------------------------------------------------------------------------


def render_summary(
    groups: list[FindingGroup],
    sidecar_matches: dict[str, Any],
    result: DiscoveryResult,
    options: GeneratorOptions,
    overflow_hint: TrimmedOverflow | None = None,
    repo_path: str = ".",
) -> str:
    """Render the top-level ``SUMMARY.md`` for the multi-file threat model.

    Parameters
    ----------
    groups:
        Ranked :class:`FindingGroup` instances (one per vulnerability class).
    sidecar_matches:
        Mapping of finding fingerprint to :class:`MitigationEntry` (or dict
        with a ``status`` key).  Empty dict means nothing is mitigated.
    result:
        The full :class:`DiscoveryResult` from the discovery pipeline.
    options:
        :class:`GeneratorOptions` controlling caps and detail level.
    overflow_hint:
        Optional overflow data describing findings trimmed by the cap.
    repo_path:
        Path to the repository root (used for display name derivation).

    Returns
    -------
    str
        Complete Markdown content for ``SUMMARY.md``.
    """
    # Flatten all findings for the executive summary counts.
    all_findings: list[CandidateFinding] = []
    for group in groups:
        all_findings.extend(group.findings)

    md: list[str] = ["# Threat Model Report", ""]
    md.extend(_render_executive_summary(result, all_findings, repo_path))
    md.extend(_render_top_risks(groups, sidecar_matches, options, overflow_hint))
    md.extend(_render_unmitigated(groups, sidecar_matches))
    md.extend(_render_companion_links())
    md.extend(_render_recommendations(groups, sidecar_matches))
    md.extend(_render_verification_prompts())
    md.extend(_render_limitations(result, overflow_hint))
    return "\n".join(md) + "\n"
