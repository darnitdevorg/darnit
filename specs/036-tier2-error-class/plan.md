# Implementation Plan: Distinguishable Side-Effect Failures via `error_class`

**Branch**: `036-tier2-error-class` | **Date**: 2026-09-07 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/036-tier2-error-class/spec.md`

## Summary

Add a strict-`Literal` `error_class` field to the sieve result envelope so operators can distinguish "we couldn't verify (network / auth / timeout failed)" from "we verified and it concluded FAIL/WARN". Six v0 values: `network`, `auth`, `timeout`, `rate_limit`, `not_found`, `crashed`. Classified at four sites (exec handler, MCP handler, orchestrator crash-catch, context auto-detect), propagated to the `CheckResult` from the resolving pass only, surfaced in markdown / JSON / SARIF output, and carried additively in the in-toto attestation predicate. Environmental failures also move from DEBUG to WARN logging so the default log level surfaces a degraded audit.

Technical approach in five moves:

1. **New type module** `core/error_class.py` with `ErrorClass = Literal[...]` plus a runtime `_ERROR_CLASSES` frozenset, mirroring `core/authority.py`'s Literal+frozenset pairing. Separate module so `darnit-baseline` can import the type without pulling in the sieve registry (R-001). The frozenset is load-bearing, not decorative: `Literal` is erased at runtime, so FR-002a's rejection guarantee depends on it.
2. **Additive field on three objects**: `HandlerResult` (dataclass, `error_class: ErrorClass | None = None`), `SieveResult` (dataclass, same), `CheckResult` (TypedDict, `error_class: NotRequired[str]` next to `authority`). Same placement pattern feature 025 used for `authority` (R-002).
3. **Classification at four sites**: `exec_handler` (GitHub-only stderr patterns per clarify Q4, plus timeout + generic-network fallback), `mcp_handler` (8-way exception mapping per R-007), orchestrator's outer exception catch (`crashed`), context auto-detect git failures. Each also bumps its log line DEBUG -> WARN.
4. **Preservation through the CEL post-step**: `_apply_cel_expr` constructs new `HandlerResult` objects at four exit paths and currently drops fields not explicitly threaded (feature 026 hit this exact bug with `authority`). Thread `error_class` at every construction site (R-003).
5. **Surface in three formatters + predicate**: markdown conditional line, JSON in both full and summary shapes, SARIF `properties["errorClass"]`, predicate conditional-emit next to `authority` (R-005, R-006).

The feature is silent in the happy path -- an audit with zero environmental failures produces byte-for-byte identical output in every format (FR-014, SC-002).

## Technical Context

**Language/Version**: Python 3.11 / 3.12 (workspace targets)

**Primary Dependencies**: stdlib only (`typing.Literal`, `re` for stderr patterns -- `re` already imported in `builtin_handlers.py`). No new packages (FR-015, SC-007).

**Storage**: N/A. `error_class` is an in-memory result field that serializes into existing output surfaces (JSON / SARIF / predicate). No new persistence.

**Testing**: pytest. New test module for the classification + preservation guarantees; golden-file regression for SC-002's byte-for-byte happy-path invariance.

**Target Platform**: macOS + Linux. No OS-specific branching (stderr pattern matching is text-only).

**Project Type**: Library change spanning `packages/darnit/` (type, sieve, orchestrator, driver, markdown formatter) and `packages/darnit-baseline/` (JSON formatter, SARIF formatter, attestation predicate). Cross-package but strictly framework-defines / implementation-consumes -- Principle I intact.

**Performance Goals**: N/A. Classification is a handful of string `in` checks on a stderr buffer already in memory. Zero measurable cost.

**Constraints**:
- No new runtime dependency (FR-015).
- Strict `Literal` paired with a runtime `frozenset` guard (FR-002a). `Literal` alone is erased at runtime and enforces nothing; the frozenset in `HandlerResult.__post_init__` is what actually rejects unknown values. `core/authority.py` uses the same Literal+frozenset pairing but for a fail-safe rather than a rejection -- this feature diverges deliberately, because an unknown `error_class` has no safe default.
- Happy-path output byte-for-byte identical (FR-014, SC-002).
- `error_class = crashed` MUST be unrepresentable alongside `status = PASS` (spec edge case; enforce in code, not just docs).
- Additive only: no existing field renamed or removed.
- DEBUG->WARN bump scoped to exactly four sites (clarify Q3 / FR-008a).
- GitHub-only classification patterns for v0 (clarify Q4 / FR-004, FR-005, FR-005a).

**Scale/Scope**: 1 new module (~20 lines), 3 dataclass/TypedDict field additions, 4 classification sites, 4 CEL construction sites threaded, 3 formatters, 1 predicate. Estimated ~250 lines implementation, ~350 lines tests.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|---|---|---|
| I. Plugin Separation | PASS | `ErrorClass` type and all classification logic live in `packages/darnit/`. `darnit-baseline` imports the type and reads the field -- implementation-imports-framework, which Rule 2 explicitly permits. No framework->implementation import added. |
| II. Conservative-by-Default | **PASS -- this feature strengthens it** | The whole point is to stop conflating "unverified due to environment" with "verified and non-compliant". Both still gate the audit identically (WARN counts as FAIL for compliance math, unchanged), but the operator can now tell which is which. An attestation that carries a bare verdict when the underlying audit was a network failure is precisely the misleading claim Principle II forbids. |
| III. TOML-First Architecture | PASS | No control metadata moves into Python. The stderr-classification patterns are framework-internal heuristics, not control definitions (R-004 rationale). |
| IV. Never Guess User Values | N/A | `error_class` describes a mechanical failure cause, not a user-judgment value. No candidate/confirmation flow involved. |
| V. Sieve Pipeline Integrity | PASS | The four-phase cascade and "first conclusive result" semantics are unchanged. FR-009a's resolving-pass-only propagation explicitly matches that rule. `error_class` is metadata on a result, never an input to the phase-advance decision. |

**Initial gate: PASS.** No violations, no justifications needed. Re-check after Phase 1 design.

## Project Structure

### Documentation (this feature)

```text
specs/036-tier2-error-class/
|-- plan.md                     # this file
|-- spec.md                     # /speckit-specify + /speckit-clarify output
|-- research.md                 # Phase 0 output
|-- data-model.md               # Phase 1 output
|-- quickstart.md               # Phase 1 output
|-- contracts/
|   `-- error-class.md          # Phase 1 output
|-- checklists/
|   `-- requirements.md         # spec quality checklist
`-- tasks.md                    # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
packages/darnit/src/darnit/
|-- core/
|   `-- error_class.py              # NEW: ErrorClass Literal (mirrors authority.py)
|-- sieve/
|   |-- handler_registry.py         # HandlerResult gains error_class field
|   |-- models.py                   # SieveResult + CheckResult gain error_class
|   |-- builtin_handlers.py         # exec + mcp classification; pattern constants
|   `-- orchestrator.py             # _apply_cel_expr threading; crash-catch classify
|-- context/
|   `-- auto_detect.py              # git-failure classify + DEBUG->WARN
`-- tools/
    `-- audit.py                    # markdown formatter surfaces error_class

