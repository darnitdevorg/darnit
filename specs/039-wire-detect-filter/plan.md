# Implementation Plan: Wire detect_filter Into Context Detection

**Branch**: `039-wire-detect-filter` | **Date**: 2026-09-23 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/039-wire-detect-filter/spec.md`

## Summary

`detect_filter` is declared on `security_contact` in `openssf-baseline.toml:303` and evaluated nowhere. The expression exists to stop a template `SECURITY.md` containing `security@example.com` from being taken as the project's real security contact, which feeds three OSPS-VM controls.

The work is small and in one package:

- declare the field on `ContextDefinitionConfig`
- evaluate it against detected values, on both detection routes, before the auto-accept threshold
- re-evaluate on read so repositories audited before the fix are covered
- report failures instead of failing silently, which is the defect being fixed
- add a CI check that catches the next unwired key

## Technical Context

**Language/Version**: Python 3.11/3.12 (workspace targets)

**Primary Dependencies**: none added. `cel-python` is already a core runtime dependency and `darnit/sieve/cel_evaluator.py` already wraps it with a timeout and sandbox.

**Storage**: filesystem only. `.project/` is read but never written by this feature (FR-015).

**Testing**: pytest. New tests in `tests/darnit/context/` and `tests/darnit/config/`; the CI check extends `scripts/validate_sync.py`.

**Target Platform**: local context collection during an audit.

**Project Type**: Python monorepo; this feature touches `packages/darnit/` only.

**Performance Goals**: none new. One CEL evaluation per detected value, with the evaluator's existing 1s timeout. Element-wise filtering on a list multiplies that by the element count, which is small for the keys in question.

**Constraints**:
- FR-005: filtering must happen before the auto-accept threshold is consulted, or a rejected value is still written.
- FR-004: both detection routes must be covered, or the guard has a hole in the path that produced the original complaint.
- FR-015: `.project/` must not be rewritten.
- FR-009/SC-007: keys with no filter must behave identically.

**Scale/Scope**: one shipped filter on one key today. Roughly 3 source files and 3 test files.

## Constitution Check

*GATE: evaluated before Phase 0 and re-evaluated after Phase 1.*

### I. Plugin Separation -- PASS

Entirely within `packages/darnit/`. The filter is declared in plugin TOML and evaluated by the framework, which is the existing direction of that relationship. No framework import of an implementation.

### II. Conservative-by-Default -- PASS, and it is the point

An unevaluable filter discards the value (FR-006). Research R2 found the failure mode is worse than the spec assumed: a list bound whole does not error, it returns true and passes everything. Both the old behaviour and the naive fix fail open; this feature closes both.

### IV. Never Guess User Values -- PASS, and this is the principle at stake

`security_contact` carries `auto_detect = true`, so it is not a user-judgment key and confidence-based auto-acceptance legitimately applies (`context_storage.py:556`, threshold 0.8). The constitution permits concluding it without a person. `detect_filter` is the mechanism that decides which detected values are eligible for that conclusion, and it is not running.

FR-015 is the other half: a stored value may carry a human confirmation, and "human confirmation is the only transition that makes a value usable" cuts both ways. The framework re-evaluates on read and reports, but does not silently revoke what a person put there.

### V. Sieve Pipeline Integrity -- not engaged

Context detection is a separate pipeline from the control sieve. No pass semantics, handler outcomes or orchestrator behaviour change.

### Development Workflow

No framework behaviour documented in `docs/architecture/framework-design.md` changes. `validate_sync.py` gains a check (FR-010) and must pass.

### Gate result

No violations. One judgment call recorded below.

## Project Structure

### Documentation (this feature)

```text
specs/039-wire-detect-filter/
|-- plan.md                      # This file
|-- spec.md
|-- research.md                  # Phase 0
|-- data-model.md                # Phase 1
|-- quickstart.md                # Phase 1
|-- contracts/
|   `-- detect-filter.md         # Evaluation contract
|-- checklists/requirements.md
`-- tasks.md                     # /speckit-tasks output, not created here
```

### Source Code (repository root)

```text
packages/darnit/src/darnit/
|-- config/
|   |-- framework_schema.py      # declare detect_filter on ContextDefinitionConfig
|   `-- context_storage.py       # apply filter on both detect routes; re-check on read
`-- context/
    `-- detect_filter.py         # NEW -- evaluation, element-wise handling, reporting

scripts/validate_sync.py         # FR-010: reject undeclared [context.*] keys

tests/darnit/
|-- context/test_detect_filter.py        # NEW -- evaluation table
|-- config/test_context_filtering.py     # NEW -- both routes, ordering, read path
`-- config/test_validate_context_keys.py # NEW -- the FR-010 check
```

**Structure Decision**: evaluation goes in a new `context/detect_filter.py` rather than inline in `context_storage.py`. The element-wise rule, the compile-versus-runtime error split, and the reporting requirements together are more than a helper, and `context_storage.py` is already the file where the auto-accept ordering lives. The new module takes a value and an expression and returns a decision; it reads no files and touches no storage.

## Complexity Tracking

| Decision | Why | Alternative rejected because |
|---|---|---|
| Re-evaluate on read (FR-014) rather than only at detection | Without it the fix protects only repositories that have never been audited, and the ones holding a bad `security_contact` are exactly those audited while the guard was off. | Detection-time only leaves the existing population unprotected permanently, since nothing re-validates stored context (`get_context_value`, `context_storage.py:177`). |
| A CI check over shipped TOMLs rather than `extra="forbid"` on the schema | Catches the misspelled or unwired key in TOMLs darnit ships, which is where both known instances came from. | Tightening the schema changes how third-party plugin configs load. That is a behaviour change for plugin authors and deserves its own decision, not a side effect of this fix. |
