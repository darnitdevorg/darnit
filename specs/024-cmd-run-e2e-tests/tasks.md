---
description: "Tasks for feature 024: E2E regression baseline for `darnit run` (cmd_run)"
---

# Tasks: E2E Regression Baseline for `darnit run` (cmd_run)

**Input**: Design documents from `specs/024-cmd-run-e2e-tests/`

**Prerequisites**: plan.md (loaded), spec.md (loaded), research.md (loaded), data-model.md (loaded), contracts/cmd_run-output.md (loaded), quickstart.md (loaded)

**Tests**: This feature IS the tests. There is no separate implementation to test; test tasks and implementation tasks are the same.

**Organization**: Tasks are grouped by user story from spec.md. Each story ships as an independently valuable increment of coverage.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel with other [P] tasks in the same phase (different files, no dependencies)
- **[Story]**: Which user story this task belongs to (US1, US2, US3)
- File paths are exact and repository-relative

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Create the new test-package tree so subsequent tasks have a home.

- [X] T001 Create the `tests/darnit/cli/` package directory with an empty `tests/darnit/cli/__init__.py`.
- [X] T002 [P] Create the fixtures parent directory `tests/darnit/cli/fixtures/` (no `.gitkeep`; the first fixture in T003 makes it non-empty).

**Checkpoint**: Package layout exists; pytest will discover `tests/darnit/cli/` on the next collection.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Build the fixture, the copy-to-tmp helper, and the stub registry that ALL three user stories rely on.

**CRITICAL**: No user-story tests can be authored until this phase is complete.

- [X] T003 Create the `MinimalRepo` fixture tree at `tests/darnit/cli/fixtures/minimal_repo/` per `data-model.md` section 1. Populate every file enumerated there (README.md, LICENSE, CHANGELOG.md, .editorconfig, .gitignore with `.env`/`*.key`/`credentials` substrings, .pre-commit-config.yaml, .github/workflows/ci.yml containing a test command, hello.py with no forbidden patterns, .baseline.toml selecting `framework = "testchecks"`, .project/project.yaml with `name: minimal-repo`) so `testchecks` at level 3 produces zero FAIL. Do NOT check in a `.git/` directory. All content ASCII (FR-012, contract C9).
- [X] T004 [P] Create the `MalformedProjectYaml` fixture tree at `tests/darnit/cli/fixtures/malformed_project/` per `data-model.md` section 2 (same `.baseline.toml`, intentionally invalid `.project/project.yaml`).
- [X] T005 Write `tests/darnit/cli/conftest.py` implementing:
  (a) `minimal_repo_tree(tmp_path)` fixture that shutil-copies the `MinimalRepo` tree into `tmp_path`, runs `git init` and `git commit --allow-empty -m init` on the copy, and returns the path;
  (b) `malformed_project_tree(tmp_path)` doing the same for the malformed fixture;
  (c) BOTH module-level tuples per `data-model.md` section 4 (revised): `_MUST_NOT_BE_CALLED` (LLM/MCP entry points; may be empty until such an entry point exists) AND `_SUBPROCESS_STUBS` (subprocess call sites);
  (d) helper builders `_fake_git_remote_get_url` and `_fake_generic_subprocess_run` that return `subprocess.CompletedProcess` instances;
  (e) `deterministic_run(monkeypatch)` fixture that applies BOTH tiers: raises via `Mock(side_effect=RuntimeError("must not be called: <dotted-name>"))` for each `_MUST_NOT_BE_CALLED` entry, AND replaces each `_SUBPROCESS_STUBS` module's `subprocess` attribute with a namespace object whose `.run` returns canned success (or the git-remote-specific fake, depending on the command).
  Follow the module-scoped `patch("<module>.subprocess.run", side_effect=<fake>)` idiom established in `tests/darnit_baseline/controls/test_branch_protection.py:121` (FR-008). Do not invent a new stubbing style.
- [X] T006 In the same `conftest.py`, add a collection-time guard that asserts every `(module_path, attr_name)` in BOTH `_MUST_NOT_BE_CALLED` AND `_SUBPROCESS_STUBS` resolves at import time; on failure, raise a `pytest.UsageError` naming the missing attribute so a production-code rename produces a helpful collection error rather than a silent bypass. An empty `_MUST_NOT_BE_CALLED` is acceptable and the guard skips it. Reference: research.md R2 (revised for two-tier registry).
- [X] T007 Add an `invoke_cmd_run(argv: list[str]) -> tuple[int, str]` helper in `tests/darnit/cli/conftest.py` that (a) imports the argparse parser via `darnit.cli.build_parser()` (or the current equivalent -- verify at implementation time), (b) parses `["run", ...argv]`, (c) calls `args.func(args)`, (d) captures stdout/stderr via `capsys` (fixture injected by caller), and (e) returns `(exit_code, captured_stdout)`. Reference: research.md R4.