packages/darnit-baseline/src/darnit_baseline/
|-- tools.py                        # JSON formatter (full + summary shapes)
|-- formatters/
|   `-- sarif.py                    # SARIF properties["errorClass"]
`-- attestation/
    `-- predicate.py                # conditional-emit next to authority

tests/darnit/
|-- sieve/
|   |-- test_error_class_classification.py   # NEW: 4 classification sites
|   `-- test_error_class_cel_preservation.py  # NEW: SC-005, 4 CEL transitions
`-- test_error_class_happy_path.py            # NEW: SC-002 golden-file regression

tests/darnit_baseline/
`-- test_error_class_output_surfaces.py       # NEW: JSON/SARIF/predicate carry it
```

**Structure decision**: cross-package but one-directional. The framework defines the type and produces the field; the implementation consumes it in three output surfaces. This is the same topology feature 025 used for `authority`, which is the strongest available precedent that the shape is constitutionally sound.

## Complexity Tracking

No constitution violations to justify.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| n/a       | n/a        | n/a                                  |

## Phase 0: Outline & Research

Seven items, all resolved by source inspection. See [research.md](research.md).

1. **R-001** -- where `ErrorClass` lives and what shape (new `core/error_class.py`, mirroring `core/authority.py`'s Literal-plus-frozenset pairing; the frozenset is what enforces FR-002a at runtime since `Literal` is erased).
2. **R-002** -- `HandlerResult` / `SieveResult` / `CheckResult` extension points, following `authority`'s precedent.
3. **R-003** -- `_apply_cel_expr` field-dropping confirmed; four construction sites need threading. Feature 026 hit the identical bug with `authority`.
4. **R-004** -- GitHub stderr patterns as module constants in `builtin_handlers.py`.
5. **R-005** -- attestation predicate needs no version bump; additive within v1 per feature 025's precedent.
6. **R-006** -- three formatter sites, each already carrying analogous optional transparency fields.
7. **R-007** -- eight MCP exception types mapped (FR-006 names three; five documented extensions flagged for reviewer).

One item in R-007 slightly widens FR-006's letter (classifying five MCP exceptions the FR doesn't name) while honoring its spirit. Recorded explicitly so it's reviewable rather than silent.

## Phase 1: Design & Contracts

### Data model

See [data-model.md](data-model.md). Five entities:

* **`ErrorClass`** -- `Literal["network", "auth", "timeout", "rate_limit", "not_found", "crashed"]`.
* **`HandlerResult.error_class`** -- per-pass classification, set by the handler that failed.
* **`SieveResult.error_class`** -- per-control, populated from the resolving pass (FR-009a).
* **`CheckResult["error_class"]`** -- wire shape, `NotRequired[str]`.
* **GitHub stderr pattern sets** -- two tuples of substrings for rate-limit and auth classification.

### Contracts

See [contracts/error-class.md](contracts/error-class.md). Enumerates:

* The six-value enum and its expansion rule (code change + release).
* Classification decision table per site (exec / mcp / orchestrator / auto-detect).
* MCP exception -> `error_class` mapping (all eight types).
* Propagation rule: resolving pass only.
* CEL post-step preservation obligation across all four transitions.
* The `PASS` + `crashed` unrepresentable-shape constraint.
* Output-surface shapes: markdown line, JSON key (both shapes), SARIF `properties["errorClass"]`, predicate conditional-emit.
* Happy-path invariance guarantee.

### Quickstart

See [quickstart.md](quickstart.md). Three operator walkthroughs:

1. **Expired token** -- run an audit with an invalid `GH_TOKEN`; see `error_class = auth` in markdown and a WARN log line; contrast against a clean-environment run of the same repo.
2. **Rate limit** -- exhaust the GitHub API rate limit (or mock it); see `error_class = rate_limit` distinguish those controls from real failures.
3. **Machine consumption** -- parse the JSON output and branch on `error_class` to build a "environment problems vs repo problems" split for a CI summary.

### Agent context update

CLAUDE.md's `<!-- SPECKIT START -->` marker currently points at feature 035's plan. Update to this feature's plan at end of Phase 1.

## Constitution re-check (post-design)

| Principle | Status |
|---|---|
| I. Plugin Separation | PASS -- framework defines and produces; implementation consumes. Same topology as feature 025. |
| II. Conservative-by-Default | PASS, strengthened -- removes a class of misleading verdict. |
| III. TOML-First Architecture | PASS -- no control metadata moves to Python. |
| IV. Never Guess User Values | N/A |
| V. Sieve Pipeline Integrity | PASS -- cascade semantics unchanged; FR-009a matches "first conclusive result". |

**Final gate: PASS.** Ready for `/speckit-tasks`.
