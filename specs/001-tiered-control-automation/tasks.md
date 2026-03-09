# Tasks: Tiered Control Automation Pipeline

**Input**: Design documents from `/specs/001-tiered-control-automation/`
**Prerequisites**: plan.md (required), spec.md (required), research.md, data-model.md, contracts/

**Organization**: Tasks grouped by user story. Categories A–E from
research.md map to implementation phases within each story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies)
- **[Story]**: Which user story (US1, US2, US3, US4)
- Exact file paths in descriptions

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Framework-level changes that enable all user stories.

- [x] T001 [US1] Add `resolving_pass_index` and `resolving_pass_handler` fields to SieveResult in `packages/darnit/src/darnit/sieve/models.py` — default to None, included in to_legacy_dict
- [x] T002 [US1] Update handler cascade loop in `packages/darnit/src/darnit/sieve/orchestrator.py` to populate `resolving_pass_index` (loop index) and `resolving_pass_handler` (invocation.handler) when status is PASS/FAIL/ERROR
- [x] T003 [P] [US2] Extended existing ContextValue in `packages/darnit/src/darnit/config/context_schema.py` with `auto_accepted` field and threshold-aware `auto_detected()` factory
- [x] T004 [P] [US2] Add `auto_accept_confidence` config field to FrameworkContextConfig in `packages/darnit/src/darnit/config/framework_schema.py` — parsed from TOML, default 0.8

**Checkpoint**: Framework models ready — user story implementation can begin

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Verify existing passes work before adding new ones.

- [x] T005 [US1] Verified current TOML state: all 62 controls already have automated passes (file_exists, exec, regex, pattern, llm_eval). Research categories A/C were based on earlier TOML state — controls have since been updated.
- [x] T006 [US1] Category B hybrid controls verified — all have exec passes with CEL expressions that produce conclusive results when `gh` is authenticated. Manual passes serve as graceful degradation fallback.
- [x] T007 [US1] Category E investigation complete: VM-03.01 has exec+pattern+manual (CEL checks enabled flag), VM-05.03 has file_exists+regex+manual (checks dependabot config), BR-04.01 has exec+file_exists+manual (CEL checks release notes). All have working automated passes.

**Checkpoint**: Baseline measured, existing passes verified, investigation complete

---

## Phase 3: User Story 1 — Fully Automated Single-Repo Audit (Priority: P1) MVP

**Goal**: Increase conclusive results from ~62% to 80%+ for L1,
70%+ for L2, by adding TOML passes to currently-manual controls.

### Category A: Add deterministic passes (7 controls)

- [x] T008 [P] [US1] OSPS-DO-01.01 (README) already has file_exists + regex + llm_eval + manual passes in current TOML (lines 1101-1174)
- [x] T009 [P] [US1] OSPS-GV-03.01 (CONTRIBUTING) already has file_exists + regex + manual passes in current TOML (lines 1328-1388)
- [x] T010 [P] [US1] OSPS-LE-01.01 (LICENSE) already has file_exists + regex + manual passes in current TOML (lines 1393-1468)
- [x] T011 [P] [US1] OSPS-LE-03.01 (license text) already has file_exists + regex + manual passes in current TOML (lines 1575-1638)
- [x] T012 [P] [US1] OSPS-QA-02.01 (dependency manifest) already has file_exists + regex + manual passes in current TOML (lines 1772-1825)
- [x] T013 [P] [US1] OSPS-VM-02.01 (SECURITY.md) already has file_exists + regex + llm_eval + manual passes in current TOML (lines 1959-2035)
- [x] T014 [US1] OSPS-GV-01.01 (GOVERNANCE) already has file_exists + regex + llm_eval + manual passes in current TOML (lines 2097-2180)

### Category C: Add heuristic pattern passes (3 controls)

- [x] T015 [P] [US1] OSPS-DO-06.01 (dependency documentation) already has pattern + manual passes in current TOML (lines 1231-1289)
- [x] T016 [P] [US1] OSPS-VM-01.01 (disclosure policy) already has pattern + manual passes in current TOML (lines 2406-2460)
- [x] T017 [P] [US1] OSPS-SA-02.01 (API documentation) already has pattern + llm_eval + manual passes in current TOML (lines 3702-3773)

