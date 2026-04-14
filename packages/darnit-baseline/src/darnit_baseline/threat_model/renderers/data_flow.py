"""Renderer for the ``data-flow.md`` output file.

Produces the asset inventory (entry points, data stores, auth mechanisms),
the Mermaid data-flow diagram, and the attack-chain analysis.  All content
is extracted from the tree-sitter :class:`DiscoveryResult`.
"""

from __future__ import annotations

from typing import Any

from ..discovery_models import (
    DiscoveredDataStore,
    DiscoveredEntryPoint,
    DiscoveryResult,
)
from .common import GeneratorOptions

# ---------------------------------------------------------------------------
# Internal helpers
# ---------------------------------------------------------------------------


def _render_asset_inventory(result: DiscoveryResult) -> list[str]:
    md: list[str] = ["## Asset Inventory", ""]

    # Entry Points
    md.append("### Entry Points")
    md.append("")
    if result.entry_points:
        md.append("| Kind | Framework | Method | Path / Name | Location |")
        md.append("|------|-----------|--------|-------------|----------|")
        _dash = "\u2014"
        for ep in result.entry_points[:30]:
            path_or_name = ep.route_path or ep.name
            framework = ep.framework or _dash
            method = ep.http_method or _dash
            md.append(
                f"| {ep.kind.value} | {framework} | "
                f"{method} | `{path_or_name}` | "
                f"`{ep.location.file}:{ep.location.line}` |"
            )
        if len(result.entry_points) > 30:
            md.append(f"| \u2026 | | | | *{len(result.entry_points) - 30} more entries not shown* |")
    else:
        if result.file_scan_stats and result.file_scan_stats.in_scope_files > 50:
            md.append(
                f"\u26a0\ufe0f No entry points detected in a repository with "
                f"{result.file_scan_stats.in_scope_files} source files. "
                f"This likely indicates missing query coverage for the "
                f"project's framework or registration pattern. Review the "
                f"Limitations section."
            )
        else:
            md.append("No HTTP route handlers, CLI commands, or MCP tool endpoints detected.")
    md.append("")

    # Data Stores
    md.append("### Data Stores")
    md.append("")
    if result.data_stores:
        md.append("| Technology | Kind | Import Evidence | Location |")
        md.append("|------------|------|-----------------|----------|")
        for ds in result.data_stores[:30]:
            evidence = ds.import_evidence or ds.dependency_manifest_evidence or "\u2014"
            md.append(f"| {ds.technology} | {ds.kind.value} | `{evidence}` | `{ds.location.file}:{ds.location.line}` |")
    else:
        md.append("No data stores detected.")
    md.append("")

    # Authentication Mechanisms
    md.append("### Authentication Mechanisms")
    md.append("")
    auth_entries = [ep for ep in result.entry_points if ep.has_auth_decorator]
    if auth_entries:
        for ep in auth_entries:
            md.append(
                f"- `{ep.name}` at `{ep.location.file}:{ep.location.line}` ({ep.framework or 'unknown framework'})"
            )
    else:
        md.append(
            "\u26a0\ufe0f No authentication decorators identified by the structural "
            "pipeline. This does NOT mean the application is unauthenticated \u2014 "
            "it means no recognized decorator pattern was found. Review the "
            "entry points above manually."
        )
    md.append("")
    return md


def _render_dfd(result: DiscoveryResult, options: GeneratorOptions) -> list[str]:
    md: list[str] = ["## Data Flow Diagram", ""]

    stats = result.file_scan_stats
    if stats is not None and stats.shallow_mode:
        md.append(
            "Data flow diagram omitted in shallow analysis mode. "
            "Re-run with a smaller in-scope file set for the full DFD."
        )
        md.append("")
        return md

    if not result.entry_points and not result.data_stores:
        md.append("No assets discovered; data flow diagram empty.")
        md.append("")
        return md

    md.append("```mermaid")
    md.append("flowchart LR")
    md.append('    User(["External Actor"])')

    # Entry point nodes -- cap at max_dfd_nodes to keep the diagram readable
    ep_nodes: list[tuple[str, DiscoveredEntryPoint]] = []
    for idx, ep in enumerate(result.entry_points[: options.max_dfd_nodes]):
        node_id = f"EP{idx}"
        label = ep.route_path or ep.name or ep.kind.value
        # Strip characters Mermaid mis-parses
        label_clean = label.replace('"', "'").replace("`", "'")
        md.append(f'    {node_id}["{label_clean}"]')
        ep_nodes.append((node_id, ep))

    # Data store nodes
    ds_nodes: list[tuple[str, DiscoveredDataStore]] = []
    if result.data_stores:
        md.append('    subgraph DataLayer["Data Layer"]')
        for idx, ds in enumerate(result.data_stores[: options.max_dfd_nodes]):
            node_id = f"DS{idx}"
            md.append(f'        {node_id}[("{ds.technology}")]')
            ds_nodes.append((node_id, ds))
        md.append("    end")

    # Edges: User -> every entry point
    for node_id, _ep in ep_nodes:
        md.append(f"    User --> {node_id}")

    # Edges: each entry point -> data stores. Try locality heuristic first
    # (same file); if that produces zero edges, fall back to connecting
    # every entry point to every data store (the application uses all
    # stores; we just can't tell which routes access which from
    # structural analysis alone without cross-file call-graph resolution).
    locality_edges: list[str] = []
    for ep_id, ep in ep_nodes:
        ep_file = ep.location.file
        for ds_id, ds in ds_nodes:
            if ds.location.file == ep_file:
                locality_edges.append(f"    {ep_id} --> {ds_id}")

    if locality_edges:
        md.extend(locality_edges)
    elif ds_nodes:
        # No same-file locality; connect every EP to every DS as a
        # "this application uses these stores" approximation.
        for ep_id, _ep in ep_nodes:
            for ds_id, _ds in ds_nodes:
                md.append(f"    {ep_id} --> {ds_id}")

    md.append("```")
    md.append("")

    total_nodes = len(result.entry_points) + len(result.data_stores)
    if total_nodes > options.max_dfd_nodes:
        md.append(
            f"*DFD simplified: only the top {options.max_dfd_nodes} nodes are "
            f"shown (total asset count: {total_nodes}).*"
        )
        md.append("")
    return md


