# Implementation Plan: Conservative-by-default verdict correctness

**Branch**: `019-verdict-correctness` | **Date**: 2026-07-31 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/019-verdict-correctness/spec.md`

## Summary

Two independent fixes ship under this spec:

- **US1 (issue #342):** Reclassify `OSPS-LE-01.01` from Level 1 to Level 2 in `packages/darnit-baseline/openssf-baseline.toml` so per-level counts match OSPS Baseline v2025.10.10 (24 / 18 / 20).
- **US2 (issue #343):** Change the sieve orchestrator's CEL post-step so a handler-conclusive FAIL is preserved when the CEL expression also evaluates falsy. Today, `gh api /repos/.../branches/.../protection` returns exit 1 on 404 (exec handler → FAIL), and then the CEL expression `has(output.json.required_pull_request_reviews)` returns false against the `{"message": "Branch not protected"}` body, which the orchestrator maps to INCONCLUSIVE. The pipeline then falls through to the manual handler, yielding WARN. The fix keeps FAIL when both the handler and CEL agree there is no compliance.

A regression test asserts per-level counts equal the upstream OSPS Baseline for the pinned `spec_version` so future TOML edits cannot silently drift out of parity.

## Technical Context

**Language/Version**: Python 3.11/3.12 (workspace targets, unchanged).

**Primary Dependencies**: `cel-python` (for CEL evaluation in the sieve orchestrator), `PyYAML` (for the regression test that reads upstream OSPS Baseline YAML). No new runtime deps.

**Storage**: TOML only. `packages/darnit-baseline/openssf-baseline.toml` for LE-01.01 tag; upstream OSPS Baseline YAML fixtures vendored under `tests/darnit_baseline/fixtures/` (already used by the existing `upstream` mark).

**Testing**: `pytest` with existing marks (`unit`, `integration`, `upstream`). Unit tests for orchestrator CEL post-step change. Regression test for per-level counts runs under `unit` (uses vendored fixture, no network).

**Target Platform**: Cross-platform. No platform-specific changes.

**Project Type**: Library + CLI + MCP server (existing workspace layout, no new packages).

**Performance Goals**: N/A — correctness fix, not a perf change.

**Constraints**: (a) must not regress any currently-passing control; (b) must preserve WARN = "unknown" and FAIL = "known non-compliant" semantics; (c) framework code change must respect Principle I (plugin separation) — no import of implementation packages.

**Scale/Scope**: ~5 lines of TOML (US1), ~10 lines of orchestrator Python (US2), plus ~150 lines of tests (per-level regression + orchestrator unit tests + branch-protection integration tests).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Plugin Separation:** US1 is confined to `packages/darnit-baseline/openssf-baseline.toml` (implementation). US2 modifies `packages/darnit/src/darnit/sieve/orchestrator.py` (framework); no cross-package imports introduced. PASS.
- **II. Conservative-by-Default:** Both fixes strengthen this principle. US2 makes a definitive negative surface as FAIL rather than being downgraded to INCONCLUSIVE (then WARN). US1 removes a manufactured false-negative at Level 1 (over-scoping). Neither weakens WARN semantics. PASS.
- **III. TOML-First:** US1 is TOML-only. US2 modifies orchestrator engine code, not a control definition; control metadata remains in TOML. PASS.
- **IV. Never Guess User Values:** Not applicable — no user-judgment keys touched.
- **V. Sieve Pipeline Integrity:** The current CEL post-step in `orchestrator.py:71-75` demotes handler-conclusive FAIL to INCONCLUSIVE when CEL returns false. This is arguably an existing violation of §V ("orchestrator stops at first conclusive result" — the handler was conclusive, and the orchestrator's post-step undid it). The fix restores that guarantee. PASS (and clarifies §V's application to the CEL post-step).

**All gates pass. No entries in Complexity Tracking.**

## Project Structure

### Documentation (this feature)

```text
specs/019-verdict-correctness/
├── plan.md              # This file
├── research.md          # Phase 0 output (below)
├── data-model.md        # Phase 1 output (below)
├── quickstart.md        # Phase 1 output (below)
├── contracts/           # Phase 1 output (below)
└── tasks.md             # Phase 2 output (/speckit-tasks command - NOT created here)
```

### Source Code (repository root)

```text
packages/darnit/                          # Framework
├── src/darnit/sieve/
│   └── orchestrator.py                   # US2: CEL post-step logic (lines 60-75)
└── (no other framework changes)

