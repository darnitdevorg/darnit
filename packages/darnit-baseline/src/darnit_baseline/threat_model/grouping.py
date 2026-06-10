"""Group findings by tree-sitter query ID for multi-file threat model output."""

from __future__ import annotations

import os
from collections import defaultdict
from typing import Any

from .discovery_models import (
    CandidateFinding,
    CommandFamily,
    DiscoveredEntryPoint,
    EntryPointKind,
    FindingGroup,
)
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


# ---------------------------------------------------------------------------
# CLI command-family grouping (feature 014-cobra-threat-model)
# ---------------------------------------------------------------------------


#: Minimum distinct child directories an ancestor must have to count as
#: a viable command_root. Three or more siblings is a reasonable signal
#: that the directory is a "command organiser" rather than a leaf or a
#: single-command holder. Tuned against gittuf and similar Go CLIs.
_COMMAND_ROOT_MIN_CHILDREN = 3


def infer_command_root(file_paths: list[str]) -> str:
    """Infer the project's command_root from a list of cobra source files.

    Strategy: walk from the shallowest possible ancestor downward and
    return the **first depth** at which any single ancestor has at least
    :data:`_COMMAND_ROOT_MIN_CHILDREN` distinct cobra-bearing immediate
    children. That depth is the "family organiser" level — the directory
    whose immediate children look like top-level commands.

    For gittuf, this resolves at ``internal/cmd/`` (which has ~12 child
    directories each containing cobra files). For cosign it resolves at
    ``cmd/cosign/cli/``.  For small CLIs that don't have enough breadth
    to satisfy the threshold, returns ``""`` so the caller degrades to
    per-file family keys.

    Why not "deepest ancestor with most children"? That tends to land on
    a deeply-nested directory (e.g., ``internal/cmd/trust/`` for gittuf)
    where many leaf subcommand directories live as children — producing
    many one-finding families instead of a few well-grouped families.
    The shallowest-with-threshold rule mirrors how users mentally
    organise their command surface.

    Args:
        file_paths: Repository-relative paths of source files that
            participated in CLI discovery. May be empty.

    Returns:
        The inferred command_root with no trailing slash, or ``""``.
    """
    if not file_paths:
        return ""

    # Normalise to POSIX-style paths and split into directory chains.
    normalised = [p.replace("\\", "/") for p in file_paths]
    dirs_per_file: list[list[str]] = [
        [c for c in p.split("/") if c][:-1] for p in normalised
    ]
    if not dirs_per_file:
        return ""
    max_depth = max(len(d) for d in dirs_per_file)

    # Walk shallowest → deepest. At each depth, partition by the depth-th
    # ancestor and check whether any partition has ≥ threshold children.
    for depth in range(max_depth + 1):
        partitions: dict[tuple[str, ...], set[str]] = defaultdict(set)
        for dirs in dirs_per_file:
            if len(dirs) <= depth:
                continue
            ancestor = tuple(dirs[:depth])
            partitions[ancestor].add(dirs[depth])
        # Pick the best (most children) at this depth.
        if partitions:
            best_ancestor, best_children = max(
                partitions.items(), key=lambda kv: len(kv[1])
            )
            if len(best_children) >= _COMMAND_ROOT_MIN_CHILDREN:
                return "/".join(best_ancestor)

    # No depth satisfied the threshold — the project doesn't have enough
    # command-breadth to produce useful families. Caller degrades.
    return ""


def family_key_for_path(file_path: str, command_root: str) -> str:
    """Compute the family key (first subdirectory beneath ``command_root``).

    For a file at ``internal/cmd/cache/init/init.go`` with command_root
    ``internal/cmd``, returns ``"cache"``. For a file directly at the
    command_root (e.g., ``internal/cmd/root.go``), returns the file's
    parent directory name as a degenerate-but-valid fallback. For an
    empty command_root, returns the immediate parent directory name.
    """
    path = file_path.replace("\\", "/")
    rel = path
    if command_root:
        # Strip the command_root prefix (with trailing slash).
        prefix = command_root.rstrip("/") + "/"
        if path.startswith(prefix):
            rel = path[len(prefix):]
    parts = [p for p in rel.split("/") if p]
    if len(parts) >= 2:
        # File at <key>/.../<file>; the first component is the family.
        return parts[0]
    # File directly under command_root with no nested directory — use the
    # file's parent dir name (degenerate fallback for single-file CLIs).
    parent = os.path.basename(os.path.dirname(path)) if "/" in path else ""
    return parent or "root"


