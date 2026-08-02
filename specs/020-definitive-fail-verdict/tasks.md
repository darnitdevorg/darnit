---

description: "Task list for feature 020: preserve handler-conclusive FAIL through the CEL post-step (issue #343)"
---

# Tasks: Preserve handler-conclusive FAIL through the CEL post-step

**Input**: Design documents from `/specs/020-definitive-fail-verdict/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/cel-post-step.md`, `quickstart.md`

**Tests**: Included and TDD-ordered. The orchestrator change affects 12 downstream controls (research.md R5); tests must be written first and confirmed failing before the implementation change, both to prevent regression and to make the buggy-behavior audit surgical.

**Organization**: single P1 user story. All work maps to US1.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no shared state).
- **[Story]**: US1 for user-story tasks.
- File paths are absolute-from-repo-root.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Test-suite discovery before we start writing new tests, so we know what existing assertions need updating.

- [X] T001 Run the grep from `research.md` R7 to identify existing tests that assert behavior for the 12 affected controls. Command: `grep -rn "fail_exit_codes\|HandlerResultStatus.FAIL" tests/ | grep -E "(orchestrator|cel|branch_protection|AC-0[123]|BR-0[13]|GV-02|LE-02|QA-0[137]|VM-0[34])"`. Record the hits in this task's completion note. Categorize each hit as either (a) exercising the buggy `H=FAIL + CEL=true -> PASS` transition (must update in T009 after implementation), (b) exercising the correct-and-preserved behavior (no action needed), or (c) unrelated. Do NOT modify any test yet.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: None. Single user story with no shared prerequisites beyond T001.

**Checkpoint**: T001 complete; audit findings recorded. Ready to write tests.

---

## Phase 3: User Story 1 - Preserve handler-conclusive FAIL (Priority: P1)

**Goal**: The sieve orchestrator's CEL post-step preserves a handler-conclusive FAIL when the CEL expression also evaluates falsy. The four named branch-protection controls (`OSPS-AC-03.01`, `OSPS-AC-03.02`, `OSPS-QA-03.01`, `OSPS-QA-07.01`) report FAIL (not WARN) on a GitHub API 404 "Branch not protected" response.

**Independent Test**: `uv run pytest tests/darnit/sieve/test_orchestrator_cel.py tests/darnit_baseline/controls/test_branch_protection.py -v` passes; `/darnit-audit` against `/tmp/darnit-test-repo` reports the four controls as FAIL (verified per `quickstart.md` Layer 3).

**Ships as one PR.**

### Tests for User Story 1 (write first, must FAIL before implementation)

- [X] T002 [P] [US1] Write orchestrator CEL post-step unit tests at `tests/darnit/sieve/test_orchestrator_cel.py`. Cover all eight cells of the transition table in `contracts/cel-post-step.md` (test coverage section, items 1-8). Each test constructs a `HandlerResult` with an explicit `status` and `evidence`, invokes `_apply_cel_expr(handler_config, handler_result)` from `packages/darnit/src/darnit/sieve/orchestrator.py`, and asserts the resulting `PassOutcome`. Mark all with `@pytest.mark.unit`. Confirm tests 3 and 4 (Handler FAIL + CEL true -> INCONCLUSIVE; Handler FAIL + CEL false -> FAIL) FAIL on `main` before T008.

- [X] T003 [P] [US1] Write branch-protection FAIL-case integration tests at `tests/darnit_baseline/controls/test_branch_protection.py`. For each of `OSPS-AC-03.01`, `OSPS-AC-03.02`, `OSPS-QA-03.01`, `OSPS-QA-07.01`: patch the exec handler's subprocess invocation (e.g., via `unittest.mock.patch` on `subprocess.run`) to return `returncode=1` and `stdout=b'{"message": "Branch not protected", "documentation_url": "...", "status": "404"}'`; assert the control's final `PassOutcome` is `FAIL` (not `INCONCLUSIVE`); assert the resulting message string contains `Branch not protected`. Mark with `@pytest.mark.unit`. Confirm all four assertions FAIL on `main` before T008.

