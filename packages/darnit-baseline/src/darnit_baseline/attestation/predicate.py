"""Attestation predicate builder.

This module builds the in-toto attestation predicate for
OpenSSF Baseline assessment results.

RFC-0001 Stage 1 (feature 025 T046, T054): each result entry now carries
an ``authority`` field ("dispositive" | "suggestive" | "asserted"). The
predicate type string ``https://openssf.org/baseline/assessment/v1`` does
NOT change; the addition is field-additive within v1 per Q2 clarification.
Consumers with permissive schemas continue to load unchanged; consumers
with field-strict validation must update. See
specs/025-rfc0001-stage1/contracts/attestation-authority-field.md.

Feature 040: a result that is N/A because a not-applicable claim was honored
carries ``authority: asserted``, ``asserted_by``, and, when a confirmation
made it count, ``confirmed_by`` and ``confirmed_at``. Level compliance uses
the framework's shared rule (``darnit.tools.audit.calculate_compliance``).

Feature 041, additive within v1 like ``authority``: every control carries
``concluded_by`` when the result has one; PENDING carries ``pending.kind``
(``llm_judgment`` or ``confirmation``); a PASS candidate stays PENDING and
carries ``candidate`` with ``confirmed: false`` and no verdict, so it never
reads as PASS; a PASS from a confirmed candidate carries ``authority:
asserted``, ``concluded_by: confirmation``, ``confirmation``, and the
confirmed ``candidate``; ERROR carries ``error.class`` and ``error.cause``.
The summary and each level add ``pending``, ``pass_candidates``,
``warnings``, and ``errors`` counts.
"""

from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Optional

from darnit.tools.audit import calculate_compliance

if TYPE_CHECKING:
    from darnit.config.schema import ProjectConfig


