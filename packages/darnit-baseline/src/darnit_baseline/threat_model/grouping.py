"""Group findings by tree-sitter query ID for multi-file threat model output."""

from __future__ import annotations

from collections import defaultdict
from typing import Any

from .discovery_models import CandidateFinding, FindingGroup
from .renderers.common import query_id_to_slug


def group_by_query_id(
    findings: list[CandidateFinding],
    query_registries: dict[str, Any] | None = None,
) -> list[FindingGroup]:
    """Group findings by ``source_query_id`` and return sorted groups.

    Each group becomes one per-class detail file in the multi-file output.

    Args:
        findings: Ranked list of findings (ordering within each group is
            preserved from this list).
        query_registries: Optional merged dict mapping query IDs to query
            objects that have a ``mitigation_hint`` attribute.  Used to
            populate the group-level mitigation narrative.

    Returns:
        List of :class:`FindingGroup` sorted by ``max_severity_score``
        descending.
    """
    if not findings:
        return []

    registries = query_registries or {}

    # Bucket findings by query_id, preserving input order within each bucket.
    buckets: dict[str, list[CandidateFinding]] = defaultdict(list)
    for f in findings:
        buckets[f.query_id].append(f)

    groups: list[FindingGroup] = []
    for qid, bucket in buckets.items():
        slug = query_id_to_slug(qid)

        # Pick class_name from the highest-severity finding's title.
        best = max(bucket, key=lambda f: f.severity * f.confidence)
        class_name = best.title

        # Pick STRIDE category from the highest-severity finding.
        stride_category = best.category

        # Look up mitigation_hint from the query registry if available.
        mitigation_hint = ""
        query_obj = registries.get(qid)
        if query_obj is not None and hasattr(query_obj, "mitigation_hint"):
            mitigation_hint = query_obj.mitigation_hint or ""

        max_score = max(f.severity * f.confidence for f in bucket)

        groups.append(
            FindingGroup(
                query_id=qid,
                slug=slug,
                stride_category=stride_category,
                class_name=class_name,
                mitigation_hint=mitigation_hint,
                findings=tuple(bucket),
                max_severity_score=max_score,
            )
        )

    # Sort by max severity score descending.
    groups.sort(key=lambda g: g.max_severity_score, reverse=True)
    return groups
