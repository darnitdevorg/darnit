---
description: "Tasks for feature 025: RFC-0001 Stage 1 -- Authority, ActionPlan Protocol, and MCP Loop"
---

# Tasks: RFC-0001 Stage 1

**Input**: Design documents from `specs/025-rfc0001-stage1/`

**Prerequisites**: plan.md (loaded), spec.md (loaded, with 3 clarifications), research.md (loaded), data-model.md (loaded), contracts/{action-plan-protocol,mcp-tools,attestation-authority-field}.md (loaded), quickstart.md (loaded)

**Tests**: Test tasks are included. Every FR and SC has explicit test coverage; SC-001, SC-005, and SC-008 are load-bearing safety pins.

**Organization**: Tasks are grouped by user story per spec.md. Each user story maps to a "slice" per plan.md and can ship as its own PR. Slices A/B/C/D correspond to US1/US2/US3/US4.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Can run in parallel with other [P] tasks in the same phase (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3, US4)
- File paths are exact and repository-relative

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Add the new runtime dependency (Pydantic AI) and confirm the workspace still installs and passes existing tests.

- [X] T001 Add `pydantic-ai-slim[anthropic]` (>= latest stable matching Python 3.11/3.12) to `packages/darnit/pyproject.toml`'s `[project] dependencies` list; do NOT add to `[dependency-groups] dev` (this is a runtime dep, not dev-only per Q3 clarification). Do not add extras or opt-in flags -- required by all users.
- [X] T002 Run `uv sync --dev` and confirm the workspace installs cleanly, then run `uv run pytest tests/darnit/ tests/darnit_baseline/ -q --deselect tests/darnit/context/test_dot_project_upstream.py::TestUpstreamSpecSync::test_upstream_spec_unchanged` and confirm 0 regressions (the deselected upstream-hash test is pre-existing drift, unrelated).

**Checkpoint**: Pydantic AI installed workspace-wide; existing suite green; ready to add new code that imports from it.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Create the type primitives that ALL four user stories consume: the `Authority` Literal, the error types, and the `LLMStep` Protocol scaffold. Nothing here has behavior on its own; each entry is a pure type declaration.

**CRITICAL**: No user-story work can begin until this phase is complete.

- [X] T003 Create `packages/darnit/src/darnit/core/authority.py` defining `Authority = Literal["dispositive", "suggestive", "asserted"]` and a small helper `is_terminal_authority(authority) -> bool` (True for dispositive+asserted). ASCII-only. Module docstring cites data-model.md section 1.
- [X] T004 [P] Create `packages/darnit/src/darnit/core/errors.py` (or extend if it exists) with `OutOfOrderSubmission`, `ResultSchemaMismatch`, and `AuthorityViolation` exception classes per data-model.md section 7. Each carries structured fields (expected_step_id, submitted_step_id, offending_fields, message) accessible after `except` for downstream serialization.
- [X] T005 [P] Create `packages/darnit/src/darnit/core/llm_step.py` with the `ConsultationRequest`, `LLMJudgment`, and `LLMStep` Protocol per research.md R6. Include the `PydanticAILLMStep` class as a skeleton whose `evaluate()` raises `NotImplementedError` for now; concrete implementation lands in Slice A when the reference control exercises it. Include a `MockLLMStep` helper in the same module (or a sibling `_test_helpers.py`) that returns a canned `LLMJudgment` for use in tests.
- [X] T006 Write `tests/darnit/core/test_authority.py` covering: (a) the Literal domain is exactly the three values; (b) `is_terminal_authority` returns True for dispositive/asserted and False for suggestive; (c) an integer or unknown string outside the domain raises at load time when passed through a Pydantic model field that types as `Authority`.
- [X] T007 [P] Write `tests/darnit/core/test_errors.py` covering: `OutOfOrderSubmission` carries `expected_step_id` and `submitted_step_id`; `ResultSchemaMismatch` carries `step_id` and `offending_fields`; `AuthorityViolation` is raisable with an informative message. Each error's `str()` includes the structured fields.
- [X] T008 [P] Write `tests/darnit/core/test_llm_step.py` covering: `MockLLMStep` returns the canned `LLMJudgment`; a class satisfying the `LLMStep` Protocol passes an `isinstance(obj, LLMStep)` runtime-checkable check (add `runtime_checkable` decorator if needed); `PydanticAILLMStep()` construction does NOT require an API key (deferred to `evaluate()` call time).