packages/darnit-baseline/                 # Implementation
├── openssf-baseline.toml                 # US1: LE-01.01 level tag (line ~1543)
└── (no plugin Python changes)

tests/
├── darnit/sieve/
│   └── test_orchestrator_cel.py          # US2: unit tests for the CEL post-step change
└── darnit_baseline/
    ├── test_level_counts.py              # US1: regression test for 24/18/20 parity
    └── controls/
        └── test_branch_protection.py     # US2: integration test with fake 404 body
```

**Structure Decision:** Single-project workspace layout (existing). No new packages; edits are localized to `packages/darnit/src/darnit/sieve/orchestrator.py` (framework) and `packages/darnit-baseline/openssf-baseline.toml` (implementation). Tests split under the existing `tests/darnit/` and `tests/darnit_baseline/` trees to mirror the package they exercise.

## Phase 0: Outline & Research

Consolidated in [`research.md`](research.md). Highlights:

1. **Current CEL post-step semantics** — confirmed at `packages/darnit/src/darnit/sieve/orchestrator.py:60-75`. Handler FAIL + CEL false → INCONCLUSIVE (root cause of #343).
2. **exec handler exit-code classification** — confirmed at `packages/darnit/src/darnit/sieve/builtin_handlers.py:247-266`. `pass_exit_codes` → PASS, `fail_exit_codes` → FAIL, else INCONCLUSIVE.
3. **`gh api` behavior for unprotected branch** — HTTP 404 with body `{"message": "Branch not protected", "documentation_url": "..."}`. `gh api` exit code is 1. JSON body is parsed by exec handler's `output_format = "json"` path.
4. **Regression-test source of truth** — the OSPS Baseline YAML at `ossf/security-baseline` (`baseline/OSPS-*.yaml`) is the authoritative applicability map. Options for consuming it: fetch at test time (network dependency), vendor a fixture (needs update on spec bump), or reuse the existing `upstream`-marked drift-check fixture. Decision recorded in research.md.
5. **Regression risk for the orchestrator change** — audit all TOML passes that combine `fail_exit_codes` + `expr` before flipping the post-step semantics. Grep in research.md.
6. **Semantic content of LE-01.01 vs upstream** — noted but out of scope: darnit's `OSPS-LE-01.01` is implemented as a LICENSE-file check (`name = "HasLicense"`), while OSPS Baseline v2025.10.10 defines LE-01.01 as a DCO/CLA contribution track. This spec fixes only the level tag; the content misalignment is a separate issue to file after this ships.

## Phase 1: Design & Contracts

### Data model

The change touches four entities already defined in the framework; no new data model is introduced. See [`data-model.md`](data-model.md) for the mapping.

### Contracts

The framework's sieve engine has one internal contract that this spec modifies: the CEL post-step transformation. Documented in [`contracts/cel-post-step.md`](contracts/cel-post-step.md). No external (public API, CLI, MCP) contract changes.

### Agent context update

Update the plan reference between the `<!-- SPECKIT START -->` and `<!-- SPECKIT END -->` markers in `CLAUDE.md` to point to `specs/019-verdict-correctness/plan.md`.

**Output**: [`data-model.md`](data-model.md), [`contracts/cel-post-step.md`](contracts/cel-post-step.md), [`quickstart.md`](quickstart.md), updated `CLAUDE.md`.

## Complexity Tracking

*No entries — Constitution Check has no violations.*
