# Feature Specification: Type AuditState.audit_results

**Feature Branch**: `022-type-audit-results`

**Created**: 2026-08-04

**Status**: Draft

**Input**: User description: "type audit_results in AuditState (BLOCKING pre-Stage-1 architecture review item)"

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Typed audit results across the agent boundary (Priority: P1)

A framework contributor works on the audit -> collect_context -> remediate flow (today) or on the RFC-0001 Stage 1 harness driver (upcoming). They read from or write to `AuditState.audit_results`. Today, that field is `list[dict[str, Any]]`: keys are documented in a docstring, spelled correctly only by convention, and a typo like `r["idd"]` or `r["staus"]` compiles fine and blows up at runtime. Every future harness node that consumes check results inherits the same risk. This story replaces the untyped bag with a `CheckResult` TypedDict whose keys are known statically, so type-checkers and IDEs surface wrong-key access before it ships.

**Why this priority**: This is the second of two BLOCKING prereqs from the pre-Stage-1 architecture review. Stage 1 introduces a `HarnessState` that must carry check results through multiple driver steps; each step handling an untyped `list[dict[str, Any]]` multiplies the surface area for silent key drift. Fixing it now costs one small PR; fixing it after Stage 1 lands means retro-typing across every new harness node too. The change is a type-only refactor with no runtime behavior change, so it slots in before Stage 1 without blocking anything else.

**Independent Test**: Run a type checker (mypy or pyright, project-appropriate) across `packages/darnit/src/darnit/agent/` and `packages/darnit/src/darnit/cli.py`. Zero errors related to `audit_results` access. Introduce a deliberate typo (`r["idd"]`) in a temporary local edit; the type checker MUST flag it. Delete the edit; type check remains clean. Runtime: `uv run pytest tests/darnit/agent/` -- all existing tests pass with no behavior change.

**Acceptance Scenarios**:

1. **Given** the current `AuditState` and its helpers (`failing_control_ids`, `warn_control_ids`), **When** a type checker inspects the file, **Then** all dict accesses are recognized as `CheckResult` keys (no `dict[str, Any]`-flavored warnings).
2. **Given** a downstream caller writes `result["status"]` on a `CheckResult`, **When** the checker runs, **Then** it accepts the access; when the caller writes `result["staus"]`, **Then** the checker flags it.
3. **Given** an audit run completes and populates `state.audit_results`, **When** existing tests execute (`tests/darnit/agent/`), **Then** every test passes with no behavior change vs `main`. Result serialization (JSON output, MCP responses, SARIF) MUST be byte-identical.
4. **Given** the `SieveResult.to_legacy_dict()` method (the sole producer of these dicts), **When** its return type is inspected, **Then** it is annotated as `CheckResult`, so mismatches between producer and consumer are caught by the checker.
5. **Given** the upcoming Stage 1 `HarnessState` that carries check results between driver steps, **When** a harness contributor references check results, **Then** they get IDE completions on the known keys and the checker refuses unknown keys -- no need to re-derive the schema from the audit pipeline.

---

### Edge Cases

