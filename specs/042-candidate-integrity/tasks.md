# Tasks: Candidate Integrity for Project Values

**Input**: Design documents from `/specs/042-candidate-integrity/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included. Success criteria SC-001 to SC-006 are reproducible test outcomes (no writes, no consumed candidates, byte-identical files), and the project works test-first. Write each story's tests first and confirm they fail.

**Organization**: Grouped by user story so each story can be implemented and verified independently.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1-US6 map to the user stories in spec.md

## Path Conventions

- Core: `packages/darnit/src/darnit/`
- Baseline implementation: `packages/darnit-baseline/src/darnit_baseline/`
- CSL implementation: `packages/darnit-csl/src/darnit_csl/`
- Tests: `tests/darnit/`, `tests/darnit_baseline/`, `tests/darnit_csl/`

---

## Phase 1: Setup (Shared Infrastructure)

- [X] T001 Update `docs/architecture/framework-design.md` first: context value standing (confirmed, candidate, concluded, unknown) and the rule that consumers read only usable values; confirmation records (fields, in-repository `confirmations:` section in `.project/darnit.yaml`, operator-side claim `context_value`, location by trust, precedence); `validity_days` on context definitions and lapse rules; strict detection fallbacks; canonical key names; the `get_pending_data` payload and the new `confirm_project_data` parameters (`accept_candidates`, `confirm_stored`, `reject_stored`, `expires_at`, generated per-key parameters) per contracts/context-confirmation-tools.md; run `uv run python scripts/validate_sync.py --verbose`
- [X] T002 [P] Create shared scratch-repository builders (`R-maint`, `R-rel`, `R-ci`, `R-hand`, `R-legacy` per quickstart.md) and a tree-snapshot helper that asserts no file was created, modified, or deleted, in `tests/darnit/context_integrity/conftest.py` with an empty `tests/darnit/context_integrity/__init__.py`

---

## Phase 2: Foundational (Blocking Prerequisites)

**CRITICAL**: No user story work can begin until this phase is complete.

- [X] T003 [P] Write tests for canonical key names and vocabularies (`ci.provider` and bare `provider` read as `ci_provider`; `github_actions` -> `github`, `gitlab_ci` -> `gitlab`, `azure_pipelines` -> `azure`, `bitbucket_pipelines` -> `other`, `unknown` -> no value) and the value digest (stable under list reordering for maintainers, changes on any content change) in `tests/darnit/config/test_context_keys.py`
- [X] T004 [P] Write resolver tests: standing per key; `usable()` excludes candidates and unknowns; a judgment key (`auto_detect = false`) is never `concluded` at any confidence; a stored value without a matching record is a candidate with origin `stored_unconfirmed` and its location; a matching in-repository record makes it confirmed; an operator-side record makes it confirmed only for that operator; the in-repository record wins when both match; lapse at the earliest of `expires_at` and `last_validated + validity_days` with origin `expired_confirmation`; operator policy `confirmation_expiry_days` has no effect, in `tests/darnit/config/test_context_resolve.py`
- [X] T005 [P] Write loader and writer tests: `load_project_config_checked` returns absent, valid, or invalid (with errors) for `project.yaml` and `darnit.yaml` independently; the writer refuses on invalid and returns the errors; writing `darnit.yaml` preserves sections it does not change (feature 040 `controls:` claims) and comments, in `tests/darnit/config/test_context_writes.py`
- [X] T006 [P] Implement canonical names, vocabularies from framework definitions, legacy mapping, normalization, and the `sha256:` value digest in `packages/darnit/src/darnit/config/context_keys.py`
- [X] T007 [P] Add `ResolvedValue`, `Origin`, and the standing enum per data-model.md in `packages/darnit/src/darnit/config/context_schema.py` (keep `ContextSource` for parsing stored data only)
- [X] T008 [P] Add optional `validity_days` (positive int) to `ContextDefinitionConfig` and carry it into the runtime `ContextDefinition` in `packages/darnit/src/darnit/config/framework_schema.py` and `packages/darnit/src/darnit/config/context_schema.py`
- [X] T009 Add an explicit `expires_at` parameter to `record_confirmation` (context records must not inherit `policy.confirmation_expiry_days`) and a `context_bases` section for candidate bases, keeping the store readable by existing 040/041 code, in `packages/darnit/src/darnit/trust/confirmations.py`
- [X] T010 Implement `load_project_config_checked` (absent | valid | invalid) and ruamel.yaml round-trip read/write helpers that change only targeted keys, keeping `load_project_config` as a thin read-only wrapper, in `packages/darnit/src/darnit/config/loader.py`
- [X] T011 Implement `resolve_context(local_path, definitions, *, target, operator) -> ResolvedContext` (reads stored values through `context_keys`, in-repository `confirmations:` and operator-side `context_value` records, and per-run detection; returns `usable()`, `pending()`, `stored_unconfirmed()`) in `packages/darnit/src/darnit/config/context_resolve.py`
- [X] T012 Implement the single writer (`record_value_confirmation`, `delete_stored_value`) that writes values and in-repository records to `.project/darnit.yaml` for trusted targets or an operator-side record otherwise (requires a trusted-eligible identity), refuses on an invalid project file, and never writes `project.yaml`, in `packages/darnit/src/darnit/config/context_writes.py`

**Checkpoint**: The resolver and writer exist and pass their tests; no consumer uses them yet.

---

## Phase 3: User Story 1 - Audits and queries never write project data (Priority: P1) MVP

**Goal**: Every read path is side-effect free.

**Independent Test**: quickstart.md section 1.

### Tests for User Story 1

- [X] T013 [P] [US1] Write no-write tests on `R-maint`, `R-ci`, `R-legacy`, and an empty repository for `audit_openssf_baseline`, the builtin audit, `get_pending_data`, `remediate_audit_findings(dry_run=True)`, and a harness run with `MockLLMStep`, using the tree-snapshot helper, in `tests/darnit/context_integrity/test_reads_do_not_write.py`
- [X] T014 [P] [US1] Write a structural test that only `config/context_writes.py` (context values and records), `remediation/executor.py` (applied remediation), `locate/locator.py` and `config/resolver.py` (file-location references, not context values), and `config/loader.py` itself call the `.project/` write helpers, in `tests/darnit/context_integrity/test_single_writer.py`

### Implementation for User Story 1

- [X] T015 [US1] Make `get_pending_context` pure: remove the auto-accept branch and its `save_context_value` call and the unused `level` parameter; build pending requests from `resolve_context(...).pending()`, each carrying its candidate and origin, in `packages/darnit/src/darnit/config/context_storage.py`
- [X] T016 [US1] Stop `init_project_config` from seeding detected values and make it build nothing on disk; fix the `init_project_config` MCP tool to create only an empty `.project/darnit.yaml` through the writer when `.project/` is absent (and report instead of overwriting when present), in `packages/darnit/src/darnit/config/loader.py` and `packages/darnit-baseline/src/darnit_baseline/tools.py`
- [X] T017 [US1] Make the audit next-steps section, `get_pending_data`, and the `remediate_audit_findings` guard (in every mode) use only read functions, in `packages/darnit/src/darnit/tools/audit.py` and `packages/darnit-baseline/src/darnit_baseline/tools.py`
- [X] T018 [US1] Harness: `_enumerate_framework_pending` uses the pure pending list; `ProjectYamlAnswerSource` supplies only `usable()` values; collect never persists answers, in `packages/darnit/src/darnit/harness/driver.py` and `packages/darnit/src/darnit/harness/answer_sources.py`
- [X] T019 [US1] Stop persisting ActionPlan `collect_context` answers submitted over MCP (keep them in the run's ActionPlan state as `asserted` answers only; remove `_persist_new_asserted_values`) in `packages/darnit/src/darnit/server/tools/harness_loop.py`; route CLI `darnit run` collect answers (typed by a person) through `context_writes` as confirmations with basis origin `answer` in `packages/darnit/src/darnit/agent/graph.py`; delete `save_context_value`/`save_context_values` once they have no callers; add a test that an MCP `collect_context` submission writes nothing and records no confirmation, in `tests/darnit/context_integrity/test_actionplan_answers_not_persisted.py`

**Checkpoint**: SC-001 holds; no read path writes.

---

## Phase 4: User Story 2 - User-judgment keys are proposed, never concluded (Priority: P1)

**Goal**: Only usable values reach verification, remediation, attestations, and the harness.

**Independent Test**: quickstart.md section 2.

### Tests for User Story 2

- [X] T020 [P] [US2] Write consumer tests: audit applicability and feature 040 context-value assertions see only usable values; a detected maintainers candidate at confidence 0.95 is not used; an attestation contains no unconfirmed value (a regression guard: attestations do not carry context values today, so no implementation task is needed), in `tests/darnit/context_integrity/test_consumers_use_usable.py`
- [X] T021 [P] [US2] Write remediation tests: a template reading an unusable judgment key returns `confirmation required: <key>` regardless of `requires_context`; `default()` in templates does not mask it; remediation `when` evaluates against usable values, in `tests/darnit/remediation/test_confirmation_required.py`
- [X] T022 [P] [US2] Write CSL tests: `remediate_community_spec` without `code_license` (and other judgment parameters) uses confirmed context only and otherwise returns `confirmation required`, in `tests/darnit_csl/test_csl_judgment_params.py`

### Implementation for User Story 2

- [X] T023 [US2] Set `auto_detect = false` on `maintainers` and `security_contact` (keep `allow_sieve_hints` and `hint_sources`) in `packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml`
- [X] T024 [US2] Build audit applicability from `ResolvedContext.usable()` and feed feature 040 `context_value_assertions` only confirmed repository values, in `packages/darnit/src/darnit/tools/audit.py` and `packages/darnit/src/darnit/trust/assertions.py`
- [X] T025 [US2] Make `collect_auto_context` return canonical per-run detections only and read stored values via the resolver, in `packages/darnit/src/darnit/context/auto_detect.py`
- [X] T026 [US2] Add a guarded `context` mapping that raises `ConfirmationRequired(key)` on reading an unusable key, and turn it into a per-control "confirmation required" result, in `packages/darnit/src/darnit/remediation/executor.py`
- [X] T027 [US2] Build the remediation template context and `when` values from the resolver in `packages/darnit-baseline/src/darnit_baseline/remediation/orchestrator.py`; make `check_context_requirements` standing-based in `packages/darnit/src/darnit/remediation/context_validator.py`
- [X] T028 [US2] Default judgment parameters of `remediate_community_spec` to None and fall back to confirmed context only, in `packages/darnit-csl/src/darnit_csl/mcp_tools.py`

**Checkpoint**: SC-002 holds.

---

## Phase 5: User Story 3 - Questions show candidates as data (Priority: P1)

**Goal**: No executable form contains a guessed value; every enum value is reachable; accepting a candidate records it as the basis.

**Independent Test**: quickstart.md section 3.

### Tests for User Story 3

- [X] T029 [P] [US3] Write payload tests for `get_pending_data`: `candidate {value, origin, digest, label}`; no candidate value or configuration example in any `command_template` or answer mapping; `value_map["Yes"]` is the `accept_candidates` form with a placeholder referring to `candidate.digest`, not the digest itself; all enum values in `allowed_values` (no truncation); examples only as `format_hint`, in `tests/darnit_baseline/test_pending_payload.py`
- [X] T030 [P] [US3] Write tests for `confirm_project_data(accept_candidates=...)`: matching digest confirms with basis; mismatched digest refuses and writes nothing, in `tests/darnit/context_integrity/test_accept_candidates.py`
- [X] T031 [P] [US3] Write prompt tests for the remediation preflight and `format_context_prompt`: candidates as labelled data, placeholder-only command templates, in `tests/darnit/remediation/test_placeholder_prompts.py`

### Implementation for User Story 3

- [X] T032 [US3] Rewrite `_build_context_question`, `_build_ask_user_params`, and the `answer_mapping` in `get_pending_data` per the contract (no truncation, examples as hints, accept by digest), in `packages/darnit-baseline/src/darnit_baseline/tools.py`
- [X] T033 [US3] Generate `confirm_project_data` parameters from the framework's context definitions (adds `platform` and CSL keys) and add `accept_candidates`, in `packages/darnit-baseline/src/darnit_baseline/tools.py` and `packages/darnit/src/darnit/server/tools/project_data.py`; update the tool descriptions in `packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml`
- [X] T034 [US3] Replace value-embedding in `_format_preflight_prompt` with candidate data and placeholders in `packages/darnit-baseline/src/darnit_baseline/remediation/orchestrator.py`, and in `format_context_prompt` in `packages/darnit/src/darnit/remediation/context_validator.py`; remove the unused `_format_context_collection_step` and its tests in `packages/darnit/src/darnit/tools/audit.py` and `tests/darnit/test_audit_next_steps.py`
- [X] T035 [US3] Update the darnit-data skill: accept candidates by digest only after the person has answered (fill `candidate.digest` into the `accept_candidates` placeholder at that point, never before), never type a detected value, never submit context answers through the ActionPlan expecting them to be saved, the review flow, correct file locations (`.project/darnit.yaml`), no manual-edit advice that contradicts the tools, in `packages/darnit/src/darnit/skills/darnit-data/SKILL.md`

**Checkpoint**: SC-003 holds.

---

## Phase 6: User Story 4 - Confirmation is recorded and stays distinguishable (Priority: P2)

**Goal**: Confirmations carry who, when, basis, last-validated, and optional expiry; legacy values can be reviewed in one step.

**Independent Test**: quickstart.md section 4.

### Tests for User Story 4

- [ ] T036 [P] [US4] Write confirmation tests: trusted target writes `confirmations.<key>` in `.project/darnit.yaml`; untrusted target writes operator-side only and nothing in the repository; missing owner/repo refuses; `expires_at` recorded; re-confirmation updates `last_validated` and keeps a project-set `expires_at` unless replaced; a hand edit makes the key a candidate with `lapsed` set; new process reads identical standing (SC-006), in `tests/darnit/context_integrity/test_confirmation_records.py`
- [ ] T037 [P] [US4] Write review tests on `R-legacy`: `get_pending_data` lists `stored_unconfirmed` with locations; one call confirms some and rejects others; a rejected `darnit.yaml` value is deleted; a rejected `project.yaml` value returns the file and field and leaves the file byte-identical, in `tests/darnit/context_integrity/test_review_stored.py`

### Implementation for User Story 4

- [ ] T038 [US4] Rewrite the context branch of `confirm_project_data_impl` to require owner/repo, validate against the vocabulary, decide location via `decide_trust`, and write through `context_writes` with who, when, basis, `last_validated`, and optional `expires_at`; fix the result message to name the file actually written, in `packages/darnit/src/darnit/server/tools/project_data.py`
- [ ] T039 [US4] Add `confirm_stored`, `reject_stored`, and `expires_at` to `confirm_project_data` and the `stored_unconfirmed` list to `get_pending_data`, in `packages/darnit-baseline/src/darnit_baseline/tools.py` and `packages/darnit/src/darnit/server/tools/project_data.py`

- [ ] T039a [US4] Scope generated `confirm_project_data` parameters to the server's bound framework only (drop the union across installed frameworks), and register a framework-neutral builtin `confirm_project_data` (context values only: per-key parameters, `accept_candidates`, `confirm_stored`, `reject_stored`, `expires_at`, owner/repo/host, local_path) on every server whose framework does not define its own, the same way `register_judgment_tools` registers `submit_judgment`, in `packages/darnit/src/darnit/server/tools/project_data.py` and `packages/darnit/src/darnit/server/factory.py`; document it in `docs/architecture/framework-design.md` first; test that a CSL-only server exposes it with only `csl_*` keys and that the Baseline tool no longer exposes other frameworks' keys, in `tests/darnit/server/test_confirm_tool_per_framework.py`

**Checkpoint**: SC-006 holds; legacy repositories can be repaired in one call.

---

## Phase 7: User Story 5 - Failed detection is not a value; one name per key (Priority: P2)

**Goal**: No value from a failed lookup; canonical CI provider everywhere.

**Independent Test**: quickstart.md section 5.

### Tests for User Story 5

- [ ] T040 [P] [US5] Write detection tests: `value_if_fail` applies only on a concluded negative; ERROR and INCONCLUSIVE yield no value; `has_releases` with a failing `gh` (recorded response) is unknown and release-gated controls match the unknown case (SC-004), in `tests/darnit/context_integrity/test_detection_failures.py`
- [ ] T041 [P] [US5] Write CI provider tests: confirming an unrelated key on `R-ci` stores nothing for `ci_provider` or stores `github`; legacy `github_actions` reads as `github`; CI controls stay applicable, in `tests/darnit/context_integrity/test_ci_provider_canonical.py`

### Implementation for User Story 5

- [ ] T042 [US5] Remove the non-strict mode from `_run_detect_pipeline` (keep the feature 040 strict semantics for all callers) in `packages/darnit/src/darnit/config/context_storage.py`; update `observe_context_evidence` callers accordingly in `packages/darnit/src/darnit/trust/assertions.py`
- [ ] T043 [US5] Remove `detect_ci` in favour of `detect_ci_provider` and route every read of the CI provider through `context_keys`, in `packages/darnit/src/darnit/context/detectors.py`, `packages/darnit/src/darnit/config/context_storage.py`, and `packages/darnit/src/darnit/config/schema.py` (`get_ci_provider`)

**Checkpoint**: SC-004 holds.

---

## Phase 8: User Story 6 - A user-authored project file is never destroyed (Priority: P2)

**Goal**: No writer replaces or reformats `project.yaml`; invalid files are reported, not overwritten.

**Independent Test**: quickstart.md section 6.

### Tests for User Story 6

- [ ] T044 [P] [US6] Write tests on `R-hand`: audit and `confirm_project_data` leave `project.yaml` byte-identical and return the validation errors; an unparseable `darnit.yaml` blocks writes instead of being rewritten without its `controls:`; an applied remediation updating one field of a valid hand-written `project.yaml` preserves comments, order, and other fields (SC-005), in `tests/darnit/context_integrity/test_user_files_survive.py`

### Implementation for User Story 6

- [ ] T045 [US6] Replace every `load_project_config() or init_project_config()` write pattern with `load_project_config_checked` and a refusal on invalid, and make the remaining `save_project_config` writers use the loader's round-trip helper, in `packages/darnit/src/darnit/server/tools/project_data.py`, `packages/darnit/src/darnit/config/resolver.py`, and `packages/darnit/src/darnit/locate/locator.py`
- [ ] T046 [US6] Make `apply_project_update` patch only the targeted `project.yaml` fields through the round-trip helper (and refuse on invalid, as today) in `packages/darnit/src/darnit/remediation/executor.py`

**Checkpoint**: SC-005 holds.

---

## Phase 9: Polish & Cross-Cutting Concerns

- [ ] T047 [P] Update tests that pinned the old behaviour (bare values read as `user_confirmed`, auto-accept writes, enum truncation, `_CONTEXT_KEY_ORDER` of eight keys, value-embedding prompts, asserted submissions persisted as bare values) in `tests/darnit/config/test_context_storage.py`, `tests/darnit_baseline/test_get_pending_context.py`, `tests/darnit/remediation/test_context_validator.py`, `tests/darnit/server/test_harness_loop_mcp.py`, `tests/darnit/harness/test_answer_sources.py`, `tests/darnit/config/test_context_filtering.py`, `tests/darnit/config/test_loader.py`, `tests/darnit/config/test_framework_context.py`, `tests/darnit/sieve/test_invariants.py`, `tests/darnit/test_audit_next_steps.py`, `tests/darnit/context/test_context_sieve.py`, `tests/darnit/context/test_auto_detect.py`, `tests/darnit/context/test_detectors.py`, `tests/darnit_baseline/test_context_validation_dry_run.py`, `tests/darnit_baseline/test_integration_e2e.py`, `tests/darnit/harness/test_driver.py`, `tests/darnit/harness/conftest.py`, `tests/darnit/agent/test_graph.py`, `tests/darnit/core/test_action_plan_equivalence.py`, `tests/darnit/remediation/test_executor.py`, `tests/darnit/remediation/test_project_update.py`, `tests/darnit_baseline/remediation/test_template_rendering.py`, `tests/darnit_baseline/remediation/test_all_templates.py`, `tests/darnit_baseline/test_remediation_project_integration.py`, `tests/darnit_csl/test_csl.py`, and `tests/integration/test_mcp_server.py`; each change states which requirement replaced the pinned behaviour
- [ ] T048 [P] Update CHANGELOG `[Unreleased]`: context standing and confirmation records; BREAKING: stored values without a record become candidates (review with `confirm_stored`/`reject_stored`); BREAKING: `confirm_project_data` requires owner/repo and accepts candidates by digest; BREAKING: `remediate_community_spec` judgment parameters no longer default; reads never write, in `CHANGELOG.md`
- [ ] T049 [P] Update the "Context System" section of `CLAUDE.md` and `docs/` pages that describe context storage or auto-acceptance, to match framework-design.md
- [ ] T050 Run quickstart.md sections 1-6 and record results under a "Validation log" section in `specs/042-candidate-integrity/quickstart.md` (scratch repositories only; no real organization's settings)
- [ ] T051 File follow-up issues for research R14 items (attestation `project_type`, CSL `coc_policy` vocabulary) without referencing unpublished advisories
- [ ] T052 Run `uv run ruff check .`, `uv run pytest tests/ --ignore=tests/integration/ -q`, `uv run python scripts/validate_sync.py --verbose`, and the corpus report; fix failures

---

## Dependencies & Execution Order

- **Setup (T001-T002)** first; T001 before any code (spec-first rule).
- **Foundational (T003-T012)** blocks all stories. Within it: T006-T008 in parallel; T009 and T010 in parallel; T011 needs T006-T009; T012 needs T010-T011.
- **US1** first (MVP): it removes the write-on-read source of new bad data.
- **US2** after US1 (shares `tools/audit.py` and the Baseline `tools.py`; sequence T017 before T024).
- **US3** after US1 (shares `get_pending_data`); T033 needs the writer (T012).
- **US4** after US3 (T039 extends the same tool signature as T033).
- **US5** independent of US2-US4 after Foundational; T042 touches `context_storage.py` after T015.
- **US6** independent after Foundational; T045 touches `project_data.py` after T038.
- **Polish** last.

## Parallel Opportunities

- Foundational tests T003-T005 together; models T006-T008 together.
- Each story's test tasks are [P] with each other.
- US5 and US6 can proceed in parallel with US2-US4 once Foundational is done, respecting the shared-file notes above.

## Implementation Strategy

1. MVP: Setup + Foundational + US1. Stops new guesses from being written by any audit.
2. Then US2 (nothing consumes candidates) and US3 (prompts safe) to close the P1 set.
3. Then US4 (records and review, which repairs existing repositories), US5, US6.
4. Polish, CHANGELOG, quickstart validation.
