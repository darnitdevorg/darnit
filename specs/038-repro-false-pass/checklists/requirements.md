# Specification Quality Checklist: Honest Verdicts for Reproducibility Controls

**Purpose**: Validate specification completeness and quality before proceeding to planning
**Created**: 2026-09-20
**Feature**: [spec.md](../spec.md)

## Content Quality

- [X] No implementation details -- control ids (`RE-01.02`) and filenames (`Dockerfile`) are the vocabulary the operator sees in audit output and in their own repo
- [X] Focused on user value -- four stories, each framed as what a maintainer is told about their repository
- [X] Written for stakeholders who understand the reproducibility domain
- [X] All mandatory sections completed

## Requirement Completeness

- [X] No [NEEDS CLARIFICATION] markers remain -- FR-010 resolved during /speckit-specify
- [X] Requirements are testable and unambiguous
- [X] Success criteria are measurable
- [X] Success criteria are technology-agnostic at the operator level
- [X] All acceptance scenarios are defined -- 4 stories with Given/When/Then coverage
- [X] Edge cases are identified -- 7 enumerated, including the cross-control coupling
- [X] Scope is clearly bounded -- Out of Scope names 5 non-goals including two sibling issues in the same file
- [X] Dependencies and assumptions identified

## Feature Readiness

- [X] All functional requirements have clear acceptance criteria -- FR-001..015 map to SC-001..009 and story scenarios
- [X] User scenarios cover primary flows
- [X] Feature meets measurable outcomes defined in Success Criteria
- [X] No implementation details leak into specification

## Notes

**16/16 passing.**

**FR-010 resolved: the Nix gate keeps requiring RE-01.02 to have PASSED.** The gate's stated premise is that a bare flake which is not the project's confirmed build environment is not a strong signal on its own; once RE-01.02 stops confirming that, preserving the PASS would keep a verdict whose justification is gone. Accepted cost, recorded in the spec and required to be stated to users: some repositories will see RE-02.01 drop from PASS to INCONCLUSIVE without having changed anything. SC-010 pins the behaviour, including that the result must attribute the withheld signal to RE-01.02 rather than to a missing flake.

Reading the code before writing this spec changed its shape, and that is worth recording:

- The four issues were filed as one family ("PASS on presence rather than quality"). That holds for #445 and #431. It does not hold for #430 and #432: `repro_hermetic_build` already requires a *verified* Witness attestation, a Nix build, or Bazel with a blocking flag for its PASS, and explicitly rejects a mere mention of `witness run` in CI text. Those two issues are detection-coverage gaps, not verdict-strength problems.
- The two shapes are coupled in one direction. `_detect_strong_hermeticity_signal` gates its Nix path on `dependency_results.get("RE-01.02") == "PASS"`, so tightening #431 removes a hermeticity signal from repositories whose container declaration is unpinned. FR-010 is the open question about whether that propagation is wanted.

Design notes for the plan phase:

- FR-001 and FR-004 both need feature 037's conclusive WARN. This feature is unimplementable on a tree without PR #443.
- FR-015 (no matches in prose or comments) is the requirement most likely to be met with a naive substring scan. The existing `_strip_comment` helper in the same file is the obvious starting point, and the existing `_SAFE_PATTERNS` / `_DOCKERFILE_DEFERRED_PATTERNS` structure already models "matched but not a violation" -- worth reusing rather than inventing a parallel mechanism.
- SC-007 should reuse the differential capture from feature 037 (`tests/darnit/sieve/baseline_capture.py`) rather than a stored golden. Control statuses vary by environment; that approach was already tried and abandoned in 037.
- `repro_provenance_exists` has the same presence-based shape as #445 and is covered by no issue. Out of scope here, but worth filing.
