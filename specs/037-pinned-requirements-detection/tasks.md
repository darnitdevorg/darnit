---

description: "Task list for feature 037: Pinned-Requirements Detection"
---

# Tasks: Pinned-Requirements Detection

**Input**: Design documents from `/specs/037-pinned-requirements-detection/`

**Prerequisites**: plan.md, spec.md, research.md, data-model.md, contracts/

**Tests**: test tasks are included. The spec requires them explicitly -- SC-006 ("every edge case enumerated above has a fixture and an asserted verdict"), and both contracts carry numbered test obligations.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: can run in parallel (different files, no dependency on an incomplete task)
- **[Story]**: US1, US2, US3 per spec.md
- Paths are repository-relative from `/Users/mlieberman/Projects/darnit`

---

## Phase 1: Setup

**Purpose**: make `packaging` an honest dependency before anything imports it.

- [X] T001 Declare `packaging>=23.0` in the `dependencies` list of `packages/darnit-reproducibility/pyproject.toml`, with a comment pointing at research.md R4 (it is already imported at runtime by core but declared by no package).
- [X] T002 Run `uv sync` and confirm `uv run python -c "from packaging.requirements import Requirement"` succeeds from a clean resolve.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: capture the before-state, then build the shared classifier.

**CRITICAL -- ordering**: T003 through T006 MUST run on an unmodified tree, before any source file in `packages/` is touched. SC-004, SC-005, and SC-008 assert byte-identical output across this change; a baseline captured after an edit proves only that the code agrees with itself (research.md R7). If a source edit lands first, the baseline must be re-derived from `git stash` before proceeding.

- [X] T003 Write `tests/darnit_reproducibility/conftest.py` with a `lockfile_repo` and a `no_deps_repo` tmp-path fixture, plus a helper that runs `repro_deps_pinned_handler` and returns a normalized dict of `(status, message, confidence, evidence)`.
- [X] T004 On an unmodified tree, generate and commit `tests/darnit_reproducibility/baselines/deps_pinned_before.json` from T003's fixtures, capturing the pre-change handler output for the lock-file and no-dependency-files cases (SC-004, SC-005).
- [X] T005 Write `tests/darnit/sieve/baseline_capture.py` defining the SC-008 corpus explicitly, because no per-framework corpus exists today: `tests/darnit/parity/fixtures/` holds four repo directories but its `parity.toml` files scope to three OSPS controls plus one STAGE1 control, and `tests/darnit/sieve/fixtures/` holds only `mock_mcp_server`. The corpus is the cross product of all five installed frameworks (`openssf-baseline`, `reproducibility`, `gittuf`, `example-hygiene`, `hello`) against five repo inputs: the four parity fixture directories, reused read-only as plain repos, plus an empty tmp repo. Stub the LLM step; do not add files under `tests/darnit/parity/fixtures/`.
- [X] T006 On an unmodified tree, run T005's capture twice and commit `tests/darnit/sieve/baselines/control_status_before.json` plus `tests/darnit/sieve/baselines/nondeterministic_controls.txt`. Any control whose status differs between the two runs -- typically one shelling out to `gh` or the network -- is recorded by id in the exclusion file and omitted from the baseline. The exclusion list is committed so the gap is visible rather than silent (research.md R8).
- [X] T007 Create `packages/darnit-reproducibility/src/darnit_reproducibility/requirements_pins.py` with the `PinClassification` and `FileClassification` enums and a module docstring stating the boundary: this module takes text and returns a classification; it performs no file discovery, constructs no `HandlerResult`, and decides no verdict.
- [X] T008 Implement preprocessing in `requirements_pins.py` in the order fixed by research.md R5: join backslash continuations, strip comments, drop blanks, collect `--hash=` values, skip pip option lines and `-e .`-style self-references, flag `-r`/`-c` includes. Continuation joining MUST precede hash collection -- `pip-compile --generate-hashes` puts hashes on continuation lines.
- [X] T009 [P] Write `tests/darnit_reproducibility/test_requirements_preprocessing.py` covering continuation joining, hash collection off continuation lines, comment and blank handling, option-line skipping, `-e .` skipping, and include flagging.

**Checkpoint**: baselines are committed and the classifier accepts input. User story work can begin.

