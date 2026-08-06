---
description: "Tasks for feature 026: `darnit-harness` -- End-to-End Audit Driver with LLM Dispatch"
---

# Tasks: `darnit-harness`

**Input**: Design documents from `specs/026-darnit-harness/`

**Prerequisites**: plan.md (loaded), spec.md (loaded, 3 clarifications), research.md (loaded, 8 decisions), data-model.md (loaded), contracts/{cli,answer-source-protocol,report-format}.md (loaded), quickstart.md (loaded)

**Tests**: Test tasks included. Every FR and SC has explicit test coverage. SC-001 (end-to-end no PENDING_LLM), SC-002 (fail-fast on missing key), SC-005 (four exit codes), SC-008 (LLM cannot manufacture PASS through harness) are load-bearing.

**Organization**: Tasks are grouped by user story per spec.md. Each user story maps to a slice that can ship as its own PR if time slips.

## Format: `[ID] [P?] [Story?] Description`

- **[P]**: Parallelizable with other [P] tasks in the same phase (different files, no deps on unfinished tasks)
- **[Story]**: Which user story (US1, US2, US3, US4)
- File paths are exact and repository-relative

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the new subpackage tree so downstream tasks have a home. No new dependencies (feature 025 already added Pydantic AI).

- [X] T001 Create `packages/darnit/src/darnit/harness/` directory with an empty `__init__.py`.
- [X] T002 [P] Create `tests/darnit/harness/` directory with an empty `__init__.py` and a `fixtures/` subdirectory.

**Checkpoint**: Package layout exists; pytest will discover `tests/darnit/harness/` on the next collection.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build the small typed primitives (exit codes) and the answer-source Protocol scaffolding that ALL four user stories consume. Each task creates a self-contained module.

**CRITICAL**: No user-story tests can proceed until this phase is complete.

- [X] T003 Create `packages/darnit/src/darnit/harness/exit_codes.py` defining `HarnessExitCode(IntEnum)` with values `SUCCESS = 0`, `AUDIT_FAILURES = 1`, `SETUP_ERROR = 2`, `INTERNAL_ERROR = 3` per data-model.md section 5. Include a docstring citing FR-008 + contract CLI-11.
- [X] T004 [P] Create `packages/darnit/src/darnit/harness/answer_sources.py` defining the `AnswerSource` Protocol (per data-model.md section 1, contract AS-1..AS-5) with `runtime_checkable`, `name: str`, `get_answer(key) -> str | None`, `known_keys() -> set[str]`. ASCII-only. Docstring cites contract file.
- [X] T005 [P] In the same file, add `AnswerResolver` dataclass (data-model.md section 2, contract AS-6..AS-8) with ordered `sources: list[AnswerSource]`, `add(source)` (raises `ValueError` on name collision), `resolve(key) -> (answer, source_name)` iterating in list order with LAST match winning, and `summary()` returning a human-readable one-liner.
- [X] T006 In the same file, add `ProjectYamlAnswerSource(local_path: str)` MVP file adapter. Reads `.project/project.yaml` via `darnit.config.loader.load_project_config` (feature 018). Flattens the loaded ProjectConfig into `{context_key: str_value}` matching the schema mapping feature 018 already uses. `name = "project_yaml"`.
- [X] T007 In the same file, add `FileAnswerSource(path: Path | str)` MVP file adapter. Reads YAML or JSON (auto-detected by extension) at shape `{context_key: value}`. On parse error, raises a subclass of `ValueError` naming the offending file + line. `name = "--answers <path>"` (path included so log lines identify which file).
- [X] T008 Write `tests/darnit/harness/test_answer_sources.py`:
  - Protocol conformance: `isinstance(ProjectYamlAnswerSource(...), AnswerSource)` and same for `FileAnswerSource` (AS-4)
  - `AnswerResolver.resolve` returns the LAST-added source's answer when multiple sources have the key (AS-6)
  - `AnswerResolver.add` raises `ValueError` on name collision (AS-7)
  - `FileAnswerSource` reads YAML and JSON round-trip
  - `ProjectYamlAnswerSource` reads a fixture `.project/project.yaml`, extracts `security.contact` as `security_contact`, etc.
  - **MockAnswerSource conformance test**: define a small `MockAnswerSource` implementing the Protocol from an in-memory dict; add to resolver; resolve. Proves the Protocol admits a non-file source (contract "future non-file adapter" gap, FR-005a).

