---

description: "Task list for feature 019: verdict correctness fixes (issues #342 and #343)"
---

# Tasks: Conservative-by-default verdict correctness

**Input**: Design documents from `/specs/019-verdict-correctness/`

**Prerequisites**: `plan.md`, `spec.md`, `research.md`, `data-model.md`, `contracts/cel-post-step.md`, `quickstart.md`

**Tests**: Included. The spec explicitly requires a regression test (FR-003), and the orchestrator change (US2) is a framework-level behavior shift that must be TDD'd to avoid regressing the 12 affected controls (research.md R5).

**Organization**: Tasks are grouped by user story. The two stories in this spec are fully independent and are expected to ship as separate PRs (spec.md Assumptions).

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies).
- **[Story]**: Which user story this task belongs to (US1, US2).
- File paths are absolute-from-repo-root and always specified.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: The vendored upstream OSPS Baseline fixture used by the US1 regression test. Vendor once; both the test infra and the test itself live in Phase 3.

- [X] T001 Create fixtures directory at `tests/darnit_baseline/fixtures/osps-baseline/` with a README pointing to the upstream release (`ossf/security-baseline` tag `v2025.10.10`) it was vendored from and the date/commit vendored.
- [X] T002 Vendor the OSPS Baseline YAML files (`baseline/OSPS-*.yaml`) from `ossf/security-baseline` at tag `v2025.10.10` into `tests/darnit_baseline/fixtures/osps-baseline/`. Copy the source files verbatim (do not summarize into JSON) so future spec bumps produce a reviewable diff.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: None. The two user stories touch disjoint files (`packages/darnit-baseline/openssf-baseline.toml` for US1; `packages/darnit/src/darnit/sieve/orchestrator.py` for US2) and have no shared prerequisites beyond the Phase 1 fixture (which is only used by US1).

**Checkpoint**: Setup complete. US1 and US2 can start in parallel (in separate branches for separate PRs).

---

## Phase 3: User Story 1 - Level 1 audit does not over-scope (Priority: P1) MVP-A

**Goal**: `OSPS-LE-01.01` classified at Level 2, per-level counts match upstream OSPS Baseline v2025.10.10 (24 / 18 / 20). Regression test asserts parity going forward.

**Independent Test**: `uv run pytest tests/darnit_baseline/test_level_counts.py -v` passes and asserts L1=24, L2=18, L3=20 with `OSPS-LE-01.01` NOT in the Level 1 set (from `quickstart.md` US1).

**Ships as its own PR.**

### Tests for User Story 1 (write first, must FAIL before implementation)

- [X] T003 [P] [US1] Write per-level counts regression test at `tests/darnit_baseline/test_level_counts.py`. The test loads the vendored fixture from `tests/darnit_baseline/fixtures/osps-baseline/`, derives expected per-level sets from each control's `applicability` field, loads the framework's actual per-level sets via `get_implementation('openssf-baseline').get_controls_by_level(n)`, and asserts equality (symmetric diff empty). On failure, the test's message must list the misclassified control identifiers in both directions. Mark with `@pytest.mark.unit`. Confirm this test FAILS on `main` (before T005) with `OSPS-LE-01.01` reported in the L1-only-in-framework set.

- [X] T004 [P] [US1] Extend the test in T003 with a companion assertion that the count summary (`{1: 24, 2: 18, 3: 20}`) matches the values documented in `docs/USAGE_GUIDE.md:137-139`. This is a secondary check: if the doc drifts, the test still fails. Both assertions live in the same test file.

### Implementation for User Story 1

- [X] T005 [US1] Change the `level` tag for `OSPS-LE-01.01` from `1` to `2` at `packages/darnit-baseline/openssf-baseline.toml:1543`. Line reads: `tags = { level = 1, domain = "LE", legal = true, license = true }`. Change to `level = 2`. No other change in this file.

- [X] T006 [US1] Run `uv run pytest tests/darnit_baseline/test_level_counts.py -v` and confirm it now passes. Run `uv run python scripts/validate_sync.py --verbose` and confirm no regression.

### Manual verification (per quickstart.md US1)

- [X] T007 [US1] Execute the quickstart cross-check block from `specs/019-verdict-correctness/quickstart.md` (US1 section, "Manual cross-check") and confirm it prints `OK` without assertion errors.

**Checkpoint**: US1 is fully functional and shippable as a standalone PR. Level 1 audits no longer over-scope; regression test blocks CI on future drift.

---

## Phase 4: User Story 2 - Definitive "not protected" is reported as failing (Priority: P1) MVP-B

> **Superseded by feature 020.** US2 was lifted into its own feature
> (`specs/020-definitive-fail-verdict/`) after US1 shipped as PR #349,
> per the "one PR per feature" pattern that emerged during US1
> implementation. See feature 020's spec/plan/tasks for the current work
> plan; the tasks below are retained for historical context only.

