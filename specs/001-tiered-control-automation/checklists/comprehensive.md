# Comprehensive Requirements Quality Checklist: Tiered Control Automation Pipeline

**Purpose**: Pre-implementation sanity check across all requirement domains (audit passes, context confidence, safety invariants)
**Created**: 2026-03-08
**Feature**: [spec.md](../spec.md)
**Depth**: Standard (author-facing)
**Focus**: All three domains — audit passes, context confidence, safety

## Requirement Completeness — Audit Passes

- [ ] CHK001 Are file discovery patterns explicitly listed for each Category A control (DO-01.01, GV-03.01, LE-01.01, LE-03.01, QA-02.01, VM-02.01, GV-01.01)? [Completeness, Research §Cat-A]
- [ ] CHK002 Are regex patterns for heuristic passes (Category C) specified with enough detail to implement without ambiguity? [Clarity, Research §Cat-C]
- [ ] CHK003 Are LLM evaluation prompts (Category D) defined with explicit assessment criteria, not just open-ended questions? [Clarity, Research §Cat-D]
- [ ] CHK004 Is the expected behavior of each new pass on INCONCLUSIVE specified — does the spec state that all new passes MUST fall through to the next pass on uncertainty? [Completeness, Spec §FR-001]
- [ ] CHK005 Are the Category E investigation controls (VM-03.01, VM-05.03, BR-04.01) scoped with clear acceptance criteria for "fixed," or are they open-ended? [Measurability, Tasks §T007/T018-T020]
- [x] CHK006 Is it specified which existing manual passes should be preserved as fallbacks vs. which can be removed? [Resolved — FR-013 added: manual passes MAY be removed when automated passes fully cover the control. Every control MUST end up with equal or better coverage.]
- [ ] CHK007 Are the file path variants for file_must_exist passes comprehensive — do they include `.github/` and `docs/` subdirectories where applicable? [Coverage, Research §Cat-A]

## Requirement Completeness — Context Confidence

- [ ] CHK008 Are all context fields that support auto-detection enumerated with their expected confidence levels? [Completeness, Contracts §toml-schema-extensions]
- [ ] CHK009 Is the full list of canonical sources mapped to specific context fields (e.g., CODEOWNERS→maintainers, SECURITY.md→security_contact)? [Completeness, Data-Model §ContextField]
- [ ] CHK010 Are the heuristic detection methods for low-confidence fields described with enough detail to implement (governance_model, project_type, has_subprojects)? [Clarity, Tasks §T028]
- [ ] CHK011 Is the behavior specified for when a canonical source exists but contains ambiguous data (e.g., CODEOWNERS with wildcards only)? [Edge Case, Gap]
- [ ] CHK012 Is the user override flow defined — what happens to confidence and source fields when a user modifies an auto-accepted value? [Completeness, Spec §FR-005]

## Requirement Clarity

- [ ] CHK013 Is "conclusive result" consistently defined across all artifacts as PASS, FAIL, or ERROR (not WARN, not INCONCLUSIVE)? [Clarity, Spec §FR-001]
- [ ] CHK014 Is the distinction between "pass" (handler invocation) and "control" (the thing being evaluated) consistently maintained? [Terminology, Spec/Tasks]
- [ ] CHK015 Is "deterministic" vs "heuristic" defined with a clear boundary — what makes a pattern pass "heuristic" vs "deterministic"? [Ambiguity, Spec §Clarifications]
- [ ] CHK016 Is the 0.8 default threshold for auto_accept_confidence justified with rationale, or is it arbitrary? [Clarity, Research §Decision-3]
- [ ] CHK017 Is "generative remediation" scoped — which specific controls trigger LLM-customized output vs. template-only output? [Clarity, Spec §FR-007]

## Requirement Consistency