**Checkpoint**: Answer-source machinery is tested and standalone-usable. No harness driver yet.

---

## Phase 3: User Story 1 -- Fleet operator runs a scheduled audit with an API key (Priority: P1) [MVP]

**Goal**: Ship the end-to-end harness path: `darnit harness <path>` runs an audit, dispatches LLM steps via `PydanticAILLMStep`, produces a report, exits with the documented code. Non-interactive; no answers required.

**Independent Test**: `uv run pytest tests/darnit/harness/test_driver.py -v` passes. `MockLLMStep` is injected; no live API needed. The mocked LLM's output appears as `suggestive` evidence; no control ends up `PENDING_LLM`.

### Implementation for User Story 1

- [X] T009 [US1] Create `packages/darnit/src/darnit/harness/driver.py` with `HarnessRun` dataclass (data-model.md section 3). Fields: `local_path`, `framework_name`, `level`, `answer_resolver`, `llm_step`, `per_call_timeout_s=60`, `total_run_timeout_s=900`. Include the lifecycle docstring citing data-model.md "State transitions".
- [X] T010 [US1] In the same file, implement `HarnessRun._check_credentials()` that returns `None` on success or an error message string on failure (per research.md R7): reads `ANTHROPIC_API_KEY`; if unset, returns `"missing ANTHROPIC_API_KEY environment variable"`. Fails fast per SC-002 in <2s (no API ping).
- [X] T011 [US1] In the same file, implement `HarnessRun._initial_audit()` calling `run_sieve_audit(stop_on_llm=True, ...)` from `darnit.tools.audit`. Returns `(results, summary)`. Wraps in a try/except that surfaces framework-load failures as `SetupError` with the message pointing at `darnit init` per CLI-1.
- [X] T012 [US1] In the same file, implement `HarnessRun._dispatch_llm_step(result: CheckResult)` per research.md R6: extracts the `consultation_request` from the result's evidence, constructs a `ConsultationRequest`, wraps `await self.llm_step.evaluate(request)` in `asyncio.wait_for(timeout=self.per_call_timeout_s)`, returns an `LLMConsultationResponse`. On timeout/exception, returns an INCONCLUSIVE response with `reasoning="LLM call failed: <reason>"` (does NOT abort the audit).
- [X] T013 [US1] In the same file, implement `HarnessRun._llm_continuation_loop(results, orchestrator, controls_by_id, contexts)`: iterates every `PENDING_LLM` result, dispatches via `_dispatch_llm_step`, feeds each response into `orchestrator.verify_with_llm_response(control, ctx, response)`, replaces the pending result with the returned `SieveResult` (converted via `to_legacy_dict()`). Increments `self.llm_calls_total` counter each dispatch. Bounded by `total_run_timeout_s` via outer `asyncio.wait_for`.
- [X] T014 [US1] In the same file, implement `HarnessRun._collect_unanswered(results)`: iterates every feedback question across every result; for each unanswered question, calls `self.answer_resolver.resolve(question.context_key)`; if answer found, marks question `answered=True`, sets `answer`, adds to `context_values`. Does NOT re-audit (MVP policy, data-model.md "State transitions" COLLECT_UNANSWERED section): a control whose verdict depends on the newly-answered key RETAINS its pre-Collect status. Does NOT persist to `.project/` (research.md R4 idempotence argument). Returns the mutated results. A control's `verdict` field is what carries forward to the report; the newly captured answer appears only in `context_values` + `feedback_questions[i].answer`, not as a status change.
- [X] T015 [US1] In the same file, implement `HarnessRun.run() -> HarnessReport` as an async method orchestrating the lifecycle from data-model.md "State transitions": startup check -> initial audit -> LLM continuation -> unanswered collection -> report assembly. Emit progress lines at each phase transition per research.md R8 (defer the actual logger config to T023).
- [X] T016 [US1] Create `packages/darnit/src/darnit/harness/report.py` with `HarnessSummary`, `PendingFeedbackEntry`, `HarnessReport` Pydantic models (data-model.md section 4). `HarnessReport.to_json()` uses `model_dump_json(by_alias=True)` to emit the `"pass"` string key (RF-3) via a Pydantic Field alias on `pass_`.
- [X] T017 [US1] In `report.py`, implement `HarnessReport.to_markdown()` per contract report-format.md sections 1-7 (ordered section headings, per-control authority parenthetical, empty-section "None." rule per RF-7). No emoji, no non-ASCII (feature 022/024 convention).
- [X] T018 [US1] In `driver.py`, wire the report-assembly step: build `HarnessReport` from the final results + `self.llm_calls_total` + `self.answer_resolver.summary()` details. Compute `exit_class` from the results (any FAIL -> AUDIT_FAILURES, otherwise SUCCESS).
- [X] T019 [US1] Create a minimal `tests/darnit/harness/fixtures/minimal_llm_repo/` fixture: a repo tree with `.baseline.toml`, `.project/project.yaml` (containing `name` only, no security_contact), and no `SECURITY.md`. This targets the `STAGE1-REF-SECURITY-01` control from feature 025 which has a `suggestive` `llm_extract` + `dispositive` `file_exists`. With no SECURITY.md, the LLM step will be dispatched; the mocked LLM returns a proposed contact string; the file_exists step concludes FAIL.
- [X] T020 [US1] Add a `tests/darnit/harness/conftest.py` with fixtures: (a) `mock_llm_step` returning a `MockLLMStep` with a canned `LLMJudgment(outcome="yes", confidence=0.95, reasoning="mock: security@example.com found in docs")`, (b) `minimal_llm_repo_tree(tmp_path)` copy helper mirroring feature 024's pattern (git init + fake remote + commit), (c) `harness_run_factory(mock_llm_step, minimal_llm_repo_tree)` constructing a `HarnessRun` with the mock LLM injected.
- [X] T021 [US1] Write `tests/darnit/harness/test_driver.py::test_end_to_end_llm_dispatched` covering SC-001 + SC-004: run the harness against the LLM fixture with `MockLLMStep`; assert `report.llm_calls.total > 0`, no result has `status == "PENDING_LLM"`, at least one result includes `llm_extract_prompt` in evidence, exit code follows FAIL count (should be 1 since SECURITY.md is missing).
- [X] T022 [US1] Write `test_driver.py::test_llm_suggestive_cannot_conclude_pass` covering SC-008: force the fixture to a scenario where LLM output would (pre-Stage-1) conclude PASS; verify final control status is FAIL or WARN, NOT PASS. This closes SC-008 in the harness path.
- [X] T023 [US1] Configure a `darnit.harness` logger (module-level `logging.getLogger("darnit.harness")` used across driver.py) and emit the exact progress-line format from research.md R8: `INFO:darnit.harness:[N/M] <control_id> <phase-verb> [<detail>]`. Ensure phases are logged for: control-start, LLM dispatch, verdict resolution. Add a test in `test_driver.py::test_progress_lines_format` that captures caplog records and asserts on the shape.