**Goal**: Branch-protection controls report FAIL (not WARN) when the GitHub API returns HTTP 404 with body "Branch not protected". The fix modifies the sieve orchestrator's CEL post-step so a handler-conclusive FAIL is preserved when the CEL expression also evaluates falsy (see `contracts/cel-post-step.md`).

**Independent Test**: `uv run pytest tests/darnit_baseline/controls/test_branch_protection.py -v` passes; all four named controls (`OSPS-AC-03.01`, `OSPS-AC-03.02`, `OSPS-QA-03.01`, `OSPS-QA-07.01`) resolve to FAIL against a stubbed 404 response (from `quickstart.md` US2 path b).

**Ships as its own PR, independent of US1.**

### Tests for User Story 2 (write first, must FAIL before implementation)

- [ ] T008 [P] [US2] Write orchestrator CEL post-step unit tests at `tests/darnit/sieve/test_orchestrator_cel.py`. Cover all eight cells of the transition table in `specs/019-verdict-correctness/contracts/cel-post-step.md` (test coverage section, items 1-8). Each test asserts the exact resulting `PassOutcome` for a given (handler status, CEL result, `expr` presence) triple. Mark with `@pytest.mark.unit`. Confirm tests 3 and 4 (the new-behavior rows: FAIL+true and FAIL+false) FAIL on `main` before T012.

- [ ] T009 [P] [US2] Write branch-protection integration test at `tests/darnit_baseline/controls/test_branch_protection.py`. For each of `OSPS-AC-03.01`, `OSPS-AC-03.02`, `OSPS-QA-03.01`, `OSPS-QA-07.01`: patch the exec handler's subprocess call to return `returncode=1`, `stdout=b'{"message": "Branch not protected", "documentation_url": "...", "status": "404"}'`, and assert the control's final `PassOutcome` is `FAIL` (not `INCONCLUSIVE`, not `WARN`). Also assert that the resulting message string contains "Branch not protected" so users can see the reason. Mark with `@pytest.mark.unit`. Confirm all four assertions FAIL on `main` before T012.

- [ ] T010 [P] [US2] Regression-guard test at `tests/darnit_baseline/controls/test_branch_protection.py` (same file as T009): given the same four controls, patch the exec handler to return `returncode=0` with a healthy branch-protection JSON body (containing `required_pull_request_reviews`, `required_status_checks`, `required_pull_request_reviews.required_approving_review_count=1`), and assert the final outcome is `PASS` for each. Confirms the orchestrator change does not regress the happy path.

### Audit before implementation

- [ ] T011 [P] [US2] Audit the existing test suite for tests that rely on the old (buggy) CEL post-step behavior for `H=FAIL + CEL=true -> PASS`. Grep `tests/` for handler results with `status=HandlerResultStatus.FAIL` combined with a truthy-CEL assertion expecting PASS. For each hit, determine whether the test is exercising buggy behavior (documented in `research.md` R5) or a legitimate scenario, and record the finding in this task's completion note. Do NOT modify tests yet — that happens in T013 if needed.

### Implementation for User Story 2

- [ ] T012 [US2] Modify `_apply_cel_expr` in `packages/darnit/src/darnit/sieve/orchestrator.py` (lines 60-75) to implement the new transition table from `contracts/cel-post-step.md`. Specifically: when the handler returned FAIL, CEL true yields INCONCLUSIVE (was PASS); CEL false yields the original FAIL (was INCONCLUSIVE). Preserve all existing invariants: pass-through of ERROR/INCONCLUSIVE handler statuses, pass-through when `expr` is absent, pass-through on CEL evaluation error. Update the docstring at lines 33-42 to reflect the new table. Do NOT introduce new config knobs or TOML fields; the semantics change is the correct default.

- [ ] T013 [US2] For each existing test flagged in T011 as relying on buggy behavior: update the assertion to match the new (correct) semantics, and add a one-line comment referencing `specs/019-verdict-correctness/contracts/cel-post-step.md` for context. If none were flagged, this task is a no-op — note that in the task completion.

- [ ] T014 [US2] Run `uv run pytest tests/darnit/sieve/test_orchestrator_cel.py -v` and confirm all eight cases pass.

- [ ] T015 [US2] Run `uv run pytest tests/darnit_baseline/controls/test_branch_protection.py -v` and confirm the four FAIL assertions from T009 and the four PASS assertions from T010 all pass.

### Full regression sweep

- [ ] T016 [US2] Run `uv run pytest tests/ --ignore=tests/integration/ -m "not upstream" -q` and confirm no regression outside the tests updated in T013. If any test unrelated to the audit in T011 fails, stop and diagnose; do not blanket-update assertions.

### Manual verification (per quickstart.md US2, live-repo path)

- [ ] T017 [US2] Optional: if a repository with no branch protection is available, execute the "Manual live-repo check" block from `quickstart.md` US2 and confirm all four named controls report `FAIL` in the JSON output. If no such repo is available, skip and rely on T009/T010 unit coverage. Record which path was used.