---

## Phase 3: User Story 1 - A fully hash-pinned requirements.txt is not reported as unpinned (Priority: P1) -- MVP

**Goal**: a `pip-compile --generate-hashes` output stops receiving a hard FAIL.

**Independent test**: a repo whose only dependency file is a `requirements.txt` with `==` and `--hash=` on every line returns PASS, and the message names hash-pinning as the reason.

**Why this is a shippable MVP on its own**: US1 needs no framework change. With only this phase merged, a hash-pinned file passes and everything else keeps today's presence-based verdict -- strictly better than the current behavior, with no regression and no WARN in sight.

- [X] T010 [US1] Implement exact-version detection in `requirements_pins.py`: a specifier set of exactly one clause whose operator is `==` or `===` and whose version contains no wildcard. Test the wildcard on the version string, not the operator -- `pkg==1.*` parses with operator `==` (FR-008).
- [X] T011 [US1] Implement line classification for `HASH_PINNED` and `EXACTLY_PINNED` in `requirements_pins.py`, discarding extras and environment markers as non-bearing (FR-009).
- [X] T012 [US1] Implement `classify(text) -> FileClassification` in `requirements_pins.py` with the weakest-line-governs rule, returning `HASH_PINNED` only when at least one requirement line exists and every line is hashed. Everything that is not `HASH_PINNED` and not `NO_REQUIREMENTS` returns `UNPINNED` at this stage; T030 splits `VERSION_PINNED` back out of it. This is what makes Phases 1-3 a coherent MVP -- a non-hash-pinned file maps to the existing presence-based FAIL, so nothing regresses while the WARN tier is still absent.
- [X] T013 [P] [US1] Add fixture `tests/darnit_reproducibility/fixtures/hash_pinned_repo/requirements.txt` reproducing the reporter's case from issue #429 -- real `pip-compile --generate-hashes` output shape, hashes on continuation lines (SC-001).
- [X] T014 [P] [US1] Add fixture `tests/darnit_reproducibility/fixtures/mixed_hash_repo/requirements.txt` where some lines carry hashes and some carry only `==`.
- [X] T015 [US1] Rewrite `repro_deps_pinned_handler` in `packages/darnit-reproducibility/src/darnit_reproducibility/handlers.py` to follow the data-model.md evaluation order: lock file first and short-circuiting without reading contents (FR-001), then root `requirements.txt` content inspection (FR-002), then other loose manifests by presence, then INCONCLUSIVE. Discovery stays at the root filename only (FR-019).
- [X] T016 [US1] Map `HASH_PINNED` to PASS at confidence 0.8 in `handlers.py`, with a message that names hash-pinning as the reason so the operator can tell the verdict came from reading the file rather than from its name (FR-004, FR-020, US1 scenario 2).
- [X] T017 [US1] Populate result evidence in `handlers.py` with the inspected file path, the classification, the requirement-line count, and the driving requirements; cap enumerated examples and record the total alongside so a 400-requirement file does not produce a result larger than the file (FR-012).
- [X] T018 [US1] Handle unreadable and undecodable files in `handlers.py` as `NOT_INSPECTABLE` -> FAIL, with a message stating that contents could not be inspected. The classifier is never called for these (FR-007).
- [X] T019 [P] [US1] Write `tests/darnit_reproducibility/test_requirements_pins.py` covering every row of the line-classification table in contracts/requirements-classification.md (T-1), plus the `HASH_PINNED` and mixed-file rows of the file table (T-2, T-3).
- [X] T020 [US1] Extend the existing `TestDepsPinned` class in `tests/darnit_reproducibility/test_handlers.py:396` -- do not create a parallel handler test file -- asserting PASS on the hash-pinned fixture with a message naming hashes, plus the evidence contents from T017 (SC-001, FR-012). Its six existing tests survive this change unmodified (`requests>=2.0` classifies UNPINNED and still FAILs); confirm that rather than assume it.

**Checkpoint**: issue #429's reported case is fixed and independently verifiable.

---

## Phase 4: User Story 2 - A version-pinned requirements.txt is distinguished from an unpinned one (Priority: P1)

**Goal**: `==`-pinned files WARN with a message about transitive dependencies; open ranges FAIL naming an offender.