**Checkpoint**: US1 shipped in isolation. The harness runs end-to-end, dispatches LLM calls via the injected step, produces a report, exits with the right code. Feature 025's safety property (SC-001) holds in this new path.

---

## Phase 4: User Story 2 -- Batch feedback without a human present (Priority: P1)

**Goal**: `AnswerResolver` composes with the driver so declared answers resolve pending feedback questions automatically. `--answers <path>` supplements/overrides the auto-discovered `.project/project.yaml`.

**Independent Test**: `pytest tests/darnit/harness/test_driver.py -k answers` passes. Answers from a config-declared file resolve feedback questions without any interactive prompt.

### Implementation for User Story 2

- [X] T024 [US2] Add `HarnessRun.build_default_resolver(local_path: str, answers_path: str | None = None) -> AnswerResolver` classmethod per data-model.md section 3 (revised). Order: `ProjectYamlAnswerSource(local_path)` first, then `FileAnswerSource(answers_path)` if provided (LAST wins per contract AS-6). Do NOT modify `HarnessRun.__init__` or `__post_init__`; the constructor still takes an already-composed `answer_resolver`. This keeps the class testable in isolation and moves the "look at the filesystem" behavior into the named factory.
- [X] T025 [US2] Write `tests/darnit/harness/fixtures/answers.yaml` example file containing `security_contact: security@example.com` and one other key. Documented as a reference for the quickstart.
- [X] T026 [US2] Add `test_driver.py::test_answers_from_file_resolve_feedback_questions`: fixture repo emits a `security_contact` feedback question; pass `--answers` file with `security_contact: sec@example.com`; assert the question is answered (`answered=True`, `answer="sec@example.com"`) and the value is in the final state's context_values.
- [X] T027 [US2] Add `test_driver.py::test_project_yaml_answers_used_when_no_answers_flag`: fixture repo has `.project/project.yaml` with `security.contact: existing@example.com`; no `--answers` flag; assert the auto-discovered source resolves the question.
- [X] T028 [US2] Add `test_driver.py::test_answers_flag_overrides_project_yaml`: fixture has BOTH sources with different values; assert the `--answers` file value wins (contract AS-6 last-wins precedence).
- [X] T029 [US2] Add `test_driver.py::test_unanswered_questions_appear_in_report_pending_section`: fixture emits a question whose `context_key` is NOT in any answer source; assert `report.pending_feedback` contains an entry naming that control + key. Exit code follows the audit's own pass/fail state (question being unanswered may or may not cause a FAIL depending on the control; test asserts on the pending section, not on exit code).
- [X] T029b [US2] Add `test_driver.py::test_answered_question_does_not_change_control_status_in_mvp` covering the "no re-audit after Collect" MVP policy from data-model.md "State transitions". Fixture emits a control whose LLM/dispositive path already concluded FAIL, plus a feedback question. Provide the answer via `--answers`. Assert: (a) `report.controls[<id>].status == "FAIL"` UNCHANGED post-Collect, (b) the answer IS captured in `report.controls[<id>]` context or in `context_values`, and in `feedback_questions[i].answered=True`, (c) `report.pending_feedback` does NOT contain the now-answered question. This locks the policy in a test so a future "auto-reaudit" change is forced to be a deliberate contract update.

