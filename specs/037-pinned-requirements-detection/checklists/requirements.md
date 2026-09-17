# Specification Quality Checklist: Pinned-Requirements Detection

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-14
**Feature**: [spec.md](../spec.md)

## Content Quality

- [X] No implementation details (languages, frameworks, APIs) -- names like `repro_deps_pinned` and `requirements.txt` are the vocabulary the operator sees in audit output and in their own repo, not stack choices
- [X] Focused on user value and business needs -- three stories covering the hash-pinned, version-pinned, and regression cases
- [X] Written for stakeholders who understand the reproducibility domain
- [X] All mandatory sections completed

## Requirement Completeness

- [X] No [NEEDS CLARIFICATION] markers remain -- both resolved during /speckit-specify (see Notes)
- [X] Requirements are testable and unambiguous
- [X] Success criteria are measurable
- [X] Success criteria are technology-agnostic at the operator level
- [X] All acceptance scenarios are defined -- 3 stories with Given/When/Then coverage
- [X] Edge cases are identified -- 7 enumerated, including the three that a naive `"==" in line` check gets wrong
- [X] Scope is clearly bounded -- Out of Scope names 6 non-goals, including the three sibling issues
- [X] Dependencies and assumptions identified

## Feature Readiness

- [X] All functional requirements have clear acceptance criteria -- FR-001..015 map to SC-001..007 and story scenarios
- [X] User scenarios cover primary flows
- [X] Feature meets measurable outcomes defined in Success Criteria
- [X] No implementation details leak into specification

## Notes

Two decisions were surfaced as questions during `/speckit-specify` rather than defaulted through, and both were resolved:

- **Q1 (FR-005) -- version-pinned verdict: WARN.** A build whose transitive dependencies float is not reproducible, so WARN is substantively accurate rather than merely conservative, and Principle II is explicit that doubt resolves to WARN. Accepted cost, recorded in the spec: because WARN counts as FAIL for compliance calculations, a project that pins every direct dependency cannot reach compliance on this control without adopting a lock file. For a framework whose subject is reproducibility, that is the intended message.
- **Q2 (FR-011) -- empty or comments-only file: treat as absent.** A file declaring no dependencies is evidence of neither good nor bad pinning practice. Any other loose manifest then decides; with none, the existing no-dependency-files INCONCLUSIVE stands.

Design notes for the plan phase, after `/speckit-clarify` (session 2026-09-17, 5 questions):

- **The feature now spans two packages.** FR-005's WARN is not expressible at the handler layer -- the handler verdict vocabulary is PASS / FAIL / INCONCLUSIVE / ERROR, and the only existing route to WARN is the all-inconclusive fallthrough, which replaces the handler's message with a fixed manual-verification string. FR-016 adds a conclusive WARN outcome to the framework; FR-017 and SC-008 bound the blast radius. Plan must treat this as a `darnit` core change plus a `darnit-reproducibility` change, not a plugin-local fix.
- **The false-negative direction matters here.** This bug is constitutionally *safe* -- it under-reports compliance -- which is why it has caused no harm despite being obviously wrong to any user who opens their own file. The fix must not overcorrect into the false-PASS direction, which is the error Principle II actually forbids. Resolving the version-pinned case as WARN is what keeps the fix on the safe side of that line.
- **Three edge cases defeat the obvious implementation** (`"==" in line`): wildcard pins (`pkg==1.*`), compound specifiers (`pkg>=1.0,<2.0`), and environment markers. Whatever parses these should be chosen deliberately at plan time, including whether an existing dependency already provides PEP 440 parsing.
- **FR-007's not-inspectable case** exists because "we read it and it is unpinned" and "we could not read it" are different claims. This is the same distinction feature 036 drew with `error_class`, and the plan should check whether that mechanism applies here rather than inventing a parallel one.
- **Three deliberate non-widenings**, each now an explicit requirement rather than an assumption: file discovery stays at the root `requirements.txt` (FR-019), non-requirement lines are skipped (FR-018), and confidence stays at 0.8 everywhere (FR-020). Each was a plausible place to quietly expand scope; each is now testable as a non-change.
