---
description: "Task list for feature 030-dot-project-spec-sync"
---

# Tasks: Sync `.project/` reader with current CNCF spec

**Input**: Design documents in `specs/030-dot-project-spec-sync/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/reader-contract.md](./contracts/reader-contract.md), [quickstart.md](./quickstart.md).

**Tests**: Included. The spec's SC-002 (behavior parity pre-/post-reconciliation) and User Story 3's Independent Test both require a fixture-plus-golden-dict verification. User Story 2's Independent Test requires a fail-message regression. Both are covered below.

**Organization**: One phase per user story after Setup + Foundational. Every user-story task carries a `[USn]` label. Cross-story files are only touched in Setup / Foundational / Polish.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks).
- **[Story]**: `[US1]`, `[US2]`, `[US3]` matching spec's user stories.
- File paths are absolute-from-repo-root.

## Path Conventions

Single workspace repo. `packages/darnit/src/darnit/context/` is the sole product-code surface. Tests live in `tests/darnit/context/` and `tests/darnit/context/fixtures/`. Auxiliary docs in `specs/030-dot-project-spec-sync/`.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Prepare the two upstream `types.go` blobs the reconciliation reasons over. No source-code edits yet.

- [X] T001 Snapshot the tracked and current CNCF `types.go` into `/tmp/cncf-diff/` for reference during editing: fetch the current tip via `curl https://raw.githubusercontent.com/cncf/automation/main/utilities/dot-project/types.go` and the tracked-hash referent (commit `979abb1e07fa`) via the corresponding SHA URL; verify SHA-256 values match `860df23ecfd970b3d603098b6597a787e7ee6954b8592cdd17e431198eff70b4` (current) and `d8ca8361c0aff434e9d7288851717f88f149785419ca062a520cdd506ae6b27e` (tracked, matches `.github/dot-project-spec-hash.txt`).

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: Produce the single source-of-truth diff summary all three user stories reference. Editing `dot_project.py` without this artifact risks missing a field.

**CRITICAL**: No user story work begins until this phase completes.

- [X] T002 Write the authoritative upstream diff summary at `specs/030-dot-project-spec-sync/upstream-diff.md`, listing every changed field between `/tmp/cncf-diff/tracked.go` and `/tmp/cncf-diff/current.go` with per-row classification (RESHAPE / RENAMED / REMOVED / NEW). The rows MUST match [data-model.md](./data-model.md) Decision 1's table verbatim (`project_lead` RESHAPE, `package_managers` value-type RESHAPE, `cncf_slack_channel` RENAMED-with-alias, `slack_channels` NEW-IGNORED, `StringOrSlice` helper-only). Reviewers use this file to confirm the reconciliation covered the full drift.

**Checkpoint**: Foundation ready — user story implementation can begin.

---

## Phase 3: User Story 1 - Restore CI green on new PRs (Priority: P1) MVP

**Goal**: Reconcile `dot_project.py` with the current CNCF upstream so `test_upstream_spec_unchanged` passes without any override, controls that read `.project/`-sourced fields keep receiving the same values, and the tracked-hash file records the current upstream tip.

**Independent Test**: On a clean checkout of the reconciled branch, `uv run pytest tests/darnit/context/test_dot_project_upstream.py::TestUpstreamSpecSync::test_upstream_spec_unchanged` exits 0.

### Implementation for User Story 1

- [X] T003 [US1] Add a private helper `_coerce_scalar_or_list(value: Any) -> str` to `packages/darnit/src/darnit/context/dot_project.py` that returns the input when it is a scalar string, returns the first element when it is a non-empty list of strings, and returns `""` when the input is `None`, an empty list, or any other shape. Docstring cites CNCF `StringOrSlice` type and notes the parse-only scope (per feature 030 Q1 clarification).

- [X] T004 [US1] In `DotProjectReader._parse_project` (or the equivalent parsing site) inside `packages/darnit/src/darnit/context/dot_project.py`, route `data.get("project_lead", "")` through `_coerce_scalar_or_list` before assigning to `config.project_lead`. Preserve the existing scalar attribute type on `ProjectConfig`. Verify by mental trace that a scalar-form YAML value produces identical output to pre-reconciliation.

