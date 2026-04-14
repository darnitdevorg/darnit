"""Sieve remediation handler for generating dynamic STRIDE threat models.

Uses the tree-sitter discovery pipeline (``ts_discovery.discover_all``)
with optional Opengrep taint enrichment and the new Markdown generator
(``ts_generators.generate_markdown_threat_model``). On pipeline failure,
falls back to the static template content (pre-resolved by the executor).
"""

from __future__ import annotations

import os
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from darnit.core.logging import get_logger
from darnit.sieve.handler_registry import (
    HandlerContext,
    HandlerResult,
    HandlerResultStatus,
)

from .discovery_models import CandidateFinding, FileScanStats, FindingGroup
from .grouping import group_by_query_id
from .ranking import apply_cap
from .renderers.common import GeneratorOptions, severity_band
from .renderers.data_flow import render_data_flow
from .renderers.group_file import render_group_file
from .renderers.raw_json import render_raw_json
from .renderers.summary import render_summary
from .sidecar import compute_fingerprint, detect_stale, load_sidecar, match_findings, save_sidecar
from .ts_discovery import DiscoveryConfig, discover_all

# Backward-compat alias
_severity_band = severity_band

logger = get_logger("threat_model.remediation")


def _empty_scan_stats() -> FileScanStats:
    """A zeroed FileScanStats, used when discovery cannot run at all."""
    return FileScanStats(
        total_files_seen=0,
        excluded_dir_count=0,
        unsupported_file_count=0,
        in_scope_files=0,
        by_language={},
        shallow_mode=False,
        shallow_threshold=500,
    )


@dataclass
class _TsRunOutput:
    """Result of running the tree-sitter pipeline.

    ``result`` is the raw DiscoveryResult. ``ranked`` is the full ranked
    list (no findings dropped). ``groups`` are findings grouped by query ID.
    ``evidence`` is metadata for HandlerResult. ``failure_reason`` is set
    iff the pipeline couldn't produce any findings.
    """

    result: Any  # DiscoveryResult | None
    ranked: list[CandidateFinding]
    groups: list[FindingGroup]
    evidence: dict[str, Any]
    failure_reason: str | None


def _run_ts_pipeline(
    local_path: str,
    shallow_threshold: int,
    max_findings: int,
) -> _TsRunOutput:
    """Run the full pipeline: discovery → ranking → grouping.

    Never raises — on any failure returns ``_TsRunOutput(result=None, …)``
    so the handler can fall back to the legacy generator.
    """
    from dataclasses import asdict as _asdict

    try:
        result = discover_all(
            Path(local_path),
            config=DiscoveryConfig(shallow_threshold=shallow_threshold),
        )
    except Exception as exc:  # noqa: BLE001 — never break the handler
        logger.warning(
            "ts_discovery.discover_all raised (%s); falling back to template",
            exc,
        )
        return _TsRunOutput(
            result=None,
            ranked=[],
            groups=[],
            evidence={
                "file_scan_stats": _asdict(_empty_scan_stats()),
                "entry_point_count": 0,
                "data_store_count": 0,
                "candidate_finding_count": 0,
                "opengrep_available": False,
                "opengrep_degraded_reason": f"ts_discovery failed: {exc}",
            },
            failure_reason=f"ts_discovery: {exc}",
        )

    # Rank all findings (no drop — all are returned).
    ranked, overflow_hint = apply_cap(result.findings, max_findings)

    evidence: dict[str, Any] = {
        "file_scan_stats": _asdict(result.file_scan_stats)
        if result.file_scan_stats is not None
        else _asdict(_empty_scan_stats()),
        "entry_point_count": len(result.entry_points),
        "data_store_count": len(result.data_stores),
        "candidate_finding_count": len(ranked),
        "opengrep_available": result.opengrep_available,
        "opengrep_degraded_reason": result.opengrep_degraded_reason,
    }

    # Group by query ID for multi-file output.
    groups = group_by_query_id(ranked)

    return _TsRunOutput(
        result=result,
        ranked=ranked,
        groups=groups,
        evidence=evidence,
        failure_reason=None,
    )