**Checkpoint**: US2 is fully functional and shippable as a standalone PR. Branch-protection controls give conclusive verdicts; the orchestrator's CEL post-step correctly preserves handler conclusions.

---

## Phase 5: Polish & Cross-Cutting Concerns

- [ ] T018 Run the full quickstart (`specs/019-verdict-correctness/quickstart.md`) end-to-end after both US1 and US2 have merged, and confirm every command produces the documented output. This is a final smoke test independent of the story-level checks.

- [ ] T019 [P] File a follow-up GitHub issue in `darnitdevorg/darnit` for the LE-01.01 semantic content drift noted in `research.md` R6 (darnit implements LE-01.01 as `HasLicense`, but upstream OSPS defines it as DCO/CLA contribution track). Link this feature's PR(s) for context and reference upstream `baseline/OSPS-LE.yaml`. Do NOT bundle the content fix into this feature — it is a separate scope.

- [ ] T020 Add an entry in `CHANGELOG.md` (or wherever release notes accumulate for v0.1.x) noting the two verdict corrections: LE-01.01 reclassified to Level 2; branch-protection controls now FAIL on definitive 404. Cite issues #342 and #343.

---

## Dependencies & Execution Order

### Phase Dependencies

- **Setup (Phase 1)**: No dependencies. Blocks only Phase 3 (US1 depends on the vendored fixture).
- **Foundational (Phase 2)**: Empty. No blocking work.
- **User Story 1 (Phase 3)**: Depends on Phase 1 (fixture vendored). Independent of US2.
- **User Story 2 (Phase 4)**: Independent of US1 and Phase 1. Can start immediately after Phase 2 checkpoint (which is trivially satisfied).
- **Polish (Phase 5)**: Depends on both US1 and US2 having merged.

### Story-level Dependencies

- **US1 and US2 have zero dependency on each other.** They touch different files, exercise different tests, and can be developed, reviewed, and merged in either order or in parallel by different contributors. The spec bundles them by theme only.

### Within Each User Story

- Tests are written and confirmed FAILING before implementation (TDD).
- For US2 specifically: T011 (audit of existing tests) must complete before T012 (the orchestrator change) so we know which tests need updating in T013.

### Parallel Opportunities

- T001 and T002 are sequential (T002 vendors into the dir T001 creates).
- Within US1: T003 and T004 are the same file and depend on T001+T002; not parallel to each other but can be a single commit.
- Within US2: T008, T009, T010, T011 are all [P] — different files, no shared state, all read-only against the (still-unfixed) codebase.
- Cross-story: **US1 and US2 can run entirely in parallel** by two contributors on two branches after Phase 1 completes.

---

## Parallel Example: User Story 2 setup

```bash
# T008 through T011 can be spawned as four parallel work items after Phase 1 checkpoint:
Task: "Write orchestrator CEL post-step unit tests at tests/darnit/sieve/test_orchestrator_cel.py"
Task: "Write branch-protection integration test at tests/darnit_baseline/controls/test_branch_protection.py (FAIL cases)"
Task: "Add branch-protection regression guard test at tests/darnit_baseline/controls/test_branch_protection.py (PASS cases)"
Task: "Audit existing tests for reliance on buggy H=FAIL+CEL=true -> PASS behavior"
```

---

## Implementation Strategy

### Two independent shippable PRs

The spec explicitly bundles US1 and US2 at the spec level only. Each should ship as its own PR:

**PR A (US1):** T001 + T002 + T003 + T004 + T005 + T006 + T007. Small: one TOML line change, one new test file, one vendored fixture directory. Low risk. Merge first if convenient; not blocking on US2.

**PR B (US2):** T008 + T009 + T010 + T011 + T012 + T013 + T014 + T015 + T016 + T017. Larger: framework-level orchestrator change with 12 downstream controls affected. TDD required. Higher review burden.

**Polish (Phase 5):** After both PRs merge. T018-T020 can be a single small PR or folded into the second PR's cleanup.

### Suggested MVP scope

Either US1 or US2 alone is a valid MVP for this spec. If cadence dictates picking one:

- **Pick US1 first** if the goal is a quick, low-risk correctness win with immediate user-visible impact (Level 1 audits stop over-scoping).
- **Pick US2 first** if the goal is to unlock better verdicts across 12 controls (broader reach, but larger change).

### Parallel team strategy

With two contributors: A takes PR A (US1), B takes PR B (US2). Neither blocks the other. Merge in whichever order reviews complete. Then the polish PR reconciles.

---

## Notes

- [P] tasks = different files, no shared state.
- Every task cites the exact file path it edits or the exact command it runs.
- TDD is enforced: T003, T008, T009, T010 must fail on `main` before their corresponding implementation tasks are begun.
- Commit granularity: at least one commit per completed task, more if a task naturally splits (e.g., T002 could be one commit per vendored YAML file if that helps the diff).
- Constitution reminder: this feature strengthens Principles II and V. Any code review comment that would move a "we know it fails" case back to WARN should be rejected on constitutional grounds.