**Checkpoint**: Type primitives exist and are tested. No runtime behavior changed; existing tests still pass.

---

## Phase 3: User Story 1 -- Authority prevents LLM-only PASS (Priority: P1) [Slice A]

**Goal**: Add `authority` to `HandlerResult` and `CheckResult`; implement the Check-phase execution rule keyed on authority; prove the safety property with SC-001 and SC-008 tests. This slice ships US1 in isolation and is standalone-mergeable.

**Independent Test**: `uv run pytest tests/darnit/sieve/test_strategy_runner.py tests/darnit/sieve/test_authority_terminates.py -v` passes. Deliberate perturbation of the runner's suggestive-can't-conclude branch (per quickstart.md) causes a named test failure.

### Implementation for User Story 1

- [X] T009 [US1] Modify `packages/darnit/src/darnit/sieve/handler_registry.py`: add `authority: Authority` as a required field on `HandlerResult` (no default). Update ALL construction sites in this file and in `sieve/builtin_handlers.py` to pass the authority per data-model.md section 2's migration table (`file_exists`/`exec`/`regex`/`api_call` -> `dispositive`; `llm_eval` -> `suggestive`; `manual` -> `authority = "asserted"` at the step declaration level, resolved at confirmation time).
- [X] T010 [US1] Modify `packages/darnit/src/darnit/sieve/models.py`: add `authority: NotRequired[Authority]` to the `CheckResult` TypedDict per data-model.md section 3. NotRequired because pre-Stage-1 serialized results may lack it; the runner treats absence as "unknown, not yet migrated" and refuses to conclude a control from an authority-less result.
- [X] T011 [US1] Modify `packages/darnit/src/darnit/sieve/orchestrator.py`: add `StepDisposition` enum + `resolve_step_result(step, result, state) -> StepDisposition` function per data-model.md "Check-phase execution rule" section. Encodes the rule from spec FR-003 exactly.
- [X] T012 [US1] Modify `packages/darnit/src/darnit/sieve/orchestrator.py` further: change the per-phase pass loop to consult `resolve_step_result` on every step. A `TERMINATE_ERROR` disposition stops the loop regardless of remaining phases; `ATTACH_EVIDENCE_AND_CONTINUE` attaches evidence and advances; `CONCLUDE_PASS`/`CONCLUDE_FAIL` set the control status and stop the loop. The public function names (`run_sieve_audit`, `SieveOrchestrator.run`) stay unchanged; the internal decision function is what's swapped.
- [X] T013 [US1] Modify `packages/darnit/src/darnit/config/control_loader.py`: implement the legacy-phase translator per research.md R2. Reading a control TOML with `[[controls.X.passes]]` blocks that lack an explicit `authority` field, infer authority per handler-name table: `file_exists`/`exec`/`regex`/`api_call` -> `dispositive`; `llm_eval` -> `suggestive`; `manual` -> `asserted`. Log at DEBUG which controls were auto-inferred. Do NOT modify any TOML files in this task -- pure loader-side translation.
- [X] T013b [US1] Write `tests/darnit/config/test_legacy_phase_translation.py::test_legacy_phase_toml_round_trip_lossless` covering SC-006 + FR-015: create a fixture TOML with a control using the legacy `[[controls.X.passes]]` blocks (multiple handlers, mix of handler types); parse it through `control_loader`; translate to strategy list (T013); re-serialize (via a helper that dumps the internal representation back to TOML); re-parse; assert semantic equality -- same handler names in same order, same params, same effective authority per handler. Add at least three cases: (a) a control with only `file_exists`; (b) a control with `file_exists` then `llm_eval` then `manual`; (c) a control with `exec` + `regex` in the same pass (compound step).
- [X] T014 [US1] Modify `packages/darnit/src/darnit/config/framework_schema.py` (or wherever `PassConfig` lives): add optional `authority: Authority | None = None` field so authors CAN write explicit authority in TOML. Load-time validation: if a step's declared `handler` produces `HandlerResult.authority` that conflicts with an explicit TOML `authority`, raise `AuthorityViolation`. If TOML omits `authority`, use the handler's default.
- [X] T015 [US1] Write `tests/darnit/sieve/test_strategy_runner.py` covering: `resolve_step_result` returns each `StepDisposition` for the appropriate (authority, outcome) combination; the full `run_sieve_audit` produces PASS from a single dispositive step, INCONCLUSIVE from a suggestive-only strategy list, ERROR that terminates the list, and CONCLUDE_PASS that terminates on first hit.
- [X] T016 [US1] Write `tests/darnit/sieve/test_authority_terminates.py::test_llm_only_control_never_passes` covering SC-001: a fixture control with a single `llm_eval` step (marked `authority = "suggestive"`), invoked with a `MockLLMStep` returning `LLMJudgment(outcome="yes", confidence=0.99)`, produces `CheckResult.status == "WARN"` (inconclusive), NOT `"PASS"`. Evidence carries the LLM output with `authority = "suggestive"`.
- [X] T017 [US1] Add `test_dispositive_after_suggestive_still_terminates` in the same file: strategy list `[llm_eval (suggestive), file_exists (dispositive)]` against a fixture where file exists; assert PASS from `file_exists` AND the LLM's suggestive evidence is preserved on the result.
- [X] T018 [US1] Add `test_error_from_dispositive_terminates_without_escalation` in the same file: strategy list `[exec (dispositive, returns ERROR), llm_eval (suggestive)]`; assert status is `ERROR` (not INCONCLUSIVE); assert the LLM step was NOT invoked.
- [X] T019 [US1] Create `tests/darnit_baseline/fixtures/prompt_injection_repo/` per research.md R9: a repo with README containing a prompt-injection payload targeting the LLM. Include `.baseline.toml`, `.project/project.yaml`, `README.md` with the injection payload. ASCII-only content in files (the payload itself is ASCII).
- [X] T020 [US1] Write `tests/darnit_baseline/controls/test_prompt_injection_safety.py::test_prompt_injection_does_not_produce_false_pass` covering SC-008: audits the prompt_injection_repo with a `MockLLMStep` that naively echoes the injection ("outcome=yes, high confidence"). Asserts the affected control's status is `WARN` (inconclusive), NOT PASS. Asserts the LLM's output IS captured as evidence with `authority = "suggestive"`.
- [X] T021 [US1] Run existing regression sweep: `uv run pytest tests/darnit_baseline/ tests/darnit/sieve/ tests/darnit/cli/ -q`. All pre-existing tests MUST still pass (the authority additions are back-compat by design). The `tests/darnit/cli/` inclusion is deliberate -- feature 024's E2E baseline could regress if the runner change silently alters `cmd_run` output, and Slice A should ship with that baseline confirmation, not defer it to Slice B (T033). If any existing test fails, either the migration table (T009) is wrong, the loader translator (T013) has a bug, OR the runner rule (T012) altered output; fix before proceeding.