def group_by_cli_family(
    entry_points: list[DiscoveredEntryPoint],
) -> list[CommandFamily]:
    """Coalesce CLI command entry points into command families by filesystem layout.

    Filters the input to ``EntryPointKind.CLI_COMMAND`` entries, infers a
    ``command_root`` via :func:`infer_command_root`, partitions by the
    first subdirectory beneath the root, and produces one
    :class:`CommandFamily` per partition.

    Family display name defaults to the ``family_key`` — US2's T024 will
    enrich this with the parent literal's ``Use:`` text when available.
    Empty members lists are filtered out.

    Ordering: sorted by ``len(members)`` descending, then ``family_key``
    ascending. This makes the document deterministic for snapshot tests
    and surfaces the largest command surfaces first.
    """
    cli_entries = [
        ep for ep in entry_points if ep.kind == EntryPointKind.CLI_COMMAND
    ]
    if not cli_entries:
        return []

    file_paths = [ep.location.file for ep in cli_entries]
    command_root = infer_command_root(file_paths)

    buckets: dict[str, list[DiscoveredEntryPoint]] = defaultdict(list)
    for ep in cli_entries:
        key = family_key_for_path(ep.location.file, command_root)
        buckets[key].append(ep)

    families: list[CommandFamily] = []
    for family_key, members in buckets.items():
        # source_root = command_root + "/" + family_key (relative to repo root).
        # When command_root is empty (single-file CLI), the source_root is just
        # the family_key (typically the file's directory).
        if command_root:
            source_root = f"{command_root.rstrip('/')}/{family_key}/"
        else:
            source_root = f"{family_key}/" if family_key != "root" else ""

        # T024: pick the display_name from the parent cobra.Command literal
        # if one exists at the family's source_root level. A "parent" member
        # is one whose file lives directly in source_root (not in a deeper
        # subdirectory). Its name (the captured Use: text) is what shows up
        # in the project's --help output. If multiple parents qualify, take
        # the first by sort order for determinism; if none qualify, keep
        # family_key as the display name.
        display_name = _pick_display_name(members, source_root, family_key)

        family = CommandFamily(
            family_key=family_key,
            source_root=source_root,
            display_name=display_name,
            members=members,
            import_signatures=set(),  # populated by ranking layer if needed
            stride_categories=[],  # populated by assign_cli_stride_categories
            needs_reviewer_attention=True,
        )
        families.append(family)

    families.sort(key=lambda f: (-len(f.members), f.family_key))
    return families


def _pick_display_name(
    members: list[DiscoveredEntryPoint],
    source_root: str,
    family_key: str,
) -> str:
    """Return the family display name, preferring the parent literal's Use: text.

    A "parent" member is one whose file path's directory portion equals
    ``source_root`` (no trailing slash) — i.e., the file lives directly in
    the family's source root, not in a deeper subdirectory. The name on
    that DiscoveredEntryPoint is the Use: text captured by the cobra
    extractor.

    Falls back to ``family_key`` when:
    - The family has no member at the source-root level (only subcommands).
    - The selected parent's name starts with the "unnamed:" placeholder
      (FR-011 graceful skip).
    - ``source_root`` is empty (degenerate single-file project).
    """
    if not source_root:
        return family_key
    target_dir = source_root.rstrip("/")
    candidates = [
        m for m in members
        if os.path.dirname(m.location.file.replace("\\", "/")) == target_dir
    ]
    if not candidates:
        return family_key
    # Determinism: sort by file path, then by line.
    candidates.sort(key=lambda m: (m.location.file, m.location.line))
    name = candidates[0].name
    if name.startswith("(unnamed:"):
        return family_key
    return name
