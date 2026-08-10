# Specification Quality Checklist: Two-Tier Audit Parity Tests

**Purpose**: Validate specification completeness and quality before proceeding to planning

**Created**: 2026-08-09

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

- This spec is diagnostic, not remedial: it defines a test surface that WILL detect drift between the three audit consumers. It does NOT define fixes for any specific drift the tests might discover. That intentional scoping keeps the feature small and its purpose clear.
- Constitution IV echo: the whole reason this feature exists is that a downstream layer (the `/darnit-audit` coding-agent skill) was observed silently reinterpreting the tool's verdicts. Tier 2 makes that behavior visible; a fix for it would be a separate feature.
- Feature dependencies: 026 (harness) is hard-required for Tier 1. 027 (interactive resolvers) is intentionally out of scope; parity tests do not exercise interactive answer collection.
- Two areas were considered for [NEEDS CLARIFICATION] but resolved with defaults instead:
  - Tier 2 cadence: chose "nightly or weekly, plan-phase decides." A specific number would over-fit the spec.
  - Claude Agent SDK vs Claude Code CLI subprocess: chose "SDK if available, CLI subprocess as fallback." The plan phase pins the exact choice.
- The spec commits to closing issue #366 on merge (FR-016 + SC-009). This is the audit trail linking the surfaced problem to the shipped diagnostic.

## Clarification Session Log

Five clarifications recorded during the 2026-08-09 clarify session:

1. **Tier 2 invocation mechanism** -> Claude Agent SDK (test-only dep). Follow-up issue #368 opened for OpenAI-SDK and other-provider parity checks; those are separate features.
2. **Skill's summary artifact** -> Final assistant message. Diagnostic feature must compare user-facing output; structured-artifact alternatives rejected as intrusive.
3. **Tier 2 cadence** -> Manual-only for MVP (`workflow_dispatch`); no schedule. Governance driver: repo is under neutral governance, API key belongs to a specific company. FR-007a + FR-007b + SC-005a lock down the access-control shape. Follow-up issue #369 opened for adding scheduled cadence + governance-appropriate key-sourcing.
4. **Tier 1 MCP-tool call shape** -> Direct Python function call (`audit_openssf_baseline(...)`). No MCP server bootstrap; JSON-RPC serialization is a separate concern.
5. **Fixture metadata format** -> `parity.toml` at each fixture root, TOML-parsed. Matches Constitution III convention; no code execution; stdlib `tomllib`.

Two governance-motivated additions surfaced from Q3:

- FR-007a: Environment-gated dispatch, reviewer-list required, repo-level secret exposure forbidden.
- FR-007b: Operator-provided API-key inputs forbidden in MVP.
- SC-005a: Grep-verifiable: no other workflow references `secrets.ANTHROPIC_API_KEY` outside the gated Tier 2 workflow.

## /speckit-analyze findings applied

The 2026-08-10 analyze pass surfaced 8 findings (0 CRITICAL, 1 HIGH, 4 MEDIUM, 3 LOW). Applied remediations:

- **HC1 (git-init in Tier 1 conftest)**: T012 updated with explicit `prepared_fixture` shape mirroring feature 026's `minimal_llm_repo_tree` pattern. Load-bearing -- without this, the Tier 1 harness invocation would fail before running any control.
- **MC1 (FR-010 missing-key test)**: T025 gains a `test_missing_api_key_raises_setup_error` subtest with both unit-level (`invoke_skill` raises) and integration-level (`run.py` subprocess exit code 3) assertions.
- **MC2 (FR-013 green-run summary)**: T013 gains a `capsys.readouterr()` capture + regex-pattern assertion on the summary line, run for EVERY test (green or red).
- **MC3 (FR-014 no product code changes)**: New task T031a creates `tests/darnit/parity/tier1/test_no_product_changes.py` that runs `git diff --name-only <base>...HEAD` and asserts no file under `packages/darnit/src/` or `packages/darnit-baseline/src/` is modified. Skips on local dev when no base ref is reachable.
- **MC4 (FR-015 determinism)**: T006 gains a "run compare() twice, assert byte-identical outputs" subtest.
- **LC1 (allowed-drift wildcard resolution)**: T014's allowed-drift positive cases expanded from just PENDING_LLM->WARN to all three (PENDING_LLM -> WARN | PASS | FAIL).
- **LC2 (grep portability)**: T024 replaces `subprocess.run(["grep", ...])` with pure-Python file iteration.
- **LC3 (T024/T031 redundancy)**: No action taken. T024 is the automated test; T031 is the maintainer sanity ritual. Both are cheap; keep both.

Coverage after remediation: 30/30 requirements have >=1 task; 30/30 have >=1 test task (or manual sign-off for the two doc-shaped ones -- SC-009 via PR body, T033).