**Checkpoint**: Slice A ships. Safety property is mechanically enforced. Every existing audit continues to work; new LLM-only strategy lists cannot manufacture PASS.

---

## Phase 4: User Story 2 -- ActionPlan protocol replaces inline route() (Priority: P1) [Slice B]

**Goal**: Extract `route()` from `cmd_run` into a public typed `ActionPlan` protocol in `darnit.core.action_plan`. `HarnessState` is a Pydantic model derived from today's `AuditState`. `cmd_run` refactors to consume the new protocol internally while keeping feature 024's `test_cmd_run_e2e.py` passing without modification.

**Independent Test**: `uv run pytest tests/darnit/core/test_action_plan.py tests/darnit/cli/test_cmd_run_e2e.py -v` passes. The `test_action_plan_equals_cmd_run` test asserts direct-Python protocol driving produces the same final state as `darnit run` on the feature-024 fixture.

### Implementation for User Story 2

- [X] T022 [US2] Create `packages/darnit/src/darnit/core/action_plan.py` with `StrategyStep`, `ActionPlan`, `HarnessState`, and `EvidenceItem` as Pydantic models per data-model.md sections 4-6. `HarnessState` is a schema evolution of today's `AuditState` (`packages/darnit/src/darnit/agent/state.py`) that adds `current_position: int`, `evidence: dict[str, list[EvidenceItem]]`, and enforces `model_config = ConfigDict(extra="forbid")`. All fields must be JSON-serializable; no `Path`, callable, or handle types.
- [X] T023 [US2] In `packages/darnit/src/darnit/core/action_plan.py`, implement `next_action(state: HarnessState) -> ActionPlan | None` per data-model.md "State transitions" section. Pure function; does not mutate state.
- [X] T024 [US2] In the same file, implement `submit_result(state: HarnessState, step_id: str, result: dict) -> HarnessState` per data-model.md "State transitions" section. Raises `OutOfOrderSubmission` and `ResultSchemaMismatch` per spec FR-008/FR-009 and contract A3/A4. Applies `resolve_step_result` (from T011) to determine `StepDisposition`. Pure function; returns new state.
- [X] T025 [US2] Modify `packages/darnit/src/darnit/agent/state.py` to re-export `HarnessState` as `AuditState` for backward compatibility (per data-model.md section 5 "Backward compatibility"). Existing imports of `AuditState` MUST continue to work. Add a `# TODO(025): remove after downstream migration` comment on the re-export.
- [X] T026 [US2] Modify `packages/darnit/src/darnit/agent/graph.py`: change `route(state)` into a thin adapter that internally calls `next_action(state)` and translates the returned `ActionPlan | None` into today's four-string return values ("audit" | "collect_context" | "remediate" | "end") per research.md R10 point 3. Preserves the existing `route()` signature so no downstream caller breaks.
- [~] T027 [US2] DEFERRED to Slice C. Rationale: T026 already makes `route()` a thin adapter around `next_action()`, so `cmd_run` consumes the ActionPlan protocol INDIRECTLY through `route`. The observable US2 property (SC-002: driving via the protocol produces equal results to `darnit run`) is proven by T031's equivalence test, which drives via `next_action` / `submit_result` directly and asserts equality with `cmd_run`'s output. Feature 024 baseline is preserved. Extracting `drive_action_plan` as a named helper adds no observable value in Slice B; deferred to Slice C where the MCP tool wrapper naturally shapes the shared helper. Existing CLI-side persistence via `graph.collect_context` is unchanged (feature 018 mechanism preserved).
- [X] T028 [US2] Write `tests/darnit/core/test_action_plan.py::test_next_action_pure_no_mutation` covering contract A1: `next_action(state)` does not mutate `state`; a deep-copy comparison of `state` before/after the call returns equal.
- [X] T029 [US2] Add `test_submit_result_out_of_order_raises` in the same file covering contract A3 + FR-008: calling `submit_result(state, "wrong_step_id", result)` raises `OutOfOrderSubmission` whose `expected_step_id` and `submitted_step_id` are set correctly; the state is NOT modified (deep-copy equal).
- [X] T030 [US2] Add `test_submit_result_schema_mismatch_raises` in the same file covering contract A4 + FR-009: calling `submit_result` with a result payload that lacks a required field from the step's `result_schema` raises `ResultSchemaMismatch` naming the offending field; state NOT modified.
- [X] T031 [US2] Add `test_action_plan_equals_cmd_run` in the same file covering SC-002 + US2 acceptance #1: drive the ActionPlan protocol against the feature-024 `minimal_repo_tree` fixture (import the copy helper from `tests/darnit/cli/conftest.py`) via a manual `next_action` / `submit_result` loop; assert the final `state.audit_results` (by control id + status) and `state.feedback_questions` (by set-equality on `(control_id, context_key)`) match what `darnit run` produces on the same fixture.
- [~] T031b [US2] DEFERRED with T027. The CLI-side persistence path is unchanged in Slice B (`graph.collect_context` -> `save_context_values` from feature 018 still fires exactly as before). The dedicated `drive_action_plan` persistence test lands in Slice C alongside T027.
- [X] T032 [US2] Add `test_harness_state_json_roundtrip` in the same file covering contract A7: build a non-trivial `HarnessState`; assert `HarnessState.model_validate_json(state.model_dump_json()) == state`. Cover both empty and populated states.
- [X] T033 [US2] Run `uv run pytest tests/darnit/cli/test_cmd_run_e2e.py -v` and confirm all 14 pass + 1 skip. If any test fails, either (a) revert the `cmd_run` refactor changes and fix, OR (b) update the corresponding feature-024 contract item AND its assertion in the same commit, with a `Contract change:` note in the PR description (per feature 024 quickstart). Silently editing the assertion is NOT permitted.
- [X] T034 [US2] Run full sweep `uv run pytest tests/darnit/ tests/darnit_baseline/ -q --deselect tests/darnit/context/test_dot_project_upstream.py::TestUpstreamSpecSync::test_upstream_spec_unchanged` and confirm 0 new regressions.