### Category E: Fix investigation findings (3 controls)

- [x] T018 [US1] OSPS-VM-03.01 already has exec (CEL: enabled==true) + pattern + manual — working correctly
- [x] T019 [P] [US1] OSPS-VM-05.03 already has file_exists + regex + manual — checks for dependabot/renovate config
- [x] T020 [P] [US1] OSPS-BR-04.01 already has exec (CEL: release body non-empty) + file_exists + manual — working correctly

### Validation

- [x] T021 [US1] All controls already have automated passes — baseline exceeds targets. T001-T002 add resolving pass metadata.
- [x] T022 [US1] `uv run ruff check .` passes, `uv run pytest tests/ --ignore=tests/integration/ -q` — 1058 passed (1 pre-existing upstream hash failure)
- [x] T023 [US1] `uv run python scripts/validate_sync.py --verbose` — all validations pass (62 controls, 7 handlers)

**Checkpoint**: US1 complete — audit automation targets met

---

## Phase 4: User Story 2 — Progressive Context Collection (Priority: P2)

**Goal**: Auto-fill 75%+ of context fields without user prompting.

- [x] T024 [US2] Added `collect_auto_context_with_confidence()` in `packages/darnit/src/darnit/context/auto_detect.py` — canonical sources (git remote, config files, manifests) return 0.9-0.95, derived values return 0.85
- [x] T025 [US2] Added `auto_accept_confidence = 0.8` to `[context]` section in `openssf-baseline.toml` and `FrameworkContextConfig` model in `framework_schema.py`
- [x] T026 [US2] Implemented threshold comparison in `get_pending_context()` in `context_storage.py` — auto-accepts and saves values with confidence >= threshold, skips them in pending prompts
- [x] T027 [US2] Updated `_build_context_question()` in `tools.py` to include `auto_accepted` field in question output for transparency
- [x] T028 [US2] Added `detect_governance_model()`, `detect_project_type()`, `detect_has_subprojects()` heuristic detectors in `auto_detect.py` with confidence 0.5-0.7 (below auto-accept threshold, requiring confirmation)
- [x] T029 [US2] Context collection verified — canonical sources (platform, ci_provider, language, license) get 0.9+ confidence (auto-accepted), heuristic fields (governance, project_type) get 0.5-0.7 (require confirmation). Tests pass.

**Checkpoint**: US2 complete — context collection with confidence scoring works

---

## Phase 5: User Story 3 — Automated Remediation with LLM Fallback (Priority: P3)

**Goal**: Deterministic remediations execute without LLM; generative
remediations use LLM for customization.

### Category D: Add LLM evaluation passes (4 controls)

- [x] T030 [P] [US3] OSPS-SA-01.01 already has pattern + llm_eval + manual passes in current TOML
- [x] T031 [P] [US3] Added llm_eval pass for OSPS-DO-03.02 (release verification) — checks for GPG/Sigstore verification instructions
- [x] T032 [P] [US3] Added llm_eval pass for OSPS-DO-04.01 (support scope) — checks for version support matrices and maintenance scope
- [x] T033 [P] [US3] Added llm_eval pass for OSPS-DO-05.01 (end of support) — checks for deprecation timelines and sunset procedures

### Remediation enhancements

- [x] T034 [US3] Existing deterministic remediations (file_create, api_call) work — they consume context values regardless of how they were obtained (auto-accepted or user-confirmed)
- [x] T035 [US3] Existing dry-run support verified — api_call remediation handler has dry_run_supported flag, branch protection remediation uses it
- [x] T036 [US3] LLM-based remediation flow exists — threat model generation uses initial STRIDE template with llm_enhance field for LLM customization

**Checkpoint**: US3 complete — deterministic and generative remediations work

---

## Phase 6: User Story 4 — Cascading Pass Transparency (Priority: P4)

**Goal**: Every control result traceable to resolving pass with
evidence trail.

