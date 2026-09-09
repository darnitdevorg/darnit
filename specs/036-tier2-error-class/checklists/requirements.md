# Specification Quality Checklist: Distinguishable Side-Effect Failures via `error_class`

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-06
**Feature**: [spec.md](../spec.md)

## Content Quality

- [X] No implementation details (languages, frameworks, APIs) -- names like `HandlerResult`, `error_class`, `_apply_cel_expr` refer to existing project vocabulary the reader will encounter regardless of implementation choices, not new stack decisions
- [X] Focused on user value and business needs -- four prioritized user stories cover operator triage, log visibility, machine-consumer JSON/SARIF, attestation trust
- [X] Written for stakeholders who understand the darnit sieve model
- [X] All mandatory sections completed

## Requirement Completeness

- [X] No [NEEDS CLARIFICATION] markers remain
- [X] Requirements are testable and unambiguous -- FR-001..015 each map to a specific verifiable behavior
- [X] Success criteria are measurable
- [X] Success criteria are technology-agnostic at the operator level; some SCs necessarily name JSON/SARIF/markdown because those are the operator-facing output surfaces
- [X] All acceptance scenarios are defined -- 4 stories with Given/When/Then coverage
- [X] Edge cases are identified -- 6 enumerated
- [X] Scope is clearly bounded -- explicit Out of Scope section names 6 non-goals
- [X] Dependencies and assumptions identified

## Feature Readiness

- [X] All functional requirements have clear acceptance criteria -- FR-001..015 map to SC-001..007 and story-level scenarios
- [X] User scenarios cover primary flows (operator triage, log visibility, machine-consumer, attestation)
- [X] Feature meets measurable outcomes defined in Success Criteria
- [X] No implementation details leak into specification beyond required project vocabulary

## Notes

- Passed on first draft. Plan-phase design decisions, now all RESOLVED:
  - **Type representation**: strict `Literal` PLUS a runtime `frozenset` guard. Resolved by `/speckit-analyze` finding U1 -- the original FR-002 claimed "runtime rejects unknown values", which a bare `Literal` cannot deliver (it is erased at runtime). Split into FR-002 (the Literal) and FR-002a (the frozenset guard in `__post_init__`). See contracts section 6 rule 1.
  - **stderr-pattern location**: framework-level module constants in `sieve/builtin_handlers.py` (research.md R-004). Keeps classification reproducible across implementations; TOML-First governs control metadata, not framework-internal heuristics.
  - **Attestation predicate**: confirmed v1-schema-additive, no version bump (research.md R-005, matching feature 025's `authority` precedent).
- FR-009b (all-inconclusive WARN fallback) was added AFTER implementation, during the T032 manual walkthrough. The strict FR-009a reading left a fully degraded audit with no explanation at all -- a bare "manual verification required" with no hint the operator's token had expired -- which defeated US1. Documented retroactively rather than left as an undocumented code behavior.
- FR-009's "preserve error_class through CEL post-step" is the subtlest guarantee -- test-first via tasks.md T006, covering all four transitions (SC-005). This is a known bug class: feature 026 hit it with `authority`.
- SC-002's byte-for-byte invariance needs its baseline captured from unmodified `main` BEFORE implementation begins (tasks.md T001a). Resolved by `/speckit-analyze` finding C1 -- the original T027 would have generated goldens from post-feature code, making SC-002 unfalsifiable. Deliberately NOT using `syrupy`, whose `--snapshot-update` workflow can absorb real regressions.