**Checkpoint**: Slice B ships. The pipeline loop is a public typed contract; `cmd_run` uses it internally; feature 024's baseline is preserved.

---

## Phase 5: User Story 3 -- Coding agent walks the loop over MCP (Priority: P1) [Slice C]

**Goal**: Expose `run_next_action` / `submit_action_result` as MCP tools that take `HarnessState` on input and return the new state (Q1 clarification: client-owned state). Three-way equivalence test (direct-Python == CLI == MCP) locks in the "one core, two drivers" premise.

**Independent Test**: `uv run pytest tests/darnit/server/test_harness_loop_mcp.py -v` passes. The three-way equality test surfaces divergence between any two of {direct-call, CLI, MCP} on the same fixture.

### Implementation for User Story 3

- [X] T035 [US3] Create `packages/darnit/src/darnit/server/tools/harness_loop.py` implementing the `run_next_action(state: dict) -> dict | None` and `submit_action_result(state: dict, step_id: str, result: dict) -> dict` MCP tool functions per `contracts/mcp-tools.md`. Both tools validate `state` structurally at the boundary (contract M2), call the direct-Python `next_action` / `submit_result`, and translate `OutOfOrderSubmission` / `ResultSchemaMismatch` into structured error responses (contract M3). No print, no stdout (contract M6). `submit_action_result` MUST mirror the CLI's persistence hook: if the returned state's `context_values` gained keys via an `asserted` submission (delta between input and output states), the wrapper MUST call `save_context_values` on those new keys per data-model.md "Persistence hook" -- so an MCP-driven audit persists confirmations to disk the same way `darnit run` does. Persistence failure is logged but does not fail the MCP call (the in-memory state still holds the values).
- [X] T036 [US3] Register the two tools in `packages/darnit/src/darnit/server/factory.py` (or equivalent registration site) using the existing `server.add_tool(handler, name=, description=)` pattern. Names finalize as `run_next_action` and `submit_action_result`; descriptions cite `contracts/mcp-tools.md`.
- [X] T037 [US3] Write `tests/darnit/server/test_harness_loop_mcp.py::test_mcp_walks_loop_to_termination` per research.md R8: use in-process `fastmcp.Client` connected to a `fastmcp.Server` instance; drive the loop against the feature-024 `minimal_repo_tree`; assert termination occurs and final state is well-formed.
- [X] T038 [US3] Add `test_mcp_equals_direct_equals_cli` in the same file covering SC-003 + US3 acceptance #3: three-way equality on the same fixture -- direct-Python protocol result, `darnit run` result, MCP-driven result. Uses the equality contract from US2 acceptance #1 (control-id + status; feedback questions by set-equality).
- [X] T039 [US3] Add `test_mcp_out_of_order_returns_structured_error` in the same file covering FR-012 + contract M3: submit a result for a step id that is not the current expected one; assert the MCP tool returns a structured error whose fields (`expected_step_id`, `submitted_step_id`) match what the direct-call `OutOfOrderSubmission` carries.
- [X] T040 [US3] Add `test_mcp_schema_mismatch_returns_structured_error` covering FR-012 + contract M3 for the schema-mismatch case. Same shape as T039 for `ResultSchemaMismatch`.
- [X] T041 [US3] Add `test_mcp_state_roundtrips_through_json` covering contract M7: the state returned by `run_next_action` MUST validate-and-load as a `HarnessState` in the next call without loss. Emit -> serialize -> submit-back -> assert equal.
- [X] T042 [US3] Add `test_mcp_tools_discoverable_via_list_tools` covering contract M4: instantiate the MCP server, call `list_tools`, assert both `run_next_action` and `submit_action_result` appear with non-empty descriptions.
- [X] T042b [US3] Add `test_mcp_asserted_submission_persists_to_project_yaml` covering the MCP-side persistence hook from T035: use the in-process fastmcp.Client to drive a fixture whose control emits a feedback question; supply the confirmation via `submit_action_result`; assert the fixture's `.project/project.yaml` gained the confirmed value. Mirrors T031b for the MCP driver.
- [X] T043 [US3] Run `uv run pytest tests/darnit/ tests/darnit_baseline/ -q --deselect tests/darnit/context/test_dot_project_upstream.py::TestUpstreamSpecSync::test_upstream_spec_unchanged` and confirm 0 regressions.

