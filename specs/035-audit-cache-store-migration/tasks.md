---

description: "Task breakdown for feature 035 (audit-cache store migration)"
---

# Tasks: Audit-Cache Store Migration

**Input**: Design documents from `/specs/035-audit-cache-store-migration/`

**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/audit-cache-wrapper.md](contracts/audit-cache-wrapper.md), [quickstart.md](quickstart.md)

**Tests**: Tests ARE included. FR-011 requires existing surface to keep passing; FR-013 requires a new driver-level integration test; SC-001/SC-006 are test-verified. Test tasks are explicit below.

**Organization**: Tasks are grouped by user story (US1..US4) so each story is independently testable. Foundational (Phase 2) wraps the three code touches that unblock every user story.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task belongs to (US1..US4)
- Include exact file paths in descriptions

## Path Conventions

- Product code: `packages/darnit/src/darnit/`
- Tests: `tests/darnit/`

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Verify preconditions. No new dependencies, no scaffolding.

- [X] T001 Verify feature 033 (`bundle.cache`, `FilesystemAuditCacheStore`, `resolve_stores`) and feature 034 (`LocalFsAuditCacheStore`, `UserLocalAuditCacheStore`) are importable from a clean `uv sync`: `uv run python -c "from darnit.stores.selection import resolve_stores; from darnit.stores.defaults.local_fs import LocalFsAuditCacheStore; print('ok')"`. If either import fails, halt and rebase.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The three code touches that make every user story work. All three land together.

**CRITICAL**: No user-story test tasks can pass until this phase is complete.

- [X] T002 Update `packages/darnit/src/darnit/stores/selection.py`: change the `cache` default_factory in `resolve_stores` so `cache_root` defaults to `Path(tempfile.gettempdir()) / "darnit" / hashlib.sha256(str(repo_path.resolve()).encode()).hexdigest()[:16]` (instead of `repo_path / ".darnit" / "audit-cache"`). Add `import hashlib` and `import tempfile` at the top of the file. Leave the attestation/report/project defaults unchanged (they still use `<repo>/.darnit/{attestations,reports}` and `<repo>/.project/`).

- [X] T003 Rewrite `packages/darnit/src/darnit/core/audit_cache.py`: keep the module's public docstring, `CACHE_FILENAME`, `CACHE_VERSION`, `_get_head_commit`, `_is_working_tree_dirty`, and `_get_cache_dir` (the last is kept as an internal helper for the default-store backward-compat path and for existing test fixtures). Introduce a module-level `_EXPIRED_ENVELOPE = {"version": 1, "timestamp": "1970-01-01T00:00:00Z", "commit": None, "commit_dirty": False, "level": 0, "framework": "", "results": [], "summary": {}}`. Rewrite `write_audit_cache(local_path, results, summary, level, framework, *, store=None, cache_key=None)`, `read_audit_cache(local_path, ttl_seconds=3600, *, store=None, cache_key=None)`, and `invalidate_audit_cache(local_path, *, store=None, cache_key=None)` per [contracts/audit-cache-wrapper.md](contracts/audit-cache-wrapper.md). When both `store` and `cache_key` are `None`, wrapper builds `FilesystemAuditCacheStore(root=_get_cache_dir(local_path))` and uses `cache_key = "audit-cache"` (byte-for-byte legacy path). If exactly one of the two is `None`, raise `TypeError("store and cache_key must be passed together")`. TTL / null-commit / HEAD-commit / dirty-state staleness checks stay in `read_audit_cache` (unchanged logic). `write_audit_cache` MUST NOT raise on any `OSError` from the store (FR-007); wrap the `store.write` call in try/except and log at warning level.

- [X] T004 Close the wiring gap in `packages/darnit/src/darnit/tools/audit.py::run_sieve_audit` (around line 667). Replace the direct `write_audit_cache(local_path, all_results, summary, level, resolved_fw or "")` with a store-routed call: compute `cache_key = "audit-cache" if (stores_config is None or stores_config.cache is None) else hashlib.sha256(str(Path(local_path).resolve()).encode()).hexdigest()[:16]`, then call `write_audit_cache(local_path, all_results, summary, level, resolved_fw or "", store=stores_bundle.cache, cache_key=cache_key)`. Import `hashlib` at the top of the file if not already present. Keep the enclosing `try/except Exception` (defensive belt-and-braces) but note the wrapper now swallows internally per FR-007.

**Checkpoint**: Foundation ready. All existing `tests/darnit/core/test_audit_cache.py` cases that don't touch the two behavior-change assertions (see US3 tasks) should now pass without modification. Run `uv run pytest tests/darnit/core/test_audit_cache.py -v` to sanity-check before proceeding.

---

## Phase 3: User Story 1 - Operator configures `[stores.cache]` (Priority: P1) MVP