**Checkpoint**: All three user stories can now be authored in parallel; each will pull its fixture(s), stubs, and invocation helper from `conftest.py`.

---

## Phase 3: User Story 1 - Golden-path regression pin (Priority: P1) MVP

**Goal**: Lock down the observable output of `darnit run` on a healthy fixture repository so any behavior drift in a future harness driver surfaces as a named test failure.

**Independent Test**: Run `pytest tests/darnit/cli/test_cmd_run_e2e.py -k golden` on `main` at merge time; all tests pass. Then apply the perturbation from quickstart.md (force `return 0` in `cmd_run`) and confirm at least one test fails naming exit code.

### Implementation for User Story 1

- [X] T008 [US1] Create `tests/darnit/cli/test_cmd_run_e2e.py` with the module docstring, imports, and a `TestGoldenPath` class scaffold. Reference every assertion to a contract item from `contracts/cmd_run-output.md` (e.g. `# pins C1`) in inline comments so failure sites cite the contract.
- [X] T009 [US1] Add `test_golden_exit_code_matches_failed_count` in `tests/darnit/cli/test_cmd_run_e2e.py::TestGoldenPath` covering acceptance #1 and #3, spec FR-003(a). Uses `minimal_repo_tree`, invokes via `invoke_cmd_run([str(path), "--feedback", "noninteractive"])`, asserts `exit_code == 0` (fixture has zero FAIL) and derives the expected code from a parsed `Failed :` line to prove the rule (not just the value).
- [X] T010 [US1] Add `test_golden_prints_header_and_footer` in the same class covering acceptance #1 and spec FR-003(b)/(c). Asserts the exact strings from contract C1 (`Darnit run`) and C3 (`Run complete.`) each appear on their own line.
- [X] T011 [US1] Add `test_golden_prints_count_lines_in_order` in the same class covering spec FR-003(b)/(c) and contracts C4/C10-C13. Asserts the four count labels appear in order `Total`, `Passed`, `Failed`, `Warned`, each with the two-space indent, each followed by a numeric value.
- [X] T012 [US1] Add `test_golden_no_error_line_no_traceback_no_pending` in the same class covering acceptance #2 and FR-003(d). Asserts none of the substrings `Error:`, `Traceback (most recent call last):`, `Pending human feedback` appear in captured stdout.
- [X] T013 [US1] Add `test_golden_output_is_ascii` in the same class covering FR-012 and contract C9. Asserts every byte of captured stdout is in the ASCII printable range plus `\n`.

**Checkpoint**: User Story 1 delivers the P1 MVP: healthy-path behavior is pinned end-to-end.

---

## Phase 4: User Story 2 - Deterministic-only execution guarantee (Priority: P1)

**Goal**: Prove that `cmd_run` under `--feedback noninteractive` makes no LLM call, no MCP round-trip, and no unstubbed network egress.

**Independent Test**: Run `pytest tests/darnit/cli/test_cmd_run_e2e.py -k deterministic` in isolation. Passes if the current codepath does not exercise any patched entry point. Introducing an unguarded `subprocess.run([...])` inside `cmd_run`'s codepath surfaces as `RuntimeError: must not be called: <dotted-name>`.

### Implementation for User Story 2

- [X] T014 [US2] Add a `TestDeterministicOnly` class to `tests/darnit/cli/test_cmd_run_e2e.py`. Every test in this class uses the `deterministic_run` fixture from T005, so patches are applied uniformly.
- [X] T015 [US2] Add `test_deterministic_llm_mcp_entries_never_called` and `test_deterministic_subprocess_stays_stubbed` in `TestDeterministicOnly`. Both invoke `cmd_run` against `minimal_repo_tree` under the `deterministic_run` fixture (both tiers applied). The first asserts `exit_code` matches the value produced by US1's `test_golden_exit_code_matches_failed_count` under the same fixture (i.e. the deterministic guarantee does not change verdicts) -- if any `_MUST_NOT_BE_CALLED` entry existed and was invoked, the `RuntimeError` would surface and the test would fail with a name identifying the call site. The second asserts (via the fake's call-recording) that `_SUBPROCESS_STUBS` entries were invoked with expected argv shapes (e.g. `["git", "remote", "get-url", ...]`) and that no unexpected argv (`["gh", "api", ...]` targeting the real network) reached the fake. Together these cover acceptance #1 (LLM/MCP never called) and acceptance #2 (subprocess routed to canned stubs, no real network), FR-004.
- [X] T016 [US2] Add `test_deterministic_no_llm_or_mcp_log_lines` in `TestDeterministicOnly`. Uses pytest's `caplog` fixture at `WARNING` level; asserts no captured log message contains a case-insensitive match for `llm`, `anthropic`, `openai`, or `mcp`. Belt-and-suspenders against a "call, catch, log" pattern per research.md R5. NOTE: do NOT include `api` in the substring blocklist -- production code legitimately logs about API URLs (bestpractices.dev, GitHub API) that are unrelated to LLM calls.
- [X] T017 [US2] Add `test_deterministic_stub_registry_is_exhaustive` in `TestDeterministicOnly`. Reads BOTH `_MUST_NOT_BE_CALLED` and `_SUBPROCESS_STUBS`, imports each `(module, attr)` at test time, and asserts each resolves. Duplicates the T006 collection-time guard as a run-time signal that a future production rename will trip.

