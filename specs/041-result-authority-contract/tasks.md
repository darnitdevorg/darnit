# Tasks: Result and Authority Contract

**Input**: Design documents from `/specs/041-result-authority-contract/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included. Success criteria SC-001 to SC-006 are test-suite and corpus outcomes, and the project works test-first. Write each story's tests first and confirm they fail.

**Organization**: Grouped by user story so each story can be implemented and verified independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1-US5 map to the user stories in spec.md

## Path Conventions

- Core: `packages/darnit/src/darnit/`
- Baseline implementation: `packages/darnit-baseline/src/darnit_baseline/`
- Tests: `tests/darnit/`, `tests/darnit_baseline/`

---

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 In a separate change based on main (not this branch), narrow the parity guard so it applies only to changes to the parity harness (tier1/tier2 code), not to fixture and expectation updates under `tests/darnit/parity/fixtures/`, in `tests/darnit/parity/tier1/test_no_product_changes.py` (research R8); rebase this branch on it once merged (opened as #509)
- [X] T002 Update `docs/architecture/framework-design.md` first: step ceilings and declarations (`concludes`, `existence`, `fail_on_miss`, `fail_on_status`, `promotion`), the `gh_api` handler, the result statuses (PENDING replaces PENDING_LLM; ERROR with cause), PASS candidates and confirmation, and the corpus gate; add `gh_api` to the handler-name registry so `scripts/validate_sync.py` passes
- [X] T003 [P] Create the corpus skeleton `tests/darnit_baseline/corpus/README.md` (fixture layout and `labels.toml` format per data-model.md) and an empty `tests/darnit_baseline/corpus/__init__.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**CRITICAL**: No user story work can begin until this phase is complete.

- [X] T004 [P] Write result-model tests (statuses PASS, FAIL, WARN, N/A, ERROR, PENDING; ERROR requires `error {class, cause}`; PENDING requires `pending.kind`; PENDING_LLM no longer produced) in `tests/darnit/sieve/test_result_model.py`
- [X] T005 [P] Write ceiling and declaration tests (registry ceilings per data-model.md; effective set = ceiling narrowed by `concludes`, widened only by `promotion`; `existence` only on presence/pattern; `fail_on_miss` requires fail; `fail_on_status` only on `gh_api`; load-time errors name framework, control, step index, outcome) in `tests/darnit/sieve/test_step_ceilings.py`
- [X] T006 [P] Write a test that authority validation runs on every control-loading path, including `load_controls_from_framework` used by the MCP audit path, in `tests/darnit/config/test_authority_validation_paths.py`
- [X] T007 Replace `PENDING_LLM` with `PENDING` plus `pending.kind`, and add `error`, `pending`, `candidate`, `confirmation`, and `concluded_by` fields to results in `packages/darnit/src/darnit/sieve/models.py`; update every in-repo consumer (CLI, harness report, formatters, `tools/audit.py`) in the same change
- [X] T008 Replace scalar `default_authority` with a ceiling set and optional `existence_ceiling` in `packages/darnit/src/darnit/sieve/handler_registry.py`; register ceilings for built-ins in `packages/darnit/src/darnit/sieve/builtin_handlers.py` per data-model.md (plugin handlers without a ceiling default to `{}`)
- [X] T009 Add step fields `concludes`, `existence`, `fail_on_miss`, `fail_on_status`, `promotion` to the pass/handler-invocation model in `packages/darnit/src/darnit/config/framework_schema.py`
- [X] T010 Consolidate authority validation into one function called from every control-loading path after plugin handlers register (including `load_controls_from_framework` in `packages/darnit/src/darnit/tools/audit.py` and `control_from_effective` in `packages/darnit/src/darnit/config/control_loader.py`)
- [X] T011 Change `resolve_step_result` and the effective-authority computation in `packages/darnit/src/darnit/sieve/orchestrator.py` to conclude only when the step's outcome is in its effective set; otherwise record the result as evidence and continue; route `inferred_from` through the same rule

**Checkpoint**: Foundation ready.

---

## Phase 3: User Story 1 - Weak evidence can no longer produce a PASS (Priority: P1) MVP

**Goal**: Presence and pattern steps prove only FAIL (unless existence); pattern misses are inconclusive.

**Independent Test**: quickstart.md section 1.

### Tests for User Story 1