def build_assessment_predicate(
    owner: str,
    repo: str,
    commit: str,
    ref: str | None,
    level: int,
    results: list[dict[str, Any]],
    project_config: Optional["ProjectConfig"],
    adapters_used: list[str],
    trust: dict[str, Any] | None = None,
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
        trust: Trust decision for the audited repository (feature 040)

    Returns:
        Dictionary containing the attestation predicate
    """
    # Count results by status
    passes = [r for r in results if r["status"] == "PASS"]
    fails = [r for r in results if r["status"] == "FAIL"]
    warns = [r for r in results if r["status"] == "WARN"]
    nas = [r for r in results if r["status"] == "N/A"]
    errors = [r for r in results if r["status"] == "ERROR"]
    pendings = [r for r in results if r["status"] == "PENDING"]

    # Calculate level compliance
    compliance = calculate_compliance(results, min(level, 3))
    levels = {}
    for lvl in [1, 2, 3]:
        if lvl <= level:
            lvl_results = [r for r in results if (r.get("level") or 1) == lvl]
            levels[str(lvl)] = {
                "total": len(lvl_results),
                "passed": _count(lvl_results, "PASS"),
                "failed": _count(lvl_results, "FAIL"),
                "warnings": _count(lvl_results, "WARN"),
                "errors": _count(lvl_results, "ERROR"),
                "pending": _count(lvl_results, "PENDING"),
                "pass_candidates": len([r for r in lvl_results if _is_pass_candidate(r)]),
                "compliant": compliance[lvl],
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
            "id": r["id"],
            "level": r.get("level") or 1,
            "category": r["id"].split("-")[1] if "-" in r["id"] else "UNKNOWN",
            "status": r["status"],
            "message": r.get("details", ""),
        }
        if r.get("evidence"):
            control["evidence"] = r["evidence"]
        if r.get("source"):
            control["source"] = r["source"]
        else:
            control["source"] = "builtin"
        # RFC-0001 Stage 1 (feature 025 T046): additive `authority` field.
        # Present when the result carries one; absent for results loaded
        # from a pre-Stage-1 serialized state. Per contract T2, a Stage-1
        # producer emits authority for every result it generates.
        if r.get("authority") is not None:
            control["authority"] = r["authority"]
        # Feature 036: additive `error_class` field, present only when the
        # resolving pass could not run to completion. Additive within the v1
        # predicate schema -- no version bump, same treatment `authority`
        # got above. A signed attestation carrying a bare verdict when the
        # underlying check never reached the network is exactly the
        # misleading claim Constitution Principle II forbids.
        if r.get("error_class") is not None:
            control["error_class"] = r["error_class"]
        control.update(_result_contract_labels(r))
        assertion = r.get("assertion")
        if assertion and assertion.get("outcome") == "honored" and r["status"] == "N/A":
            control["authority"] = "asserted"
            control["asserted_by"] = assertion.get("asserted_by")
            confirmation = assertion.get("confirmation")
            if confirmation:
                control["confirmed_by"] = confirmation.get("confirmed_by")
                control["confirmed_at"] = confirmation.get("confirmed_at")
        elif assertion:
            control["assertion_outcome"] = assertion.get("outcome")
        controls.append(control)

    # Build configuration section
    config_section = {
        "project_type": project_config.project_type if project_config else "software",
        "adapters_used": adapters_used or ["builtin"],
    }

    excluded = [c["id"] for c in controls if c.get("authority") == "asserted" and c["status"] == "N/A"]
    if excluded:
        config_section["excluded_controls"] = excluded

    predicate = {
        "assessor": {"name": "openssf-baseline-mcp", "version": "0.1.0", "uri": "https://github.com/ossf/baseline-mcp"},
        "timestamp": datetime.now(UTC).isoformat(),
        "baseline": {"version": "2025.10.10", "specification": "https://baseline.openssf.org/versions/2025-10-10"},
        "repository": {"url": f"https://github.com/{owner}/{repo}", "commit": commit},
        "configuration": config_section,
        "summary": {
            "level_assessed": level,
            "level_achieved": level_achieved,
            "total_controls": len(results),
            "passed": len(passes),
            "failed": len(fails),
            "warnings": len(warns),
            "not_applicable": len(nas),
            "errors": len(errors),
            "pending": len(pendings),
            "pass_candidates": len([r for r in results if _is_pass_candidate(r)]),
        },
        "levels": levels,
        "controls": controls,
    }

    if ref:
        predicate["repository"]["ref"] = ref
    # Feature 040: additive within the v1 predicate, like `authority`.
    if trust is not None:
        predicate["trust"] = trust

    return predicate


def _count(results: list[dict[str, Any]], status: str) -> int:
    return len([r for r in results if r["status"] == status])


def _is_pass_candidate(result: dict[str, Any]) -> bool:
    return result["status"] == "PENDING" and (result.get("pending") or {}).get("kind") == "confirmation"


def _candidate_label(candidate: dict[str, Any], *, confirmed: bool) -> dict[str, Any]:
    label: dict[str, Any] = {"confirmed": confirmed}
    for key in ("source", "model", "model_version", "evidence_digest", "reasoning"):
        if candidate.get(key) is not None:
            label[key] = candidate[key]
    label["cited_evidence"] = list(candidate.get("cited_evidence") or [])
    return label


def _result_contract_labels(result: dict[str, Any]) -> dict[str, Any]:
    """Feature 041 result-contract fields for one control; a candidate never reads as PASS."""
    labels: dict[str, Any] = {}
    status = result["status"]
    if result.get("concluded_by") is not None:
        labels["concluded_by"] = result["concluded_by"]
    if status == "PENDING":
        labels["pending"] = {"kind": (result.get("pending") or {}).get("kind", "llm_judgment")}
        if _is_pass_candidate(result) and result.get("candidate"):
            labels["candidate"] = _candidate_label(result["candidate"], confirmed=False)
    elif status == "ERROR":
        error = result.get("error") or {}
        labels["error"] = {
            "class": error.get("class") or result.get("error_class") or "evaluation",
            "cause": error.get("cause") or result.get("details") or "",
        }
    elif status == "PASS" and result.get("concluded_by") == "confirmation":
        confirmation = result.get("confirmation") or {}
        labels["confirmation"] = {
            key: confirmation.get(key) for key in ("confirmed_by", "confirmed_at", "expires_at")
        }
        if result.get("candidate"):
            labels["candidate"] = _candidate_label(result["candidate"], confirmed=True)
    return labels


__all__ = [
    "build_assessment_predicate",
]