**Checkpoint**: User Story 2 delivers the deterministic-only proof; regressions that add a live network or LLM call surface as named failures.

---

## Phase 5: User Story 3 - Failure-path exit contract (Priority: P2)

**Goal**: Pin the exit-code + diagnostic behavior of each documented failure path so that a change in error-classification is not silently absorbed.

**Independent Test**: Run `pytest tests/darnit/cli/test_cmd_run_e2e.py -k failure` in isolation. Each test targets one failure category; each fails independently if that category's classification drifts.

### Implementation for User Story 3

- [X] T018 [US3] Add a `TestFailurePaths` class to `tests/darnit/cli/test_cmd_run_e2e.py`.
- [X] T019 [US3] Add `test_failure_missing_repo_path` in `TestFailurePaths`. Invokes `cmd_run` with a nonexistent path (e.g. `tmp_path / "does-not-exist"`); asserts `exit_code == 1` and captured stdout OR stderr contains a diagnostic naming the missing path. Reference: spec acceptance #1, FR-005; research.md R6 row 1.
- [X] T02& [US3] Add `test_failure_no_framework_implementation` in `TestFailurePaths`. Uses `monkeypatch.setattr("darnit.core.discovery.get_implementation", lambda *_: None)` (or the current equivalent), or uses a fixture whose `.baseline.toml` names an unregistered framework. Asserts `exit_code == 1` and the printed diagnostic mentions the missing framework name. Reference: spec acceptance #2, FR-005; research.md R6 row 2.
- [X] T02& [US3] Add `test_failure_malformed_project_yaml` in `TestFailurePaths`. Uses `malformed_project_tree` fixture from T004; invokes `cmd_run`; asserts `exit_code == 1` and captured output identifies either the config file or the YAML parse error. Reference: spec acceptance #3, FR-005; research.md R6 row 3.
- [X] T02& [US3] Add `test_failure_pending_feedback_prints_section` in `TestFailurePaths`. Uses a fixture that produces at least one unanswered question in noninteractive mode. If `darnit-testchecks` does not currently emit such a question, mark this test with `pytest.mark.skip(reason="pending feedback fixture not available in testchecks; TODO(#359)")` per data-model.md section 3 deferral. When enabled: asserts stdout contains `Pending human feedback (` and asserts the exit code follows the audit's pass/fail state (not the pending-question count) per contracts C5-C6, spec acceptance #4, FR-006.

**Checkpoint**: All three user stories deliver their coverage independently. Every FR from spec.md is now exercised by at least one test.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Final quality checks and documentation touch-ups.

- [X] T02& Run `uv run ruff check tests/darnit/cli/` and `uv run ruff format tests/darnit/cli/`; fix any lint findings.
- [X] T02& Run `uv run pytest tests/darnit/cli/test_cmd_run_e2e.py -v` on a clean workspace and verify all tests pass and total runtime is under 30 s locally (SC-005). Record the local timing in the PR description.
- [X] T02& [P] Run `uv run pytest tests/darnit/ -v` and confirm no existing test regressed. Existing suite runtime should not increase by more than the new file's local timing.
- [X] T02& [P] Manually execute the "Verify the golden-path pin actually pins" procedure from `quickstart.md`; confirm the deliberate `return 0` perturbation triggers at least one test failure whose message names exit code, then revert. Note the outcome in the PR description under `Verification:`.
- [X] T02& [P] Grep `tests/darnit/cli/` for non-ASCII characters; confirm zero hits (FR-012, contract C9).
- [ ] T028 Update the PR description to link to `specs/024-cmd-run-e2e-tests/spec.md` and `contracts/cmd_run-output.md`; note this is a test-only feature per issue #359 with no production code changes.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies. T001 must complete before T003-T007 can create files in that tree; T002 can run in parallel with T001.
- **Foundational (Phase 2)**: Depends on Setup. Within Phase 2: T003 and T004 are parallel; T005 depends on both being present in the tree; T006 and T007 are additions to the same conftest.py file so they run sequentially after T005.
- **User Story 1 (Phase 3)**: Depends on Phase 2. Within US1, T008 must land first (scaffold); T009-T013 all edit the same file (`test_cmd_run_e2e.py`) so they run sequentially.
- **User Story 2 (Phase 4)**: Depends on Phase 2. Can start in parallel with US1 in principle (different classes in the same file); in practice, T008 (the file scaffold) must land first, then T014-T017 append to the same file and run sequentially.
- **User Story 3 (Phase 5)**: Same shape as US2. T008 first, then T018-T022 sequential.
- **Polish (Phase 6)**: Depends on Phases 3-5. T023 and T024 sequential; T025/T026/T027 can run in parallel with each other; T028 last.

