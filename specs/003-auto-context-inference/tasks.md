# Tasks: Auto Context Inference

## Phase 1: Foundational — Fix `file_exists` handler (FR-1)

**Goal**: Fix the `file_exists` handler so it detects directories (not just files). This unblocks all TOML detect pipelines that reference directories.

**Test criteria**: `file_exists_handler` returns PASS for directories, files, and globs; returns FAIL for nonexistent paths.

- [X] T001 Change `os.path.isfile(path)` to `os.path.exists(path)` in `packages/darnit/src/darnit/sieve/builtin_handlers.py` (line 72)
- [X] T002 [P] Add test `test_file_exists_handler_directory` — handler returns PASS for a directory path in `tests/darnit/sieve/test_builtin_handlers.py`
- [X] T003 [P] Add test `test_file_exists_handler_file` — handler still returns PASS for a regular file in `tests/darnit/sieve/test_builtin_handlers.py`
- [X] T004 [P] Add test `test_file_exists_handler_nonexistent` — handler returns FAIL for a missing path in `tests/darnit/sieve/test_builtin_handlers.py`
- [X] T005 Run existing tests to verify no regressions: `uv run pytest tests/darnit/sieve/ -v`

## Phase 2: TOML detect pipeline — `has_releases` (FR-2)

**Goal**: Add local filesystem detection steps to the `has_releases` detect pipeline so it works offline.

**Test criteria**: `has_releases` is detected as `true` when CHANGELOG.md exists, when git tags exist, or when release workflows exist — without network access.

- [X] T006 [US1] Add 3 filesystem detect steps before the existing `gh release list` step in `[context.has_releases].detect` in `packages/darnit-baseline/openssf-baseline.toml`
- [X] T007 [P] [US1] Add test `test_has_releases_detect_changelog` — `_run_detect_pipeline` returns `value=true` when CHANGELOG.md exists in `tests/darnit/config/test_context_storage.py`
- [X] T008 [P] [US1] Add test `test_has_releases_detect_git_tags` — `_run_detect_pipeline` returns `value=true` when `git tag --list` returns output (mock exec) in `tests/darnit/config/test_context_storage.py`
- [X] T009 [P] [US1] Add test `test_has_releases_detect_release_workflow` — `_run_detect_pipeline` returns `value=true` when `.github/workflows/release.yml` exists in `tests/darnit/config/test_context_storage.py`
- [X] T010 [US1] Run tests: `uv run pytest tests/darnit/config/test_context_storage.py -v -k has_releases`

## Phase 3: TOML detect pipeline — `platform` (FR-3)

**Goal**: Add a `[context.platform]` definition with a detect pipeline that identifies the hosting platform from git remote URLs and `.github/` directory presence.

**Test criteria**: `platform` is detected as `"github"` when git remote contains `github.com`; appears with null value when no remote exists; falls back to `.github/` directory check.

- [X] T011 [US2] Add `[context.platform]` section with detect pipeline to `packages/darnit-baseline/openssf-baseline.toml`
- [X] T012 [P] [US2] Add test `test_platform_detect_github_remote` — `_run_detect_pipeline` returns `value="github"` when git remote contains `github.com` (mock exec) in `tests/darnit/config/test_context_storage.py`
- [X] T013 [P] [US2] Add test `test_platform_detect_gitlab_remote` — `_run_detect_pipeline` returns `value="gitlab"` when git remote contains `gitlab.com` (mock exec) in `tests/darnit/config/test_context_storage.py`
- [X] T014 [P] [US2] Add test `test_platform_detect_no_remote_fallback` — pipeline falls through exec steps, detects `.github/` directory via `file_exists` in `tests/darnit/config/test_context_storage.py`
- [X] T015 [US2] Add test `test_platform_in_pending_context_null` — `platform` appears in `get_pending_context` with `current_value=None` when all detect steps fail in `tests/darnit/config/test_context_storage.py`
- [X] T016 [US2] Run tests: `uv run pytest tests/darnit/config/test_context_storage.py -v -k platform`

## Phase 4: Wire persisted context into audit (FR-4)

**Goal**: Make `collect_auto_context()` merge persisted `.project/darnit.yaml` values into its returned dict so the audit sees confirmed context.

**Test criteria**: `collect_auto_context()` returns persisted values from `.project/darnit.yaml`; persisted values override auto-detected; works without `.project/`.

- [X] T017 [US3] Add persisted context loading at top of `collect_auto_context()` with lazy import and try/except in `packages/darnit/src/darnit/context/auto_detect.py`
- [X] T018 [US3] Guard each existing auto-detect call with `if key not in context` to avoid overriding persisted values in `packages/darnit/src/darnit/context/auto_detect.py`
- [X] T019 [P] [US3] Add test `test_collect_auto_context_with_persisted` — returns persisted `ci_provider` from `.project/darnit.yaml` in `tests/darnit/context/test_auto_detect.py`
- [X] T020 [P] [US3] Add test `test_collect_auto_context_persisted_overrides` — persisted value takes precedence over auto-detected in `tests/darnit/context/test_auto_detect.py`
- [X] T021 [P] [US3] Add test `test_collect_auto_context_no_project_dir` — auto-detection works normally when no `.project/` exists in `tests/darnit/context/test_auto_detect.py`
- [X] T022 [US3] Run tests: `uv run pytest tests/darnit/context/test_auto_detect.py -v`

## Phase 5: Validation & Polish

**Goal**: Ensure all tests pass, linting is clean, and spec sync validates.

- [X] T023 Run full test suite: `uv run pytest tests/ --ignore=tests/integration/ -q`
- [X] T024 Run linter and fix any issues: `uv run ruff check .`
- [X] T025 Run spec-implementation sync: `uv run python scripts/validate_sync.py --verbose`
- [X] T026 Run doc generation and check for changes: `uv run python scripts/generate_docs.py && git diff docs/generated/`

## Dependencies

```
Phase 1 (FR-1) ──→ Phase 2 (FR-2) ──→ Phase 4 (FR-4) ──→ Phase 5 (Validation)
                ──→ Phase 3 (FR-3) ──↗
```

- Phase 1 must complete before Phases 2 and 3 (FR-2/FR-3 use `file_exists` handler)
- Phases 2 and 3 are independent and can run in parallel
- Phase 4 depends on Phases 2+3 (needs values to persist and read back)
- Phase 5 runs last

## Parallel Execution Opportunities

- **T002, T003, T004**: All handler tests are independent (different test functions, same file)
- **T007, T008, T009**: All `has_releases` detect tests are independent
- **T012, T013, T014**: All `platform` detect tests are independent
- **T019, T020, T021**: All `collect_auto_context` tests are independent
- **Phase 2 and Phase 3**: Entirely parallel after Phase 1 completes

## Implementation Strategy

**MVP**: Phase 1 (T001-T005) — fixes the `file_exists` handler bug. This alone unblocks `ci_provider` auto-detection for all GitHub Actions projects.

**Incremental delivery**:
1. Phase 1: Bug fix — immediate value
2. Phase 2: `has_releases` offline detection — reduces API dependency
3. Phase 3: `platform` TOML detection — completes the context inference story
4. Phase 4: Audit integration — connects confirmed context to audit results