**Independent test**: two repos, one all-`==` and one all-`>=`. The first returns WARN, the second FAIL.

**Depends on**: US1 (shares the classifier). The framework subtasks T021-T027 are independent of US1 and can start in parallel with Phase 3.

### Framework: conclusive WARN outcome (FR-016, FR-017)

- [X] T021 [US2] Document the WARN handler outcome and the updated disposition table in `docs/architecture/framework-design.md`, per constitution Development Workflow item 3 (spec first, then code). Content comes from contracts/handler-warn-outcome.md C-1 through C-7.
- [X] T022 [US2] Add `WARN = "warn"` to `HandlerResultStatus` in `packages/darnit/src/darnit/sieve/handler_registry.py`, with a docstring distinguishing it from INCONCLUSIVE in kind: INCONCLUSIVE means the handler determined nothing, WARN means it determined the evidence is insufficient.
- [X] T023 [US2] Add `WARN = "warn"` to `PassOutcome` in `packages/darnit/src/darnit/sieve/models.py` (research.md R2).
- [X] T024 [US2] Add `CONCLUDE_WARN` to `StepDisposition` and extend `resolve_step_result` in `packages/darnit/src/darnit/sieve/orchestrator.py` so WARN joins the PASS/FAIL branch: concludes only under terminal authority, otherwise attaches evidence and continues, terminating INCONCLUSIVE on the last step (contract C-2).
- [X] T025 [US2] Add the `CONCLUDE_WARN` branch to `_dispatch_handler_invocations` in `orchestrator.py`, mirroring `CONCLUDE_FAIL` and carrying `message`, `confidence`, `evidence`, `resolving_pass_index`, `resolving_pass_handler`, `authority`, and `error_class`. Unlike `CONCLUDE_PASS`, nothing forbids WARN with an `error_class`, so it must be threaded rather than reasoned away (contract C-5).
- [X] T026 [US2] Add the explicit `HandlerResultStatus.WARN -> PassOutcome.WARN` entry to `_handler_status_to_outcome` in `orchestrator.py`. The function ends in `mapping.get(status, PassOutcome.INCONCLUSIVE)`, so omitting it degrades silently instead of raising.
- [X] T027 [P] [US2] Write `tests/darnit/sieve/test_handler_warn_outcome.py` covering contract obligations T-1 through T-7: dispositive WARN concludes with the handler's own message; suggestive WARN continues; suggestive WARN on the last step terminates INCONCLUSIVE; fields carry through; `error_class` is preserved; `_apply_cel_expr` returns a WARN unchanged both with and without an `expr` configured; `pass_history` records WARN, not INCONCLUSIVE.
- [X] T028 [US2] Run `uv run python scripts/validate_sync.py --verbose` because the constitution's Development Workflow requires the gate. Note what it does NOT prove: `validate_pass_types_sync` (`scripts/validate_sync.py:111`) greps a hardcoded list of seven handler *names* against `builtin_handlers.py` and cannot detect whether the WARN outcome is documented. It will pass whether or not T021 was done correctly.
- [X] T029 [US2] Add a test in `tests/darnit/sieve/test_handler_warn_outcome.py` asserting that `docs/architecture/framework-design.md` contains the WARN row of the disposition table, so T021 has a mechanical check rather than relying on reviewer attention.

### Plugin: the WARN and FAIL tiers