- [X] T012 [P] [US1] Write tests: presence step on a content control with the file present does not conclude PASS; with the file missing concludes FAIL; with `existence = true` concludes PASS, in `tests/darnit/sieve/test_presence_authority.py`
- [X] T013 [P] [US1] Write tests: pattern match on a content control does not conclude PASS; a miss is INCONCLUSIVE unless `fail_on_miss = true`, in `tests/darnit/sieve/test_pattern_authority.py`
- [X] T014 [P] [US1] Write an end-to-end test auditing a placeholder-docs scratch repository (README "TODO", SECURITY.md denying a process, placeholder governance files) asserting no content control is PASS, in `tests/darnit_baseline/test_weak_evidence.py`

### Implementation for User Story 1

- [X] T015 [US1] Implement pattern-miss INCONCLUSIVE and `fail_on_miss` in the regex/pattern handler in `packages/darnit/src/darnit/sieve/builtin_handlers.py`
- [X] T016 [US1] Make `file_exists` honor `existence` via the registry's `existence_ceiling` (no handler logic change beyond reporting) in `packages/darnit/src/darnit/sieve/builtin_handlers.py`
- [X] T017 [US1] Update the existing handler/authority tests that encode per-handler dispositive behavior (`tests/darnit/sieve/test_authority_terminates.py`, `tests/darnit/sieve/test_handler_authority_regression.py`, `tests/darnit/sieve/test_builtin_handlers.py`) to the new rules, listing each changed assertion in the commit message

**Checkpoint**: Weak evidence cannot conclude PASS.

---

## Phase 4: User Story 2 - Broken measurements are reported as errors (Priority: P1)

**Goal**: ERROR with cause for API/tool/model failures; only declared responses prove FAIL.

**Independent Test**: quickstart.md section 2.

### Tests for User Story 2

- [X] T018 [P] [US2] Write `gh_api` handler tests with recorded responses: 200 + expr, 404 with `fail_on_status = [404]` -> FAIL, 404 without it -> ERROR, 401/403 -> ERROR class `auth`, 429 -> `rate_limit`, 5xx/transport -> `unavailable`, `gh` missing -> `missing_tool`, in `tests/darnit/sieve/test_gh_api_handler.py`
- [X] T019 [P] [US2] Write tests: exec with a missing binary -> ERROR `missing_tool`; mcp step with a missing required server -> ERROR; branch-protection 401/403/429 -> ERROR with class, in `tests/darnit/sieve/test_error_outcomes.py` and `tests/darnit_baseline/test_branch_protection_errors.py`
- [X] T020 [P] [US2] Write a compliance test: any ERROR at a level makes it non-compliant, via `calculate_compliance`, in `tests/darnit/tools/test_compliance_errors.py`

### Implementation for User Story 2

- [X] T021 [US2] Implement the `gh_api` handler (endpoint with `$OWNER/$REPO/$BRANCH` substitution, CEL `expr` over `response`, `fail_on_status`, error classes) using the existing `gh_api_with_status` helper in `packages/darnit/src/darnit/sieve/builtin_handlers.py`; add a recorded-response stub hook for tests and the corpus
- [X] T022 [US2] Return ERROR `missing_tool` from `exec` when the binary is absent, and ERROR from the mcp handler when a required server is missing, in `packages/darnit/src/darnit/sieve/builtin_handlers.py`
- [X] T023 [US2] Return ERROR with an error class for 401/403/429 in `packages/darnit-baseline/src/darnit_baseline/branch_protection.py`
- [X] T024 [US2] Propagate ERROR through the orchestrator so an ERROR step never concludes FAIL and the control ends ERROR when no later step concludes, recording the cause, in `packages/darnit/src/darnit/sieve/orchestrator.py`

**Checkpoint**: Broken measurements read as ERROR everywhere.

---

## Phase 5: User Story 3 - Model judgments become PASS candidates (Priority: P1)

**Goal**: Positive judgments with verified citations become candidates confirmed by the operator; agents use the same path.

**Independent Test**: quickstart.md section 3.

### Tests for User Story 3

- [ ] T025 [P] [US3] Write judgment tests (positive + verified citations -> PENDING confirmation with candidate; unverifiable citation -> WARN, nothing stored; negative -> suggestive FAIL; model failure -> ERROR; confirmation -> asserted PASS; digest change or expiry -> lapse) in `tests/darnit/trust/test_judgments.py`
- [ ] T026 [P] [US3] Write `submit_judgment` MCP tool tests (pass/fail/rejection; stored operator-side; next audit shows the candidate) in `tests/darnit/server/test_submit_judgment.py`
- [ ] T027 [P] [US3] Write a test that the ActionPlan audit step rejects client-supplied per-control statuses in `tests/darnit/core/test_action_plan_verdicts.py`
- [ ] T028 [P] [US3] Write a harness test that its report uses `calculate_compliance` and treats candidates as non-compliant in `tests/darnit/harness/test_harness_compliance.py`