- [X] T005 [US1] In the same parsing site in `packages/darnit/src/darnit/context/dot_project.py`, transform each map value in `data.get("package_managers", {})` through `_coerce_scalar_or_list` before assigning to `config.package_managers`. Existing scalar-shape entries produce identical output; list-shape entries collapse to the first element per registry key.

- [X] T006 [US1] Add deprecation-warning emission for `cncf_slack_channel` in `packages/darnit/src/darnit/context/dot_project.py`: at the point where `data.get("cncf_slack_channel", "")` is read, if the key is present in `data` (regardless of value), call `warnings.warn(<message>, DeprecationWarning, stacklevel=2)` where `<message>` names the old key (`cncf_slack_channel`), the replacement (`slack_channels`), the current spec version (`1.2.0`), and the release in which the alias will be removed. Message text follows the pattern in `contracts/reader-contract.md`. Import `warnings` at module top if not already imported.

- [X] T007 [US1] Verify `slack_channels` lands in `ProjectConfig._extra` under the existing `_extra` forward-compat catch-all in `packages/darnit/src/darnit/context/dot_project.py`. If the current code path collects `_extra` from a whitelist of known keys, add `slack_channels` to that path's unknown-key aggregation. No new attribute on `ProjectConfig` (per feature 030 Q1: parse-only).

- [X] T008 [US1] Bump `DOT_PROJECT_SPEC_VERSION` from `"1.1.0"` to `"1.2.0"` in `packages/darnit/src/darnit/context/dot_project.py` (line 39). `DOT_PROJECT_SPEC_URL` unchanged.

- [X] T009 [US1] Add a reconciliation-history note to the module docstring of `packages/darnit/src/darnit/context/dot_project.py` recording the `1.1.0 -> 1.2.0` transition and the four items covered (project_lead reshape, package_managers reshape, cncf_slack_channel alias-with-warning, slack_channels NEW-IGNORED). Format matches the example in [quickstart.md](./quickstart.md) Step 3.

- [X] T010 [US1] Refresh `.github/dot-project-spec-hash.txt` to the current CNCF upstream SHA (`860df23ecfd970b3d603098b6597a787e7ee6954b8592cdd17e431198eff70b4`) by running `uv run pytest tests/darnit/context/test_dot_project_upstream.py -v --update-hash` from the repo root. Verify the file contents afterward match the expected hash.

**Checkpoint**: The reader parses the current upstream cleanly and CI's `test_upstream_spec_unchanged` passes without override. User Story 1 delivers its independent value at this point.

---

## Phase 4: User Story 2 - Loud detection of the next drift (Priority: P2)

**Goal**: When CNCF next changes their `.project/` specification, `test_upstream_spec_unchanged` fails loudly with a diagnostic that names both hashes and points a maintainer at this feature's reconciliation runbook.

**Independent Test**: Fabricate a stale hash in a copy of `.github/dot-project-spec-hash.txt` and confirm the test's failure message names both hashes and references `specs/030-dot-project-spec-sync/quickstart.md`.

### Implementation for User Story 2

- [X] T011 [P] [US2] Update the failure message in `tests/darnit/context/test_dot_project_upstream.py::test_upstream_spec_unchanged` (the `pytest.fail(...)` call around lines 88-105) to add a reference to `specs/030-dot-project-spec-sync/quickstart.md` as the runbook for the next reconciliation. Keep the existing links to `https://github.com/cncf/automation/tree/main/utilities/dot-project` and the open-PRs URL; add one more line: `Runbook for reconciling with a new upstream: specs/030-dot-project-spec-sync/quickstart.md`.

- [X] T012 [P] [US2] Add a regression test `test_upstream_spec_failure_message_names_both_hashes` in `tests/darnit/context/test_dot_project_upstream.py` that: (a) monkeypatches `HASH_FILE.read_text` (or the `get_tracked_hash` function) to return a fabricated hash different from any real upstream; (b) invokes the underlying comparison logic; (c) asserts the failure message string contains both the fabricated tracked hash AND the real current-upstream hash AND the substring `specs/030-dot-project-spec-sync/quickstart.md`. This test locks the loud-diagnostic behavior spec §User Story 2 relies on.