- [X] T030 [US2] Extend `classify` in `requirements_pins.py` to return `VERSION_PINNED` (all lines pinned, at least one without a hash -- this deliberately covers partially hashed files) and `UNPINNED` (any line not pinned).
- [X] T031 [US2] Implement direct-reference handling in `requirements_pins.py`: a URL whose fragment after the final `@` is 40 or 64 hex characters is `EXACTLY_PINNED`; a branch, tag, or abbreviated id is `NOT_PINNED`. A SHA reference is never hash evidence, so it caps the file at `VERSION_PINNED` (FR-010, research.md R6).
- [X] T032 [US2] Return `NOT_INSPECTABLE` from `classify` when a surviving line fails to parse, distinct from a line that was skipped during preprocessing. The tool must not claim to have understood a file containing a line it could not read (FR-007).
- [X] T033 [US2] Map `VERSION_PINNED` to WARN at confidence 0.8 in `handlers.py`, with a message that says what is missing -- transitive dependencies resolve at install time -- rather than only that the check did not pass (FR-005, FR-020).
- [X] T034 [US2] Map `UNPINNED` to FAIL at confidence 0.8 in `handlers.py`, naming at least one offending requirement so the operator can act without re-deriving the finding (FR-006, FR-020).
- [X] T035 [US2] Implement `NO_REQUIREMENTS` fallthrough in `handlers.py`: an empty or comments-only file is treated as absent, so any other loose manifest decides, and with none the existing no-dependency-files INCONCLUSIVE stands (FR-011).
- [X] T036 [P] [US2] Add fixtures under `tests/darnit_reproducibility/fixtures/`: `version_pinned_repo` (all `==`), `unpinned_repo` (all `>=`), `wildcard_repo` (`pkg==1.*`), `compound_repo` (`pkg>=1.0,<2.0`), `markers_repo` (extras plus environment markers), `vcs_sha_repo`, `vcs_branch_repo`, `empty_repo` (comments and blanks only), `include_repo` (unresolved `-r`), `options_repo` (pinned plus `-e .` and `--index-url`).
- [X] T037 [P] [US2] Extend `tests/darnit_reproducibility/test_requirements_pins.py` with the remaining file-classification rows and the option-line case (contract T-2, T-4, T-6).
- [X] T038 [US2] Extend `TestDepsPinned` in `tests/darnit_reproducibility/test_handlers.py` to assert WARN on `version_pinned_repo` with a transitive-dependency message, FAIL on `unpinned_repo` naming an offender, and that all three of PASS, WARN, FAIL are mutually distinct for the same control (SC-002, SC-003).
- [X] T039 [US2] Assert in `TestDepsPinned` that one floating dependency among pinned ones produces FAIL -- the weakest line governs (US2 scenario 3).
- [X] T040 [US2] Assert in `TestDepsPinned` that an unreadable file (written then `chmod(0o000)`) and an undecodable file (non-UTF-8 bytes written at test time) both produce FAIL with a message saying contents could not be inspected, and that `requirements_pins.classify` is never called for either -- patch it and assert zero calls. Neither case can be a committed fixture, which is why it is a runtime-constructed test (FR-007, contracts/requirements-classification.md T-7, SC-006).

**Checkpoint**: the common case is fixed and the framework can express a WARN that says why.

---

## Phase 5: User Story 3 - Lock files continue to take precedence (Priority: P2)

**Goal**: prove the change is a no-op everywhere it claims to be.

**Independent test**: a repo with both `uv.lock` and a deliberately unpinned `requirements.txt` passes on the lock file, and the requirements contents are never read.

- [X] T041 [P] [US3] Add fixture `tests/darnit_reproducibility/fixtures/lock_plus_loose_repo/` containing `uv.lock` and a `requirements.txt` full of open ranges.
- [X] T042 [US3] Assert in `TestDepsPinned` (`tests/darnit_reproducibility/test_handlers.py`) that the lock-file fixture returns PASS and that the classifier is never invoked -- patch `requirements_pins.classify` and assert zero calls (FR-001, contracts/requirements-classification.md T-8).
- [X] T043 [US3] Assert handler output for the lock-file and no-dependency-files fixtures matches `tests/darnit_reproducibility/baselines/deps_pinned_before.json` exactly, including confidence (SC-004, SC-005).
- [X] T044 [US3] Assert in `TestDepsPinned` that a repo whose only requirements file is `requirements-dev.txt` or `requirements/base.txt` stays INCONCLUSIVE -- discovery did not widen (FR-019).
- [X] T045 [US3] Assert in `TestDepsPinned` that `setup.py`, `package.json`, `Cargo.toml`, and `go.mod` are still judged by presence alone with unchanged messages (FR-014).

**Checkpoint**: the no-op claims are mechanically verified rather than argued.

---

## Phase 6: Polish and Cross-Cutting Concerns

