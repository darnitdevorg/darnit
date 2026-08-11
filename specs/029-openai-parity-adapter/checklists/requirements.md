# Specification Quality Checklist: OpenAI Tier 2 Parity Adapter

**Purpose**: Validate specification completeness and quality before proceeding to planning

**Created**: 2026-08-10

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

- This feature closes issue #368 (opened during feature 028's clarify pass as the follow-up for provider-agnostic Tier 2 checks).
- Two spec-level decisions were made explicitly in the spec rather than deferred as [NEEDS CLARIFICATION]:
  - **Separate workflow per provider** (FR-005): rather than one aggregate workflow with a `provider` input. This preserves per-provider governance -- the OpenAI Environment has its own reviewer list distinct from the Claude Environment.
  - **Shared skill prompt snapshot** (FR-009): feature 028's `skill_prompt_snapshot.md` is used verbatim by both backends. If provider-specific transformations are required (e.g., differing tool-call syntax), those live in the adapter, not in a forked snapshot.
- Corners intentionally deferred to /speckit-clarify:
  - Which specific OpenAI API surface (Assistants API vs Chat Completions with tools). Both work; the choice affects turn-loop implementation but not the spec's contract.
  - Whether the `NoopBackend` used to prove SC-005 / SC-007 lives in the tests package or is a documented "how to write a backend" reference. Plan-phase decision.
  - The exact CI cadence question (US3 aggregate reporting) -- Priority 3, out of scope for MVP, no clarify question needed.
- Constitution IV echo: the OpenAI adapter, like the Claude adapter, MUST NOT modify the `/darnit-audit` skill it diagnoses. Any prompt-shape transformation is adapter-internal.
- Feature dependencies: feature 028 (parity test suite) is hard-required. Its `SkillReport` parser, `Tier2DiffReport` differ, `write_fixture_artifacts` writer, and `run.py` runner CLI are all consumed by this feature -- extended, but not forked.

## Clarification Session Log

Five clarifications recorded during the 2026-08-10 clarify session:

1. **OpenAI API surface** -> Chat Completions with `tools=[...]` and hand-rolled tool-call loop. Stateless per-invocation; symmetric with feature 028's Claude adapter. (FR-001)
2. **Backend registration mechanism** -> Simple factory dict in a shared module; no entry-point discovery. TEST-ONLY seam; distinct from feature 027's product-facing `QuestionResolver`. (FR-004)
3. **Turn cap exhausted** -> New distinct outcome `turn_cap_exhausted` with exit code `5`. Diagnostically separate from `unparseable` and `per_control_disagree`. (FR-010; SC-011 added)
4. **Model default** -> Pin a version-suffixed string in the workflow YAML (e.g., `gpt-4o-2024-08-06`). Reproducibility is load-bearing for a diagnostic; moving aliases forbidden. (SC-010 added)
5. **NoopBackend location** -> Test-only fixture at `tests/darnit/parity/tier2/backends/noop.py`; Protocol shape documented in `contracts/skill-invocation-backend-protocol.md` for real backend authors.

Two new SCs surfaced from these decisions: SC-010 (pinned model check) and SC-011 (turn-cap adversarial test). Coverage after clarify: 17 FR + 11 SC = 28 requirements, all with concrete acceptance criteria.

## /speckit-analyze findings applied

The 2026-08-11 analyze pass surfaced 8 findings (0 CRITICAL, 0 HIGH, 4 MEDIUM, 4 LOW). Applied remediations:

- **MC1 (FR-013 fixture-diff)**: New task T024a manually verifies no fixture files were modified in this PR. Documented as a soft-constraint pre-PR check rather than a test.
- **MC2 (FR-014 parser reuse test)**: T016 gains a subtest `test_openai_style_markdown_is_parseable_by_shared_parser` that feeds an OpenAI-shaped Markdown response through feature 028's `SkillReport.parse()` and asserts parseable.
- **MC3 (shim export inventory)**: New task T009a creates `test_shim_exports.py` that imports every public name from feature 028's original module surface via the shim path.
- **MC4 (rebase watch list)**: New "Rebase conflict watch list" section in tasks.md enumerates the 6 files most likely to conflict on rebase from feature 028's PR review.
- **LC1 (T007/T008 ordering)**: Deps chart updated to explicitly state T008 runs before T007.
- **LC3 (Environment UI callout)**: New "Before-merge maintainer actions" section (M1-M4) documents the manual GitHub UI configuration that no code task performs.
- **LC4 (T009 canary list)**: T009 gains a pointer to the feature-028 test files most likely to surface a shim regression.

Not applied:

- **LC2 (T018 split)**: Would renumber tasks; declined as churn without material benefit.

Task count after remediation: 32 tasks (T001-T024a, T029 with T009a, T024a intercalated). Coverage after remediation: 27/28 requirements have a concrete task or automated check; 1/28 (SC-009 30-min corpus wall clock) remains manual verification post-merge, as designed.