- [X] T013 [P] [US2] Add a regression test `test_upstream_spec_skips_when_offline` in `tests/darnit/context/test_dot_project_upstream.py` that monkeypatches `urllib.request.urlopen` (via `pytest.MonkeyPatch.setattr`) to raise `urllib.error.URLError("simulated offline")` and asserts the test collects as `SKIPPED` (not `FAILED`). This locks the FR-007 offline-skip behavior against a future rewrite of the sync-test's fetch path.

**Checkpoint**: The next upstream drift produces a failure whose diagnostic points every maintainer at this feature's runbook, and a network outage still skips cleanly.

---

## Phase 5: User Story 3 - Preserve real-world compatibility (Priority: P3)

**Goal**: Every field darnit reads from `.project/project.yaml` today continues to produce the same downstream value after the reconciliation, mechanically verified by a golden-dict test that exercises the mapper output.

**Independent Test**: `uv run pytest tests/darnit/context/test_full_field_coverage.py -v` exits 0.

### Implementation for User Story 3

- [X] T014 [P] [US3] Create `tests/darnit/context/fixtures/full_field_coverage.yaml`: a single `.project/project.yaml` populated with representative values for every field darnit consumes today (walk `dot_project.py`'s `ProjectConfig` attributes, cross-reference `dot_project_merger.py` and `dot_project_mapper.py` for the consumer surface). For `project_lead`, use the LIST form (`- @alice`) so the collapse-to-first path is exercised. For `package_managers`, use the LIST form for at least one registry so the same collapse path is exercised. For `cncf_slack_channel`, use the OLD YAML key (not `slack_channels`) so the deprecation-warning path is exercised.

- [X] T015 [P] [US3] Create `tests/darnit/context/test_full_field_coverage.py` with two tests: (a) `test_reader_output_matches_golden` loads `fixtures/full_field_coverage.yaml` via `DotProjectReader.load`, runs the resulting `ProjectConfig` through `dot_project_mapper.get_context`, and asserts the returned flat context dict equals a hand-authored golden `EXPECTED` dict inlined in the test source; (b) `test_extra_captures_slack_channels` asserts the resulting `ProjectConfig._extra["slack_channels"]` equals the raw list-of-objects value from the fixture (NEW-IGNORED verification). Suppress the `cncf_slack_channel` deprecation-warning noise during the fixture load by wrapping the `DotProjectReader.load(...)` call in a `warnings.catch_warnings():` block with `warnings.simplefilter("ignore", DeprecationWarning)` -- this test asserts on the mapper output and the `_extra` catch-all, not on the warning. The warning's content is separately asserted in T016.

- [X] T016 [P] [US3] Add TWO tests to `tests/darnit/context/test_dot_project.py` (or a new `test_dot_project_deprecations.py` if the file gets crowded):

  (a) `test_cncf_slack_channel_emits_deprecation_warning`: load a minimal `.project/project.yaml` containing the `cncf_slack_channel` key and assert (via `pytest.warns(DeprecationWarning) as record`) that a `DeprecationWarning` fires whose `str(warning.message)` contains `cncf_slack_channel`, `slack_channels`, and `1.2.0`. This is the PRESENCE case (US1 Acceptance Scenario 2).

  (b) `test_no_warning_when_cncf_slack_channel_absent`: load a minimal `.project/project.yaml` that OMITS `cncf_slack_channel` entirely. Assert (via `warnings.catch_warnings(record=True) as record` followed by `assert not any(issubclass(w.category, DeprecationWarning) for w in record)`) that no `DeprecationWarning` fires. Also assert `config.cncf_slack_channel == ""`. This is the ABSENCE case (US1 Acceptance Scenario 3): a repo that has already migrated must not be nagged.

**Checkpoint**: The mapper's output for the golden fixture is locked byte-for-byte; the deprecation warning content is locked. Any silent semantic drift in a future reconciliation trips one of these tests.

---

## Phase 6: Polish & Cross-Cutting Concerns

**Purpose**: Verify no unrelated regression, lint clean, product-scope invariants preserved.

- [X] T017 Run the full workspace sweep from repo root: `uv run pytest tests/ -q --deselect tests/darnit/context/test_dot_project_upstream.py::TestUpstreamSpecSync::test_upstream_spec_unchanged` (excluding the deselected test because it is separately verified in T010, T012, and T013). Confirm exit code 0.

- [X] T018 [P] Verify no file outside `packages/darnit/src/darnit/context/` and `.github/dot-project-spec-hash.txt` was modified under `packages/*/src/`: `git diff --name-only main..HEAD | grep -E 'packages/(darnit-baseline|darnit-gittuf|darnit-reproducibility)/src/'` MUST produce zero lines. This is the plan's Structure Decision property (single-file reconciliation in `dot_project.py`).

- [X] T019 [P] Run `uv run ruff check .` and `uv run ruff format --check .` on the repo root; both MUST exit 0. Fix any formatting-only issues raised.

- [X] T020 Post-implementation consistency review of `packages/darnit/src/darnit/context/dot_project.py`. Two sub-steps, both MUST pass:

  (a) Docstring vs. diff cross-read: read the reconciliation-history block added in T009 alongside `git diff main..HEAD -- packages/darnit/src/darnit/context/dot_project.py`. Any item in the history block with no matching diff hunk, or any diff hunk that touches consumer-visible behavior without a history entry, is a discrepancy to fix.

  (b) FR-008 signature check: run `git diff main..HEAD -- packages/darnit/src/darnit/context/dot_project.py | grep -E '^[+-] *(async )?def '` and confirm that every changed `def` line is either (i) unchanged in signature, (ii) added a new PARAMETER WITH A DEFAULT VALUE (not a required arg), or (iii) is the new `_coerce_scalar_or_list` private helper introduced in T003. Any public callable that gained a required parameter is a FR-008 violation and MUST be fixed before merge.

---

## Dependencies

```
Phase 1 (T001) ──> Phase 2 (T002) ──> Phase 3 (US1: T003..T010)
                                          │
                                          ├──> Phase 4 (US2: T011, T012, T013) [all [P] within phase]
                                          │
                                          ├──> Phase 5 (US3: T014, T015, T016) [all [P] within phase]
                                          │
                                          └──> Phase 6 (Polish: T017..T020)
```

Within Phase 3 (US1), tasks T003 → T004 → T005 → T006 → T007 → T008 → T009 are sequential because they all edit the same file (`dot_project.py`); T010 depends on T003..T009 completing (the tracked-hash refresh runs the reconciled reader against the current upstream). No `[P]` markers on US1 tasks.

Phase 4 (US2) and Phase 5 (US3) can execute in parallel with each other because their file surfaces are disjoint (test files vs. `dot_project.py` and its dependents already fixed in US1). Within each phase, the `[P]`-marked tasks touch distinct files.

Phase 6 tasks T018 and T019 are parallelizable (`git diff` inspection vs. `ruff` invocation, no shared state); T017 (full sweep) runs first because it is the most expensive; T020 (final consistency + FR-008 signature review) requires the final state and runs last.

## Parallel execution examples

Once US1 (Phase 3) completes:

```sh
# Fire the three US2 tasks and the three US3 tasks concurrently
# (each edits a distinct file; no serialization needed).
uv run pytest tests/darnit/context/test_dot_project_upstream.py -v &
# ... US2 T011 message edit, US2 T012 both-hashes test, US2 T013 offline-skip test,
# US3 T014 fixture, US3 T015 golden test, US3 T016 deprecation tests
wait
```

Within Phase 6:

```sh
uv run pytest tests/ -q --deselect ... # T017 (long-running; start it first)
git diff --name-only main..HEAD | grep ...  # T018 (fast, [P])
uv run ruff check . && uv run ruff format --check .  # T019 (fast, [P])
# T020 runs after T017 completes
```

## Implementation strategy

MVP scope = Phase 1 + Phase 2 + Phase 3 (User Story 1 alone). Landing US1 restores CI green on every downstream PR — the highest-leverage outcome.

Incremental delivery order:

1. Land T001..T010 as a single commit (or a small stack of commits, per maintainer preference). At this point CI is green and the reader is reconciled.
2. Land T011..T013 (US2) as a follow-up commit; independent of US1 code but a much smaller diff.
3. Land T014..T016 (US3) as a follow-up commit; introduces the golden-fixture safety net that catches future silent semantic drift and locks the deprecation-warning content (both presence and absence cases).
4. Land T017..T020 (Polish) as the last commit or squash into a prior commit.

All four commits belong to the same PR against `main`. If the PR is reviewed piecewise, the recommended reviewer order is (reader edits, US2 tests, US3 tests, polish) so each commit's contract-level effect is legible independently.