- [X] T046 Assert per-control status across T005's corpus matches `tests/darnit/sieve/baselines/control_status_before.json`, skipping the ids in `nondeterministic_controls.txt` (SC-008, contracts/handler-warn-outcome.md T-8). This is the claim that makes the framework change acceptable; it must be a test, not an inspection.
- [X] T047 Verify SC-007 by checking the imports of `packages/darnit-reproducibility/src/darnit_reproducibility/` against its declared dependencies after T001 -- no import outside the declared set.
- [X] T048 Confirm every edge case in spec.md is represented by a fixture with an asserted verdict, including the ones whose correct answer is "we could not determine" (SC-006).
- [X] T049 [P] Update the `repro_deps_pinned_handler` docstring in `handlers.py` -- it currently says "Looks for lock files ... FAIL if only a loose manifest exists," which this feature makes wrong.
- [X] T050 [P] Correct the stale claim in `CLAUDE.md` that `packaging` is "already a transitive dep via setuptools metadata" (Active Technologies, feature 013 entry). `uv pip show packaging` reports `Required-by: pytest`.
- [X] T051 File a follow-up issue for core's two undeclared runtime `packaging` imports (`packages/darnit/src/darnit/core/composition.py:363`, `packages/darnit/src/darnit/config/framework_schema.py:1445`) and the inaccurate comment at `framework_schema.py:1443`. Out of scope for this branch; do not fix here.
- [X] T052 Run the full gate: `uv run ruff check .`, `uv run pytest tests/ --ignore=tests/integration/ --ignore=tests/darnit/parity/tier2 -q`, `uv run python scripts/validate_sync.py --verbose`. Note the ignore spelling -- `--ignore=tests/darnit/parity` would skip parity tier 1, which CI runs.
- [X] T053 Run `uv run ruff format` on touched files only. A repository-wide format run reformats hundreds of unrelated files and must not be part of this change.

---

## Dependencies

```text
Phase 1 (T001-T002)
    |
Phase 2 (T003-T009)  <- T003-T006 MUST precede every edit under packages/
    |
    +-- Phase 3 / US1 (T010-T020)  ---> shippable MVP
    |        |
    +-- Phase 4 framework (T021-T029)  <- independent of US1, may run alongside
             |
        Phase 4 plugin (T030-T040)  <- needs US1 classifier and T022-T026
             |
        Phase 5 / US3 (T041-T045)   <- needs T004 baseline
             |
        Phase 6 (T046-T053)         <- needs T006 baseline
```

Story order: US1 -> US2 -> US3. US3 is last because it verifies that the earlier phases changed nothing they did not intend to; running it before them proves nothing.

## Parallel Opportunities

- **T021-T029 alongside Phase 3.** The framework WARN outcome touches only `packages/darnit/` and `docs/architecture/`; US1 touches only `packages/darnit-reproducibility/`. Two people, no file contention.
- **Fixture authoring.** T013, T014, T036, T041 are all new files under `tests/darnit_reproducibility/fixtures/` and are mutually independent.
- **Polish.** T049, T050 touch different files and are independent of each other.
- **Not parallel**: T010 through T012 and T030 through T032 all edit `requirements_pins.py`; T015 through T018 and T033 through T035 all edit `handlers.py`; T020, T038, T039, T040, T042, T044, and T045 all edit `tests/darnit_reproducibility/test_handlers.py`.

## Implementation Strategy

**MVP = Phases 1 through 3.** That closes the reported bug in issue #429, requires no framework change, and regresses nothing: a hash-pinned file passes, everything else keeps today's verdict. T012's fold-everything-else-into-UNPINNED clause is what makes that true rather than aspirational. It is a defensible stopping point if the framework change needs more review time than the fix deserves.

**Phase 4 is the substantive increment**, and it is where reviewer attention should go -- it changes what a handler is allowed to conclude, for every handler.

**Phase 5 and 6 are not optional polish.** They are where SC-004, SC-005, and SC-008 get proven, and those criteria are the reason the framework change is acceptable. Landing Phase 4 without them ships an unverified claim.

**Blocked end to end until PR #439 merges.** Until then `repro_deps_pinned` never executes via the CLI, so `darnit audit` cannot verify any of this. Unit-level work is unaffected; only the quickstart's end-to-end walkthrough is gated.

---

## Implementation Notes

Recorded during `/speckit-implement` so the deviations are visible rather than inferred.