def _build_llm_consultation(
    findings: list[CandidateFinding],
    path: str,
) -> dict[str, Any]:
    """Build an LLM consultation payload for threat model verification.

    Returns a structured dict that the calling agent can use to review
    each finding and refine the generated threat model. The agent is
    expected to:

    1. Read the generated file at ``path``
    2. For each finding in ``findings_to_review``, judge whether it is
       a true positive or false positive based on the code snippet
    3. For true positives, optionally enrich the rationale with
       project-specific context
    4. Remove false positives from the file
    5. Commit the refined file
    """
    review_items: list[dict[str, Any]] = []
    for f in findings:
        band = _severity_band(f.severity, f.confidence)
        item: dict[str, Any] = {
            "title": f.title,
            "category": f.category.value,
            "severity_band": band,
            "score": round(f.severity * f.confidence, 2),
            "location": f"{f.primary_location.file}:{f.primary_location.line}",
            "rationale": f.rationale,
            "source": f.source.value,
            "query_id": f.query_id,
        }
        if f.code_snippet:
            marker_idx = f.code_snippet.marker_line - f.code_snippet.start_line
            if 0 <= marker_idx < len(f.code_snippet.lines):
                item["anchor_line"] = f.code_snippet.lines[marker_idx]

        # Per-finding review guidance based on category and confidence
        if band == "LOW":
            item["review_hint"] = (
                "LOW-risk finding — likely noise without taint analysis. "
                "Verify briefly; remove if the code path is internal-only."
            )
        elif f.confidence < 0.5:
            item["review_hint"] = (
                "Low-confidence structural match. Check whether external input actually reaches this code path."
            )
        else:
            item["review_hint"] = (
                "Review the code snippet. Does the described threat apply "
                "given this project's architecture? If yes, consider adding "
                "project-specific context (e.g., which callers reach this "
                "sink, what data flows through it, what mitigations exist)."
            )

        review_items.append(item)

    # Summary stats for the agent
    from collections import Counter

    band_counts = Counter(i["severity_band"] for i in review_items)
    category_counts = Counter(i["category"] for i in review_items)

    return {
        "action": "review_threat_model",
        "file_path": path,
        "total_findings": len(review_items),
        "summary": {
            "by_severity": dict(band_counts),
            "by_category": dict(category_counts),
        },
        "instructions": (
            "The threat model at the file path above was generated by "
            "darnit's tree-sitter structural analysis pipeline. Review "
            "the findings below. For each finding:\n"
            "1. Read the code at the indicated location\n"
            "2. Judge: TRUE POSITIVE (real threat) or FALSE POSITIVE "
            "(not a real threat in this project's context)\n"
            "3. For true positives: enrich the finding's narrative in "
            "the file with project-specific details (which callers "
            "reach this code, what data flows through, existing "
            "mitigations)\n"
            "4. For false positives: remove the finding from the file\n"
            "5. After reviewing all findings, commit the refined file"
        ),
        "findings_to_review": review_items,
    }


