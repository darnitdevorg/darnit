"""Candidate-finding ranking and top-N cap with overflow accounting.

Implements the severity × confidence heuristic described in
``specs/010-threat-model-ast/research.md`` §12:

- Base severity is a fixed mapping from (STRIDE category, finding source) pairs
- Confidence is a fixed mapping from (finding source, query intent) pairs
- Findings are ranked by ``severity * confidence`` descending
- The top-N cap (default 50) trims the list, producing a
  :class:`TrimmedOverflow` summary of what was dropped
- A category-diversity tie-break prevents one STRIDE category from dominating
  the draft when it numerically overwhelms all others
"""

from __future__ import annotations

import logging
from collections import Counter

from .discovery_models import (
    CandidateFinding,
    FindingSource,
    TrimmedOverflow,
)
from .models import StrideCategory

logger = logging.getLogger("darnit_baseline.threat_model.ranking")


#: Base severity (1-10 scale) for each STRIDE category, with a bump for taint
#: findings. Keys are (category, has_taint_trace) tuples.
_BASE_SEVERITY: dict[tuple[StrideCategory, bool], int] = {
    (StrideCategory.TAMPERING, True): 9,
    (StrideCategory.TAMPERING, False): 6,
    (StrideCategory.ELEVATION_OF_PRIVILEGE, True): 9,
    (StrideCategory.ELEVATION_OF_PRIVILEGE, False): 7,
    (StrideCategory.INFORMATION_DISCLOSURE, True): 8,
    (StrideCategory.INFORMATION_DISCLOSURE, False): 5,
    (StrideCategory.SPOOFING, True): 7,
    (StrideCategory.SPOOFING, False): 5,
    (StrideCategory.DENIAL_OF_SERVICE, True): 5,
    (StrideCategory.DENIAL_OF_SERVICE, False): 3,
    (StrideCategory.REPUDIATION, True): 4,
    (StrideCategory.REPUDIATION, False): 2,
}


def severity_for(category: StrideCategory, has_taint_trace: bool) -> int:
    """Return the base severity (1-10) for a finding."""
    return _BASE_SEVERITY.get((category, has_taint_trace), 3)


def confidence_for(source: FindingSource, query_intent: str = "generic") -> float:
    """Return the base confidence (0.0-1.0) for a finding source.

    ``query_intent`` is a short string from the calling query registry
    identifying what kind of match produced the finding:

    - ``"constructor_call"`` — explicit data-store constructors corroborated
      by imports or dependency manifest (highest structural confidence)
    - ``"import_resolved"`` — symbol imported from a known module
    - ``"decorator"`` — decorated function with a known framework idiom
    - ``"bare_call"`` — plain call matched by name without context
    - ``"dangerous_sink_no_taint"`` — subprocess / eval / exec call where we
      have NOT confirmed external input flows to the sink. Deliberately low
      confidence so ranking deprioritizes these below entry points and data
      stores until Opengrep taint analysis can lift matching findings to
      ``OPENGREP_TAINT`` confidence (1.0).
    """
    if source == FindingSource.OPENGREP_TAINT:
        return 1.0
    if source == FindingSource.OPENGREP_PATTERN:
        return 0.9
    # Tree-sitter structural
    if query_intent in ("constructor_call", "import_resolved"):
        return 0.9
    if query_intent == "decorator":
        return 0.85
    if query_intent == "bare_call":
        return 0.6
    if query_intent == "dangerous_sink_no_taint":
        return 0.3
    return 0.75


def _rank_key(finding: CandidateFinding) -> tuple[float, int, str]:
    """Primary sort key: severity × confidence (descending).

    Ties are broken by raw severity (descending), then by query_id (ascending)
    for determinism.
    """
    return (-finding.severity * finding.confidence, -finding.severity, finding.query_id)


def rank_findings(findings: list[CandidateFinding]) -> list[CandidateFinding]:
    """Return a new list sorted by severity × confidence descending.

    Stable under determinism: the same input list always produces the same
    output order, regardless of original position.
    """
    return sorted(findings, key=_rank_key)


