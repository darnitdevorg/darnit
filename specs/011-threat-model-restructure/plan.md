# Implementation Plan: Threat Model Output Restructure

**Branch**: `011-threat-model-restructure` | **Date**: 2026-04-13 | **Spec**: [spec.md](spec.md)
**Input**: Feature specification from `/specs/011-threat-model-restructure/spec.md`

## Summary

Replace the single-file threat model output (`THREAT_MODEL.md`) with a multi-file layout under `docs/threatmodel/` that groups findings by tree-sitter query ID, carries mitigation decisions across regenerations via a YAML sidecar at `.project/threatmodel/mitigations.yaml`, and extends control OSPS-SA-03.02 to discover the new canonical location.

The implementation decomposes `ts_generators.py` (969 lines) into a `renderers/` sub-package, adds new `grouping.py` and `sidecar.py` modules, modifies `ranking.py` to stop dropping findings, rewrites the handler in `remediation.py` to orchestrate multi-file output, and updates the TOML control's discovery paths. A backward-compat façade preserves the existing `generate_markdown_threat_model()` API for tests and programmatic callers.

## Technical Context

**Language/Version**: Python 3.11+ (project targets 3.11/3.12)
**Primary Dependencies**: tree-sitter, tree-sitter-language-pack, PyYAML (existing); hashlib (stdlib); no new external dependencies
**Storage**: Filesystem — Markdown, JSON, YAML files; no database
**Testing**: pytest with uv (`uv run pytest tests/darnit_baseline/threat_model/ -v`)
**Target Platform**: Python CLI / MCP server (Linux, macOS)
**Project Type**: Library (Python package: `darnit-baseline`)
**Performance Goals**: Regen for a repo with <500 files completes in <30s (no external API calls; FS scanning + rendering only). Not spec-mandated; deferred from spec as plan-level.
**Constraints**: Must respect plugin separation (no imports from darnit-baseline into darnit core); TOML-first for control metadata; conservative-by-default (never silently drop reviewer decisions)
**Scale/Scope**: Repos up to ~500 files (shallow mode for larger); up to ~10,000 findings pre-grouping; up to ~200 distinct query IDs (vulnerability classes)

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Rationale |
|-----------|--------|-----------|
| I. Plugin Separation | PASS | All changes are in `packages/darnit-baseline/`. No new imports into `packages/darnit/`. |
| II. Conservative-by-Default | PASS | Sidecar never auto-creates entries (FR-011). Stale entries never auto-deleted (FR-010). Adding SA-03.02 discovery paths can only increase pass rate, never decrease for existing repos. |
| III. TOML-First | PASS | SA-03.02 control changes are in the TOML file. New rendering modules don't introduce new controls. |
| IV. Never Guess User Values | PASS | Sidecar is human-edited only (FR-011). No heuristic "close enough" fingerprint matching. |
| V. Sieve Pipeline Integrity | PASS | SA-03.02 still uses `file_must_exist` as first pass. No pipeline semantics changed. |
| Architecture Constraints | PASS | Changes span Layer 2 (remediation handler) and Layer 3 (MCP tool). No Layer 1 sieve behavior altered except discovery path list. |

No violations. Complexity tracking table not needed.

## Project Structure

### Documentation (this feature)

```text
specs/011-threat-model-restructure/
├── plan.md              # This file
├── research.md          # Phase 0 output
├── data-model.md        # Phase 1 output
├── quickstart.md        # Phase 1 output
├── contracts/           # Phase 1 output
│   ├── output-format-contract.md
│   └── sidecar-format-contract.md
├── checklists/
│   └── requirements.md
└── tasks.md             # Phase 2 output (created by /speckit.tasks)
```

### Source Code (repository root)

