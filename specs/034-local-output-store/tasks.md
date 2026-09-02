---
description: "Task list for feature 034: local output data store"
---

# Tasks: Local Output Data Store

**Input**: Design documents from `/specs/034-local-output-store/`
**Prerequisites**: [plan.md](plan.md), [spec.md](spec.md), [research.md](research.md), [data-model.md](data-model.md), [contracts/](contracts/), [quickstart.md](quickstart.md)
**Branch**: `034-local-output-store`

## Format: `[ID] [P?] [Story] Description with file path`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks)
- **[Story]**: Which user story this task serves (US1, US2, US3, US4). Setup / Foundational / Polish tasks have no story label.
- Every task cites a concrete file path or contract reference so an implementer can act on it in isolation.

Tests are included per user story because the spec's SC-001..009 are testable acceptance criteria; skipping tests would leave the spec unenforced.

---

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: verify the baseline is intact so any regression this feature causes is immediately visible.

- [X] T001 Verify `git branch --show-current` prints `034-local-output-store` and `git status` is clean.
- [X] T002 Run the feature 033 store test suite to establish the pre-change baseline: `uv run pytest tests/darnit/stores/ -q`. Record the pass count; this feature MUST NOT reduce it. **Baseline: 97 passed.**

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: shared helpers every US depends on. Small; the store classes themselves live in their US phases.

**⚠️ CRITICAL**: No user story work begins until this phase is complete.

- [X] T003 Create `packages/darnit/src/darnit/stores/defaults/local_fs.py` with module-level constants and shared helpers ONLY (no concrete `LocalFs*Store` class yet). Specifically:
  - `_LOCAL_LOGGER_NAME = "darnit.stores.local"` and a module-level `logger = get_logger(_LOCAL_LOGGER_NAME)`.
  - `_resolve_root_config(root: str | Path) -> Path` per R-003 and E-001 root-resolution rules: if `Path`, return as-is; if `str`, call `substitute_dollar_vars(root, missing="raise")`, then `os.path.expanduser`, then `Path(...).resolve()`. Docstring cites data-model.md E-001.
  - `_log_wrote(kind_tag: str, backend: str, resolved_path: Path) -> None`: single `logger.info("wrote %s (%s): %s", kind_tag, backend, str(resolved_path))` call. Docstring cites FR-015.
  - Import `_sanitize_filename` from `.attestation` for later reuse by test code (do not shadow).
- [X] T004 [P] Create `packages/darnit/src/darnit/stores/defaults/platform_paths.py` skeleton with four public functions (`xdg_data_home`, `xdg_cache_home`, `user_data_root`, `user_cache_root`) that all `raise NotImplementedError` for now. Docstring per data-model.md E-003. Concrete implementation lands in Phase 5.
- [X] T005 [P] Write `tests/darnit/stores/test_local_fs_helpers.py` covering `_resolve_root_config` directly: absolute path pass-through, `~` expansion, `$VAR` interpolation, `$VAR` missing raises `KeyError`, combined `~/$VAR/x`. Uses `monkeypatch.setenv` for env vars. 6-8 test cases.

**Checkpoint**: local-fs foundation ready. US1 implementation can now begin.

---

## Phase 3: User Story 1 - OSPO leader consolidates attestations (Priority: P1) 🎯 MVP

**Goal**: `[stores.attestation] backend = "local-fs" root = "/tmp/x"` causes attestations to land at `/tmp/x/<bundle_id>.<ext>` instead of `<repo>/.darnit/attestations/`. This is the OSPO-leader consolidation story and the MVP for this feature.

**Independent Test**: with only `[stores.attestation] backend = "local-fs" root = "/tmp/agg"` configured, run an audit that emits an attestation. Verify the bundle exists at `/tmp/agg/<sanitized-bundle_id>.<ext>` and NOT under `<repo>/.darnit/attestations/`. Verify one info log line with `local-fs` and the resolved path.