- [X] T004 [P] [US1] Write branch-protection PASS-case regression-guard tests at `tests/darnit_baseline/controls/test_branch_protection.py` (same file as T003). For the same four controls: patch subprocess to return `returncode=0` with a healthy JSON body containing `required_pull_request_reviews`, `required_status_checks`, and (for `OSPS-QA-07.01`'s `--jq` command) an integer >= 1; assert the final outcome is `PASS`. Confirms no PASS-path regression.

- [X] T005 [P] [US1] Write orchestrator pass-through tests at `tests/darnit/sieve/test_orchestrator_cel.py` (same file as T002) for the invariants FR-004, FR-005, FR-006, FR-008: handler INCONCLUSIVE/ERROR passes through unchanged; handler status with no expr passes through unchanged; CEL evaluation error passes through the handler's original result. Add an explicit WARN-preservation case for FR-008: patch subprocess to return an exit code that is in neither `pass_exit_codes` nor `fail_exit_codes` (e.g., 2 or 127, simulating network failure or command-not-found); assert the exec handler returns INCONCLUSIVE and the CEL post-step passes it through unchanged. These should all PASS on main today (guards against accidental regression).

### Audit before implementation

- [X] T006 [US1] Cross-reference the T001 audit findings against the new orchestrator behavior. For each test in category (a) from T001 (relies on buggy `H=FAIL + CEL=true -> PASS`), document in this task's completion note the exact assertion that needs updating and the new expected value. Do NOT edit tests yet; that happens in T009.

### Implementation for User Story 1

- [X] T007 [US1] Read `specs/020-definitive-fail-verdict/contracts/cel-post-step.md` and internalize the new transition table. This is a read-only prep step; no code change.

- [X] T008 [US1] Modify `_apply_cel_expr` in `packages/darnit/src/darnit/sieve/orchestrator.py` (lines 60-75) to implement the new transition table. Specifically: when the handler status is FAIL, CEL true yields INCONCLUSIVE (was PASS); CEL false yields the original FAIL preserved (was INCONCLUSIVE). Preserve all invariants: pass-through of ERROR/INCONCLUSIVE handler statuses (lines 47-52 unchanged), pass-through when `expr` absent (lines 43-45 unchanged), pass-through on CEL evaluation error (lines 76-81 unchanged). Update the docstring at lines 33-42 to reflect the new table with a two-column before/after summary. Do NOT introduce new config knobs; the semantics change is the correct default.

- [X] T009 [US1] Update each test flagged in T006 to match the new (correct) semantics. Add a one-line comment on each updated assertion referencing `specs/020-definitive-fail-verdict/contracts/cel-post-step.md`. If T006 found zero flagged tests, this task is a no-op; note that in the completion.

### Verification (deterministic layers)

- [X] T010 [US1] Run `uv run pytest tests/darnit/sieve/test_orchestrator_cel.py -v` and confirm all eight transition-table cases plus the pass-through invariants pass. Per `quickstart.md` Layer 1.

- [X] T011 [US1] Run `uv run pytest tests/darnit_baseline/controls/test_branch_protection.py -v` and confirm the four FAIL assertions (T003) and four PASS assertions (T004) all pass. Per `quickstart.md` Layer 2.

- [X] T012 [US1] Run `uv run pytest tests/ --ignore=tests/integration/ -m "not upstream" -q` and confirm no unrelated regression. Any failure not accounted for by T009's updates is a real regression; stop and diagnose.

- [X] T013 [US1] Run `uv run ruff check .` and `uv run python scripts/validate_sync.py --verbose` and confirm both pass.

### Verification (nondeterministic layer — mandatory)

- [X] T014 [US1] Re-install darnit as editable so the audit skill uses the branch's code: `uv tool install --reinstall --editable ./packages/darnit --with-editable ./packages/darnit-baseline --with-editable ./packages/darnit-gittuf --with-editable ./packages/darnit-reproducibility`. Confirm `darnit list` reports the framework loaded successfully. (Non-editable install is broken today per the note in feature 019 verification; issue #350-adjacent packaging bug.)

- [X] T015 [US1] Invoke `/darnit-audit` from within Claude Code targeted at `/tmp/darnit-test-repo` (created during feature 019 verification; recreate per `quickstart.md` if missing) at Level 1. Capture the output; confirm the four named branch-protection controls resolve to FAIL with a message referencing "Branch not protected". If the test repo is not authenticated to GitHub, the response may be a 401/403 rather than 404 "Branch not protected"; in that case, either (a) authenticate with `gh auth login` and re-run, or (b) confirm the audit still returns WARN (not FAIL) for the ambiguous non-404 case, which validates FR-008 (WARN preserved for ambiguous responses).

- [ ] T016 [US1] Optional live-repo layer (per `quickstart.md` Layer 4): if you have a GitHub repo whose default branch is unprotected AND authenticated `gh`, run `uv run darnit audit /path/to/repo -t level=1 --show-all --no-fail -o json | jq '[.controls[] | select(.id | test("OSPS-AC-03|OSPS-QA-03.01|OSPS-QA-07.01")) | {id, status}]'`. Expected: all four report `"status": "FAIL"`. Skip if no such repo is available; T015 is sufficient for feature acceptance.

**Checkpoint**: US1 is complete and shippable. Framework orchestrator behavior is correct; 12 downstream controls benefit automatically; the four named branch-protection controls report FAIL on definitive 404.

---

## Phase 4: Polish & Cross-Cutting Concerns

- [X] T017 [P] Draft a one-line release-notes bullet for the next tagged release's GitHub Release description: "Branch-protection controls now report FAIL (not WARN) on definitive `Branch not protected` responses from the GitHub API (fixes #343)." Repo has no `CHANGELOG.md` today; when the packaging release runbook needs a change summary, this is where the bullet lands.

- [X] T018 [P] Update `specs/019-verdict-correctness/tasks.md` to mark T008-T017 as superseded by feature 020, since 019 was originally scoped to bundle US2 but US1 shipped alone in PR #349. Add a note at the top of that file pointing readers here.

- [X] T019 Run the full `quickstart.md` end-to-end after T008-T015 complete, confirming every command produces the documented output.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: T001 is a discovery task; blocks T006 (which reads its output) and T008 (which relies on knowing which tests to update).
- **Foundational (Phase 2)**: empty.
- **US1 (Phase 3)**: depends on T001. Internal ordering per TDD: T002-T005 (tests) -> T006 (audit) -> T007-T008 (implementation) -> T009 (test updates) -> T010-T016 (verification).
- **Polish (Phase 4)**: depends on US1 checkpoint.

### Task-level dependencies

- T002-T005 all `[P]` — different test files, no shared state, all read-only against unfixed codebase.
- T006 blocked by T001 (needs the audit findings).
- T008 blocked by T002 and T003 (must confirm they FAIL before implementing).
- T009 blocked by T006 and T008 (need both the audit and the implementation before touching flagged tests).
- T010-T013 all sequential after T008 and T009 (share the same repo state).
- T014 blocked by T008 (want to install the fixed code).
- T015 blocked by T014.

### Parallel opportunities

- All of T002, T003, T004, T005 can be spawned in parallel after Phase 1.
- Polish tasks T017 and T018 can run in parallel with each other.

---

## Parallel Example: Phase 3 test writing

```bash
# Spawn concurrently after T001 completes:
Task: "Write orchestrator CEL post-step unit tests at tests/darnit/sieve/test_orchestrator_cel.py"
Task: "Write branch-protection FAIL-case integration tests at tests/darnit_baseline/controls/test_branch_protection.py"
Task: "Write branch-protection PASS-case regression-guard tests at tests/darnit_baseline/controls/test_branch_protection.py"
Task: "Write orchestrator pass-through invariant tests at tests/darnit/sieve/test_orchestrator_cel.py"
```

Note: T002 and T005 both edit `test_orchestrator_cel.py`, and T003 and T004 both edit `test_branch_protection.py`. If executed as separate agents, coordinate on file boundaries (or fold T005 into T002 and T004 into T003 as single writer tasks).

---

## Implementation Strategy

### MVP scope

The single P1 user story IS the MVP. There is no smaller shippable increment; a partial fix (e.g., handling only the 4 branch-protection controls without touching the orchestrator) would leave the underlying bug in the other 8 controls. Do the full orchestrator change.

### Ordering rationale

TDD is important here specifically because the orchestrator change is a semantic shift with 12 downstream consumers. Writing tests first + auditing existing assertions first + confirming the new tests fail on main first gives us a mechanical safety net: if T012's regression sweep produces an un-audited failure, we know something is wrong.

### Sequential single-contributor path

For one contributor: T001 (5 min) -> T002+T005 folded (30 min) -> T003+T004 folded (30 min) -> T006 (10 min) -> T007-T008 (20 min) -> T009 (variable, likely zero-to-small) -> T010-T013 (5 min) -> T014-T015 (15 min) -> T017-T019 (10 min). Total: roughly 2 hours of focused work.

---

## Notes

- [P] tasks = different files, no shared state.
- Every task cites the exact file path it edits or the exact command it runs.
- TDD enforced: T002 and T003's new-behavior assertions MUST fail on main before T008 is begun.
- T014 is the fix for the packaging bug discovered during feature 019 verification (source-tree layout required for path-based TOML resolution). If the packaging fix (issue #350-adjacent) lands separately before this work starts, T014 becomes a no-op.
- Constitution reminder: this feature strengthens Principles II and V. Any code review comment that would move a "we know it fails" case back to WARN should be rejected on constitutional grounds.