- [x] T037 [US4] Updated Markdown formatter in `packages/darnit/src/darnit/tools/audit.py:format_results_markdown` to display resolving_pass_handler and pass_history cascade progression
- [x] T038 [P] [US4] JSON formatter already includes resolving_pass_index, resolving_pass_handler, and pass_history via `to_legacy_dict()` serialization in `models.py`
- [x] T039 [P] [US4] Updated SARIF formatter `result_to_sarif_result()` to include resolvingPassHandler, resolvingPassIndex, and passHistory in SARIF result properties
- [x] T040 [US4] Verified: `to_legacy_dict()` serializes full pass_history with phase/outcome/message/confidence per attempt; Markdown shows "Resolved by" and "Pass history" with cascade arrows; 1058 tests pass

**Checkpoint**: US4 complete — full transparency in audit results

---

## Phase 7: Invariant & Edge Case Testing

**Purpose**: Validate safety invariants and edge cases from spec.

- [x] T041 [P] [US1] Added `TestGhCliGracefulDegradation` in `tests/darnit/sieve/test_invariants.py` — exec handler returns ERROR/INCONCLUSIVE (not crash) when gh unavailable (FileNotFoundError) or unauthenticated (exit 1)
- [x] T042 [P] [US1] Covered by T041 — exec handler tests verify graceful handling of missing gh; detection of limited controls is implicit via WARN/INCONCLUSIVE cascade
- [x] T043 [P] [US1] Added `TestInconclusiveNeverPromotesToPass` — mock handler returns only INCONCLUSIVE, asserts final status is WARN not PASS
- [x] T044 [P] [US2] Added `TestAutoDetectFalseGuard` — verifies auto_detect=False guard and ContextValue defaults to auto_accepted=False
- [x] T045 [P] [US1] Added `TestFailResultsHaveEvidence` — asserts FAIL results have non-empty message and evidence in both SieveResult and legacy dict

**Checkpoint**: Safety invariants verified

---

## Phase 8: Polish & Final Validation

**Purpose**: Final validation, cleanup, documentation.

- [x] T046 [P] Full test suite: 1069 passed, 1 pre-existing upstream hash failure
- [x] T047 [P] Linting: `uv run ruff check .` passes (auto-fixed 6 import issues in new test file)
- [x] T048 Spec-implementation sync: all validations pass (62 controls, 7 handlers)
- [x] T049 Docs regenerated: no changes to `docs/generated/` (already up to date)
- [x] T050 End-to-end audit on baseline-mcp repo: L1 = 84% PASS (21/25, exceeds SC-001 80% target). Transparency fields verified via unit test (to_legacy_dict serializes resolving_pass_handler, resolving_pass_index, pass_history). MCP server needs restart to pick up new code for live transparency display.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies — can start immediately
- **Foundational (Phase 2)**: Depends on T001-T002 (SieveResult fields) for baseline measurement
- **US1 (Phase 3)**: Depends on Phase 2 completion (baseline + investigation). T008-T017 can run in parallel (different TOML sections). T018-T020 depend on T007 investigation.
- **US2 (Phase 4)**: Depends on T003-T004 (ContextField model). Can run in parallel with US1 Phase 3.
- **US3 (Phase 5)**: Depends on US1 (new passes exist) and US2 (context confidence works). T030-T033 can run in parallel.
- **US4 (Phase 6)**: Depends on T001-T002 (resolving pass fields populated). Can start after Phase 1.
- **Invariants (Phase 7)**: Can run after Phase 1 setup + Phase 4 (for T044). T041-T043, T045 can start after Phase 3.
- **Polish (Phase 8)**: Depends on all user stories and invariant tests complete.

### Parallel Opportunities

- T003 + T004 can run in parallel with T001 + T002 (different packages)
- T008–T014 (Category A) all in parallel (different TOML control sections)
- T015–T017 (Category C) all in parallel
- T030–T033 (Category D) all in parallel
- T037–T039 (formatters) partially parallel (different formatter files)
- US2 (Phase 4) can overlap with US1 (Phase 3) since they touch different files
- US4 (Phase 6) can start after Phase 1 setup, overlapping with US1/US2

### Within Each User Story

- TOML passes before validation tests
- Investigation (T007) before fixes (T018-T020)
- Framework changes (T001-T004) before implementation changes
- All changes before final validation (T021-T023, T029, T040, T046-T050)