- [X] T006 [P] [US1] Add `LocalFsAttestationStore` class to `packages/darnit/src/darnit/stores/defaults/local_fs.py`. Implements `AttestationStore`. `__init__(self, root, **_)` calls `_resolve_root_config` and stores the result; instantiates an internal `FilesystemAttestationStore(root=<resolved>)` for delegation. `write(bundle_id, bundle_bytes, content_type)` delegates to the internal store, then calls `_log_wrote("attestation", "local-fs", <target_path>)` on success. `close()` no-op. Reuses `_sanitize_filename` via the delegated store; NO local re-implementation.
- [X] T007 [US1] Add entry-point registration for `local-fs` under `darnit.stores.attestation` in `packages/darnit/pyproject.toml`. Follow the format used by feature 033's `filesystem` registration (search for `[project.entry-points."darnit.stores.attestation"]`).
- [X] T008 [P] [US1] Add `LocalFsAttestationStore` to the re-exports in `packages/darnit/src/darnit/stores/defaults/__init__.py`. Preserve alphabetical order.
- [X] T009 [P] [US1] Write `tests/darnit/stores/test_local_fs_backend.py::TestLocalFsAttestation` with cases: (a) round-trip write + read-back file bytes; (b) content-type -> extension mapping (intoto, sigstore, unknown -> `.bin`); (c) path-traversal sanitization via `bundle_id = "../../etc/foo"` -- assert the resulting on-disk path is `resolved_root / <sanitized_name>` AND that `resolved_root.resolve()` is a parent of the actual path (SC-005: verify no directory escape by resolving both sides, not just filename shape); (d) unwritable `root` (e.g. `root = /root/no-perm/` on a non-root test session) raises `StoreOperationError` -- assert the raised exception's message contains the string `"local-fs"`, the string `"attestation"`, AND the resolved absolute path (SC-008: verify the error surface, not just that an error was raised); (e) `root = "$MISSING_VAR"` raises `KeyError` at store construction, before any write.
- [X] T010 [P] [US1] Write `tests/darnit/stores/test_local_fs_logging.py::TestAttestationLogging` with caplog capturing `darnit.stores.local` at INFO. Assert exactly ONE line per write. Assert the message matches `"wrote attestation (local-fs): <resolved-path>"`. Assert that a `FilesystemAttestationStore` write emits ZERO lines to this logger (SC-009 zero-config exemption).
- [X] T011 [P] [US1] Write `tests/darnit/stores/test_local_fs_isolation.py::test_only_attestation_redirects`: build a `.baseline.toml` in a `tmp_path` repo with `[stores.attestation] backend = "local-fs" root = "<tmp_root>"` and NO other `[stores.*]` blocks. Invoke `resolve_stores`. Verify `bundle.attestation` is a `LocalFsAttestationStore`; `bundle.report`, `bundle.cache`, `bundle.project` are the pre-feature `Filesystem*Store` classes. Do NOT run a full audit (kept scoped to store selection).
- [X] T012 [US1] Add a copy-pasteable snippet to `docs/plugin-authoring/stores.md` under a new "Writing artifacts outside the repo" section, showing the `[stores.attestation] backend = "local-fs" root = "$DARNIT_ATT_ROOT"` example from quickstart § 1. Include the "env-var interpolation is the multi-repo escape hatch" explanation from the spec's Clarifications section.

**Checkpoint**: US1 complete. `pytest tests/darnit/stores/test_local_fs_backend.py tests/darnit/stores/test_local_fs_logging.py tests/darnit/stores/test_local_fs_isolation.py -q` all pass. `pytest tests/darnit/stores/ -q` overall pass count MUST be >= T002 baseline + these new tests. This satisfies SC-002 (no in-repo writes when redirected), SC-005 (sanitizer), SC-006 (partial: attestation section landed), SC-007 (partial: attestation isolation), SC-008 (unwritable root error), SC-009 (partial: attestation logging).

---

## Phase 4: User Story 2 - CI runner redirects reports and cache (Priority: P2)

**Goal**: `[stores.report] backend = "local-fs" root = "$RUNNER_ARTIFACTS_DIR/reports"` + `[stores.cache] backend = "local-fs" root = "$RUNNER_CACHE_DIR/darnit"` cause reports and cache to land outside the repo. Second-run cache hits work.