```text
packages/darnit-baseline/
├── openssf-baseline.toml                        # SA-03.02 discovery paths update
└── src/darnit_baseline/
    ├── config/
    │   └── mappings.py                          # DEFAULT_FILE_LOCATIONS update
    ├── remediation/
    │   └── enhancer.py                          # LLM_ENHANCEABLE_FILES update
    ├── tools.py                                 # generate_threat_model MCP tool update
    └── threat_model/
        ├── __init__.py                          # New exports
        ├── discovery_models.py                  # New: FindingGroup, MitigationStatus, MitigationEntry, MitigationSidecar
        ├── grouping.py                          # NEW: group_by_query_id, slug helpers
        ├── sidecar.py                           # NEW: load/save/fingerprint/match/stale
        ├── ranking.py                           # Modify: remove drop behavior, return all findings + overflow hint
        ├── remediation.py                       # Rewrite handler: multi-file output orchestration
        ├── ts_generators.py                     # Refactor: thin façade delegating to renderers/
        ├── queries/
        │   ├── python.py                        # Add mitigation_hint field
        │   ├── javascript.py                    # Add mitigation_hint field
        │   ├── go.py                            # Add mitigation_hint field
        │   └── yaml.py                          # Add mitigation_hint field
        └── renderers/                           # NEW sub-package
            ├── __init__.py
            ├── common.py                        # Shared: severity_band, STRIDE constants, GeneratorOptions, slug helpers
            ├── summary.py                       # SUMMARY.md renderer
            ├── group_file.py                    # Per-class findings/<slug>.md renderer
            ├── data_flow.py                     # data-flow.md renderer (DFD + asset inventory)
            └── raw_json.py                      # raw-findings.json renderer

tests/darnit_baseline/threat_model/
├── test_ts_generators.py                        # Existing: update if façade changes signatures (should not)
├── test_remediation.py                          # Update: expect docs/threatmodel/SUMMARY.md
├── test_grouping.py                             # NEW
├── test_sidecar.py                              # NEW
└── renderers/
    ├── test_summary.py                          # NEW
    ├── test_group_file.py                       # NEW
    └── test_data_flow.py                        # NEW
```

**Structure Decision**: All changes are within the existing `packages/darnit-baseline/` package. The `renderers/` sub-package is the only new directory under `threat_model/`. The `tests/` mirror the source structure.

## Implementation Phases

### Phase A: Foundation (grouping, sidecar, common renderers)

New modules with no existing-code edits. Can be tested independently.

1. Create `renderers/common.py` — extract `GeneratorOptions`, `_severity_band` → `severity_band`, STRIDE constants, slug helpers from `ts_generators.py`
2. Create `grouping.py` — `group_by_query_id()`, `FindingGroup` dataclass, slug generation
3. Create `sidecar.py` — fingerprint, load/save, match, stale detection
4. Add `FindingGroup`, `MitigationStatus`, `MitigationEntry`, `MitigationSidecar` to `discovery_models.py`
5. Add `mitigation_hint: str = ""` to all 4 query dataclasses
6. Write unit tests for grouping and sidecar

### Phase B: Renderers (extract from ts_generators.py)

Decompose `ts_generators.py` into per-file renderers.

1. Create `renderers/summary.py` — extract `_render_executive_summary`, `_render_recommendations`, add top-risks table, unmitigated section, overflow line
2. Create `renderers/group_file.py` — reuse `_render_finding` for representative snippets, add instance table renderer
3. Create `renderers/data_flow.py` — extract `_render_dfd`, `_render_asset_inventory`, `_render_attack_chains`, `_detect_attack_chains`
4. Create `renderers/raw_json.py` — extend `generate_json_summary` with fingerprint + sidecar fields
5. Refactor `ts_generators.py` into thin façade: `generate_markdown_threat_model` composes new renderers
6. Write unit tests for each renderer

### Phase C: Pipeline integration

Wire everything into the handler and update external references.

1. Modify `ranking.py` — `apply_cap` returns all findings plus overflow hint (no drop)
2. Rewrite `generate_threat_model_handler` in `remediation.py` — multi-file output
3. Update `openssf-baseline.toml` SA-03.02 — discovery paths, handler path, location_hint, project_update
4. Update `mappings.py` — prepend new paths to `DEFAULT_FILE_LOCATIONS["security.threat_model"]`
5. Update `enhancer.py` — add `"docs/threatmodel/SUMMARY.md"` → `"threat_model"`
6. Update `tools.py` — `generate_threat_model` MCP tool uses new pipeline
7. Update existing tests in `test_remediation.py`
8. Write integration test: end-to-end multi-file generation

### Phase D: Validation

1. Dogfood: regenerate threat model on this repo
2. Verify SUMMARY.md ≤ 150 lines, all findings preserved, detail files correct
3. Run OSPS-SA-03.02 audit — passes with new location
4. Sidecar round-trip test
5. Run full pre-commit checklist (lint, tests, spec sync, generated docs)
