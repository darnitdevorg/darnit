"""Renderer for the ``raw-findings.json`` output file.

Produces a complete JSON dump of ALL findings with metadata, fingerprints,
and optional sidecar mitigation data.  This is the machine-readable
counterpart to the Markdown reports.
"""

from __future__ import annotations

import json
from datetime import UTC, datetime
from typing import Any

from ..discovery_models import (
    CandidateFinding,
    DiscoveryResult,
)
from .common import repo_display_name

# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def render_raw_json(
    result: DiscoveryResult,
    all_findings: list[CandidateFinding],
    sidecar_matches: dict[str, Any],
    repo_path: str = ".",
) -> str:
    """Render the ``raw-findings.json`` output file.

    Parameters
    ----------
    result:
        The aggregated discovery result from the tree-sitter pipeline.
    all_findings:
        The complete list of candidate findings (not capped).
    sidecar_matches:
        Mapping of finding fingerprints to sidecar mitigation objects.
        Only findings whose ``fingerprint`` appears as a key in this dict
        will include a ``mitigation`` field in the output.
    repo_path:
        Path to the repository root, used to derive the display name.

    Returns
    -------
    str
        Pretty-printed JSON string.
    """
    stats = result.file_scan_stats

    # -- metadata -----------------------------------------------------------
    languages = sorted((stats.by_language or {}).keys()) if stats else []
    metadata: dict[str, Any] = {
        "repository": repo_display_name(repo_path),
        "scan_date": datetime.now(tz=UTC).isoformat(),
        "languages": languages,
        "files_scanned": stats.in_scope_files if stats else 0,
        "opengrep_available": result.opengrep_available,
    }

    # -- findings -----------------------------------------------------------
    findings_json: list[dict[str, Any]] = []
    for f in all_findings:
        entry: dict[str, Any] = {
            "query_id": f.query_id,
            "category": f.category.value,
            "title": f.title,
            "severity": f.severity,
            "confidence": f.confidence,
            "file": f.primary_location.file,
            "line": f.primary_location.line,
            "end_line": f.primary_location.end_line,
            "snippet": "\n".join(f.code_snippet.lines),
            "fingerprint": f.fingerprint,
        }
        # Only include mitigation if a sidecar match exists for this fingerprint
        if f.fingerprint and f.fingerprint in sidecar_matches:
            m = sidecar_matches[f.fingerprint]
            entry["mitigation"] = {
                "status": m.status if isinstance(m.status, str) else m.status.value,
                "note": m.note,
                "reviewer": m.reviewer,
                "reviewed_at": m.reviewed_at,
                "stale": m.stale,
            }
        findings_json.append(entry)

    # -- entry_points -------------------------------------------------------
    entry_points_json: list[dict[str, Any]] = [
        {
            "kind": ep.kind.value,
            "framework": ep.framework,
            "http_method": ep.http_method,
            "route_path": ep.route_path,
            "name": ep.name,
            "file": ep.location.file,
            "line": ep.location.line,
            "has_auth_decorator": ep.has_auth_decorator,
        }
        for ep in result.entry_points
    ]

    # -- data_stores --------------------------------------------------------
    data_stores_json: list[dict[str, Any]] = [
        {
            "technology": ds.technology,
            "kind": ds.kind.value,
            "import_evidence": ds.import_evidence,
            "file": ds.location.file,
            "line": ds.location.line,
        }
        for ds in result.data_stores
    ]

    # -- file_scan_stats ----------------------------------------------------
    file_scan_stats_json: dict[str, Any] | None = None
    if stats is not None:
        file_scan_stats_json = {
            "total_files_seen": stats.total_files_seen,
            "excluded_dir_count": stats.excluded_dir_count,
            "unsupported_file_count": stats.unsupported_file_count,
            "in_scope_files": stats.in_scope_files,
            "by_language": dict(stats.by_language),
            "shallow_mode": stats.shallow_mode,
            "shallow_threshold": stats.shallow_threshold,
        }

    # -- assemble payload ---------------------------------------------------
    payload: dict[str, Any] = {
        "metadata": metadata,
        "findings": findings_json,
        "entry_points": entry_points_json,
        "data_stores": data_stores_json,
        "file_scan_stats": file_scan_stats_json,
    }

    return json.dumps(payload, indent=2)


__all__ = [
    "render_raw_json",
]
