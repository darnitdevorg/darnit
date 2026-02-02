"""Attestation predicate builder.

This module builds the in-toto attestation predicate for
OpenSSF Baseline assessment results.
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Optional

if TYPE_CHECKING:
    from darnit.config.models import ProjectConfig


def build_assessment_predicate(
    owner: str,
    repo: str,
    commit: str,
    ref: str | None,
    level: int,
    results: list[dict[str, Any]],
    project_config: Optional["ProjectConfig"],
    adapters_used: list[str]
) -> dict[str, Any]:
    """Build the assessment attestation predicate.

    This creates a predicate conforming to the OpenSSF Baseline
    assessment attestation format.

    Args:
        owner: GitHub organization or user
        repo: Repository name
        commit: Git commit SHA
        ref: Git ref (branch or tag)
        level: Maximum OSPS level assessed
        results: List of check results
        project_config: Project configuration (if any)
        adapters_used: List of adapters used for checks

    Returns:
        Dictionary containing the attestation predicate
    """
    # Count results by status
    passes = [r for r in results if r['status'] == 'PASS']
    fails = [r for r in results if r['status'] == 'FAIL']
    warns = [r for r in results if r['status'] == 'WARN']
    nas = [r for r in results if r['status'] == 'N/A']
    errors = [r for r in results if r['status'] == 'ERROR']

    # Calculate level compliance
    levels = {}
    for lvl in [1, 2, 3]:
        if lvl <= level:
            lvl_results = [r for r in results if r.get('level', 1) == lvl]
            lvl_passes = len([r for r in lvl_results if r['status'] == 'PASS'])
            lvl_total = len(lvl_results)
            lvl_fails = len([r for r in lvl_results if r['status'] == 'FAIL'])
            levels[str(lvl)] = {
                "total": lvl_total,
                "passed": lvl_passes,
                "failed": lvl_fails,
                "compliant": lvl_fails == 0
            }

    # Determine highest compliant level
    level_achieved = 0
    for lvl in [1, 2, 3]:
        if str(lvl) in levels and levels[str(lvl)]["compliant"]:
            level_achieved = lvl
        else:
            break

    # Build controls list
    controls = []
    for r in results:
        control = {
            "id": r['id'],
            "level": r.get('level', 1),
            "category": r['id'].split('-')[1] if '-' in r['id'] else "UNKNOWN",
            "status": r['status'],
            "message": r.get('details', ''),
        }
        if r.get('evidence'):
            control["evidence"] = r['evidence']
        if r.get('source'):
            control["source"] = r['source']
        else:
            control["source"] = "builtin"
        controls.append(control)

    # Build configuration section
    config_section = {
        "project_type": project_config.project_type if project_config else "software",
        "adapters_used": adapters_used or ["builtin"]
    }

    if project_config:
        excluded = []
        for control_id, override in project_config.control_overrides.items():
            if override.get('status') == 'n/a':
                excluded.append(control_id)
        if excluded:
            config_section["excluded_controls"] = excluded

    predicate = {
        "assessor": {
            "name": "openssf-baseline-mcp",
            "version": "0.1.0",
            "uri": "https://github.com/ossf/baseline-mcp"
        },
        "timestamp": datetime.now(UTC).isoformat(),
        "baseline": {
            "version": "2025.10.10",
            "specification": "https://baseline.openssf.org/versions/2025-10-10"
        },
        "repository": {
            "url": f"https://github.com/{owner}/{repo}",
            "commit": commit
        },
        "configuration": config_section,
        "summary": {
            "level_assessed": level,
            "level_achieved": level_achieved,
            "total_controls": len(results),
            "passed": len(passes),
            "failed": len(fails),
            "warnings": len(warns),
            "not_applicable": len(nas),
            "errors": len(errors)
        },
        "levels": levels,
        "controls": controls
    }

    if ref:
        predicate["repository"]["ref"] = ref

    return predicate


__all__ = [
    "build_assessment_predicate",
]