**Checkpoint**: Slice C ships. The MCP surface is a first-class driver of the same loop as `darnit run`. Coding agents can walk the loop step-by-step.

---

## Phase 6: User Story 4 -- SECURITY.md reference control + acceptance gate (Priority: P1) [Slice D]

**Goal**: Wire the `STAGE1-REF-SECURITY-01` control per research.md R5 into `darnit-baseline`; add the attestation authority field per contract `attestation-authority-field.md`; prove the acceptance gate with SC-004/SC-007 end-to-end tests exercising both CLI and MCP paths.

**Independent Test**: `uv run pytest tests/darnit_baseline/controls/test_security_md_reference.py tests/darnit_baseline/attestation/test_authority_field.py -v` passes. The end-to-end SECURITY.md flow (Check -> Collect -> Remediate -> re-Check) completes identically via CLI and via MCP.

### Implementation for User Story 4

- [X] T044 [US4] Modify `packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml`: add the `[controls."STAGE1-REF-SECURITY-01"]` block per research.md R5 with the four-step strategy list (dispositive `file_exists`, suggestive `llm_extract`, asserted `manual` with `context_key = "security_contact"`, remediation `create_security_md`). Verify `create_security_md` handler and `security_policy_minimal.tmpl` template already exist in baseline; if either is missing, halt this task and escalate (out-of-scope to add new remediation handlers in this stage).
- [X] T045 [US4] Add an `llm_extract` handler to `packages/darnit/src/darnit/sieve/builtin_handlers.py` (or wherever the sieve handlers live) with `authority = "suggestive"`. Reads files matching a glob, passes their content plus the step's `prompt` to the injected `LLMStep`, returns a `HandlerResult` with the LLM's judgment attached as evidence. This is a handler; it does NOT decide -- the runner's authority check does.
- [X] T046 [US4] Modify `packages/darnit-baseline/src/darnit_baseline/attestation/` (find the module that constructs the predicate; commonly `attestation.py` or `builder.py`) to include `authority` on each result entry per contract T1/T2/T5. The predicate type string `https://openssf.org/baseline/assessment/v1` does NOT change (contract T1). Every result gets the field; a missing authority is a bug the reader flags (contract T2).
- [X] T047 [US4] Wire `PydanticAILLMStep`'s `evaluate()` method with actual Pydantic AI Agent construction per research.md R6. Use `pydantic_ai.Agent(model='anthropic:claude-sonnet-4-6', result_type=LLMJudgment)`. Cache the `Agent` instance per-process. Do NOT hard-code the API key path; the SDK reads `ANTHROPIC_API_KEY` from env. If no key is set, the `evaluate()` call raises a clear error identifying the missing env var.
- [X] T048 [US4] Create `tests/darnit_baseline/controls/test_security_md_reference.py::test_first_run_reports_inconclusive_no_security_md` covering US4 acceptance #1: fixture repo lacks SECURITY.md; audit reports `STAGE1-REF-SECURITY-01` as inconclusive; dispositive `file_exists` returns FAIL (no file); the LLM step (mocked) proposes a contact; the proposal is attached as `authority = "suggestive"` evidence but does NOT conclude.
- [X] T049 [US4] Add `test_confirmation_persists_and_second_run_passes` covering US4 acceptance #2 + #3: after confirming `security_contact` via Collect (writes to `.project/`), the Remediate phase generates SECURITY.md with the confirmed contact; re-run audit; control now reports PASS from dispositive `file_exists`; earlier suggestive LLM evidence is preserved as historical context in the attestation but is not authority for the PASS.
- [X] T050 [US4] Add `test_cli_and_mcp_produce_equal_authority_breakdowns` covering US4 acceptance #4 + SC-004: run the full flow via `invoke_cmd_run` (feature-024 helper) AND via the MCP tool chain; assert equal `audit_results` (control-id + status) and equal per-result authority values across the two paths.
- [X] T051 [US4] Create `tests/darnit_baseline/attestation/test_authority_field.py::test_stage1_output_carries_authority_per_result` covering SC-007 + contract T2: run an audit; extract the produced attestation; assert every `results[i].authority` is present and in the Literal domain.
- [X] T052 [US4] Add `test_older_reader_still_verifies` in the same file covering contract T3: load the Stage-1 attestation through a stub reader that permits unknown JSON keys (mimicking a pre-Stage-1 reader with a permissive schema); assert verification succeeds and PASS/FAIL/inconclusive shape is unchanged.
- [X] T053 [US4] Add `test_newer_reader_rejects_by_authority_accept_list` in the same file covering contract T4 + FR-005: instantiate a stub reader with `accept_list = {"dispositive"}`; feed it a result with `authority = "asserted"`; assert the reader rejects the result. Feed a result with `authority = "dispositive"`; assert acceptance.
- [X] T054 [US4] Update `packages/darnit-baseline/src/darnit_baseline/attestation/` module docstring per research.md R4 with the "Stage 1 adds `authority` per result; predicate type remains v1; consumers with field-strict validation must update" migration note. ASCII-only.

