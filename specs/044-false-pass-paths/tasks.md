# Tasks: Close Remaining False-PASS Paths

**Input**: Design documents from `/specs/044-false-pass-paths/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/, quickstart.md

**Tests**: Included. SC-001 to SC-006 are test outcomes, and the project works test-first. Write each story's tests first and confirm they fail.

**Organization**: Grouped by user story. Registration metadata and the template fix are foundational because strict loading and the expression check depend on them.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: US1-US4 map to the user stories in spec.md

## Path Conventions

- Core: `packages/darnit/src/darnit/`
- Baseline: `packages/darnit-baseline/src/darnit_baseline/`
- Reproducibility: `packages/darnit-reproducibility/src/darnit_reproducibility/`
- Tests: `tests/darnit/`, `tests/darnit_baseline/`, `tests/darnit_reproducibility/`

Commits: `git commit -s` with an `Assisted-by: Claude:claude-opus-5-5` trailer, and no Co-authored-by line.

---

## Phase 1: Setup

- [X] T001 Update `docs/architecture/framework-design.md` first, then run `uv run python scripts/validate_sync.py --verbose`. Changes, per contracts/step-contract.md and research R1-R8:
  - CEL table: names per step type; remove `response.headers` and regex `files`/`matches`; add `project` (usable values) and the repository-aware `file_exists`.
  - Rule: an expression that fails to evaluate or is not boolean makes the step ERROR (`evaluation`).
  - Step registration: `settings`, `expression_names`, and refusal of name collisions.
  - Strict loading: control keys, step keys, unregistered step types (and ERROR `missing_tool` for operator-supplied controls), expression references.
  - Reproducibility step types: ceiling `{"fail"}`.
  - `gh_api` `evidence_fields`, and the `/user` rule.
- [X] T002 [P] Add a reusable zizmor stand-in fixture to `tests/conftest_helpers.py`: an executable on `PATH` whose output and exit code the test chooses. Move it from the pattern in `tests/darnit/remediation/test_plan_contract.py`.

---

## Phase 2: Foundational (Blocking Prerequisites)

**CRITICAL**: No user story work can begin until this phase is complete.

- [X] T003 [P] Write registry metadata tests in `tests/darnit/sieve/test_handler_registry_metadata.py`:
  - `register(settings=..., expression_names=...)` stores both;
  - the defaults are `settings=None` and `expression_names=frozenset()`;
  - every core built-in declares `settings`;
  - `exec`, `pattern`, and `regex` declare `{"output", "project"}`, and `gh_api` declares `{"response"}`.
- [X] T004 Add `settings` and `expression_names` to `register` and `SieveHandlerInfo` in `packages/darnit/src/darnit/sieve/handler_registry.py`.
- [X] T005 Declare `settings` (the keys each handler reads, from its `config.get` calls) and `expression_names` for every built-in check and remediation step type in `packages/darnit/src/darnit/sieve/builtin_handlers.py`. Also declare `settings` on the Baseline's `github_branch_protection` and `generate_threat_model` in `packages/darnit-baseline/src/darnit_baseline/implementation.py`, and on the reproducibility, gittuf, and CSL step types in their `implementation.py` files.
- [X] T006 [P] Fix #501: replace `file_must_exist` / `paths` with `file_exists` / `files` in:
  - `packages/darnit-hello/src/darnit_hello/hello.toml`
  - `packages/darnit-example/example-hygiene.toml`
  - `docs/packaging-plugins.md`
  - `docs/IMPLEMENTATION_GUIDE.md`
  - the CLAUDE.md Sieve Pattern section

  Confirm that `darnit list` and the plugin-discovery smoke test still load `darnit-hello`.

**Checkpoint**: Registration metadata exists and every shipped template uses registered step types.

---

## Phase 3: User Story 1 - A step's expression decides or the step is an error (Priority: P1) MVP

**Goal**: No step keeps a verdict when its expression cannot be evaluated; expressions see usable project data and the repository.

**Independent Test**: quickstart V1, and V2 for the expression-reference cases.

### Tests for User Story 1

- [X] T007 [P] [US1] Write tests in `tests/darnit/sieve/test_expr_failure.py`:
  - Zizmor stand-in for OSPS-BR-01.01 and OSPS-AC-04.02: exit 0 with no output gives ERROR (`evaluation`); a matching finding gives FAIL; an empty list gives PASS.
  - A handler FAIL with an evaluation error gives ERROR.
  - A non-boolean value gives ERROR.
  - `project.ci_provider == "github"` evaluates true when the value is confirmed, and gives ERROR when it is only a candidate.
  - `file_exists("README.md")` is true when the file exists.
  - The original handler result does not conclude the control.
- [X] T008 [P] [US1] Write load-time reference tests in `tests/darnit/config/test_expr_references.py`:
  - `expr = 'response.body.x'` on an `exec` step fails loading and names the control and the reference;
  - `expr = 'ouput.x'` fails;
  - a syntax error fails;
  - a macro-bound variable (`exists(f, f.ident == "x")`) is accepted;
  - an `expr` on a step type with no expression names fails;
  - all 21 shipped expressions load.

### Implementation for User Story 1

- [X] T009 [US1] Add a free-identifier helper to `packages/darnit/src/darnit/sieve/cel_evaluator.py`. It compiles the expression, collects `ident` names in primary positions, and excludes comprehension-bound variables and known functions.
- [X] T010 [US1] Make `_apply_cel_expr` in `packages/darnit/src/darnit/sieve/orchestrator.py`:
  - return ERROR (`error_class="evaluation"`, with `expr` and `expr_error` in the evidence) when the expression fails or is not boolean, for a PASS or a FAIL handler result;
  - pass `{"output": evidence, "project": project_context}` and `repo_path=Path(local_path)`;
  - update its docstring table.
- [X] T011 [US1] Validate `expr` references against the step type's `expression_names` in `validate_step_authority` (`packages/darnit/src/darnit/config/control_loader.py`). Raise the load error defined in data-model.md.
- [X] T012 [US1] Update the CEL documentation in CLAUDE.md ("Available context variables") to match framework-design.md.

**Checkpoint**: SC-001 holds.

---

## Phase 4: User Story 2 - Built-in checks and settings cannot be silently changed (Priority: P1)

**Goal**: No plugin can replace a step type, and unknown keys and step types are reported at load.

**Independent Test**: quickstart V2 and V3.

### Tests for User Story 2

- [X] T013 [P] [US2] Write collision tests in `tests/darnit/sieve/test_registration_collisions.py`:
  - a plugin registering `manual` with ceiling `{"pass"}` is refused, logs a WARNING, appears in `refused_registrations`, and a manual-only control still does not PASS;
  - when two plugins register the same name, the second is refused and both are named;
  - the same plugin re-registering its own name is allowed;
  - core built-ins are registered before any plugin.
- [X] T014 [P] [US2] Write strict-loading tests in `tests/darnit/config/test_strict_framework_loading.py`:
  - control key `nmae` fails loading and names the file and control;
  - step key `fail_on_mis` fails and names the file, control, step, and key;
  - `handler = "file_must_exst"` fails;
  - a plugin step type without declared `settings` loads, with one warning per type;
  - an operator custom control naming a missing plugin step type audits as ERROR `missing_tool`;
  - every shipped framework loads;
  - `validate_sync` passes.

### Implementation for User Story 2

- [X] T015 [US2] Refuse collisions in `register` (core name taken by a plugin, or a different plugin's name) and record each one in `refused_registrations`, in `packages/darnit/src/darnit/sieve/handler_registry.py`. Surface `refused_registrations` in `darnit list` (`packages/darnit/src/darnit/cli.py`) and in the audit warnings.
- [X] T016 [US2] Set `ControlConfig` to `extra="forbid"` in `packages/darnit/src/darnit/config/framework_schema.py`. Make the error name the framework file and control.
- [X] T016a [US2] Fix the shipped keys no handler reads, which tests/darnit/sieve/test_handler_registry_metadata.py lists in `UNREAD_SHIPPED_KEYS`, before strict loading. Then empty that list.
  - OSPS-LE-02.01's regex step uses `patterns`; convert it to the handler's `pattern` form so the step runs. Do the same for the example's PH-SEC-01.
  - Remove `create_dirs` from the Baseline `file_create` steps (the executor always creates parent directories).
  - Remove `context_hints` from the Baseline `manual` remediations, unless something reads it.
  - Remove `timeout` from the `github_branch_protection` steps.

  Files: `packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml`, `packages/darnit-example/example-hygiene.toml`.
- [X] T017 [US2] In `validate_step_authority` (`packages/darnit/src/darnit/config/control_loader.py`):
  - reject step keys outside the common fields plus the type's `settings` when `settings` is declared;
  - warn once per type when it is not declared;
  - reject unregistered step types for framework-file controls.

  Apply the same key check to remediation handler steps.
- [X] T018 [US2] Replace the dispatch-time skip of an unregistered step type with an ERROR result (`error_class="missing_tool"`, naming the type) in `packages/darnit/src/darnit/sieve/orchestrator.py`. The only path that can reach it is operator-supplied controls (feature 040).

**Checkpoint**: SC-002 and SC-003 hold.

---

## Phase 5: User Story 3 - Reproducibility controls pass only on real evidence (Priority: P2)

**Goal**: The five text/presence reproducibility step types conclude only FAIL; their signals reach later steps.

**Independent Test**: quickstart V4.

### Tests for User Story 3

- [X] T019 [P] [US3] Write tests in `tests/darnit_reproducibility/test_no_pass_from_signals.py`:
  - a workflow mentioning `cosign sign` only in a comment: RE-02.02 is not PASS, and the signal is in evidence;
  - each of the five step types is registered with ceiling `{"fail"}`;
  - a manifest without a lockfile still FAILs `repro_deps_pinned`;
  - the signals appear in the evidence passed to `llm_eval`.

### Implementation for User Story 3

- [X] T020 [US3] Register `repro_hermetic_build`, `repro_provenance_exists`, `repro_bit_for_bit`, `repro_deps_pinned`, and `repro_build_env_declared` with `ceiling={"fail"}` in `packages/darnit-reproducibility/src/darnit_reproducibility/implementation.py`. Check that each handler's FAIL paths are genuine proof of non-compliance and keep them; turn any FAIL that comes from a mere absence of signals into INCONCLUSIVE.
- [X] T021 [US3] Update the reproducibility tests and fixtures that expected a PASS from signals, naming FR-010 in each, under `tests/darnit_reproducibility/`. Update the reproducibility README/docs to say that automatic PASS needs a corpus-backed promotion.

**Checkpoint**: SC-004 holds.

---

## Phase 6: User Story 4 - Audit output does not carry the auditor's personal data (Priority: P3)

**Goal**: Evidence keeps only the fields the check needs.

**Independent Test**: quickstart V5.

### Tests for User Story 4

- [X] T022 [P] [US4] Write tests in `tests/darnit_baseline/test_user_evidence_redaction.py`:
  - a recorded `/user` response with email, location, company, and bio produces AC-01.01 evidence containing only `login` and `two_factor_authentication`;
  - the JSON report and the attestation predicate contain none of the other values;
  - a `gh_api` step on `/user` without `evidence_fields` fails loading;
  - the expression still evaluates against the full response.

### Implementation for User Story 4

- [X] T023 [US4] Add the `evidence_fields` setting to `gh_api_handler` and keep only those body keys in the stored evidence, in `packages/darnit/src/darnit/sieve/builtin_handlers.py`. Add the `/user` and `/users/` load rule in `packages/darnit/src/darnit/config/control_loader.py`.
- [X] T024 [US4] Declare `evidence_fields = ["login", "two_factor_authentication"]` on the OSPS-AC-01.01 `/user` step in `packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml`.

**Checkpoint**: SC-005 holds.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T024a [US1] Implement FR-015, updating `docs/architecture/framework-design.md` 3.7 and contracts/step-contract.md first.
  - Add a common step field `expr_decides` (bool). When it is true and the handler completed successfully, the expression alone decides: true is PASS, false is FAIL, within the ceiling. A handler FAIL or ERROR is unchanged.
  - It is valid only on step types that declare `expression_names`; `gh_api` already decides through its own expression.
  - Set it on the OSPS-BR-01.01 and OSPS-AC-04.02 zizmor steps.
  - Tests: a matching zizmor finding gives FAIL, and no findings gives PASS; `expr_decides` on a type without expressions fails loading.
  - Files: `packages/darnit/src/darnit/config/framework_schema.py`, `packages/darnit/src/darnit/sieve/orchestrator.py`, `packages/darnit/src/darnit/config/control_loader.py`, `packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml`, `tests/darnit/sieve/test_expr_failure.py`.
- [X] T024b [US4] Widen the personal-record rule to `/user`, `/user/...`, and `/users/...` in `packages/darnit/src/darnit/config/control_loader.py`, `docs/architecture/framework-design.md` 3.8, and the US4 tests.
- [X] T025 [P] Add false-PASS corpus cases under `tests/darnit_baseline/corpus/` (and the corpus runner, if a plugin case needs it), with 0 false PASSes (FR-013, SC-006):
  - an exec step whose expression cannot evaluate;
  - a plugin redefining `manual`;
  - a reproducibility text signal.
- [X] T026 [P] Update the tests that pinned the old behavior, naming the replacing requirement in each:
  - the feature 020 CEL post-step tests (failure kept the verdict);
  - `tests/darnit/sieve/test_handler_registry.py` (override allowed);
  - `tests/darnit/sieve/test_builtin_handlers.py`;
  - the reproducibility handler tests.
- [X] T027 [P] Update CHANGELOG `[Unreleased]`:
  - **Security**: a failed expression is ERROR; plugins cannot redefine step types.
  - **BREAKING**: unknown control and step keys and unregistered step types fail loading; reproducibility controls no longer PASS from text signals.
  - **Changed**: `/user` evidence is limited to the fields the check reads.
  - **Fixed**: the templates use `file_exists` (#501).
- [X] T030 Amend `.specify/memory/constitution.md` with a PATCH (1.3.1 to 1.3.2): Principle V and Architecture Constraints name `file_exists` instead of the removed `file_must_exist`. Add a Sync Impact Report entry.
- [X] T028 Run quickstart V1-V6 and record the results in a "Validation log" section of `specs/044-false-pass-paths/quickstart.md`.
- [X] T029 Run `uv run ruff check .`, `uv run pytest tests/ -q`, and `uv run python scripts/validate_sync.py --verbose`, then fix failures. Rerun the integration tests with the GitHub Actions environment variables set, since CI identity differs (see the 043 CI fix).

---

## Dependencies & Execution Order

- **Setup**: T001 first (spec-first). T002 can run in parallel.
- **Foundational**: T003-T006. T004 comes before T005. T006 is independent and must land before T017 turns on strict step-type checks.
- **US1 (MVP)**: after Foundational. T009 comes before T011. T010 is independent of T011.
- **US2**: after Foundational; T017 needs T005 and T006. T018 touches `orchestrator.py` after T010.
- **US3**: independent of US1 and US2 (reproducibility package only).
- **US4**: needs T004 and T005 (`gh_api` settings).
- **Polish**: last.

## Parallel Opportunities

- T002 runs alongside T001.
- T003 and T006 can run together.
- All story test tasks are [P].
- US3 runs in parallel with US1 and US2.
- T025, T026, and T027 can run together.

## Implementation Strategy

1. **MVP**: Setup, Foundational, then US1. This closes the live false PASS in OSPS-BR-01.01 and OSPS-AC-04.02.
2. **Then US2**, which closes the authority bypass and the silent no-op settings.
3. **Then US3 and US4**.
4. **Last**: the corpus, the CHANGELOG, and validation.