def generate_threat_model_handler(
    config: dict[str, Any],
    context: HandlerContext,
) -> HandlerResult:
    """Generate a dynamic STRIDE threat model for remediation.

    Runs the full analysis pipeline (framework detection, asset discovery,
    threat analysis, attack chain detection) and writes a detailed Markdown
    report. Falls back to static template content on analysis failure.

    Config fields:
        path: str - Output file path relative to repository root
        overwrite: bool - Whether to overwrite existing file (default: false)
        content: str - Pre-resolved template content (fallback, provided by executor)

    Context fields:
        local_path: str - Repository root path

    Returns:
        HandlerResult with PASS on success, ERROR on unrecoverable failure.
    """
    path = config.get("path", "")
    if not path:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message="No path specified for threat model generation",
        )

    local_path = context.local_path
    full_path = os.path.join(local_path, path)

    shallow_threshold = int(config.get("shallow_threshold", 500))
    max_findings = int(config.get("max_findings", 50))

    # Respect overwrite flag — skip-if-exists is the conservative default.
    if os.path.exists(full_path) and not config.get("overwrite", False):
        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message=f"Threat model already exists: {path}",
            evidence={
                "path": path,
                "action": "skipped",
                "note": ("Pre-existing threat model preserved. Re-run with overwrite=true to regenerate."),
            },
        )

    # Run the tree-sitter pipeline: discover → rank → group.
    ts_output = _run_ts_pipeline(local_path, shallow_threshold, max_findings)
    ts_evidence = ts_output.evidence

    if ts_output.result is None:
        # Pipeline failed — fall back to template.
        logger.info(
            "ts_pipeline did not produce results (%s); falling back to template",
            ts_output.failure_reason,
        )
        fallback_content = config.get("content", "")
        if not fallback_content:
            return HandlerResult(
                status=HandlerResultStatus.ERROR,
                message=(f"Tree-sitter pipeline failed ({ts_output.failure_reason}) and no template content available"),
                evidence={
                    "path": path,
                    "error": ts_output.failure_reason or "unknown",
                    **ts_evidence,
                },
            )
        try:
            os.makedirs(os.path.dirname(full_path) or ".", exist_ok=True)
            with open(full_path, "w", encoding="utf-8") as f:
                f.write(fallback_content)
        except OSError as write_err:
            return HandlerResult(
                status=HandlerResultStatus.ERROR,
                message=f"Failed to write fallback template: {write_err}",
                evidence={
                    "path": path,
                    "error": str(write_err),
                    **ts_evidence,
                },
            )
        return HandlerResult(
            status=HandlerResultStatus.PASS,
            message=f"Tree-sitter pipeline unavailable — created from template: {path}",
            confidence=1.0,
            evidence={
                "path": path,
                "action": "created_from_template",
                "fallback_reason": ts_output.failure_reason,
                **ts_evidence,
            },
        )

    # Pipeline succeeded — write multi-file output.
    result = ts_output.result
    groups = ts_output.groups
    ranked = ts_output.ranked
    options = GeneratorOptions()

    # Compute fingerprints for all findings.
    repo_root = Path(local_path)
    for f in ranked:
        if not f.fingerprint:
            fp = compute_fingerprint(f, repo_root)
            # CandidateFinding is frozen, so we need object.__setattr__
            object.__setattr__(f, "fingerprint", fp)

    # Sidecar support: load, match, detect stale.
    sidecar_matches: dict[str, Any] = {}
    try:
        sidecar = load_sidecar(repo_root)
    except ValueError as exc:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message=f"Malformed mitigation sidecar: {exc}",
            evidence={"path": path, "error": str(exc), **ts_evidence},
        )

    if sidecar is not None:
        sidecar_matches = match_findings(ranked, sidecar)
        active_fps = {f.fingerprint for f in ranked if f.fingerprint}
        if detect_stale(sidecar, active_fps):
            try:
                save_sidecar(repo_root, sidecar)
            except OSError as exc:
                logger.warning("Failed to save sidecar stale flags: %s", exc)

    # Check for legacy THREAT_MODEL.md at repo root.
    legacy_path = os.path.join(local_path, "THREAT_MODEL.md")
    migration_note: str | None = None
    is_writing_to_legacy = os.path.abspath(full_path) == os.path.abspath(legacy_path)
    if os.path.exists(legacy_path) and not is_writing_to_legacy:
        logger.warning(
            "Legacy THREAT_MODEL.md detected at repo root; "
            "new canonical location is %s. You may remove the legacy file.",
            path,
        )
        migration_note = (
            "Legacy THREAT_MODEL.md detected at repo root. The new canonical "
            f"location is {path}. You may remove the legacy file."
        )

    # Compute overflow hint for SUMMARY display.
    _, overflow_hint = apply_cap(result.findings, options.top_risks_cap)

    # Derive output directory from the configured path's parent.
    output_dir = os.path.dirname(full_path)
    findings_dir = os.path.join(output_dir, "findings")

    try:
        os.makedirs(findings_dir, exist_ok=True)

        files_written: list[str] = []

        # SUMMARY.md
        summary_content = render_summary(
            groups=groups,
            sidecar_matches=sidecar_matches,
            result=result,
            options=options,
            overflow_hint=overflow_hint,
            repo_path=local_path,
        )
        with open(full_path, "w", encoding="utf-8") as f:
            f.write(summary_content)
        files_written.append(path)

        # data-flow.md
        data_flow_path = os.path.join(output_dir, "data-flow.md")
        data_flow_content = render_data_flow(result=result, options=options)
        with open(data_flow_path, "w", encoding="utf-8") as f:
            f.write(data_flow_content)
        files_written.append(os.path.relpath(data_flow_path, local_path))

        # raw-findings.json
        raw_json_path = os.path.join(output_dir, "raw-findings.json")
        raw_json_content = render_raw_json(
            result=result,
            all_findings=ranked,
            sidecar_matches=sidecar_matches,
            repo_path=local_path,
        )
        with open(raw_json_path, "w", encoding="utf-8") as f:
            f.write(raw_json_content)
        files_written.append(os.path.relpath(raw_json_path, local_path))

        # Per-class detail files: findings/<slug>.md
        for group in groups:
            group_path = os.path.join(findings_dir, f"{group.slug}.md")
            group_content = render_group_file(
                group=group,
                sidecar_matches=sidecar_matches,
            )
            with open(group_path, "w", encoding="utf-8") as f:
                f.write(group_content)
            files_written.append(os.path.relpath(group_path, local_path))

    except OSError as e:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message=f"Failed to write threat model: {e}",
            evidence={
                "path": path,
                "error": str(e),
                **ts_evidence,
            },
        )
    except Exception as e:  # noqa: BLE001 — renderer bugs must not crash the handler
        logger.warning("Renderer error during multi-file output: %s", e)
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message=f"Renderer error generating threat model: {e}",
            evidence={
                "path": path,
                "error": str(e),
                "generator": "multi_file_renderers",
                **ts_evidence,
            },
        )

    consultation = _build_llm_consultation(ranked, path)
    return HandlerResult(
        status=HandlerResultStatus.PASS,
        message=(
            f"Generated multi-file threat model: {path} "
            f"({len(groups)} classes, {len(ranked)} findings) "
            "— calling agent should verify findings per the embedded "
            "verification prompt block"
        ),
        confidence=1.0,
        evidence={
            "path": path,
            "action": "created",
            "files_written": files_written,
            "group_count": len(groups),
            "llm_verification_required": True,
            "llm_consultation": consultation,
            "note": (
                "Multi-file threat model produced by the tree-sitter discovery "
                "pipeline. Summary at the path above; per-class details in "
                "findings/ subdirectory. Review each finding against its code "
                "snippet and remove false positives before committing."
            ),
            "generator": "multi_file_renderers",
            **({"migration_note": migration_note} if migration_note else {}),
            **ts_evidence,
        },
    )


__all__ = [
    "generate_threat_model_handler",
]
