# Research: Threat Model Output Restructure

**Date**: 2026-04-13 | **Spec**: [spec.md](spec.md) | **Plan**: [plan.md](plan.md)

## R-001: Refactoring strategy for ts_generators.py

**Decision**: Extract into a `renderers/` sub-package. Keep `ts_generators.py` as a thin façade.

**Rationale**: The file is 969 lines with 9 `_render_*` helpers plus 3 top-level generators. The new multi-file output needs 4 distinct renderers (summary, group_file, data_flow, raw_json) that each compose different subsets of these helpers. Extracting into a sub-package keeps each renderer <200 lines, makes them independently testable, and avoids a single 1200+ line file. The façade preserves backward compat for 8 existing tests that call `generate_markdown_threat_model()`.

**Alternatives considered**:
- Keep everything in ts_generators.py and add new functions: rejected — file would exceed 1500 lines with mixed responsibilities.
- Move everything to a single new file: rejected — same monolith problem.

## R-002: Ranking cap behavior change

**Decision**: `apply_cap()` returns `(all_findings_sorted, overflow_hint)` where `overflow_hint` is used only by the summary renderer to decide when to show the "and N more classes" line. No findings are ever dropped from the pipeline.

**Rationale**: FR-005 requires no findings dropped from detail docs. The current `apply_cap()` (line 104 of `ranking.py`) trims to `max_findings` with diversity rebalancing. Changing it to return all findings preserves the scoring and sorting logic (still useful for ordering detail files and selecting representative snippets) while removing the truncation. The `TrimmedOverflow` dataclass is repurposed: instead of recording dropped findings, it records "findings below the SUMMARY display threshold."

**Alternatives considered**:
- Keep cap for summary, run a separate uncapped pipeline for detail files: rejected — duplicates work, complicates the pipeline.
- Remove cap entirely and always show all classes in summary: rejected — breaks SC-001 (~150 line target) for repos with 80+ classes.

## R-003: Sidecar file format

**Decision**: YAML (`.project/threatmodel/mitigations.yaml`)

**Rationale**: The project already uses YAML for `.project/project.yaml`, so reviewers are familiar with the format. YAML supports multiline strings (for notes), comments (for human annotation), and is widely hand-editable. PyYAML is already a project dependency. The sidecar location under `.project/` follows the existing convention for committed per-project configuration.

**Alternatives considered**:
- JSON: rejected — no comments, harder to hand-edit.
- TOML: considered — aligns with TOML-first principle, but TOML is used for framework configuration in this project, not for user-facing data files. The sidecar is closer to project metadata (like project.yaml) than to control definitions.

## R-004: Fingerprint algorithm

**Decision**: `sha256(query_id + "\n" + repo_relative_path + "\n" + whitespace_normalized_snippet)[:16]` — 16 hex chars (64 bits).

**Rationale**: 16 hex chars is sufficient for a per-repo sidecar with <10K findings (collision probability negligible at ~2^-32 for 10K items via birthday bound). Including query_id prevents collisions between different vulnerability classes that happen to appear at the same location. Including the file path (per clarification Q3) prevents decisions from silently reattaching after file moves. Whitespace normalization (strip leading whitespace per line, drop blank lines) survives code reformatting.

**Alternatives considered**:
- Full 64-char SHA256: rejected — 16 hex chars is sufficient and more readable in YAML.
- Include line number in fingerprint: rejected — line numbers shift on any edit above the finding, causing excessive staleness.
- Exclude file path: rejected — safety concern (clarification Q3 resolved this).

## R-005: Group slug generation

**Decision**: `query_id.replace(".", "-")` — e.g., `python.sink.dangerous_attr` becomes `python-sink-dangerous_attr.md`

**Rationale**: Query IDs are already unique strings, using dots as separators. Replacing dots with hyphens produces valid, readable filenames. No collision risk since query IDs are globally unique within the query registries.

**Alternatives considered**:
- Hash-based slugs: rejected — not human-readable.
- Category prefix (e.g., `tampering--python-sink-dangerous_attr`): rejected — redundant since each detail file already states its STRIDE category in the header.

## R-006: mitigation_hint field on query dataclasses

**Decision**: Add `mitigation_hint: str = ""` with a default value to all four query dataclasses (`PythonQuery`, `JsQuery`, `GoQuery`, `YamlQuery`). Populate per-query defaults inline.

**Rationale**: All four dataclasses are frozen. Adding a field with a default value is backward-compatible (existing positional construction still works if the new field is appended). The `intent` field already serves a similar role (categorizing the query's purpose), and `mitigation_hint` extends this with reviewer-facing guidance. Empty string default means queries without a hint still produce valid output (FR edge case: "no guidance available").

**Alternatives considered**:
- Separate lookup table mapping query_id → hint: rejected — scatters related data, harder to maintain when adding new queries.
- Store hints in TOML: considered — aligns with TOML-first, but these are query-level metadata, not control-level metadata. Queries are defined in Python, not TOML.

## R-007: Multi-file write strategy in handler

**Decision**: The handler uses `os.makedirs(exist_ok=True)` + `open()` for each output file, writing to `docs/threatmodel/` relative to `context.local_path` (repo root). Same pattern as the current single-file write at `remediation.py:296`.

**Rationale**: `HandlerContext.local_path` provides the repo root. The current handler already creates parent directories and writes via `open()`. Extending to multiple files uses the same mechanism — no framework change needed. The handler's `config["path"]` value changes from `"THREAT_MODEL.md"` to `"docs/threatmodel/SUMMARY.md"`, and the handler derives the directory tree from that anchor path's parent.

**Alternatives considered**:
- Write to a temp dir first, then atomic move: considered — adds complexity, and the current handler doesn't do this either. If a write fails mid-way, the user re-runs; partial output is acceptable since the handler is idempotent.
- Return content as string and let the framework write: rejected — framework's HandlerResult doesn't support multi-file content.

## R-008: Backward-compat façade for generate_markdown_threat_model

**Decision**: Keep `generate_markdown_threat_model()` in `ts_generators.py` with its current signature. Internally, it calls the new renderers and concatenates: summary + each group file + data-flow. It does NOT include raw JSON (that's a separate format). Tests calling this function continue to pass without modification.

**Rationale**: 8 tests in `test_ts_generators.py` call this function and assert on section headings and markers. The façade preserves all 9 H2 sections (some now composed from renderer output). The `TestMarkdownRequiredSections` test (line 156) checks for specific H2 headings — the façade must reproduce them in the same order.

**Alternatives considered**:
- Deprecate and rewrite all tests: rejected — unnecessary churn; the function is a valid public API for callers that want a single-string output.
- Return only the summary: rejected — breaks callers that expect complete threat model content.