### Implementation for User Story 3

- [ ] T029 [US3] Add `cited_evidence`, `model`, `model_version` to `LLMJudgment` and populate model/version from the configured provider in `packages/darnit/src/darnit/core/llm_step.py`
- [ ] T030 [US3] Implement `packages/darnit/src/darnit/trust/judgments.py`: whitespace-normalized citation verification, evidence digest over gathered content and the control rubric, candidate record/lookup using the feature 040 confirmation store with claim `pass_candidate`
- [ ] T031 [US3] Replace `verify_with_llm_response` behavior in `packages/darnit/src/darnit/sieve/orchestrator.py` with the judgment state machine from data-model.md
- [ ] T032 [US3] Apply stored candidates and confirmations to PENDING controls when assembling results in `packages/darnit/src/darnit/tools/audit.py`
- [ ] T033 [US3] Harness: model-service failure -> ERROR; judgments through `trust/judgments.py`; compliance via `calculate_compliance`, in `packages/darnit/src/darnit/harness/driver.py`
- [ ] T034 [US3] Implement the `submit_judgment` MCP tool in `packages/darnit/src/darnit/server/tools/judgments.py` and register it for every framework server
- [ ] T035 [US3] Extend the confirmation tool to confirm a PASS candidate by `control_id` for the audit target in `packages/darnit/src/darnit/server/tools/project_data.py`
- [ ] T036 [US3] Stop accepting client-supplied verdicts for the audit step in `packages/darnit/src/darnit/core/action_plan.py` and `packages/darnit/src/darnit/server/tools/harness_loop.py`
- [ ] T037 [US3] Update skills to call `submit_judgment` for PENDING (llm_judgment) controls with verbatim excerpts and never state verdicts or confirm without the operator's instruction, in `packages/darnit/src/darnit/skills/darnit-audit/SKILL.md` and `packages/darnit/src/darnit/skills/darnit-comply/SKILL.md`

**Checkpoint**: No driver can produce a PASS from a model judgment without confirmation.

---

## Phase 6: User Story 4 - A corpus of adversarial fixtures measures every step (Priority: P2)

**Goal**: Per-step, per-outcome measurement and a CI gate on false PASS.

**Independent Test**: quickstart.md section 4.

### Tests for User Story 4

- [ ] T038 [P] [US4] Write runner self-tests (a synthetic framework with a promoted step that is fooled by a fixture fails the run and names step and fixture; a new fixture with only `labels.toml` is measured) in `tests/darnit_baseline/corpus/test_runner.py`

### Implementation for User Story 4

- [ ] T039 [P] [US4] Create fixtures `placeholder-docs`, `policy-denies-process`, `write-all-workflow`, `placeholder-governance` with `labels.toml` under `tests/darnit_baseline/corpus/`
- [ ] T040 [P] [US4] Create fixtures `empty`, `reference-good`, and platform scenarios `platform-no-protection`, `platform-ruleset-protection`, `platform-permission-denied`, `platform-rate-limited` (recorded responses) under `tests/darnit_baseline/corpus/`
- [ ] T041 [US4] Implement the corpus runner (load fixtures and labels, run the sieve with the `gh_api` recorded-response stub, collect per-step/per-outcome conclusions, fail on any false PASS by a step allowed to conclude PASS) in `tests/darnit_baseline/corpus/runner.py` and the pytest entry `tests/darnit_baseline/corpus/test_corpus.py`
- [ ] T042 [US4] Implement `scripts/corpus_report.py` (Markdown and JSON; corpus version digest over fixtures and labels; eligibility for promotion)
- [ ] T043 [US4] Add a CI step running the corpus test in `.github/workflows/ci.yml`

**Checkpoint**: Every step is measured; false PASS fails CI.

---

## Phase 7: User Story 5 - The Baseline implementation follows the new rules (Priority: P2)

**Goal**: Baseline controls re-declared with zero false PASS on the corpus.

**Independent Test**: quickstart.md section 5.

### Tests for User Story 5