**Checkpoint**: US2 shipped. A fleet operator can pre-declare batch answers and run the harness without human presence.

---

## Phase 5: User Story 3 -- Report format the operator can consume (Priority: P2)

**Goal**: `--format=markdown` (default) and `--format=json` both produce reports matching the contract. `--output <path>` writes to a file; without it, stdout carries the report.

**Independent Test**: `pytest tests/darnit/harness/test_report.py -v` passes. Both formats round-trip; `--output` writes to file with stdout clean.

### Implementation for User Story 3

- [X] T030 [US3] Write `tests/darnit/harness/test_report.py::test_json_report_shape` covering contract report-format.md JSON section + RF-1 + RF-3: build a `HarnessReport` with fixture data; call `to_json()`; assert keys, `authority` present per control, `summary.pass` key (via alias).
- [X] T031 [US3] Add `test_report.py::test_markdown_report_sections` covering RF-1 + RF-7 (empty-section "None."): assert section headings in order, control lines include authority in parentheses, empty Failed section renders as `## Failed Controls\n\nNone.`.
- [X] T032 [US3] Add `test_report.py::test_report_json_hides_api_key` covering RF-4: build a report with fake `ANTHROPIC_API_KEY=secret123` in env; call `to_json()`; assert the string `secret123` does NOT appear anywhere in the output.
- [X] T033 [US3] Add `test_report.py::test_answer_sources_used_lists_all` covering RF-5: HarnessReport built with two sources; assert both appear in `answer_sources_used`.

**Checkpoint**: US3 shipped. JSON is schema-stable for programmatic consumers; Markdown is issue-paste ready.

---

## Phase 6: User Story 4 -- Verifiable exit code contract for CI integration (Priority: P2)

**Goal**: The four exit code classes are distinct and observable via the stderr summary line. CI scripts can pattern-match on either the exit code or the stderr line.