### User Story Dependencies

- All three user stories share Phase 2 foundational artifacts (fixtures, conftest, invocation helper), but each story's *coverage* is independent of the others. US2 does not depend on US1 passing; US3 does not depend on US1 or US2.
- The test file `test_cmd_run_e2e.py` is single-file; the three `Test*` classes coexist without interference.

### Within Each User Story

- No pre-implementation test writing here; the tests ARE the implementation.
- Task order within a story follows: class scaffold -> first assertion (simplest) -> additional assertions.
- Each story's tests can be authored, run, and reviewed independently.

### Parallel Opportunities

- Phase 1: T001 and T002 parallelizable.
- Phase 2: T003 and T004 parallelizable.
- Phase 6: T025, T026, T027 parallelizable.
- Across user stories: Phase 2 gates all three; after Phase 2, each user story can be authored in a separate short-lived branch and merged in any order (though they all land in the same PR here).

---

## Parallel Example: Phase 2

```bash
# After T001/T002 complete, run T003 and T004 in parallel:
Task: "Create the MinimalRepo fixture tree at tests/darnit/cli/fixtures/minimal_repo/"
Task: "Create the MalformedProjectYaml fixture tree at tests/darnit/cli/fixtures/malformed_project/"
```

## Parallel Example: Phase 6

```bash
Task: "Run uv run pytest tests/darnit/ -v and confirm no regressions"
Task: "Manually execute the 'Verify the golden-path pin actually pins' procedure from quickstart.md"
Task: "Grep tests/darnit/cli/ for non-ASCII characters; confirm zero hits"
```

---

## Implementation Strategy

### MVP first (User Story 1 only)

1. Complete Phase 1 (T001-T002).
2. Complete Phase 2 (T003-T007) -- foundational.
3. Complete Phase 3 (T008-T013) -- US1 golden path.
4. Stop and validate: `pytest tests/darnit/cli/test_cmd_run_e2e.py -k golden -v`. If green, US1 is done; a PR shipping just this delivers the primary regression baseline value.

### Incremental delivery

1. Setup + Foundational -> foundation ready.
2. Add US1 -> golden-path pin (MVP).
3. Add US2 -> deterministic-only proof (raises confidence bar).
4. Add US3 -> failure-path pinning (extends coverage).
5. Polish (Phase 6) -> ship.

For this feature the ship-as-one-PR path is preferred because all three stories are small, share fixtures, and land in a single test file. The independent-slice property still holds: any subset of the three stories is mergeable if the others are dropped or deferred.

### Parallel team strategy

Single-author feature; not applicable. If ever staffed by two authors, US2 and US3 can be authored in parallel after the shared foundational artifacts land in a base PR.

---

## Notes

- [P] tasks = different files (or independent operations), no dependencies on other unfinished tasks.
- [Story] label maps every user-story-phase task to its user story for traceability against spec.md.
- The feature is test-only per issue #359. No production code under `packages/darnit/src/`, `packages/darnit-baseline/src/`, or any other implementation package is modified. Any task that would require such a modification MUST be surfaced as an out-of-scope escalation before proceeding.
- Constitution Principle I safety net: tests under `tests/darnit/cli/` MUST reach the framework via plugin discovery (`.baseline.toml` -> `get_implementation`), NOT via direct `import darnit_testchecks` or `import darnit_baseline` from a test body. If a direct import ever becomes necessary (e.g. to inspect a test-check adapter's output shape), it MUST be justified in the test's docstring with a one-line rationale. This mirrors the framework-side Rule 1 that the constitution codifies for production code.
- Every assertion in the test file should cite (via inline comment or docstring) the contract item from `contracts/cmd_run-output.md` it pins. This makes each failure self-describing.
- Do not use `--no-verify` on commits. Do not add Co-Authored-By footers. ASCII-only in every new file.
- If the pending-feedback test (T022) cannot be written because `darnit-testchecks` lacks a feedback-emitting control, skip it with a documented `TODO(#359)` marker rather than expanding scope into implementation-package changes.