- [ ] CHK018 Do the success criteria percentages (SC-001: 80%, SC-002: 70%) align with the projected impact numbers in research.md (88%, 82%)? [Consistency, Spec §SC vs Research §Projected-Impact]
- [ ] CHK019 Are the control counts consistent across spec (62 controls), research (59 manual, 15 manual-only), and tasks (7+3+4+3 = 17 controls touched)? [Consistency]
- [ ] CHK020 Does the data-model ContextField lifecycle diagram match the FR-004 requirement text — specifically, do both agree on what happens at the threshold boundary? [Consistency, Spec §FR-004 vs Data-Model §ContextField]
- [ ] CHK021 Are SieveResult field names consistent between data-model.md, contracts/sieve-result-extensions.md, and tasks.md references? [Consistency]

## Acceptance Criteria Quality

- [ ] CHK022 Can US1 acceptance scenario 1 ("at least 80% of level 1 controls") be measured with existing tooling, or does it require new measurement infrastructure? [Measurability, Spec §US1-AS1]
- [ ] CHK023 Is SC-003 ("auto-fills at least 75% of context fields") testable — is the denominator (total context fields) defined? [Measurability, Spec §SC-003]
- [ ] CHK024 Is SC-006 ("fewer manual steps") measurable as stated, or is it purely qualitative with no baseline? [Measurability, Spec §SC-006]
- [ ] CHK025 Are the "3+ diverse test repos" for T029 specified, or is repo selection left undefined? [Measurability, Tasks §T029]

## Scenario Coverage

- [ ] CHK026 Are requirements defined for the case where a repo has NO dependency manifest at all (not just the wrong format)? [Coverage, Edge Case]
- [ ] CHK027 Are requirements specified for controls that depend on org-level GitHub settings when auditing a personal repo (no org)? [Coverage, Edge Case]
- [ ] CHK028 Is the behavior defined when the LLM evaluation pass is unavailable (standalone CLI mode) — do those controls fall through to manual? [Coverage, Spec §Assumptions]
- [ ] CHK029 Are requirements defined for partial context collection — what happens if some fields auto-detect but the user abandons confirmation of remaining fields? [Coverage, Gap]
- [ ] CHK030 Is the behavior specified when a file_must_exist pass finds the file but it's empty (0 bytes)? [Edge Case, Gap]

## Edge Case Coverage

- [ ] CHK031 Is rate-limiting behavior defined with specifics — how many API calls before the system backs off, and what's the retry strategy? [Clarity, Spec §Edge-Cases]
- [ ] CHK032 Are requirements defined for repos with non-standard structures (monorepos, multiple LICENSE files, nested SECURITY.md)? [Edge Case, Gap]
- [ ] CHK033 Is behavior specified when a CEL expression in a new TOML pass has a syntax error — does it fail gracefully or crash the audit? [Edge Case, Gap]

## Non-Functional Requirements

- [ ] CHK034 Is the performance target (SC-005: <30s per remediation) specified for a particular hardware/network baseline? [Clarity, Spec §SC-005]
- [ ] CHK035 Are observability requirements defined — should the system log which pass resolved each control for debugging/monitoring? [Gap]
- [ ] CHK036 Are backward compatibility requirements specified — do existing audit results remain comparable after this change? [Gap]

## Dependencies & Assumptions

- [ ] CHK037 Is the assumption that `gh` CLI is the primary GitHub API mechanism validated against the existing codebase — are there controls that use other mechanisms? [Assumption, Spec §Assumptions]
- [ ] CHK038 Is the assumption that "organization-wide automation is out of scope" clearly communicated in the spec, or only in Assumptions? [Assumption, Spec §Assumptions]
- [ ] CHK039 Is it documented which version of the OpenSSF Baseline spec (OSPS v2025.10.10) these control changes target? [Dependency, Gap]

## Notes

- Focus: All three domains (audit passes, context confidence, safety)
- Depth: Standard pre-implementation sanity check
- Actor: Author-facing
- 39 items total across 8 categories
- Constitution treated as background context (already validated in /speckit.analyze)