**Independent Test**: `pytest tests/darnit/harness/test_cli.py -v` passes. Each of the four scenarios (missing key, missing repo, FAIL result, all-pass) produces its expected exit code + stderr summary.

### Implementation for User Story 4

- [X] T034 [US4] Modify `packages/darnit/src/darnit/cli.py`: add a `cmd_harness` function following the same pattern as `cmd_audit`/`cmd_run`/`cmd_serve`. Argv per contract cli.md CLI-1..CLI-9. Composes the resolver explicitly via `resolver = HarnessRun.build_default_resolver(args.repo_path, args.answers)`, then constructs `HarnessRun(local_path=..., answer_resolver=resolver, llm_step=PydanticAILLMStep(), ...)`. Calls `asyncio.run(run.run())`. Writes the report to stdout or `--output`. Prints the exit-summary line to stderr (CLI-13). Returns the exit code. Do NOT rely on any auto-discovery inside `HarnessRun`; the explicit factory call is the ONLY place filesystem-based resolver composition happens (data-model.md section 3 contract).
- [X] T035 [US4] In `cli.py`, register the `harness` subparser in the `create_parser()` function (or wherever existing subcommands are registered). Include all flags from contract cli.md: `<repo-path>` positional, `--framework`, `--level`, `--answers`, `--format`, `--output`, `--per-call-timeout`, `--total-run-timeout`. Description string cites the spec.
- [X] T036 [US4] Write `tests/darnit/harness/test_cli.py::test_exit_code_success` for a fixture with all-PASS: invoke `darnit harness` via the argparse dispatcher (following feature 024's `invoke_cmd_run` pattern); assert exit code 0 and stderr summary line matches `harness: complete, N PASS, 0 FAIL, ...`.
- [X] T037 [US4] Add `test_cli.py::test_exit_code_audit_failures` for a fixture with at least one FAIL: assert exit code 1 and stderr summary line names the FAIL count.
- [X] T038 [US4] Add `test_cli.py::test_exit_code_setup_error_missing_key` (SC-002 + FR-002). Unset `ANTHROPIC_API_KEY` via monkeypatch, invoke the harness against a valid fixture path, capture wall-clock elapsed, exit code, and stderr. Assert ALL THREE conditions (SC-002's "before any audit control runs" invariant is only satisfied when all three hold): (a) `exit_code == 2`, (b) `elapsed_seconds < 2.0` (fail-fast timing bound), (c) stderr contains the literal substring `harness: setup_error, missing ANTHROPIC_API_KEY, exit 2`, (d) stderr contains ZERO progress lines matching the regex `^INFO:darnit\.harness:\[\d+/\d+\]` -- this proves NO audit control ran, closing the "before any audit control runs" invariant that would otherwise only be assumed. Without (d), a future regression could leak "one control ran, then noticed the key was missing" and still pass (a)+(b)+(c).
- [X] T039 [US4] Add `test_cli.py::test_exit_code_setup_error_missing_repo`: invoke harness with a nonexistent path; assert exit code 2 and stderr summary names the missing path OR references `darnit init`.
- [X] T040 [US4] Add `test_cli.py::test_stderr_summary_grep_pattern`: run in success + failure modes; assert each stderr summary line matches the grep pattern `^INFO:darnit.harness:harness: (complete|setup_error|internal_error)` from contract CLI-13. Validates SC-009.
- [X] T041 [US4] Add `test_cli.py::test_stdout_clean_when_output_flag_used` covering CLI-16: invoke harness with `--output /tmp/report.md`; assert stdout is empty (or only whitespace) and the file contains the report.
- [X] T042 [US4] Add `test_cli.py::test_help_lists_harness_subcommand` covering CLI-17: invoke `darnit --help`; assert `harness` appears in the output alongside `audit`, `run`, `serve`.

**Checkpoint**: US4 shipped. CI-consumable exit codes + stderr summary + `darnit --help` discovery all work.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Lint, sync validation, ASCII sweep, feature 024/025 baseline reconfirmation, docstring / README updates, and the perturbation verification of SC-008.

- [X] T043 Run `uv run ruff check packages/darnit/src/darnit/harness/ tests/darnit/harness/` and `uv run ruff format packages/darnit/src/darnit/harness/ tests/darnit/harness/`; fix any lint findings.
- [X] T044 Run `uv run python scripts/validate_sync.py --verbose` and confirm green. No TOML schema changes; this validates the harness didn't accidentally break sync.
- [X] T045 [P] Grep for non-ASCII across all new files: `python3 -c "import os; [print(p) for root,_,fs in os.walk('packages/darnit/src/darnit/harness') for f in fs if f.endswith('.py') for p in [os.path.join(root,f)] if any(b > 127 for b in open(p,'rb').read())]"` and same for `tests/darnit/harness/`. Zero unintended hits.
- [X] T046 [P] Perturbation verification of SC-008: temporarily patch `resolve_step_result` to treat suggestive as CONCLUDE_PASS (mirroring feature 025 Slice A T057 procedure); run the harness's US1 test; expect `test_llm_suggestive_cannot_conclude_pass` to fail with a named message. Revert. Retest green. Note the outcome in the PR description under `Verification:`.
- [X] T047 [P] Verify feature 024's `tests/darnit/cli/test_cmd_run_e2e.py` continues to pass on the final commit. `uv run pytest tests/darnit/cli/ -v`; expect 14 pass + 1 skip.
- [X] T048 [P] Verify feature 025's `tests/darnit/sieve/test_authority_terminates.py` continues to pass. `uv run pytest tests/darnit/sieve/test_authority_terminates.py -v`; expect 4 pass.
- [X] T049 [P] Run the full suite: `uv run pytest tests/ -q --deselect tests/darnit/context/test_dot_project_upstream.py::TestUpstreamSpecSync::test_upstream_spec_unchanged`. Expect 0 new regressions. Record the pass count in the PR description.
- [X] T050 Update `CLAUDE.md` "Recent Changes" section: add one line naming feature 026 as "adds `darnit harness` subcommand: end-to-end audit driver with in-band LLM dispatch, non-interactive by default, pluggable AnswerSource Protocol, four-class exit codes." Do NOT add to "Active Technologies" (no new tech stack).
- [ ] T051 [P] Verify quickstart.md's "Run with a config-declared answer file" section works: manually create a temp answers.yaml, invoke `darnit harness /path/to/some/repo --answers /tmp/answers.yaml` with `ANTHROPIC_API_KEY` unset (should exit 2 fast) and with it set (should run to completion if a repo has an LLM-required control). Note the outcome under `Verification:` in the PR description.
- [ ] T052 Update the PR description: cite `specs/026-darnit-harness/spec.md`, `plan.md`, and the three contract files. Note which SCs the PR satisfies (all nine). Include `Contract change:` heading only if any pinned contract was intentionally changed.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001 || T002 (different dirs).
- **Foundational (Phase 2)**: Depends on Setup. Within Phase 2: T003 || T004; T005 depends on T004 (same file); T006/T007 depend on T005; T008 depends on T004-T007.
- **US1 / Slice 1 (Phase 3)**: Depends on Phase 2. Within US1: T009 must land first (types); T010-T014 all edit driver.py in sequence; T015 combines them; T016/T017 in a separate file (report.py) can run in parallel with driver work AFTER T009; T018 depends on all of T015+T016+T017; T019 creates a fixture (independent); T020 creates conftest (depends on T019); T021-T023 depend on T015+T018+T020.
- **US2 (Phase 4)**: Depends on US1's driver landing (T024 modifies HarnessRun). Within US2: T024 first; T025 (fixture file) parallel with T024; T026-T029 depend on T024+T025.
- **US3 (Phase 5)**: Depends on US1's report.py landing. Tests T030-T033 all edit the same test file and run sequentially, but can be authored in any order.
- **US4 (Phase 6)**: Depends on US1-US3 landing (cmd_harness pulls it all together). Within US4: T034/T035 sequential (same cli.py); T036-T042 all edit the same test file; T038 has a timing assertion so shouldn't run in parallel with heavy load.
- **Polish (Phase 7)**: Depends on Phases 3-6. T043-T050 mostly parallel; T052 last.

### User Story Dependencies

- US1 (Slice 1) is standalone-mergeable; ships the end-to-end LLM dispatch on its own.
- US2 depends on US1 (needs `HarnessRun` to compose with).
- US3 depends on US1 (needs `HarnessReport`).
- US4 depends on US1-US3 (`cmd_harness` glues them; tests exercise the four-class exit contract).

### Parallel Opportunities

- Phase 1: T001 || T002.
- Phase 2: T003 || T004; T006 || T007; T008 across many independent test cases.
- Phase 3: T016/T017 || T010-T014 (different files after T009).
- Phase 7: T045/T046/T047/T048/T049/T051 mostly parallel.

Across slices: none. Strict serial (US1 -> US2 -> US3 -> US4) because each depends on artifacts from the previous.

---

## Parallel Example: Phase 2 Foundational

```bash
Task: "Create packages/darnit/src/darnit/harness/exit_codes.py with HarnessExitCode IntEnum"
Task: "Create packages/darnit/src/darnit/harness/answer_sources.py with AnswerSource Protocol scaffold"
```

## Parallel Example: Phase 3 Report Module

```bash
Task: "Create HarnessSummary/PendingFeedbackEntry/HarnessReport Pydantic models in report.py"
Task: "Implement HarnessReport.to_markdown() per contract report-format.md sections 1-7"
```

## Parallel Example: Phase 7 Polish

```bash
Task: "Grep for non-ASCII across all new files"
Task: "Perturbation verification of SC-008"
Task: "Verify feature 024 test_cmd_run_e2e.py still passes"
```

---

## Implementation Strategy

### MVP first (User Story 1 only)

Ships the end-to-end harness for real fleet-operator use: single command, API key from env, LLM dispatch, Markdown report, exit code. Skip US2 (batch answers), US3 (JSON format), US4 (documented exit-code polish) if time is tight -- US1 alone delivers "actually deliverable" per the user prompt that started this feature.

1. Complete Phase 1 + Phase 2 (T001-T008): foundational types + answer sources.
2. Complete Phase 3 (T009-T023): US1 driver + tests.
3. Stop and validate: `pytest tests/darnit/harness/test_driver.py -v` green. If yes, US1 is done; a PR shipping just this closes the "harness delivered" ask.

### Incremental delivery

1. Setup + Foundational -> substrate ready.
2. Add US1 -> harness works end-to-end (MVP).
3. Add US2 -> batch answers for non-interactive CI.
4. Add US3 -> JSON output for pipeline integration.
5. Add US4 -> polished exit-code + stderr contract for CI dashboards.
6. Polish (Phase 7) -> ship.

### Parallel team strategy

Single-author feature. If ever staffed by two: US3 (report format) and US4 (CLI polish) could parallelize after US1 lands, since they touch different files (report.py vs cli.py + test files).

---

## Notes

- [P] tasks = different files (or independent test cases in different classes), no dependencies on incomplete tasks.
- [Story] label maps every user-story-phase task to its user story for traceability.
- Feature 024's `tests/darnit/cli/test_cmd_run_e2e.py` MUST stay green through all slices (SC-005 from feature 025 carries forward). T047 is the mechanical guarantee.
- Feature 025's SC-001 safety property (LLM cannot conclude PASS) MUST hold in the harness path. T022 + T046 are the mechanical guarantees.
- ASCII-only in all new files (FR-015, project convention).
- Do NOT use `--no-verify` on commits. Do NOT add Co-Authored-By footers. No em-dashes / curly quotes / arrows in files.
- Do NOT invoke `PydanticAILLMStep.evaluate()` directly in tests (would require a real API key and hit the network). All test paths use `MockLLMStep`.
- `HarnessRun.run()` is an `async def` -- callers (T034 `cmd_harness`) drive it via `asyncio.run(...)`. Do NOT introduce an event loop inside `run()` itself.
- The `--interactive` flag is NOT part of MVP (spec Assumption A3). Do not add stdin prompting; that's a future feature.
- Persistence is deliberately not called from the harness in MVP (research.md R4 idempotence argument). Do not call `save_context_values` from the driver.