**Checkpoint**: Slice D ships. Stage 1's acceptance gate closes -- SECURITY.md control runs end-to-end via BOTH drivers with authority-tracked evidence; attestation carries authority additively; older readers still work.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Final quality checks, docs, and PR-side wrap-up. Applies to whichever slice is being submitted.

- [X] T055 Run `uv run ruff check packages/darnit/ packages/darnit-baseline/ tests/darnit/ tests/darnit_baseline/` and `uv run ruff format packages/darnit/ packages/darnit-baseline/ tests/darnit/ tests/darnit_baseline/`; fix any lint findings.
- [X] T056 Run `uv run python scripts/validate_sync.py --verbose` and confirm green. Any TOML schema drift from Slice A's `authority` field addition surfaces here.
- [X] T057 [P] Manually verify the safety-property pin actually pins per `specs/025-rfc0001-stage1/quickstart.md` "Verify the safety property actually pins" procedure. Note the outcome in the PR description under `Verification:`.
- [X] T058 [P] Grep for non-ASCII across all new/modified files: `python3 -c "import os; [print(p) for root,_,fs in os.walk('.') for f in fs if f.endswith(('.py', '.md', '.toml')) for p in [os.path.join(root,f)] if any(b > 127 for b in open(p,'rb').read())]"`. Confirm zero unintended hits (feature 022/024 patterns; FR-017).
- [ ] T059 [P] For each slice's PR: update the description to cite the spec + relevant contract files; note which SCs the slice satisfies; note whether the slice is Complete stage-wise (only Slice D truly closes the gate). Include the "Contract change:" heading if any pinned contract item was intentionally changed.
- [X] T060 [P] Verify `tests/darnit/cli/test_cmd_run_e2e.py` (feature 024 baseline) continues to pass on the final Stage 1 commit. This is SC-005; a green run here is the mechanical guarantee that Stage 1's refactor did not silently regress `darnit run` observable behavior.
- [X] T061 Update `CLAUDE.md` "Active Technologies" section (around line 351) to note that Pydantic AI is a required runtime dep of `darnit-core` as of Stage 1. Do NOT add "Recent Changes" for each slice individually; a single Stage 1 entry at the top of the Recent Changes list is sufficient.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001 gates T002 (dep add before sync). No downstream dependencies on ordering beyond that.
- **Foundational (Phase 2)**: Depends on Setup. Within Phase 2: T003 gates T006 (authority tests need the type); T004/T005 are [P] alongside T003; T006/T007/T008 are [P] alongside each other.
- **US1 / Slice A (Phase 3)**: Depends on Phase 2. Within US1: T009 (HandlerResult authority) must land before T011-T012 (runner uses HandlerResult.authority); T010 (CheckResult authority) is independent of T009 and can run in parallel; T013 (loader translator) depends on T009 for the migration table; T014 (schema validation) depends on T009 + T013; tests T015-T020 all depend on T009-T014 landing; T021 is a final regression sweep.
- **US2 / Slice B (Phase 4)**: Depends on Phases 2+3. Within US2: T022 (types) gates T023 (next_action) and T024 (submit_result); T025 (AuditState re-export) is independent and can run in parallel with T023/T024; T026 (route adapter) needs T023; T027 (cmd_run refactor) needs T022-T026 all landed; tests T028-T032 need the core types (T022-T024); T033 is the feature-024 regression gate; T034 is the full sweep.
- **US3 / Slice C (Phase 5)**: Depends on Phase 4. Within US3: T035 (MCP tools) needs T022-T024; T036 (registration) needs T035; tests T037-T042 need both landed.
- **US4 / Slice D (Phase 6)**: Depends on Phases 3-5. Within US4: T044 (TOML) is a config change; T045 (`llm_extract` handler) is independent of T044 but is used by the strategy list T044 declares; T046 (attestation authority) is independent of T044-T045; T047 (real Pydantic AI wiring) is a code change independent of the others; tests T048-T053 depend on the corresponding implementation tasks landing.
- **Polish (Phase 7)**: Depends on whichever slices are being submitted. T055-T056 run sequentially (lint then sync validation); T057/T058/T059/T060 are all [P].

