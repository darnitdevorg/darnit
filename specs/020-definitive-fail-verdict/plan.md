# Implementation Plan: Preserve handler-conclusive FAIL through the CEL post-step

**Branch**: `020-definitive-fail-verdict` | **Date**: 2026-08-01 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/020-definitive-fail-verdict/spec.md`

## Summary

Change the sieve orchestrator's CEL post-step so a handler-conclusive FAIL is preserved when the CEL expression also evaluates falsy. Today `gh api /repos/.../branches/.../protection` returns exit 1 on 404 (exec handler -> FAIL), then the CEL expression `has(output.json.required_pull_request_reviews)` returns false against the `{"message": "Branch not protected"}` body, and the orchestrator demotes to INCONCLUSIVE, causing the pipeline to fall through to the manual handler and yield WARN. The fix keeps FAIL when both the handler and CEL agree there is no compliance.

Scope: single framework file (`packages/darnit/src/darnit/sieve/orchestrator.py`), roughly a 15-line diff to `_apply_cel_expr`. Twelve controls that combine `fail_exit_codes` + `expr` benefit automatically; the four named branch-protection controls (`OSPS-AC-03.01`, `OSPS-AC-03.02`, `OSPS-QA-03.01`, `OSPS-QA-07.01`) are the acceptance bar.

## Technical Context

**Language/Version**: Python 3.11/3.12 (unchanged).

**Primary Dependencies**: `cel-python` (already used for CEL evaluation). No new deps.

**Storage**: N/A. Pure code change with test coverage.

**Testing**: `pytest` with existing marks (`unit`, `integration`). Unit tests for the orchestrator transition table (8 cells). Integration tests for the four named controls using patched subprocess return values for `gh api`.

**Target Platform**: Cross-platform.

**Project Type**: Library + CLI + MCP server (workspace layout, unchanged).

**Performance Goals**: N/A - correctness fix.

**Constraints**: (a) must not regress any currently-passing control; (b) must preserve WARN semantics (unknown); (c) must respect Principle I (no cross-package imports); (d) any existing test that relied on the buggy H=FAIL + CEL=truthy -> PASS transition needs an assertion update.

**Scale/Scope**: ~15 lines of Python in `orchestrator.py`, ~200 lines of new/updated tests, no TOML changes, no docs changes required.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

- **I. Plugin Separation:** the change is confined to `packages/darnit/src/darnit/sieve/orchestrator.py` (framework). No implementation-package import introduced. PASS.
- **II. Conservative-by-Default:** this fix strengthens Principle II. Today a definitive negative is demoted to INCONCLUSIVE (then WARN); the fix restores FAIL. FR-008 explicitly guards that WARN semantics are preserved for genuinely-unknown cases. PASS.
- **III. TOML-First:** no control definitions change. Orchestrator engine code is not a control. PASS.
- **IV. Never Guess User Values:** N/A.
- **V. Sieve Pipeline Integrity:** the change restores this principle. The constitution states "the orchestrator stops at the first conclusive result." Today's CEL post-step demotes a handler-conclusive FAIL to INCONCLUSIVE, which violates that guarantee. The new behavior preserves it. PASS (and clarifies §V's application to the CEL post-step).

**All gates pass. No entries in Complexity Tracking.**

## Project Structure

### Documentation (this feature)

```text
specs/020-definitive-fail-verdict/
├── plan.md              # This file
├── spec.md              # Feature spec
├── research.md          # Phase 0 output (lifted from feature 019 R1/R2/R3/R5)
├── data-model.md        # Phase 1 output (no new entities; documents which types are touched)
├── contracts/
│   └── cel-post-step.md # Internal framework contract; lifted verbatim from feature 019
├── quickstart.md        # Phase 1 output (verification commands, US2-only)
└── tasks.md             # Phase 2 output (/speckit-tasks - NOT created here)
```

### Source Code (repository root)

```text
packages/darnit/
├── src/darnit/sieve/
│   └── orchestrator.py                          # Change target: _apply_cel_expr (lines 60-75)
└── (no other framework changes)

tests/
├── darnit/sieve/
│   └── test_orchestrator_cel.py                 # New: unit tests for the 8-cell transition table
└── darnit_baseline/
    └── controls/
        └── test_branch_protection.py            # New: integration tests for the 4 named controls
```

**Structure Decision:** identical workspace layout to feature 019. Framework change lives in `packages/darnit/`. Integration tests exercise the four named branch-protection controls via `packages/darnit-baseline/` but do not modify any TOML there. No new packages.

## Phase 0: Outline & Research

Consolidated in [`research.md`](research.md). Lifted from feature 019's research with pointers back to the original for context. Key items:

1. **Current CEL post-step semantics** and root cause (feature 019 R1).
2. **exec handler exit-code classification** (feature 019 R2).
3. **`gh api` 404 response shape** (feature 019 R3).
4. **Regression risk audit for the 12 affected controls** (feature 019 R5).
5. **New: testing the nondeterministic path** — this feature explicitly requires verification via the audit skills (`/darnit-audit` + MCP client), not just pytest. Lesson from feature 019 US1.

No open unknowns. No `[NEEDS CLARIFICATION]` markers.

## Phase 1: Design & Contracts

### Data model

No new entities. See [`data-model.md`](data-model.md) for which existing framework types this feature touches (`PassOutcome`, `HandlerResult`, the CEL post-step function).

### Contracts

Single internal contract modified: the CEL post-step transition table. Documented in [`contracts/cel-post-step.md`](contracts/cel-post-step.md) (lifted verbatim from feature 019 with adjusted references). No external contract changes (public API, CLI, MCP tool shapes unchanged).

### Agent context update

Update the plan reference between the `<!-- SPECKIT START -->` and `<!-- SPECKIT END -->` markers in `CLAUDE.md` to point at `specs/020-definitive-fail-verdict/plan.md`.

**Output**: [`data-model.md`](data-model.md), [`contracts/cel-post-step.md`](contracts/cel-post-step.md), [`quickstart.md`](quickstart.md), updated `CLAUDE.md`.

## Complexity Tracking

*No entries - Constitution Check has no violations.*