**Independent Test**: with the two blocks above, run an audit twice back-to-back against the same commit. Verify (a) Markdown/JSON/SARIF reports land under `<RUNNER_ARTIFACTS_DIR>/reports/`; (b) audit-cache hits on second run because it was written to `<RUNNER_CACHE_DIR>/darnit/` and read back from there; (c) neither location is `<repo>/.darnit/*`.

- [X] T013 [P] [US2] Add `LocalFsReportStore` class to `packages/darnit/src/darnit/stores/defaults/local_fs.py`. Same shape as T006 but delegates to `FilesystemReportStore`. `write_markdown` / `write_json` / `write_sarif` each call `_log_wrote(kind_tag, "local-fs", <target_path>)` with `kind_tag` = `"report:markdown"` / `"report:json"` / `"report:sarif"` respectively.
- [X] T014 [P] [US2] Add `LocalFsAuditCacheStore` class to same file. Delegates to `FilesystemAuditCacheStore`. On successful `write`, log `_log_wrote("cache", "local-fs", <target_path>)`. `read` does NOT log (it's a no-op on miss and doesn't produce a new file). Failed writes (best-effort per Protocol) do NOT emit the info line; they hit `logger.debug` only, inherited from the delegate.
- [X] T015 [DEFERRED - see plan revision] Originally: `LocalFsProjectStateStore`. Deferred because (a) reimplementing `.project/`-prefix-free YAML I/O is scope creep the plan didn't budget for, (b) the audit driver still uses `repo_path` for non-store work so a redirected project store has weird semantics, and (c) FR-009's canonical answer is "`.project/` stays in-repo". Matches how `user-local` deliberately skips the project registration. Documented as unavailable in T012's docs update rather than shipped-but-unusual.
- [X] T016 [US2] Add TWO entry-point registrations to `packages/darnit/pyproject.toml`: `local-fs` under `darnit.stores.report` and `darnit.stores.cache`. (Not three -- see T015 deferral for why `darnit.stores.project` is skipped.)
- [X] T017 [P] [US2] Extend `packages/darnit/src/darnit/stores/defaults/__init__.py` re-exports to include `LocalFsReportStore`, `LocalFsAuditCacheStore`, `LocalFsProjectStateStore`.
- [X] T018 [P] [US2] Add `TestLocalFsReport` to `tests/darnit/stores/test_local_fs_backend.py`. Cases: (a) round-trip for all three formats; (b) filename extensions correct (`.md`, `.json`, `.sarif`); (c) sanitization of `report_id` (same escape-parent assertion shape as T009 case (c)). About 4 tests.
- [X] T019 [US2] Add `TestLocalFsAuditCache` to the same file (`test_local_fs_backend.py`). NOT parallelizable with T018: both tasks append to the same file, so serialize -- T018 lands first, T019 second. Cases: (a) write then read round-trip; (b) tempfile-then-rename is same-directory (assert on `tempfile.mkstemp` `dir=` argument via monkeypatch OR inspect the file list during a controlled failure); (c) write to unwritable `root` returns None on subsequent read AND does NOT raise (best-effort per Protocol); (d) TTL / staleness passes through to the delegate unchanged (feature 033's existing tests cover this at the delegate level; assert one integration hit here). About 4-5 tests.
- [X] T020 [P] [US2] Add `TestReportLogging` and `TestCacheLogging` to `tests/darnit/stores/test_local_fs_logging.py`. Report logging: three writes -> three log lines with distinct `kind_tag`. Cache logging: successful write -> one line; failed write -> ZERO info lines (but debug line is fine).
- [X] T021 [US2] Extend `tests/darnit/stores/test_local_fs_isolation.py` with `test_report_and_cache_isolation`: `[stores.report]` + `[stores.cache]` set to `local-fs` with different roots, `[stores.attestation]` and `[stores.project]` unset. Assert `bundle.report` is `LocalFsReportStore`, `bundle.cache` is `LocalFsAuditCacheStore`, and the other two are the pre-feature filesystem defaults.
- [X] T022 [US2] Update `docs/plugin-authoring/stores.md` "Writing artifacts outside the repo" section: add the quickstart § 2 CI example.

**Checkpoint**: US2 complete. Full `pytest tests/darnit/stores/ -q` continues to pass. SC-002, SC-005, SC-006 (report+cache), SC-007 (report+cache isolation), SC-009 (report+cache logging) all satisfied.

---

## Phase 5: User Story 3 - `user-local` with platform-conventional roots (Priority: P2)

**Goal**: `[stores.<kind>] backend = "user-local"` writes to XDG/Apple/LOCALAPPDATA paths without the operator spelling out a `root`. `.project/` remains in-repo (FR-009).

**Independent Test**: on Linux with `XDG_DATA_HOME` unset, configure `[stores.attestation] backend = "user-local"`. Run an audit that emits an attestation. Verify the bundle lands at `~/.local/share/darnit/attestations/`. Repeat with `XDG_DATA_HOME=/tmp/xdg`; verify it now lands under `/tmp/xdg/darnit/attestations/`.

- [X] T023 [US3] Implement `xdg_data_home()`, `xdg_cache_home()`, `user_data_root()`, `user_cache_root()` in `packages/darnit/src/darnit/stores/defaults/platform_paths.py`. Follow the platform-dispatch algorithm in data-model.md E-003 and research.md R-001. Handle unknown platforms with XDG fallback. Log the resolved root at debug level for troubleshooting.
- [X] T024 [P] [US3] Write `tests/darnit/stores/test_platform_paths.py` with parametrized coverage: (a) `xdg_data_home()` with `$XDG_DATA_HOME` set + unset; (b) `xdg_cache_home()` same; (c) `user_data_root()` with `platform.system()` monkeypatched to `"Linux"`, `"Darwin"`, `"Windows"`, `"FreeBSD"` (unknown fallback); (d) `user_cache_root()` same set; (e) `LOCALAPPDATA` env var handling for Windows path. About 10 test cases.
- [X] T025 [US3] Create `packages/darnit/src/darnit/stores/defaults/user_local.py` with `UserLocalAttestationStore`, `UserLocalReportStore`, `UserLocalAuditCacheStore`. Each extends its matching `LocalFs*Store`. In `__init__`, ignore any incoming `root` kwarg with a WARNING log line (per data-model.md E-002 and contracts/user-local.md warn-and-ignore section) that includes the resolved platform root. Then call `super().__init__(root=<platform-resolved-root>)`. Logging uses backend name `"user-local"`; the `LocalFs*Store` parent's info-log already handles that when the caller passes `backend` -- adjust the info-log helper if needed to accept an override.
  - Implementation note: to avoid duplicating log logic, either pass a `backend_name` class attribute (`_BACKEND_NAME = "user-local"` on the subclass) OR override the write methods to call `_log_wrote` with the right backend before delegating. Data-model.md E-005 says shared logger name and format; use the class-attribute approach.
- [X] T026 [US3] Add three entry-point registrations in `packages/darnit/pyproject.toml`: `user-local` under `darnit.stores.attestation`, `darnit.stores.report`, `darnit.stores.cache`. **CRITICAL: do NOT register `user-local` under `darnit.stores.project`** -- this enforces FR-009 at the discovery layer. `resolve_stores` will raise `StoreNotInstalled` if the operator writes `[stores.project] backend = "user-local"`.
- [X] T027 [P] [US3] Add `UserLocalAttestationStore`, `UserLocalReportStore`, `UserLocalAuditCacheStore` to `packages/darnit/src/darnit/stores/defaults/__init__.py` re-exports.
- [X] T028 [P] [US3] Write `tests/darnit/stores/test_user_local_backend.py` with cases: (a) round-trip for each kind on the runtime platform, using an XDG override to keep tests in `tmp_path`; (b) explicit `root` kwarg is warn-and-ignored (assert on the WARNING log via caplog; assert the platform-computed root is used regardless); (c) info-log line uses backend name `"user-local"` (SC-009 backend correctness). About 6-8 test cases.
- [X] T029 [P] [US3] Add `test_user_local_project_state_not_registered` to `tests/darnit/stores/test_user_local_backend.py`: build a `.baseline.toml` with `[stores.project] backend = "user-local"`. Call `resolve_stores`. Assert it raises `StoreNotInstalled` with a message naming `user-local` and `darnit.stores.project`. This locks FR-009 at the discovery layer.
- [X] T030 [P] [US3] Extend `tests/darnit/stores/test_local_fs_isolation.py` with `test_user_local_attestation_project_stays_in_repo`: `[stores.attestation] backend = "user-local"`, no other `[stores.*]` block set. Assert `bundle.attestation` is `UserLocalAttestationStore`, `bundle.project` is `FilesystemProjectStateStore` (in-repo). Confirms SC-007 for the user-local variant.
- [X] T031 [US3] Update `docs/plugin-authoring/stores.md` "Writing artifacts outside the repo" section: add the quickstart § 3 XDG example with the per-platform resolved-path table.

**Checkpoint**: US3 complete. Full `pytest tests/darnit/stores/ -q` passes. SC-004 (platform paths) fully satisfied via monkeypatched unit tests; a Windows-runner integration pass is a stretch goal (see Polish).

---

## Phase 6: User Story 4 - Zero-config unchanged (Priority: P1)

**Goal**: an existing darnit user who never configures `[stores.*]` sees byte-for-byte identical behavior. This story has no new production code; it's a verified invariant.

**Independent Test**: run an audit on a repo with NO `[stores.*]` block. Every artifact lands at the exact same path it landed at before this feature.

- [X] T032 [US4] Run `uv run pytest tests/darnit/stores/test_us2_zero_config.py -q`. **3/3 pass.** This is the feature-033 witness for the zero-config invariant; it MUST pass unchanged. If it fails, the change to `stores/defaults/__init__.py` or the entry-point registrations broke the invariant -- diagnose before continuing.
- [X] T033 [US4] Write `tests/darnit/stores/test_us4_zero_config_local.py` covering the NEW invariant: with no `[stores.*]` config, none of the new `LocalFs*` or `UserLocal*` entry points are loaded; the `bundle.attestation` / `.report` / `.cache` / `.project` properties still resolve to their pre-feature `Filesystem*Store` classes. Uses `_reset_discovery_cache` to ensure clean state.
- [X] T034 [US4] Add a note to `docs/plugin-authoring/stores.md` "Writing artifacts outside the repo" section: "Zero-config behavior is unchanged. If you do not add `[stores.*]` blocks, artifacts continue to land in `<repo>/.darnit/` exactly as before this feature."

**Checkpoint**: US4 verified. SC-003 satisfied via `test_us2_zero_config.py` continuing to pass.

---

## Phase 7: Polish & Cross-Cutting Concerns

- [X] T035 [P] Ensure `docs/plugin-authoring/stores.md` "Writing artifacts outside the repo" section is complete: three quickstart examples (T012, T022, T031), the `.project/` FR-009 note, and a "Troubleshooting" subsection matching quickstart § Troubleshooting. Verify against SC-006.
- [X] T036 [P] Run `uv run ruff check .` -- clean. on repo root; MUST exit 0. Auto-fix any lint issues in the files this feature touched; do NOT auto-format unrelated files.
- [X] T037 [P] Run `uv run python scripts/validate_sync.py --verbose` -- all validations pass.; MUST exit 0. This feature introduces no new handlers so the sync check should be a no-op.
- [X] T038 Run the full workspace test sweep -- **3061 passed, 26 skipped, 0 failed**. from repo root: `uv run pytest tests/ -q --deselect tests/darnit/context/test_dot_project_upstream.py::TestUpstreamSpecSync::test_upstream_spec_unchanged`. Confirm exit code 0. Pass count MUST equal the T002 baseline + all new tests added in Phases 3-6 (T005, T009, T010, T011, T018, T019, T020, T021, T024, T028, T029, T030, T033).
- [X] T039 [P] Structure decision guard -- all changes within `stores/defaults/`, `pyproject.toml`, `stores/__init__.py`, `docs/plugin-authoring/stores.md`, `tests/darnit/stores/`.: confirm no file outside `packages/darnit/src/darnit/stores/defaults/`, `packages/darnit/pyproject.toml`, `packages/darnit/src/darnit/stores/__init__.py` (if re-exports move up), `docs/plugin-authoring/stores.md`, and `tests/darnit/stores/` was modified. Command: `git diff --name-only main..HEAD | grep -vE '^(specs/|packages/darnit/src/darnit/stores/defaults/|packages/darnit/pyproject.toml|packages/darnit/src/darnit/stores/__init__.py|docs/plugin-authoring/stores.md|tests/darnit/stores/|CLAUDE.md)'` MUST produce zero lines.
- [X] T040 [P] FR-014 no-new-runtime-dep guard -- pyproject.toml diff is entry-point registrations only, no `[project.dependencies]` change.: `git diff main..HEAD -- packages/*/pyproject.toml` MUST NOT add any entry under `[project.dependencies]`. Entry-point additions under `[project.entry-points.*]` are the only permitted TOML changes.
- [ ] T041 [DEFERRED - no Windows CI runner available] Stretch goal: if a Windows CI runner is available, add an integration test job in `.github/workflows/ci.yml` that runs `test_user_local_backend.py::TestUserLocalAttestation` on Windows and asserts on the `%LOCALAPPDATA%` resolution. Skip this task if no Windows runner exists at implement time; the unit-test coverage via `platform.system()` monkeypatch is sufficient for SC-004.

**Checkpoint**: feature ready to ship. All 8 success criteria satisfied. Full sweep clean, ruff clean, sync clean, no scope creep outside the planned files.

---

## Dependency graph

```
Phase 1 (T001..T002)  ── verify baseline
        │
        ▼
Phase 2 (T003..T005)  ── shared helpers + skeleton platform_paths + helper tests
        │
        ▼
Phase 3 (T006..T012)  ── US1: LocalFsAttestationStore MVP  [P1]
        │
        ▼
Phase 4 (T013..T022)  ── US2: report + cache + project variants  [P2]
        │
        ▼
Phase 5 (T023..T031)  ── US3: platform_paths impl + UserLocal*  [P2]
        │
        ▼
Phase 6 (T032..T034)  ── US4: zero-config invariant verified  [P1]
        │
        ▼
Phase 7 (T035..T041)  ── polish + guards
```

US1..US3 are file-disjoint in their implementation half (T006/T013/T014/T015/T025) so they COULD be authored in parallel. Their tests live in overlapping files (`test_local_fs_backend.py`, `test_local_fs_logging.py`, `test_local_fs_isolation.py`), so serialize on those.

US4 depends on US1 through US3 all landing (it's a verification story, not new implementation).

## Parallel opportunities

Within Phase 3 (US1):
- T006 (class), T008 (re-exports), T009 (backend tests), T010 (logging tests), T011 (isolation test) can be authored in parallel once T003 lands. T007 (pyproject registration) can go in parallel with all of them.

Within Phase 4 (US2):
- T013, T014, T015 all touch the same `local_fs.py` file -- serialize.
- T017 (init re-exports), T018/T019 (tests in separate files), T020 (logging tests in separate file), T021 (isolation test in separate file), T022 (docs) can go in parallel once the three classes land.

Within Phase 5 (US3):
- T023 (platform_paths impl) and T024 (platform_paths tests) can go in parallel (T024 was scaffolded in T004).
- T025 (user_local classes) depends on T023.
- T028/T029/T030/T031 can go in parallel once T025 + T026 (registrations) land.

## Implementation strategy

**MVP delivery**: Phases 1-3 alone deliver US1 -- OSPO leader can consolidate attestations across many repos. This is publicly usable and worth shipping as an increment if timeline dictates.

**Incremental after MVP**: Phase 4 (US2 CI operator) is the most common secondary use case; ship next. Phase 5 (US3 XDG defaults) is convenience-layer polish; can ship third or bundle with Phase 4 if timeline allows. Phase 6 (US4 zero-config invariant) always ships in the same increment as the phases that could break it.

**Skip Phase 7's T041** if no Windows CI runner is available at implement time; note the deferral in the PR body and file a follow-up issue for later Windows validation.