**Goal**: Operator writes `[stores.cache] backend = "local-fs" root = "..."` in `.baseline.toml`, runs an audit twice, sees cache-file-under-root AND a cache hit on run 2.

**Independent Test**: Configure `[stores.cache] backend = "local-fs" root = "<tmp>/cache"` in a temp repo, run the audit driver twice, assert `<tmp>/cache/<hash>.json` exists and second run reads it.

### Tests for User Story 1

> Write these tests FIRST; they should FAIL before T004 lands and PASS after.

- [X] T005 [US1] Create `tests/darnit/test_audit_cache_store_wiring.py` with a `TestLocalFsBackendRouting` class. Add `test_config_moves_cache_to_configured_root`: (a) set up a temp git repo via the existing `temp_git_repo` fixture, (b) write a `.baseline.toml` at the repo root with `[stores.cache] backend = "local-fs"` and `root = "<tmp_path>/cache-out"`, (c) call `run_sieve_audit` with a mocked orchestrator (following the pattern from `TestRunSieveAuditCacheIntegration::test_run_sieve_audit_writes_cache` in `tests/darnit/core/test_audit_cache.py`), (d) assert a `.json` file exists under `<tmp_path>/cache-out/` with name `<sha256(abspath(repo))[:16]>.json`, (e) assert NO file exists under `<tempfile.gettempdir()>/darnit/`.

- [X] T006 [US1] Add `test_second_run_reads_cache_via_configured_store` to the same class in `tests/darnit/test_audit_cache_store_wiring.py`: run 1 writes cache under configured root; without git changes, invoke `read_audit_cache(local_path, store=bundle.cache, cache_key=<hash>)` directly (or via a helper that mimics what remediate would do) and assert the returned envelope's `results` match run-1's results. Locks SC-001.

- [X] T006a [US1] Add `test_shared_root_does_not_collide` to `TestLocalFsBackendRouting` in `tests/darnit/test_audit_cache_store_wiring.py`: set up two temp git repos (`repo_a`, `repo_b`) via explicit `tmp_path` subdirs plus git init, configure both with the same `.baseline.toml` block `[stores.cache] backend = "local-fs" root = "<shared>/cache"`, run the mocked audit driver against each in turn, assert BOTH `<shared>/cache/<hash_a>.json` AND `<shared>/cache/<hash_b>.json` exist, and assert `hash_a != hash_b`. Locks SC-006.

**Checkpoint**: US1 fully functional. Operator's `[stores.cache]` config takes effect end-to-end.

---

## Phase 4: User Story 2 - Zero-config default preserved (Priority: P1)

**Goal**: Operator who never touched `.baseline.toml` sees no on-disk change from pre-feature. Cache lands at `<tempdir>/darnit/<hash>/audit-cache.json`.

**Independent Test**: Run audit with no `[stores.*]` block, locate on-disk cache file, assert path matches legacy shape.

### Tests for User Story 2

- [X] T007 [P] [US2] Update `tests/darnit/stores/test_us2_zero_config.py::TestUS2ZeroConfig::test_filesystem_defaults_use_canonical_darnit_paths` (line 71-76). Keep the attestation and report assertions unchanged. Replace the cache assertion with: `expected_hash = hashlib.sha256(str(tmp_path.resolve()).encode()).hexdigest()[:16]; expected_root = Path(tempfile.gettempdir()) / "darnit" / expected_hash; assert bundle.cache._root == expected_root`. Add `import hashlib` and `import tempfile` at the top. Add a docstring line noting: "Cache default moved to legacy tempdir/hash location per feature 035 SC-008; other three defaults unchanged."