def apply_cap(
    findings: list[CandidateFinding],
    max_findings: int,
    diversity_threshold: float = 0.4,
) -> tuple[list[CandidateFinding], TrimmedOverflow]:
    """Rank all findings and compute a display-level overflow hint.

    **No findings are dropped.**  All findings are returned in ranked order.
    The ``max_findings`` parameter controls only the *display threshold* used
    by the SUMMARY renderer's top-risks table.  The :class:`TrimmedOverflow`
    describes findings that fall below this threshold so the summary can
    render an "and N more" line.

    Diversity rebalancing still applies to ordering: within the top
    ``max_findings``, underrepresented STRIDE categories may be promoted
    over dominant ones.

    Returns ``(all_findings_sorted, overflow_hint)``.
    """
    ranked = rank_findings(findings)

    if max_findings <= 0 or len(ranked) <= max_findings:
        return ranked, TrimmedOverflow(by_category={}, total=0)

    # Use diversity rebalancing to determine the "top N" display set,
    # but keep all findings in the returned list.
    top_display = ranked[:max_findings]
    leftover = ranked[max_findings:]
    top_display = _apply_diversity_rebalance(top_display, leftover, diversity_threshold)

    # Build overflow hint from findings not in the top display set.
    top_ids = {id(f) for f in top_display}
    below_threshold = [f for f in ranked if id(f) not in top_ids]

    by_category: dict[StrideCategory, int] = {}
    for f in below_threshold:
        by_category[f.category] = by_category.get(f.category, 0) + 1
    overflow = TrimmedOverflow(by_category=by_category, total=len(below_threshold))

    # Re-order: top display set first (preserving diversity order),
    # then remaining findings in their original rank order.
    reordered = list(top_display) + below_threshold

    logger.debug(
        "ranking.apply_cap: top_display %d of %d, overflow %d (by category: %s)",
        len(top_display),
        len(ranked),
        len(below_threshold),
        by_category,
    )
    return reordered, overflow


def _apply_diversity_rebalance(
    emitted: list[CandidateFinding],
    leftover: list[CandidateFinding],
    threshold: float,
) -> list[CandidateFinding]:
    """Swap dominated-category findings out in favor of underrepresented ones."""
    if not emitted or not leftover:
        return emitted

    counts = Counter(f.category for f in emitted)
    n = len(emitted)
    dominant, dominant_count = counts.most_common(1)[0]
    if dominant_count / n <= threshold:
        return emitted  # already diverse enough

    # Find the lowest-ranked dominant-category findings we can demote, and the
    # highest-ranked non-dominant findings we can promote from leftover.
    # We work copies to avoid mutating inputs.
    emitted = list(emitted)
    leftover = list(leftover)

    while counts[dominant] / len(emitted) > threshold:
        # Next candidate to promote: highest-ranked finding in leftover whose
        # category is NOT dominant.
        promote_idx = next(
            (i for i, f in enumerate(leftover) if f.category != dominant),
            None,
        )
        if promote_idx is None:
            break  # nothing we can swap in

        # Demote target: lowest-ranked emitted finding in the dominant category.
        demote_idx = None
        for i in range(len(emitted) - 1, -1, -1):
            if emitted[i].category == dominant:
                demote_idx = i
                break
        if demote_idx is None:
            break  # no dominants left to demote (shouldn't happen)

        promoted = leftover.pop(promote_idx)
        demoted = emitted.pop(demote_idx)
        emitted.append(promoted)
        leftover.append(demoted)

        counts = Counter(f.category for f in emitted)
        new_dominant, _ = counts.most_common(1)[0]
        dominant = new_dominant

    # Re-sort emitted by rank so the final order is still rank-stable.
    emitted.sort(key=_rank_key)
    return emitted


def build_rank_key_for_tests(finding: CandidateFinding) -> tuple[float, int, str]:
    """Expose the internal sort key for tests that want to assert on ordering."""
    return _rank_key(finding)


__all__ = [
    "severity_for",
    "confidence_for",
    "rank_findings",
    "apply_cap",
    "build_rank_key_for_tests",
]
