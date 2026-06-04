# Implementation Plan: Composition of compliance implementations

**Branch**: `013-plugin-composition` | **Date**: 2026-05-13 | **Spec**: [spec.md](./spec.md)
**Input**: Feature specification from `/specs/013-plugin-composition/spec.md`

## Summary

Add a TOML-only **composition** primitive so a darnit implementation can declare its control set as the union of (a) named slices of other installed implementations and (b) its own inline controls — without inheritance, forking, or any new Python API. Resolution runs once at framework-config load time inside `packages/darnit/`, produces a flat `FrameworkConfig.controls` dict identical in shape to today's non-composite frameworks, and stamps provenance metadata into each resolved control's `tags` so audit results trace back to the originating non-composite source. The existing audit, list-controls, and remediation pipelines see no schema change.

The two non-obvious behaviors locked in by the clarify session:

- **Strict-by-default conflicts.** Two `[[compose]]` blocks contributing the same control ID is a registration error unless the composite opts out with `allow_conflicts = true` (last-wins by file order) or resolves the conflict explicitly with an `[overrides."ID"]` block (always wins, even in strict mode).
- **Recursive composition is supported.** A `[[compose]]` block may name a composite source; the resolver fetches the source's fully-resolved control set, not its raw configuration. Cycle detection (FR-012) is the load-bearing guardrail; provenance traces to the ultimate non-composite source.

## Technical Context

**Language/Version**: Python 3.11/3.12 (workspace targets — same as the rest of darnit)
**Primary Dependencies**: `pydantic >= 2.0` (already used for `FrameworkConfig`); `packaging` (already a transitive dep via setuptools metadata) for PEP 440 `SpecifierSet`. `tomllib` from stdlib for TOML parsing. No new runtime dependencies.
**Storage**: Filesystem only. Composition is resolved in-memory at framework-config load time; no new persistent state.
**Testing**: `pytest` with fixtures generated under `tests/fixtures/composite/` (TOML-only minimal composites). Reuses the existing `darnit-hello` worked-example pattern for fixture shape.
**Target Platform**: Same as darnit itself — Linux/macOS developer laptops + CI runners. No platform-specific behavior.
**Project Type**: Single project (Python workspace of plugin packages). Composition is an additive primitive inside the `packages/darnit/` core framework; no new top-level package.
**Performance Goals**: SC-002 — resolve a composite with 50 upstream + 5 inline controls in **≤200 ms** on a developer laptop. Resolution is pure-Python dict merging over already-parsed `FrameworkConfig` objects; memoization of source loads handles the diamond case.
**Constraints**:
- Plugin Separation (Constitution I): the composition module lives in `packages/darnit/` and MUST NOT import any implementation package. It resolves sources via the existing `darnit.implementations` entry-point group; source slugs are mapped to TOML paths via `PluginRegistry`, then loaded through `_parse_framework_only(path)` (NOT `load_framework_by_name`, which would re-enter composition with a fresh cycle stack — see F-1 fix in research.md R-002).
- TOML-First (Constitution III): every composition primitive is TOML-expressible; no new Python protocol method.
- Conservative-by-Default (Constitution II): strict-by-default conflict resolution; missing source → registration error; cycle → registration error; orphan override → registration error.
**Scale/Scope**: Realistic composites land in the 20–80 control range. Worst case in scope: ~150 controls across 4–5 sources with one diamond merge. Cycle-detection stack is bounded by source-graph depth (typically ≤3 in practice; no artificial limit imposed beyond cycle detection).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|---|---|---|
| **I. Plugin Separation** | ✅ Pass | Composition module lives in `packages/darnit/src/darnit/core/composition.py`. Source resolution uses the existing `darnit.implementations` entry-point group (slug → path via `PluginRegistry`, then `_parse_framework_only(path)`) — no `import darnit_baseline` style coupling. The resolver does NOT call `load_framework_by_name` (which would re-enter composition with a fresh cycle stack — F-1 fix). New protocol fields (if any) guarded with `hasattr()`. |
| **II. Conservative-by-Default** | ✅ Pass | Strict conflicts are the default (FR-009). Missing source = registration error (FR-004). Cycle = registration error (FR-012). Orphan override / unknown-field override = registration error (FR-007, FR-008). Version mismatch = registration error (FR-013). No silent fallback path. |
| **III. TOML-First Architecture** | ✅ Pass | All composition primitives (`[[compose]]`, `[overrides."..."]`, `allow_conflicts`, `version_constraint`, inclusion/exclusion filters) are TOML schema additions. No Python override hook in v1. Resolved controls retain their original TOML-defined pass logic. |
| **IV. Never Guess User Values** | ✅ Pass | Composition does not infer membership, levels, or overrides from heuristics. The composite author types every selector by hand. INFO log on `allow_conflicts = true` is the audit-trail breadcrumb, not silent guesswork. |
| **V. Sieve Pipeline Integrity** | ✅ Pass | Composition is **upstream** of the sieve. After resolution, the framework's controls dict is shape-identical to a non-composite's. The sieve never sees a `[[compose]]` block. PASS/FAIL/INCONCLUSIVE semantics are unaffected. |

