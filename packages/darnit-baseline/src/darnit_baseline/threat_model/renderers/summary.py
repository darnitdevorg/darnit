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


def _render_verification_prompts(has_cli_families: bool = False) -> list[str]:
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
    if has_cli_families:
        md.append("")
        md.append(
            "**For the CLI Entry Points section:** this section was produced "
            "by an import-based heuristic, not a STRIDE analysis. Open each "
            "family's representative file. For each STRIDE category listed: "
            "does the file's actual behaviour match? If not, replace the "
            "category and remove this paragraph's note. If the family was "
            "over- or under-grouped (subcommands missing, or unrelated "
            "commands lumped together), restructure the table and edit the "
            "`family_key` identifier in `raw-findings.json` to match."
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

    # Feature 014-cobra-threat-model: surface cobra-specific scan counters
    # per FR-007 — total Go files scanned, count that imported cobra,
    # count of cobra-importing files where no query matched.
    cobra_stats = getattr(result, "cobra_stats", None) or {}
    if cobra_stats.get("cobra_files", 0) > 0:
        md.append(
            f"- Scanned **{cobra_stats.get('go_files_scanned', 0)}** Go files; "
            f"**{cobra_stats['cobra_files']}** imported "
            f"`github.com/spf13/cobra`."
        )
        unmatched = cobra_stats.get("cobra_files_unmatched", 0)
        if unmatched > 0:
            examples = cobra_stats.get("unmatched_examples", []) or []
            examples_str = (
                "; example: `" + examples[0] + "`" if examples else ""
            )
            md.append(
                f"  - **{unmatched}** cobra-importing file(s) matched no "
                f"recognised pattern (builder-style or factory-returned-via-"
                f"indirection construction){examples_str}. Surfaced commands "
                f"may be incomplete."
            )

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


def _render_cli_entry_points(
    families: list[Any],
    command_metadata: dict[str, dict[str, str]] | None = None,
) -> list[str]:
    """Render the ``## Entry Points`` / ``### CLI Entry Points`` section.

    Feature 014-cobra-threat-model. See
    ``specs/014-cobra-threat-model/contracts/output-document-contract.md``
    for the contract.

    Returns the empty list when ``families`` is empty — no placeholder
    is emitted per FR-014. Families are pre-sorted by
    ``group_by_cli_family`` for deterministic output. Each family
    becomes one ``#### Family: <display_name>`` block with source root,
    subcommand list, STRIDE categories, confidence line, location
    table, and a refinement-note paragraph that flags the categories
    as heuristic.

    Args:
        families: Pre-grouped + STRIDE-categorised CommandFamily list.
        command_metadata: Optional dict mapping ``f"{file}:{line}"`` →
            ``{"short": ..., "long": ...}`` for populating the Notes
            column with each command's Short: text. Missing entries get
            an empty Notes cell.
    """
    if not families:
        return []
    md_keys = command_metadata or {}
    md: list[str] = ["## Entry Points", "", "### CLI Entry Points", ""]
    for family in families:
        md.append(f"#### Family: {family.display_name}")
        md.append("")
        md.append(f"**Source root**: `{family.source_root}`")
        sub_names = [m.name for m in family.members]
        md.append(
            f"**Subcommands**: {len(family.members)} ({', '.join(sub_names)})"
        )
        md.append(
            f"**STRIDE categories**: {', '.join(family.stride_categories)}"
        )
        md.append("**Confidence**: heuristic — needs reviewer attention")
        md.append("")
        md.append("| Subcommand | Location | Notes |")
        md.append("|---|---|---|")
        for member in family.members:
            loc = f"`{member.location.file}:{member.location.line}`"
            key = f"{member.location.file}:{member.location.line}"
            note = md_keys.get(key, {}).get("short", "")
            # Escape pipes in note text so markdown table parsing stays sane.
            safe_note = note.replace("|", "\\|") if note else ""
            md.append(f"| {member.name} | {loc} | {safe_note} |")
        md.append("")
        md.append(
            "_Refinement notes: This family was categorised by "
            "import-based heuristic; categories may need recategorisation "
            "per the project's threat model._"
        )
        md.append("")
    return md


def render_summary(
    groups: list[FindingGroup],
    sidecar_matches: dict[str, Any],
    result: DiscoveryResult,
    options: GeneratorOptions,
    overflow_hint: TrimmedOverflow | None = None,
    repo_path: str = ".",
    cli_families: list[Any] | None = None,
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
    cli_families:
        Optional list of :class:`CommandFamily` instances produced by the
        cobra extractor + grouping + STRIDE assignment (feature
        014-cobra-threat-model). When non-empty, surfaces a ``## Entry
        Points`` / ``### CLI Entry Points`` section in the rendered
        document. When ``None`` or empty, no CLI section is emitted (FR-014).

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
    md.extend(
        _render_cli_entry_points(
            cli_families or [],
            command_metadata=getattr(result, "cobra_command_metadata", None),
        )
    )
    md.extend(_render_companion_links())
    md.extend(_render_recommendations(groups, sidecar_matches))
    md.extend(_render_verification_prompts(has_cli_families=bool(cli_families)))
    md.extend(_render_limitations(result, overflow_hint))
    return "\n".join(md) + "\n"