- [ ] T044 [P] [US5] Write a test that every Baseline control's steps load under the new validation and that the corpus reports zero false PASS for `openssf-baseline`, in `tests/darnit_baseline/test_baseline_authority.py`

### Implementation for User Story 5

- [ ] T045 [US5] Re-declare presence and pattern steps in `packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml`: `existence = true` only for LE-03.01, QA-02.01, QA-05.01, QA-05.02; all others FAIL-only; add `fail_on_miss` only where a miss genuinely proves failure
- [ ] T046 [US5] Move platform checks written as `exec` + `gh api` + CEL to the `gh_api` handler with `fail_on_status` where a status proves failure, in `packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml`
- [ ] T047 [US5] Ensure every content control ends with an `llm_eval` step (PASS candidate) before `manual`, in `packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml`
- [ ] T048 [US5] Regenerate goldens that pin old results (error-class baseline in `tests/darnit/sieve/`, CLI e2e expectations in `tests/darnit/cli/`, parity expectations in `tests/darnit/parity/fixtures/`) and explain each class of change in the commit message
- [ ] T049 [US5] Audit this repository and one other real repository before and after; record the categorized differences (SC-006) in `specs/041-result-authority-contract/quickstart.md` under a "Validation log" section

**Checkpoint**: Baseline follows the contract.

---

## Phase 8: Polish & Cross-Cutting Concerns

- [ ] T050 [P] Label PENDING, candidates, suggestive FAIL, and asserted PASS in the attestation predicate in `packages/darnit-baseline/src/darnit_baseline/attestation/predicate.py`
- [ ] T051 [P] Render ERROR causes, PENDING kinds, and candidates in markdown and summary outputs in `packages/darnit/src/darnit/tools/audit.py`
- [ ] T052 [P] Update CHANGELOG `[Unreleased]` (result statuses, `gh_api`, `submit_judgment`, ActionPlan change, corpus) in `CHANGELOG.md`
- [ ] T053 [P] Update `docs/SECURITY_GUIDE.md` and CLAUDE.md Sieve Pattern section to describe per-step conclusions and PASS candidates
- [ ] T054 Run quickstart.md end to end and record results under "Validation log" in `specs/041-result-authority-contract/quickstart.md`
- [ ] T055 Run `uv run ruff check .`, `uv run pytest tests/ --ignore=tests/integration/ -q`, `uv run python scripts/validate_sync.py --verbose`; fix failures

---

## Dependencies & Execution Order

- **Setup**: T001 is a separate change that must merge before this branch merges; T002 before implementation.
- **Foundational (T004-T011)**: blocks all stories.
- **US1** and **US2**: after Foundational; independent of each other (both touch `builtin_handlers.py` -- sequence T015/T016 and T021/T022).
- **US3**: after Foundational; independent of US1/US2 except shared `orchestrator.py` (sequence T031 after T011/T024).
- **US4**: runner (T041) needs US2's recorded-response stub (T021); fixtures (T039/T040) can start after Setup.
- **US5**: after US1-US4 (uses all rules and the corpus).
- **Polish**: after the stories it documents.

Story order: Foundational -> (US1, US2, US3) -> US4 -> US5 -> Polish.

## Parallel Opportunities

- Phase 2 tests T004-T006 together.
- US1 tests T012-T014; US2 tests T018-T020; US3 tests T025-T028.
- Corpus fixtures T039 and T040 alongside US1-US3 work.
- Polish T050-T053.

### Parallel example: User Story 3 tests

```text
Task: "Judgment tests in tests/darnit/trust/test_judgments.py"
Task: "submit_judgment tests in tests/darnit/server/test_submit_judgment.py"
Task: "ActionPlan verdict test in tests/darnit/core/test_action_plan_verdicts.py"
Task: "Harness compliance test in tests/darnit/harness/test_harness_compliance.py"
```

## Implementation Strategy

### MVP first

1. Setup and Foundational.
2. US1 (weak evidence cannot PASS) -- the single most important accuracy fix.
3. Validate with quickstart section 1.

### Incremental delivery

1. US1, US2, US3 (all P1): no false PASS from weak evidence, ERROR for broken measurements, no PASS from an unconfirmed judgment.
2. US4: corpus measurement and CI gate.
3. US5: Baseline re-declaration driven by corpus results.
4. Polish.

### Notes

- Keep all documentation ASCII-only; commit with DCO sign-off (`git commit -s`).
- This branch is stacked on feature 040 and is not pushed until 040 merges.