- What happens when a control is excluded via `.baseline.toml` (produces the sparse `{"id", "status", "details", "level"}` dict at `packages/darnit/src/darnit/tools/audit.py:492`)? The `CheckResult` schema MUST allow the "extended" fields (`sieve_phase`, `confidence`, `evidence`, `pass_history`, etc.) to be optional so this sparse dict still validates. Structural typing (TypedDict with `NotRequired` on optional fields, available on Python 3.11+) covers this.
- What happens for the ad-hoc `when` key attached at `packages/darnit/src/darnit/tools/audit.py:530` after `to_legacy_dict()` returns? It MUST be a recognized optional key on `CheckResult`.
- What happens for future extensions (new optional keys added to `SieveResult.to_legacy_dict()`)? The schema is centralized in one TypedDict; adding a key updates one place. This is expected, not a regression.
- What happens for third-party MCP clients or JSON consumers that already parse the dict shape? Nothing. Structural typing does not change the on-the-wire format. This spec explicitly forbids changing dict keys.
- What happens if the codebase does not currently pass a type checker cleanly (unrelated errors)? The acceptance bar is "no NEW errors related to `audit_results`," not "clean type check across the whole project." Pre-existing type errors are out of scope.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: A `CheckResult` type MUST be introduced in a framework-level module (natural home: `packages/darnit/src/darnit/sieve/models.py` alongside `SieveResult`, or a new module such as `packages/darnit/src/darnit/agent/types.py`). It MUST use structural typing (`TypedDict`) so existing dicts satisfy it with no conversion.
- **FR-002**: The `CheckResult` type MUST declare, at minimum, the required keys currently guaranteed by `SieveResult.to_legacy_dict()` (`id`, `status`, `details`, `level`) and the optional keys attached elsewhere (`sieve_phase`, `confidence`, `verification_steps`, `evidence`, `resolving_pass_index`, `resolving_pass_handler`, `pass_history`, `when`).
- **FR-003**: `AuditState.audit_results` MUST be annotated as `list[CheckResult]` instead of `list[dict[str, Any]]`. `AuditState.remediation_results` MAY stay as `list[dict[str, Any]]` -- it is out of scope for this feature. A follow-up feature can type it later.
- **FR-004**: The `AuditState` helper methods (`failing_control_ids`, `warn_control_ids`) MUST use the typed access. Their return types stay `list[str]` (unchanged).
- **FR-005**: `SieveResult.to_legacy_dict()` MUST be annotated as returning `CheckResult` (or a supertype from which `CheckResult` is a strict subset, matching the actual returned shape).
- **FR-006**: A type checker (project's chosen tool: mypy, pyright, or ty) run over the touched files MUST produce zero NEW errors related to `audit_results` access.
- **FR-007**: The change MUST be runtime-invariant. TypedDict is structural typing only; existing dicts flow through unchanged, serialization is byte-identical, existing tests pass unmodified.
- **FR-008**: If the project's chosen type checker is not currently wired into CI for this file set, this feature MAY leave that unchanged. A separate follow-up can add CI enforcement; manual verification via a documented command is sufficient here.

### Key Entities

- **`CheckResult`** (NEW, framework-level TypedDict): The typed schema for one entry in `AuditState.audit_results`. Documents the exact keys produced by `SieveResult.to_legacy_dict()` plus the ad-hoc extensions attached downstream.
- **`AuditState.audit_results`** (existing, framework, `packages/darnit/src/darnit/agent/state.py:61`): The field whose annotation changes from `list[dict[str, Any]]` to `list[CheckResult]`. No runtime shape change.
- **`SieveResult.to_legacy_dict`** (existing, framework, `packages/darnit/src/darnit/sieve/models.py:111`): The sole producer of `CheckResult` dicts. Its return annotation changes to `CheckResult`.
- **`AuditState.failing_control_ids` / `warn_control_ids`** (existing, framework, `packages/darnit/src/darnit/agent/state.py:84-90`): Consumers whose dict access becomes typed via the parent field annotation.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A type checker run over the five files touched or transitively verified by this feature -- `packages/darnit/src/darnit/agent/state.py`, `packages/darnit/src/darnit/agent/graph.py`, `packages/darnit/src/darnit/sieve/models.py`, `packages/darnit/src/darnit/tools/audit.py`, and `packages/darnit/src/darnit/cli.py` -- reports zero errors related to `audit_results` access. Command used and expected output MUST be documented in `quickstart.md`.
- **SC-002**: A deliberate typo introduced into one of the helper methods (e.g., changing `r["id"]` to `r["idd"]`) is flagged by the type checker. This is the "the fix does something" acceptance -- if no failure results, the annotation is not being enforced.
- **SC-003**: `uv run pytest tests/ --ignore=tests/integration/ -m "not slow" -q` reports the same pass/fail counts as `main` (2276 passing after feature 021 landed). No test needs modification for this feature; if any test breaks, the change is not type-only.
- **SC-004**: RFC-0001 Stage 1 harness contributors (starting in the next feature after this) can annotate `HarnessState`'s check-results field as `list[CheckResult]` without introducing a new type or re-deriving the schema.

## Assumptions

- Constitutional reference: this fix reinforces Principle V (Sieve Pipeline Integrity) by making the wire between the sieve orchestrator's output (`SieveResult.to_legacy_dict()`) and the agent's state contract typed. It does not touch Principles I-IV.
- The project has not standardized on one type checker across all packages. Whichever tool is easiest to invoke locally (mypy in the dev dependencies, or `pyright`/`ty` if that becomes the choice) is acceptable for verifying SC-001. The spec does NOT mandate wiring the tool into CI as part of this feature.
- `TypedDict` from `typing` (Python 3.11+ has `NotRequired` in stdlib) is the intended mechanism. Alternative: `dataclass` or `pydantic.BaseModel`. Both require converting `dict` -> model -> `dict` at boundaries (producer AND every consumer, including JSON serialization), which expands the diff far beyond a type-only change and risks runtime regressions. TypedDict is the right primitive here.
- The `remediation_results` field of `AuditState` (`list[dict[str, Any]]` at `packages/darnit/src/darnit/agent/state.py:75`) is deliberately out of scope. A parallel `RemediationResult` TypedDict is a natural follow-up but is not part of this feature's acceptance bar. Keeping scope narrow reduces the diff and avoids coupling this fix to the remediation pipeline's independent decisions.
- The audit result dict schema is stable enough that codifying it as a TypedDict does not lock the framework into a bad contract. Recent evidence: features 019 and 020 modified sieve orchestration semantics without changing the `to_legacy_dict()` shape. If the shape ever does change (e.g., adding a new required key), updating the TypedDict is a one-line change and the checker surfaces every affected consumer for free -- an improvement over today, not a regression.
- The `when` key attached ad-hoc at `packages/darnit/src/darnit/tools/audit.py:530` (outside `to_legacy_dict`) is a smell; ideally the producer owns its full schema. Correcting that smell is a nice-to-have but NOT required for feature 022; the TypedDict simply lists `when` as an optional key so both sites remain valid.