- **T005 corpus was narrowed after the first attempt failed.** The full cross product (5 frameworks x 5 repos x 2 runs of a level-3 audit) did not finish in 12 minutes, because every exec handler that shells out to `gh` pays a network timeout per control. Narrowed to `reproducibility` + `openssf-baseline` against `all_pass_repo`, `mixed_repo`, and an empty repo. Rationale is in `baseline_capture.py`.
- **T005 required subprocess isolation for a reason unrelated to cost.** The in-process capture reported a 46% nondeterministic-exclusion rate. All of it was cross-framework control leakage, not flakiness: a `reproducibility` audit returns 5 controls in a clean process and 71 (65 of them OSPS baseline) if an `openssf-baseline` audit ran earlier in the same process. Pre-existing product defect, out of scope here, needs its own issue. With each pair in a fresh subprocess the capture is fully deterministic -- 213 controls, 0 excluded.
- **T012's fold-into-UNPINNED clause was not implemented as a separate step.** The whole feature landed in one pass, so folding `VERSION_PINNED` into `UNPINNED` and then unfolding it in T030 would have been make-work with an identical end state. The MVP boundary it existed to protect is preserved at the handler layer instead: the classifier tiers are complete, and Phase 3 alone would map everything but `HASH_PINNED` to the pre-existing presence-based FAIL.
- **A parser defect surfaced from T019's own test.** `-e git+https://x/y@<sha>` is valid pip input but not valid PEP 508 (which requires `name @ url`), so `Requirement()` rejected it and the classifier called a genuinely SHA-pinned line unreadable. Fixed with a bare-URL path (`_is_bare_url`, `_url_is_pinned`) that never reaches `Requirement()`.
- **The class extended in T020 is `TestRepoDepsPin`, not `TestDepsPinned`.** The tasks named it from memory; the real name is at `tests/darnit_reproducibility/test_handlers.py:395`.
- **T027 confirmed the prediction from the analysis pass.** `validate_sync.py` passes and proves nothing about the WARN outcome. T029's documentation assertion is what actually covers T021.
- **T053 formatted only touched files.** `uv run ruff format --check` reports two pre-existing files in `tests/darnit_reproducibility/` that would be reformatted; they were left alone.
- **The capture polluted the parity fixtures on its first design.** `run_checks` writes a `.project/` directory into the repository it audits, so auditing `tests/darnit/parity/fixtures/*` in place left untracked files in the source tree -- the same pollution that broke CI on PR #435 via feature 028's product-source guard. `repo_inputs` now copies each fixture into scratch space first. The two `.project/` directories created during implementation were removed; the one under `all_pass_repo/` predates this session and was left alone.
- **The baseline was re-derived after that fix.** The first capture ran against polluted fixtures, so it was not a valid pre-change baseline once the inputs became clean copies. Product changes were stashed (`git stash push -- packages/ docs/architecture/framework-design.md`), the capture re-run against unmodified code, and the changes restored. SC-008 passes against that re-derived baseline: 213 controls, 6 pairs, 0 excluded.
- **T051 filed two issues, not one.** #441 covers core's undeclared runtime `packaging` imports and the inaccurate comment at `framework_schema.py:1443`. #442 covers the cross-framework control leak found while building the SC-008 baseline. Both are out of scope for this branch.
- **The committed SC-008 golden was wrong in principle and was replaced.** It passed locally and failed in CI: seven OSPS controls resolve FAIL on a developer machine and WARN on a GitHub runner, so a golden of absolute control statuses pins the environment as much as the code. Chasing the environmental difference (an untracked `.project/` in a fixture, `gh` authentication, fixture contents) was the wrong track -- the statuses are legitimately environment-dependent and always will be. `test_control_status_baseline.py` now captures the corpus twice in the SAME environment -- once normally, once with the WARN outcome routed the way it was before this feature -- and diffs those. Whatever the environment does, it does to both runs and cancels. No golden file, portable, and it tests the actual claim rather than a snapshot of one machine.
- **An untracked `.project/` under `tests/darnit/parity/fixtures/all_pass_repo/` was removed.** It predated this session, was generated output from an earlier audit, and contaminated the first baseline. It is also the shape of file that broke CI on #435.
