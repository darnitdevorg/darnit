# Specification Quality Checklist: Interactive Question Resolvers

**Purpose**: Validate specification completeness and quality before proceeding to planning

**Created**: 2026-08-07

**Feature**: [spec.md](../spec.md)

## Content Quality

- [X] No implementation details (languages, frameworks, APIs)
- [X] Focused on user value and business needs
- [X] Written for non-technical stakeholders
- [X] All mandatory sections completed

## Requirement Completeness

- [X] No [NEEDS CLARIFICATION] markers remain
- [X] Requirements are testable and unambiguous
- [X] Success criteria are measurable
- [X] Success criteria are technology-agnostic (no implementation details)
- [X] All acceptance scenarios are defined
- [X] Edge cases are identified
- [X] Scope is clearly bounded
- [X] Dependencies and assumptions identified

## Feature Readiness

- [X] All functional requirements have clear acceptance criteria
- [X] User scenarios cover primary flows
- [X] Feature meets measurable outcomes defined in Success Criteria
- [X] No implementation details leak into specification

## Notes

- Spec is scoped tightly to the collection mechanism. It intentionally does NOT introduce automatic re-audit on interactively supplied answers (the "no re-audit after collect" MVP policy from feature 026 remains in effect); that is a separate follow-up.
- The load-bearing property is the extensibility of the `QuestionResolver` Protocol. SC-002 is the enforceable statement of that property (a third-party resolver can be added without editing `packages/darnit/src/darnit/harness/`).
- Constitution IV interaction: interactive answers carry `authority: "asserted"`. This is documented in FR-009 + SC-003 and echoed in the Assumptions block. Deliberate: a human answering at a terminal IS confirmation, but never dispositive; the audit remains conservative.

## Clarification Session Log

Five clarifications were recorded during the 2026-08-07 clarify session:

1. **Registration mechanism** -> Hybrid: entry points + direct injection (FR-014).
2. **Prompt output stream** -> `/dev/tty` for MVP; pluggable output channel as a resolver-internal seam so future variants can route to event streams / log sinks (FR-004, FR-004a; SC-005 updated).
3. **Progress display during interactive collect** -> Bookend lines only on stderr; position indicator inside the prompt payload; ordinary [N/M] audit lines suppressed for the interactive phase (FR-013a, FR-013b; SC-008).
4. **Programmatic empty-Answer semantics** -> Symmetric with interactive: empty/whitespace-only Answer collapses to skip; no supported way to assert an empty value (FR-006a; Answer entity updated).
5. **Resolution trail in the report** -> Full trail: per-question `resolution_trail` list with `answered`/`skipped`/`errored` outcomes for every resolver that was offered the question (FR-015a; ResolutionTrailEntry added to Key Entities; SC-009).

All five were HIGH or MEDIUM-HIGH impact. No question was deferred; no [NEEDS CLARIFICATION] markers were introduced or remain.

## /speckit-analyze findings applied

The 2026-08-08 analyze pass surfaced 11 findings (0 CRITICAL, 3 HIGH, 4 MEDIUM, 4 LOW). All 7 HIGH+MEDIUM findings were remediated in-line by editing spec.md, plan.md, data-model.md, tasks.md, and two contracts:

- **C1 (authority=asserted)**: `Answer.authority: Literal["asserted"] = "asserted"` enforces at construction time; `PendingFeedbackEntry.answer_authority: Literal["asserted"] | None` surfaces in the report; cross-field validator; test coverage added to T005, T014, T016.
- **C2 (per-resolver timeout)**: `HarnessRun.per_resolver_timeout_s: float | None` (default None). `asyncio.wait_for` wrapping in T009; timeout test in T014.
- **C3 (bookend count)**: explicit assertion added to T014.
- **M1 (empty-Answer skip)**: explicit unit test added to T005 and driver test in T014.
- **M2 (no values in logs)**: explicit test in T014 using distinctive-value substring assertion.
- **M3 (SC-006 reconstructibility)**: external-consumer JSON reconstruction test added to T016.
- **M4 (Constitution IV alignment reasoning)**: one-line explanatory note added to spec.md Assumptions block.

The four LOW findings (L1: T003 laziness note; L2: T022 reframe; L3: branch-base note; L4: T029 cross-reference) were all applied as documentation nits.

Coverage after remediation: 30/30 requirements have >= 1 task; 30/30 have >= 1 test task. No unmapped tasks; no constitution violations.