def _detect_attack_chains(
    result: DiscoveryResult,
) -> list[tuple[DiscoveredEntryPoint, str, str, str]]:
    """Detect multi-hop paths: entry point -> intermediary -> sink.

    Returns a list of (entry_point, intermediary_name, sink_function, sink_file)
    tuples. Only intra-file chains are detected (cross-file call-graph
    resolution is deferred).
    """
    if not result.call_graph or not result.entry_points or not result.findings:
        return []

    # Build per-file indices.
    # functions_by_file: file -> {func_name -> CallGraphNode}
    functions_by_file: dict[str, dict[str, Any]] = {}
    for node in result.call_graph:
        by_name = functions_by_file.setdefault(node.location.file, {})
        by_name[node.function_name] = node

    # findings_by_function: file -> {func_name} for functions containing a
    # dangerous finding (subprocess, eval, etc.)
    # We approximate "function contains finding" by checking if the finding's
    # file matches and its line is within the function's line range.
    finding_locations: dict[str, list[int]] = {}
    for f in result.findings:
        finding_locations.setdefault(f.primary_location.file, []).append(f.primary_location.line)

    funcs_with_sinks: dict[str, set[str]] = {}  # file -> {func_name}
    for file_path, by_name in functions_by_file.items():
        file_finding_lines = set(finding_locations.get(file_path, []))
        if not file_finding_lines:
            continue
        for func_name, node in by_name.items():
            # Check if any finding line falls within this function's span
            func_start = node.location.line
            # Approximate function end: next function start or +100 lines
            func_end = func_start + 100  # rough heuristic
            for _other_name, other_node in by_name.items():
                if other_node.location.line > func_start and other_node.location.line < func_end:
                    func_end = other_node.location.line
            if any(func_start <= ln < func_end for ln in file_finding_lines):
                funcs_with_sinks.setdefault(file_path, set()).add(func_name)

    # Now find chains: entry_point (in file) -> calls func -> func has sink
    chains: list[tuple[DiscoveredEntryPoint, str, str, str]] = []
    seen: set[tuple[str, str, str]] = set()  # dedup by (ep_name, intermediary, sink)

    for ep in result.entry_points:
        ep_file = ep.location.file
        if ep_file not in functions_by_file:
            continue
        file_funcs = functions_by_file[ep_file]
        file_sinks = funcs_with_sinks.get(ep_file, set())
        if not file_sinks:
            continue

        # Find the call graph node for the entry point function.
        # Match by closest function definition at or before the entry point line.
        ep_func = None
        best_dist = float("inf")
        for _fname, node in file_funcs.items():
            dist = ep.location.line - node.location.line
            if 0 <= dist < best_dist:
                best_dist = dist
                ep_func = node

        if ep_func is None:
            continue

        # Check if any function called by the entry point contains a sink
        for callee_name in ep_func.calls:
            if callee_name in file_sinks and callee_name != ep_func.function_name:
                key = (ep.name or "", callee_name, ep_file)
                if key not in seen:
                    seen.add(key)
                    chains.append((ep, callee_name, callee_name, ep_file))

    return chains[:10]  # cap to keep the report concise


def _render_attack_chains(result: DiscoveryResult) -> list[str]:
    md: list[str] = ["## Attack Chains", ""]
    stats = result.file_scan_stats
    if stats is not None and stats.shallow_mode:
        md.append(
            "Attack chain detection skipped in shallow analysis mode. "
            "Re-run with a smaller in-scope file set to compute chains."
        )
        md.append("")
        return md

    chains = _detect_attack_chains(result)
    if not chains:
        md.append("No compound attack paths identified.")
        md.append("")
        return md

    md.append(
        "The following multi-hop paths connect external entry points to "
        "dangerous sinks via intermediate functions. Each chain represents "
        "a potential exploitation path that should be reviewed holistically."
    )
    md.append("")

    for idx, (ep, intermediary, sink_func, sink_file) in enumerate(chains, 1):
        ep_label = ep.route_path or ep.name or ep.kind.value
        md.append(f"### Chain {idx}: {ep_label} \u2192 {intermediary} \u2192 sink")
        md.append("")
        md.append(f"1. **Entry point**: `{ep_label}` at `{ep.location.file}:{ep.location.line}`")
        md.append(f"2. **Intermediary**: `{intermediary}()` called from the entry point")
        md.append(f"3. **Sink**: `{sink_func}()` at `{sink_file}` contains a dangerous call")
        md.append("")

    return md


# ---------------------------------------------------------------------------
# Top-level entry point
# ---------------------------------------------------------------------------


def render_data_flow(result: DiscoveryResult, options: GeneratorOptions) -> str:
    """Render the ``data-flow.md`` output file.

    Produces:

    1. H1 "Data Flow Analysis"
    2. Asset Inventory (entry points, data stores, auth mechanisms)
    3. Data Flow Diagram (Mermaid flowchart)
    4. Attack Chains (multi-hop entry-point -> sink paths)
    """
    md: list[str] = ["# Data Flow Analysis", ""]
    md.extend(_render_asset_inventory(result))
    md.extend(_render_dfd(result, options))
    md.extend(_render_attack_chains(result))
    return "\n".join(md) + "\n"


__all__ = [
    "render_data_flow",
]