### User Story Dependencies

- US1 (Slice A) is standalone-mergeable. Ships the safety property alone.
- US2 (Slice B) depends on US1 being merged (HarnessState carries CheckResult with authority).
- US3 (Slice C) depends on US2 being merged (needs ActionPlan protocol as its data shape).
- US4 (Slice D) depends on all three previous slices being merged (the acceptance gate exercises all of them).

### Parallel Opportunities

- Phase 2: T003 || T004 || T005 (three different files); T006 || T007 || T008.
- Phase 3: T009 || T010 (different classes/files); then T013 || T014 after T009 lands.
- Phase 4: T022 || T025; then T023 || T024 after T022 lands.
- Phase 5: T037 || T038 || T039 || T040 || T041 || T042 (all different test methods in the same file; a maintainer can author them in any order once T035 is in place).
- Phase 6: T044 || T045 || T046 || T047 (different files, mostly independent); T048-T053 all [P] once the implementation tasks land.
- Phase 7: T057 || T058 || T059 || T060.

Across slices: none. Slices A -> B -> C -> D is a strict order because each depends on the previous slice's public types.

---

## Parallel Example: Phase 2 Foundational Types

```bash
Task: "Create packages/darnit/src/darnit/core/authority.py with the Literal + is_terminal_authority helper"
Task: "Create packages/darnit/src/darnit/core/errors.py with the three exception classes"
Task: "Create packages/darnit/src/darnit/core/llm_step.py with the Protocol + skeleton Pydantic AI adapter + MockLLMStep"
```

