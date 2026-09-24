# Specification Quality Checklist: Wire detect_filter Into Context Detection

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-22
**Feature**: [spec.md](../spec.md)

## Content Quality

- [X] No implementation details -- `detect_filter` and `security_contact` are TOML vocabulary the framework author writes, not stack choices
- [X] Focused on user value -- three stories: the placeholder is rejected, a broken filter is visible, a typo is caught
- [X] Written for stakeholders who understand the context/compliance domain
- [X] All mandatory sections completed

## Requirement Completeness

- [X] No [NEEDS CLARIFICATION] markers remain -- both resolved during /speckit-specify
- [X] Requirements are testable and unambiguous
- [X] Success criteria are measurable
- [X] Success criteria are technology-agnostic at the operator level
- [X] All acceptance scenarios are defined
- [X] Edge cases are identified -- 5, including the two-detection-route hole and the auto-accept ordering; list-valued keys resolved in /speckit-clarify
- [X] Scope is clearly bounded -- 4 non-goals
- [X] Dependencies and assumptions identified

## Feature Readiness

- [X] All functional requirements have clear acceptance criteria -- FR-001..015 map to SC-001..009
- [X] User scenarios cover primary flows
- [X] Feature meets measurable outcomes defined in Success Criteria
- [X] No implementation details leak into specification

## Notes

**16/16 passing.**

**FR-006: an unevaluable filter discards the value.** Failing closed, because the defect being fixed is a guard that failed open. Halting collection was rejected -- a framework author's typo would become an outage for users who cannot fix it.

**FR-010: a CI check over shipped TOMLs, not `extra="forbid"` on the schema.** Tightening the schema would change how third-party plugin configs load, which deserves its own decision rather than arriving as a side effect.

Verified against the code before writing, and two of the findings change the issues as filed:

- **#165 records impact as "Low -- the context collection step still asks the user to confirm."** It does not always ask. `context_storage.py:556` auto-accepts any detected value at or above `auto_accept_threshold` (0.8, matching `auto_accept_confidence` in `openssf-baseline.toml:274`) and writes it to `.project/` as `AUTO_DETECTED` with no prompt. A detect-pipeline result carrying no explicit confidence is normalized to 0.8, landing exactly on the threshold.
- **#165 says the field is "silently ignored by Pydantic."** `ContextDefinitionConfig` sets `extra="allow"`, so the value is retained in `model_extra`. It is parsed and never read, which is why nothing errors. #150's description is the accurate one.

That `extra="allow"` is also why this defect class recurs: an undeclared key and a misspelled key are both accepted in silence and both do nothing. `value_if_fail` was the same shape and was found only by diagnosing a user complaint (PR #417). FR-010 is the recurrence guard and is the reason Story 3 exists.

Design notes for the plan phase:

- Two detection routes converge at `context_storage.py:548-553` -- the TOML `detect` pipeline and the hardcoded sieve fallback. FR-004 requires both to be filtered; filtering only the first would leave the guard with a hole in exactly the path that produced the original complaint.
- FR-005's ordering constraint is the one that carries the severity: filtering after the threshold check would still write the rejected value.
- The existing expression uses `value.contains(...)`, which assumes a string. Keys whose detection yields a list or boolean will fail at evaluation rather than compile time, which is what FR-006 has to decide about.

## Clarify session 2026-09-23

Two questions, both verified against the code first.

- **FR-012/FR-013 -- list-valued keys filter element-wise.** `maintainers` is `list_or_path` with `auto_detect = true`, so it is an eligible key whose detection yields a list, and the shipped expression shape (`value.contains(...)`) errors against one. Binding the whole list would mean one bad entry discards every good one; under FR-006 that error would empty the key silently.
- **FR-014/FR-015 -- stored values are re-checked on read, without rewriting `.project/`.** `get_context_value` (`context_storage.py:177`) returns whatever is stored with no validation, so a value auto-accepted before this fix persists forever, and the repositories most likely to hold one are those audited while the guard was off. Rewriting the file was rejected: a stored value may carry a human confirmation, which Principle IV does not let the framework silently revoke.