- [X] T008 [US2] Add `TestZeroConfigInvariance` class to `tests/darnit/test_audit_cache_store_wiring.py` with `test_no_baseline_toml_lands_at_legacy_tempdir_path`: set up a temp git repo with no `.baseline.toml`, run the mocked audit driver, assert `<tempfile.gettempdir()>/darnit/<sha256(abspath(repo))[:16]>/audit-cache.json` exists, assert no file under `<tmp>/` (the operator's working area) got touched. Locks SC-002 and preserves FR-010.

**Checkpoint**: US2 fully functional. Zero-config users see byte-for-byte identical on-disk behavior.

---

## Phase 5: User Story 3 - TTL and staleness preserved (Priority: P1)

**Goal**: 3600s TTL, git HEAD commit change, and working-tree dirty state changes all still invalidate the cache -- through both the default store and configured stores.

**Independent Test**: Existing `tests/darnit/core/test_audit_cache.py` staleness tests pass under the migrated wrapper. New staleness test under a configured local-fs store also passes.

### Tests for User Story 3

- [X] T009 [P] [US3] Update `tests/darnit/core/test_audit_cache.py`, two adjustments in the same file:
  1. `TestAtomicWrite::test_no_partial_file_on_error` (lines 280-293): replace `with pytest.raises(OSError):` with a plain call that MUST NOT raise. The subsequent `assert not cache_path.exists()` stays (the wrapper's default store's tempfile-then-rename cleanup handles the invariant). Update the class docstring or add an inline comment noting FR-007 relaxation.
  2. `TestInvalidateCache::test_invalidate_existing` (lines 256-262): keep the pre-write and post-invalidate assertions structural, but change the post-invalidate check from `assert not cache_path.exists()` to `assert read_audit_cache(str(temp_git_repo)) is None` (the file exists on disk with an expired envelope; the observable behavior is that the next read misses). Add an inline comment noting Q3 write-expired semantics.

- [X] T010 [US3] Add `TestStalenessThroughConfiguredStore` class to `tests/darnit/test_audit_cache_store_wiring.py`. Add `test_head_change_invalidates_configured_cache`: configure `[stores.cache] backend = "local-fs" root = "<tmp>/x"`, run audit, `git commit --allow-empty -m x`, run audit again, assert second run rebuilt the cache envelope (envelope's `commit` differs from run 1's). Add `test_dirty_state_change_invalidates_configured_cache`: run audit with clean tree, create an uncommitted file, run audit again, assert second run's envelope has `commit_dirty = True`. Locks SC-004 + SC-005 under a configured backend.

- [X] T010a [US3] Add `TestFaultInjection` class to `tests/darnit/test_audit_cache_store_wiring.py` with `test_store_write_failure_does_not_propagate`: build a `write_audit_cache` call passing a `store` whose `write` method is monkeypatched to raise `OSError("simulated disk full")`, plus a valid `cache_key = "audit-cache"`. Assert the call returns normally (does not raise). Wrap the call in `try/except OSError` and assert the except branch does NOT fire. Also assert a warning-level log line was emitted (via `caplog`). Locks SC-007's "single `cache.write` failure MUST NOT propagate to the audit's exit code."

**Checkpoint**: US3 fully functional. Correctness invariants of the cache (staleness) preserved through the store abstraction.

---

## Phase 6: User Story 4 - Public API backward compatibility (Priority: P2)

**Goal**: Existing consumers of `from darnit.core.audit_cache import write_audit_cache, read_audit_cache, invalidate_audit_cache` keep working with pre-feature call signatures.

**Independent Test**: Call each of the three wrapper functions with only positional args (no `store=`, no `cache_key=`); observe the same on-disk path as pre-feature.

### Tests for User Story 4

- [X] T011 [P] [US4] Add `TestBackwardCompatCallForm` class to `tests/darnit/test_audit_cache_store_wiring.py` with three tests:
  1. `test_positional_write_uses_legacy_tempdir_path`: call `write_audit_cache(str(temp_git_repo), sample_results, sample_summary, 1, "test")` with no kwargs, assert `<tempdir>/darnit/<hash>/audit-cache.json` exists.
  2. `test_positional_read_after_positional_write_hits`: pair with the above, assert `read_audit_cache(str(temp_git_repo))` returns the envelope.
  3. `test_partial_kwarg_raises_type_error`: call `write_audit_cache(str(temp_git_repo), [], {}, 1, "test", store=None, cache_key="foo")` and assert `TypeError` raised. Reciprocal for `store=<a real store>, cache_key=None`.

- [X] T012 [P] [US4] Run `uv run pytest tests/darnit/core/test_audit_cache.py -v` and confirm all tests pass. This locks FR-011 (existing test surface intact aside from the two adjusted in T009).

**Checkpoint**: US4 fully functional. Any pre-feature-035 external caller (including cached copies of `darnit-baseline`, third-party MCP tool wrappers, etc.) continues to work.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T013 Run `uv run pytest tests/darnit/ -v` and confirm the full framework test suite passes. Expected diffs: the four test adjustments from T007, T009 (two), and any new tests added in T005/T006/T008/T010/T011. All other pre-existing tests MUST pass unchanged.

- [X] T014 [P] Run `uv run ruff check .` and `uv run ruff format .` -- fix any lint / format drift introduced by the changes. Repo-wide, not per-file (learned in feature 034). NOTE: `ruff format .` reformatted 234 unrelated files across the repo (accumulated format drift, not feature 035); reverted those and kept only the format changes on this feature's 7 files, all of which pass `ruff check` clean.

- [X] T015 Walk through [quickstart.md](quickstart.md) Example 1 (CI operator) manually against `/tmp/test-repo`: initialize a git repo, add `.baseline.toml` with `[stores.cache] backend = "local-fs" root = "/tmp/qs-cache"`, run `darnit audit /tmp/test-repo --level 1`, confirm `/tmp/qs-cache/<hash>.json` exists, run again, confirm the log line "Audit cache hit ..." fires (from `read_audit_cache`'s existing debug log; may need to bump log level to see it). Verifies end-to-end wiring outside of pytest fixtures.

- [X] T016 Confirm no product-package or plugin-package import surfaces changed. Grep for `write_audit_cache\|read_audit_cache\|invalidate_audit_cache` under `packages/` and `packages/darnit-baseline/`, `packages/darnit-gittuf/`, `packages/darnit-reproducibility/`, `packages/darnit-hello/`: any hits outside `packages/darnit/src/darnit/{core,tools}/` and `tests/` are unexpected and should be inspected. Locks SC-009 (file-scope boundary).

---

## Dependencies & Execution Order

### Phase Dependencies

- **Phase 1 (Setup)**: no dependencies -- can start immediately.
- **Phase 2 (Foundational)**: depends on Phase 1. BLOCKS all user stories.
  - Within Phase 2: T002 -> T003 -> T004 must be strictly ordered (T003 depends on T002's new default so its own default helper aligns; T004 depends on T003's new wrapper signature).
- **Phase 3 (US1)**: depends on Phase 2 complete. T006 and T006a depend on T005 (file creation).
- **Phase 4 (US2)**: depends on Phase 2 complete. T007 and T008 are independent of each other but both touch different files (T007 -> existing test file, T008 -> new test file); both can proceed after T005 lands.
- **Phase 5 (US3)**: depends on Phase 2 complete. T009 (existing file) can run in parallel with T010 and T010a. T010 and T010a share `test_audit_cache_store_wiring.py` and are sequential within that file.
- **Phase 6 (US4)**: depends on Phase 2 complete. T011 and T012 are independent; both can run in parallel.
- **Phase 7 (Polish)**: depends on all US phases complete.

### User Story Dependencies

- **US1**: no dependencies on other stories.
- **US2**: no dependencies on other stories.
- **US3**: no dependencies on other stories.
- **US4**: no dependencies on other stories (existing test surface is the target; foundation must be in place).

### Within Each User Story

- Test additions target the new file `tests/darnit/test_audit_cache_store_wiring.py`. Multiple tasks touching that file are sequential within the file (US1's T005/T006/T006a, US2's T008, US3's T010/T010a, US4's T011). Between stories the file order is: T005 -> T006 -> T006a -> T008 -> T010 -> T010a -> T011.
- Existing-file test updates (T007 -> `test_us2_zero_config.py`, T009 -> `test_audit_cache.py`) each touch one file and can run in parallel with the new-file tasks.

### Parallel Opportunities

- **T007** and **T009** and **T010** can run in parallel with each other (three different files).
- **T014** can run in parallel with **T015** and **T016** (lint vs manual walkthrough vs grep).
- Nothing in Phase 2 can be parallelized; the ordering is a hard sequence.

---

## Parallel Example: Phase 5 (US3)

```bash
# Tests for US3 that touch different files can run together:
Task: "Update tests/darnit/core/test_audit_cache.py (T009): two behavior-change adjustments"
Task: "Add TestStalenessThroughConfiguredStore to tests/darnit/test_audit_cache_store_wiring.py (T010)"
```

---

## Implementation Strategy

### MVP first (US1 only)

1. Complete Phase 1 (Setup).
2. Complete Phase 2 (Foundational). The wrapper + driver + default cache_root together.
3. Complete Phase 3 (US1) -- the operator-configures-and-it-works story.
4. STOP and VALIDATE: confirm `[stores.cache] backend = "local-fs" root = "..."` in `.baseline.toml` actually redirects the cache file.
5. Demo / open PR draft.

### Incremental delivery

- After MVP, add US2 (zero-config invariance test coverage) so the release notes can honestly claim "no on-disk change for zero-config users."
- Add US3 (staleness under configured store) so operators trust the correctness gate.
- Add US4 (backward-compat tests) as belt-and-braces for external consumers.
- Polish (Phase 7) closes the PR.

### Solo strategy (this is likely a single-author feature)

Straight-through top-to-bottom is fine. Estimated wall time: 3-5 hours for Phase 1-7 including manual quickstart validation. No parallelization needed.

---

## Notes

- [P] tasks: different files, no dependencies on incomplete tasks.
- [Story] label: maps task to US1/US2/US3/US4 for traceability.
- Every user story is independently completable and testable after Phase 2.
- Commit after each phase (or each task within a phase for larger changes). Recommended commit boundary: after T002/T003/T004 together (foundation), then per-phase after each US.
- The task list assumes feature 034 (PR #412) is merged. If it isn't at implementation time, T005/T006 still work against `LocalFsAuditCacheStore` (feature 034 is in the code even pre-merge if on that branch); confirm at T001.
- Avoid: unrelated cleanup in `core/audit_cache.py` (this is a compliance tool; behavior-focused edits only per CLAUDE.md).