No principle violations. No `Complexity Tracking` entries required.

## Project Structure

### Documentation (this feature)

```text
specs/013-plugin-composition/
├── plan.md              # This file
├── research.md          # Phase 0 output (Phase 0 of /speckit.plan)
├── data-model.md        # Phase 1 output (Phase 1 of /speckit.plan)
├── quickstart.md        # Phase 1 output (Phase 1 of /speckit.plan)
├── contracts/           # Phase 1 output: TOML schema contract + resolver-API contract
│   ├── toml-schema.md
│   └── resolver-api.md
├── checklists/
│   └── requirements.md  # Already passing 16/16
└── tasks.md             # Phase 2 output (created later by /speckit.tasks)
```

### Source Code (repository root)

Composition is purely additive inside `packages/darnit/`. No new top-level package.

```text
packages/darnit/src/darnit/
├── config/
│   ├── framework_schema.py     # ⊕ ADD: ComposeBlock, OverrideBlock pydantic models;
│   │                           #         FrameworkConfig.compose, .overrides, .allow_conflicts fields
│   └── merger.py               # ⊕ REFACTOR: extract _parse_framework_only(path) helper that does
│                               #              parse + template-validate WITHOUT touching composition.
│                               #              load_framework_config() becomes a thin wrapper:
│                               #              _parse_framework_only → conditional resolve_composition.
│                               #              The resolver's source_loader routes through
│                               #              _parse_framework_only so cycle detection holds (F-1).
├── core/
│   ├── composition.py          # ⊕ NEW: resolve_composition(), cycle detection, conflict
│   │                           #         enforcement, override application, provenance stamping
│   ├── plugin.py               # (unchanged — ControlSpec.tags already carries provenance)
│   └── discovery.py            # (unchanged)
└── (rest of the tree untouched — sieve, audit, remediation see no schema change)

tests/darnit/
├── test_composition.py         # ⊕ NEW: unit tests for resolver (filters, overrides,
│                               #         conflicts, cycles, version pinning, provenance)
└── fixtures/
    └── composite/              # ⊕ NEW: minimal TOML fixtures, one per scenario
        ├── basic-include-all.toml
        ├── include-levels.toml
        ├── include-controls.toml
        ├── exclude-controls.toml
        ├── overrides-remediation.toml
        ├── strict-conflict-rejects.toml
        ├── allow-conflicts-last-wins.toml
        ├── override-resolves-conflict.toml
        ├── orphan-override-rejects.toml
        ├── unknown-field-override-rejects.toml
        ├── missing-source-rejects.toml
        ├── self-cycle-rejects.toml
        ├── two-cycle-rejects.toml
        ├── three-level-recursive-resolves.toml
        ├── version-pin-satisfied.toml
        └── version-pin-violated.toml
```

**Structure Decision**: Single project (Python workspace). All new code lands in `packages/darnit/src/darnit/{core,config}/`. No changes to implementation packages (`darnit-baseline`, `darnit-gittuf`, `darnit-hello`, `darnit-testchecks`) — they remain valid non-composite implementations. Composition is detected by the presence of a `[[compose]]` table-array in a framework's TOML at load time.

## Complexity Tracking

> No constitution violations; this section intentionally empty.