## Parallel Example: Slice D Attestation Tests

```bash
Task: "Add test_stage1_output_carries_authority_per_result covering SC-007"
Task: "Add test_older_reader_still_verifies covering contract T3"
Task: "Add test_newer_reader_rejects_by_authority_accept_list covering T4 + FR-005"
```

---

## Implementation Strategy

### MVP-per-slice

Each of Slices A/B/C/D is a mergeable MVP for its user story. The recommended order:

1. Ship Slice A first. Real safety improvement; every subsequent stage benefits.
2. Ship Slice B second. Structural refactor; unblocks MCP work.
3. Ship Slice C third. MCP surface; enables coding-agent driver.
4. Ship Slice D last. Acceptance gate; closes Stage 1.

If time or attention slips, the stage is not "closed" until Slice D lands, but Slices A-C carry meaningful independent value.

### Incremental delivery within a slice

Each slice's PR follows: (a) types + primitives + tests for them; (b) integration into existing code; (c) refactor of consumers (only Slice B); (d) end-to-end tests. Ship each PR only when its slice's independent test criterion (Phase intro block) passes.

### Parallel team strategy

Slices B, C, D can be prepared in parallel branches once Slice A lands (they all depend on A but not on each other's implementation, only on each other's contract). Coordination cost is low because the ActionPlan protocol contract file is the shared boundary; each slice's PR either doesn't touch it or updates it explicitly.

---

## Notes

- [P] tasks = different files (or independent test methods), no dependencies on other unfinished tasks.
- [Story] label maps every user-story-phase task to its user story for traceability against spec.md.
- Feature 024's `tests/darnit/cli/test_cmd_run_e2e.py` MUST stay green throughout. SC-005 is the enforcement mechanism. If a test needs to change, it is a `Contract change:` in feature 024's terms and follows feature 024's quickstart procedure.
- Feature 022's `list[CheckResult]` typing is the substrate for `HarnessState.audit_results`. Preserve the six-status Literal; the `authority` addition is a schema evolution, not a rewrite of `CheckResult`.
- Do NOT use `--no-verify` on commits. Do NOT add Co-Authored-By footers (per project policy). ASCII-only in every new/modified file (FR-017).
- Do NOT gate Pydantic AI behind an install extra or user-facing flag (Q3 clarification; see `memory/feedback_no_deterministic_only_tier.md`). It is a required runtime dep. Attempts to make it optional would recreate the drift I already saved memory to correct.
- The `manual` step type is not a handler with side effects; it is a placeholder that surfaces an `ActionPlan(expected_result_kind="user_input")` to the caller. The caller (CLI or MCP agent) is responsible for prompting the human. No handler code needs to know about manual steps beyond emitting an `EvidenceItem` with `authority = "asserted"` on confirmation.
- The `PydanticAILLMStep.evaluate()` implementation lands in T047, not earlier, so Slices A-C can proceed with `MockLLMStep` in tests without requiring a real API key.
