# Implementation Plan: Type AuditState.audit_results

**Branch**: `022-type-audit-results` | **Date**: 2026-08-04 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/022-type-audit-results/spec.md`

## Summary

Replace `AuditState.audit_results: list[dict[str, Any]]` with `list[CheckResult]`, where `CheckResult` is a new framework-level `TypedDict` describing the exact shape produced by `SieveResult.to_legacy_dict()` (required: `id`, `status`, `details`, `level`; optional via `NotRequired`: `sieve_phase`, `confidence`, `verification_steps`, `evidence`, `resolving_pass_index`, `resolving_pass_handler`, `pass_history`, `when`). Annotate `to_legacy_dict()` and the `AuditState` helper methods accordingly. TypedDict is structural typing only, so existing dicts flow through unchanged and there is no runtime behavior change. Verified locally with `mypy` (already configured in `pyproject.toml`); no new dependencies. This is the second BLOCKING pre-Stage-1 prereq from the architecture review; the first (feature 021) shipped in PR #362.

## Technical Context

**Language/Version**: Python 3.11/3.12 (workspace targets); `typing.NotRequired` is available in stdlib since 3.11 and is the right primitive here.

**Primary Dependencies**: stdlib only (`typing.TypedDict`, `typing.NotRequired`, `typing.Literal`). No new runtime deps. Dev-side: existing `mypy>=1.8.0` in the root dev dependency group (`pyproject.toml:99`) with an already-configured strict-ish mypy section (`[tool.mypy]` at line 111).

**Storage**: None. This is a type-annotation-only change.

**Testing**: pytest (existing). No new tests are required for the runtime behavior (there is no runtime behavior change). One negative-verification step is documented in `quickstart.md`: temporarily introduce a typo and confirm mypy flags it, then revert. Preexisting tests must pass unmodified.

**Target Platform**: Any Python 3.11+ runtime; mypy 1.8+ on developer machines and CI.

**Project Type**: Framework internals. All edits are inside `packages/darnit/src/darnit/` -- no implementation-package changes.

**Performance Goals**: N/A. Type annotations have zero runtime cost.

**Constraints**: Runtime-invariant. Zero change to dict keys, dict values, JSON serialization, MCP responses, SARIF output, or test fixtures. Diff scope: three files (`sieve/models.py`, `agent/state.py`, and a small annotation on the `tools/audit.py:492` and `:530` spots that construct/attach to these dicts).

**Scale/Scope**: Estimated diff: ~30 lines production. No test churn expected. Zero net new mypy errors on the touched files. Baseline (from `main` after feature 021, measured 2026-08-04): 19 preexisting mypy errors total across the five in-scope files -- 1 in `sieve/models.py`, 10 in `tools/audit.py`, 4 in `cli.py`, 4 in `agent/graph.py` -- none related to `audit_results`.

## Constitution Check

*Constitution v1.3.0.*

- **I. Plugin Separation.** PASS. Change is confined to the framework package (`packages/darnit/src/darnit/`). No implementation-package edits. No new imports across the boundary.
- **II. Conservative-by-Default.** PASS. Type-only change; no verdict semantics affected. If anything, this strengthens the pipeline by making key drift a static error rather than a runtime one.
- **III. TOML-First Architecture.** PASS. Not applicable; no control definitions touched.
- **IV. Never Guess User Values.** PASS. Not applicable.
- **V. Sieve Pipeline Integrity.** PASS. Strengthens the contract between the sieve orchestrator's output and the agent's consumption of it. The producer (`SieveResult.to_legacy_dict()`) and consumers (`AuditState.audit_results` and its helpers) now share one typed contract.

No violations. Complexity Tracking left empty.

## Project Structure

### Documentation (this feature)

```text
specs/022-type-audit-results/
+-- plan.md              # This file
+-- spec.md              # Feature specification
+-- research.md          # Phase 0 output
+-- data-model.md        # Phase 1 output (the CheckResult schema)
+-- quickstart.md        # Phase 1 output (mypy commands to verify)
+-- contracts/
|   \-- check-result.md  # The typed contract between sieve orchestrator and agent
+-- checklists/
|   \-- requirements.md
\-- tasks.md             # Phase 2 output (created by /speckit-tasks)
```

### Source Code (repository root)

```text
packages/darnit/src/darnit/
+-- sieve/
|   +-- models.py                # + CheckResult TypedDict; annotate to_legacy_dict() -> CheckResult
+-- agent/
|   \-- state.py                 # audit_results: list[CheckResult]; typed access in helpers
+-- tools/
    \-- audit.py                 # Small annotation touch on the excluded-control dict (line ~492)
                                 # and the `when` attach spot (line ~530).
```

**Structure Decision**: No new directories, no new modules. `CheckResult` lives in `packages/darnit/src/darnit/sieve/models.py` alongside `SieveResult` (its producer). Importing `CheckResult` from `sieve/models.py` into `agent/state.py` is a framework-internal edge and does not cross the plugin boundary (Rule 1).

## Complexity Tracking

*No constitution violations. Table left empty.*
