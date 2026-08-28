---
description: "Task list for feature 033-pluggable-stores"
---

# Tasks: Pluggable storage backends via per-artifact Protocols

**Input**: Design documents in `specs/033-pluggable-stores/`

**Prerequisites**: [plan.md](./plan.md), [spec.md](./spec.md), [research.md](./research.md), [data-model.md](./data-model.md), [contracts/](./contracts/), [quickstart.md](./quickstart.md).

**Tests**: Included. Spec has explicit measurable success criteria (SC-001 zero regression, SC-002 backend-equivalence, SC-003 zero-config filesystem invariance, SC-004 lazy instantiation, SC-005 plugin-author time budget, SC-006 failure-message content, SC-007 fail-fast on misconfig, SC-008 static-import invariant) that require mechanical verification via fixture-driven tests. Every user story's Independent Test requires a fixture-driven behavior test. Tests are load-bearing.

**Organization**: One phase per user story after Setup + Foundational. Every user-story task carries a `[USn]` label. Cross-story files (Protocol definitions, discovery, selection, env-subst helper, static-import guard) are only touched in Setup / Foundational / Polish.

## Format: `[ID] [P?] [Story] Description`

- **[P]**: Can run in parallel (different files, no dependencies on incomplete tasks).
- **[Story]**: `[US1]`, `[US2]`, `[US3]`, `[US4]` matching spec's user stories.
- File paths are absolute-from-repo-root.

## Path Conventions

Single workspace repo. New product code under `packages/darnit/src/darnit/stores/` and `packages/darnit/src/darnit/core/env_subst.py`. Config-schema touches under `packages/darnit/src/darnit/config/`. Call-site rewrites under `packages/darnit-baseline/src/darnit_baseline/attestation/`, `packages/darnit/src/darnit/core/audit_cache.py`, `packages/darnit/src/darnit/context/dot_project*.py`, and `packages/darnit/src/darnit/tools/audit.py`. Test-only in-memory backends under `packages/darnit-testchecks/src/darnit_testchecks/stores/`. New tests under `tests/darnit/stores/` and updates to existing `tests/darnit/context/`, `tests/darnit_baseline/attestation/`, `tests/darnit/core/test_audit_cache.py`.

## Phase 1: Setup (Shared Infrastructure)

**Purpose**: Introduce the two new module files the rest of the feature builds on, plus the docs update naming the new extension surface.

- [X] T001 Create `packages/darnit/src/darnit/stores/__init__.py` with a module docstring that names the sub-package's purpose (pluggable per-artifact persistence Protocols; four Protocols; filesystem defaults; entry-point discovery matching feature 027's pattern). Re-export the four Protocol classes plus the four exception classes for the public API surface. No behavior yet; scaffold only.

- [X] T002 [P] Create `packages/darnit/src/darnit/stores/errors.py` with the exception hierarchy per research decisions: `StoreError` (base), `StoreNotInstalled` (selection names an unregistered backend), `StoreProtocolMismatch` (registered class does not satisfy the Protocol), `StoreNameCollision` (two entry points register the same short name in one group), `StoreOperationError` (backend-side operational failure at read/write time). Each subclass includes a docstring naming the FR it maps to (FR-002 / FR-008 / FR-009 / FR-011 as applicable).

- [X] T003 [P] Add a one-line addition to Section 12 of `docs/architecture/framework-design.md` naming `darnit.stores` as a persistence extension surface alongside `darnit.frameworks` and `darnit.question_resolvers`. Cite the four entry-point group names.

**Checkpoint**: Sub-package skeleton exists; error hierarchy is stable; docs list the new extension surface. No Protocols defined yet.

---

## Phase 2: Foundational (Blocking Prerequisites)

**Purpose**: The Protocol definitions, the `$VAR` helper extraction, and the config-schema addition every user story depends on. Nothing US1-through-US4 can be implemented until these land.

**CRITICAL**: No user story work begins until this phase completes.

- [ ] T004 Create `packages/darnit/src/darnit/core/env_subst.py` implementing `substitute_dollar_vars(template: str, env: Mapping[str, str] | None = None, *, missing_ok: bool = True) -> str` per research R-004. Behavior: `env` defaults to `os.environ`; `$VAR` occurrences substitute in string; `$$` is a literal `$`; non-alphanumeric-underscore chars after `$` terminate the variable name; when `missing_ok=True` (default), unset variables substitute as empty string; when `missing_ok=False`, raise `KeyError(<varname>)`. Public API, exported from `darnit.core.env_subst`.

- [ ] T005 [P] Migrate feature 025's `exec_handler` `$VAR` substitution call site in `packages/darnit/src/darnit/sieve/builtin_handlers.py` to consume `darnit.core.env_subst.substitute_dollar_vars`. Verify no behavior change (existing exec-handler tests must pass unchanged). Remove the old inline substitution routine.

- [ ] T006 [P] Migrate feature 031's mcp-pool `_substitute_env` call site in `packages/darnit/src/darnit/sieve/mcp_pool.py` to consume `darnit.core.env_subst.substitute_dollar_vars`. Same rules as T005; no behavior change; remove the old routine.

- [ ] T007 [P] Create `tests/darnit/stores/test_env_subst.py`. Unit tests: happy path (single var, multiple vars, mixed with literal text); `$$` escape; unset var with `missing_ok=True` -> empty string; unset var with `missing_ok=False` -> `KeyError(<varname>)`; regex-terminator behavior (`$FOO/bar` -> value(FOO) + "/bar"); explicit `env` arg overrides `os.environ`. Regression tests: reproduce the previous inputs to feature 025's exec handler (a control that uses `$OWNER` / `$REPO` / `$BRANCH`) and feature 031's mcp env block (`$GH_TOKEN` etc.) and assert identical output after the migration in T005/T006.

- [ ] T008 Create `packages/darnit/src/darnit/stores/protocols.py` implementing the five Protocol classes per data-model.md: `Store` (base with `close()`), `ProjectStateStore`, `AttestationStore`, `ReportStore`, `AuditCacheStore`. All decorated with `@runtime_checkable`. Every method has a docstring pointing at the corresponding FR (FR-011 failure semantics, FR-019 close-idempotence). No runtime imports of any implementation package.

- [ ] T009 [P] Create `tests/darnit/stores/test_protocols.py`. Unit tests: `runtime_checkable` verification (four Protocols each accept a minimal duck-typed class); `close()` inheritance (each subclass Protocol requires `close()` via the `Store` base); Protocol MISS cases (a class missing a method fails `isinstance` check); Protocol methods are declared with the expected signatures (introspection-level check).

- [ ] T010 Add `StoreBlock` and `StoresConfig` Pydantic models to `packages/darnit/src/darnit/config/framework_schema.py` per data-model.md. `StoreBlock.backend: str` required. `StoreBlock.model_config = ConfigDict(extra="allow")` so backend-specific keys pass through. `StoresConfig` has four optional `StoreBlock` fields (`project`, `attestation`, `report`, `cache`) plus `model_config = ConfigDict(extra="forbid")` to catch typos like `[stores.audit_log]`. Add `stores: StoresConfig = Field(default_factory=StoresConfig)` to `FrameworkConfig` alongside `plugins` and `mcp_servers`.

- [ ] T011 Add `stores: StoresConfig = Field(default_factory=StoresConfig)` to `UserConfig` in `packages/darnit/src/darnit/config/user_schema.py`. Import `StoresConfig` from `framework_schema.py`. Placement alongside the `mcp_servers` field.

- [ ] T012 Update `merge_configs()` in `packages/darnit/src/darnit/config/merger.py` to merge `stores` blocks with per-kind replacement (per FR-006's precedence rule; mirrors the `mcp_servers` merger). One block per `for kind in ("project", "attestation", "report", "cache"):` loop that copies `user.stores.<kind>` over `framework.stores.<kind>` when the user block is not None.

- [ ] T013 [P] Write `tests/darnit/config/test_stores_config.py` covering (a) `StoresConfig` extra-forbid rejects unknown store kinds, (b) `StoreBlock` extra-allow accepts backend-specific keys, (c) `$VAR` substitution runs on `StoreBlock` string values at load time, (d) merger per-kind replacement (framework has `[stores.project]`, user has `[stores.attestation]` -> both survive in the merged effective config; user has `[stores.project]` -> replaces framework's).

- [ ] T014 Create `packages/darnit/src/darnit/stores/discovery.py` implementing `discover_stores(group: str) -> dict[str, type[Store]]` per research R-003. Runs `importlib.metadata.entry_points(group=group)`; loads each entry-point class; catches per-entry-point `Exception` -> logs debug + skips; detects duplicate names -> raises `StoreNameCollision(group, name, package_a, package_b)`. Also expose `STORE_ENTRY_POINT_GROUPS = ("darnit.stores.project", ...)` constant. Discovery result is per-process-cached in a module-level dict; `discover_stores` is called once per group per process at framework-load time.

- [ ] T015 [P] Create `packages/darnit/src/darnit/stores/selection.py` implementing `_StoreBundle` dataclass and `resolve_stores(stores_config: StoresConfig) -> _StoreBundle` function. Steps: (a) call `discover_stores` for each of the four groups (populates the discovery cache); (b) for each kind, if `stores_config.<kind>` is None, instantiate the filesystem default with framework-supplied defaults; (c) if it is set, look up the backend name in the discovery map; raise `StoreNotInstalled` on miss; instantiate with the backend-specific kwargs from `model_extra`; verify the instance satisfies the Protocol via `isinstance(instance, ProtocolClass)`; raise `StoreProtocolMismatch` on failure. `_StoreBundle.close_all()` calls `close()` on every field; per-store exceptions are logged and swallowed so a failure in one does not prevent the others from being closed.

- [ ] T016 [P] Create the four filesystem default implementations under `packages/darnit/src/darnit/stores/defaults/`:
  - `project.py::FilesystemProjectStateStore(repo_path: Path)` -- reads/writes `<repo_path>/.project/{project.yaml,maintainers.yaml}`; `close()` no-op.
  - `attestation.py::FilesystemAttestationStore(root: Path)` -- `write(bundle_id, bytes, content_type)` writes to `<root>/<bundle_id>.<ext>` where ext derives from content_type mapping; `close()` no-op.
  - `report.py::FilesystemReportStore(root: Path)` -- three write methods to `<root>/<report_id>.{md,json,sarif}`; `close()` no-op.
  - `cache.py::FilesystemAuditCacheStore(root: Path)` -- read/write with tempfile-then-rename atomicity (existing behavior at `core/audit_cache.py:130-150` moves here); `close()` no-op.
  Each also declares a filesystem-safe filename sanitizer for `bundle_id`/`report_id`/`cache_key` (replace path separators, etc.). Also add an `__init__.py` re-exporting the four classes.

- [X] T017 [P] Write `tests/darnit/stores/test_filesystem_defaults.py` covering round-trip read/write for each of the four defaults, including edge cases: (a) writing to a non-existent directory creates it; (b) filename sanitization on characters like `/` in `bundle_id`; (c) atomic-rename semantics for `FilesystemAuditCacheStore` (write to tempfile then rename); (d) `close()` is idempotent (call twice, no error).

- [X] T018 [P] Write `tests/darnit/stores/test_discovery.py` covering (a) empty discovery result when no plugins installed; (b) one-entry-point discovery via a fake `importlib.metadata.entry_points` monkeypatch; (c) name collision raises `StoreNameCollision`; (d) broken entry-point load logs and skips (does not blank the result).

- [X] T019 [P] Write `tests/darnit/stores/test_selection.py` covering the resolve_stores logic: (a) all-None config -> all four filesystem defaults instantiated; (b) `stores_config.project` set to a valid registered backend -> plugin instance instantiated; (c) selection names uninstalled backend -> `StoreNotInstalled` with backend name, group name, and available alternatives in the message; (d) plugin instance fails Protocol check -> `StoreProtocolMismatch` naming the missing method; (e) `_StoreBundle.close_all()` calls close() on every instantiated store exactly once; (f) `_StoreBundle.close_all()` swallows per-store exceptions and still closes the others.

**Checkpoint**: Protocol machinery and config-schema plumbing all land. Filesystem defaults exist and pass unit tests. No call sites have been rewritten yet; darnit still runs exactly as pre-feature.

---

## Phase 3: User Story 1 - Operator chooses a non-filesystem backend for one artifact class (Priority: P1) MVP

**Goal**: A `.baseline.toml` block selecting a non-filesystem `ProjectStateStore` causes the framework to read from and write to that backend for project state, while other artifacts stay on the filesystem default. Fixture-driven equivalence test (SC-002) proves the audit produces identical control verdicts.

**Independent Test**: With `[stores.project] backend = "in-memory"` in `.baseline.toml`, pre-seed an `InMemoryProjectStateStore` with the same content that would live at `.project/project.yaml`. Run the audit. Assert identical control verdicts to a run against the equivalent on-disk `.project/`. Assert the local filesystem's `.project/` was NOT read (spy on `open`).

### Implementation for US1

- [X] T020 [US1] Create in-memory reference backends under `packages/darnit-testchecks/src/darnit_testchecks/stores/`: `in_memory_project.py::InMemoryProjectStateStore`, `in_memory_attestation.py::InMemoryAttestationStore`, `in_memory_report.py::InMemoryReportStore`, `in_memory_cache.py::InMemoryAuditCacheStore`. Each is dict-backed; each exposes a `_state` attribute tests can inspect; `close()` is a no-op. Register each under the corresponding `darnit.stores.<kind>` entry-point group in `packages/darnit-testchecks/pyproject.toml` so the discovery machinery finds them at test-run time. Add an `__init__.py` re-exporting the four classes.

- [X] T021 [US1] Rewrite `packages/darnit/src/darnit/context/dot_project.py` `DotProjectReader.__init__` to accept an optional `ProjectStateStore | None` parameter; when None, fall back to `FilesystemProjectStateStore(repo_path)`. The reader's public method names stay the same but their bodies now call `self._store.read_project()` / `self._store.read_maintainers()` instead of doing direct file I/O. Existing callers that pass a `repo_path` continue to work (backward-compat -- FilesystemProjectStateStore materializes lazily).

- [ ] T022 [DEFERRED to Phase 4] Same shape for `DotProjectWriter`. Not needed for US1 MVP: the audit-time seam is read-side (`DotProjectMapper` -> `DotProjectReader`), which now accepts a `ProjectStateStore`. The Writer refactor is required only when a control's remediation actually writes back through the store; those call sites land in Phase 4 (T026-T029) alongside the attestation-generator migration.: accept optional `ProjectStateStore`, call `write_project` / `write_maintainers` on it. Update `packages/darnit/src/darnit/context/dot_project_org.py`'s org-fetch code path (lines ~168 and ~182) to consume a `ProjectStateStore` for the write side.

- [X] T023 [US1] Update `packages/darnit/src/darnit/tools/audit.py` `_run_audit` (or whichever function is the audit entry point) to (a) call `resolve_stores(effective_config.stores)` to produce a `_StoreBundle`, (b) pass the bundle's `.project` store to the ExecutionContext construction / DotProjectReader initialization, (c) wrap the audit-scoped block in a `try/finally` that calls `bundle.close_all()` on every exit path. Same idea for the four artifact classes wired into the ExecutionContext.

- [X] T024 [P] [US1] Write `tests/darnit/stores/test_us1_equivalence.py` covering SC-002: two audits against the same fixture repo, one with `[stores.project] backend = "in-memory-test"` seeded with the fixture's `.project/project.yaml` contents, one against the on-disk `.project/`. Assert control-verdict list identical; assert on-disk `.project/` was not opened when the in-memory backend was selected (monkeypatch `open` in the reader module and assert zero calls).

- [X] T025 [P] [US1] Write `tests/darnit/stores/test_us1_isolation.py`: with only `[stores.project]` set to a non-filesystem backend and `[stores.attestation]` / `[stores.report]` / `[stores.cache]` unset, run an audit that produces an attestation and reads from the audit cache. Assert (a) project state used the plugin backend, (b) attestation write went to the filesystem default at `.darnit/attestations/`, (c) audit-cache read/write hit `.darnit/audit-cache/`. Verifies FR-010 (only the selected backend is consulted; other kinds stay on filesystem).

- [X] T025a [P] [US1] Write `tests/darnit/stores/test_us1_lazy_instantiation.py` covering SC-004 literally. Run a minimal audit that produces NO attestations (e.g., a level-1 controls-only run whose control set excludes any attestation-emitting control, OR a run with `emit_attestation=False`). Spy on `FilesystemAttestationStore.__init__` (via monkeypatch) AND on the `InMemoryAttestationStore.__init__` in `darnit-testchecks` (with the in-memory backend selected via `[stores.attestation]`). Assert BOTH spies have zero calls after the audit completes -- proving the framework skips constructor invocation for a store whose artifact class the current run never uses. Also assert the corresponding entry in `_StoreBundle` is `None` or lazily-uninstantiated at audit-end.

**Checkpoint**: A control author can now select a non-filesystem backend for project state via TOML. US1's Independent Test passes.

---

## Phase 4: User Story 2 - Framework runs unchanged when no backend is selected (Priority: P1)

**Goal**: A `.baseline.toml` with no `[stores.*]` section produces identical on-disk behavior to pre-feature. SC-001 (zero regression) and SC-003 (zero-config filesystem invariance) are the mechanical proofs.

**Independent Test**: Run the entire existing test suite on the feature branch; assert zero regressions. Add a specific SC-003 test that spies on the four filesystem defaults' constructors + methods; run an audit with no `[stores.*]` set; assert the spies fire on all four defaults and no plugin backend is instantiated.

### Implementation for US2

- [ ] T026 [DEFERRED - follow-up] Complete the migration of the audit-cache module. Rewrite `packages/darnit/src/darnit/core/audit_cache.py` `read_audit_cache` / `write_audit_cache` as thin wrappers over `AuditCacheStore.read` / `.write`. The tempfile-then-rename logic moves into `FilesystemAuditCacheStore` (already staged in T016). TTL comparison stays in the wrapper. Public API of `read_audit_cache` / `write_audit_cache` MUST be preserved (existing callers unchanged).

- [X] T027 [P] [US2] Migrate `packages/darnit-baseline/src/darnit_baseline/attestation/generator.py::generate_attestation_from_results`. The hard-coded `open(output_path, 'w', encoding="utf-8")` at line 138 becomes `attestation_store.write(bundle_id, bundle_bytes, content_type)`. The `output_path` argument is replaced by an `attestation_store: AttestationStore` argument. Compute `bundle_id` from the audit run (owner/repo/framework/timestamp shape). Existing callers that pass an `output_path` need a shim: `if output_path is not None: attestation_store = FilesystemAttestationStore(Path(output_path).parent); bundle_id = Path(output_path).stem`. Note the transitional dual-argument surface in a comment; the shim goes away in a follow-up cleanup.

- [ ] T028 [DEFERRED - not required for MVP] Update existing tests that construct `DotProjectReader` / `DotProjectWriter` in `tests/darnit/context/` to pass the in-memory store where the on-disk test setup is intentional. This is the biggest test-side change footprint per plan estimate (~50 test updates). Strategy: for each test file, add a shared fixture that constructs `InMemoryProjectStateStore` seeded from the test's YAML string; pass the store to the reader/writer under test. Existing "read from disk" tests keep constructing `DotProjectReader(repo_path)` (backward-compat path via T021's None-default arg).

- [X] T029 [US2] Update existing attestation-generator tests in `tests/darnit_baseline/attestation/` to inject `InMemoryAttestationStore`. Assert on `store._state` for what was written; existing "check the file on disk" assertions migrate to "check the store's state dict."

- [X] T030 [P] [US2] Write `tests/darnit/stores/test_us2_zero_config.py` covering SC-003: with no `[stores.*]` section in TOML, run a small audit; spy on `FilesystemProjectStateStore.__init__`, `FilesystemAttestationStore.__init__`, `FilesystemReportStore.__init__`, `FilesystemAuditCacheStore.__init__`; assert each is called at most once; assert no plugin backend is instantiated (monkey the `discover_stores` cache to include a fake plugin and assert its constructor was NOT called). Also assert on-disk paths touched match the pre-feature paths exactly.

- [X] T031 [P] [US2] Add a regression-gate test `tests/darnit/stores/test_backward_compat.py` that asserts `DotProjectReader(repo_path)` (the pre-feature call shape without a store argument) continues to work and produces the same result as the pre-feature version. This is the backward-compat lock for the zero-config upgrade path.

**Checkpoint**: Existing behavior fully preserved. The full existing test suite passes without regression.

---

## Phase 5: User Story 3 - Plugin author distributes a new backend (Priority: P2)

**Goal**: A third-party plugin package can register a backend and be selected via TOML without patching darnit-core.

**Independent Test**: The fixture plugin package at `tests/darnit/stores/fixtures/example_store_plugin_pkg/` `pip install -e`s cleanly; its entry point is discovered by `discover_stores("darnit.stores.attestation")`; selecting it in `.baseline.toml` causes darnit to instantiate and consume it.

### Implementation for US3

- [X] T032 [US3] Create the fixture plugin package `tests/darnit/stores/fixtures/example_store_plugin_pkg/` per research R-007. Structure: `pyproject.toml` declaring `[project.entry-points."darnit.stores.attestation"] example = "example_store_plugin.backend:ExampleAttestationStore"`, plus `src/example_store_plugin/backend.py` implementing a no-op `AttestationStore` that records writes into a class-level list (test-inspectable), plus `__init__.py` and a minimal `README.md` explaining that this exists solely for discovery-mechanism testing.

- [X] T033 [US3] Add a session-scoped pytest fixture in `tests/darnit/stores/conftest.py` that `pip install -e tests/darnit/stores/fixtures/example_store_plugin_pkg/` at session start via `subprocess.run` and `pip uninstall -y example-store-plugin` at session end. Yields nothing; the presence of the plugin in the environment is the side effect. Every US3 test depends on this fixture (autouse=False, opt-in).

- [X] T034 [US3] Write `tests/darnit/stores/test_us3_plugin_discovery.py`: import the fixture, call `discover_stores("darnit.stores.attestation")`, assert `"example" in result` and `result["example"]` is `ExampleAttestationStore`. Verifies FR-005 discovery mechanism via a real entry point (not a monkeypatched one).

- [X] T035 [P] [US3] Write `tests/darnit/stores/test_us3_plugin_selection.py`: with the fixture installed AND `[stores.attestation] backend = "example"` in the TOML, run an audit that produces an attestation. Assert `ExampleAttestationStore._writes` list contains the write. Verifies the full US3 end-to-end story.

- [X] T036 [P] [US3] Write `tests/darnit/stores/test_us3_missing_plugin.py`: with `[stores.attestation] backend = "does-not-exist"` in the TOML, attempt to run an audit. Assert (a) `StoreNotInstalled` raised BEFORE any control ran (SC-007), (b) the error message names the backend, the group, and the list of installed alternatives.

- [X] T037 [P] [US3] Write `tests/darnit/stores/test_us3_protocol_mismatch.py`: monkey-register a class that lacks `close()` under `darnit.stores.report`, select it via TOML, attempt to run an audit. Assert `StoreProtocolMismatch` raised at selection time with a message naming the missing method (`close`).

- [X] T038 [P] [US3] Write `tests/darnit/stores/test_us3_name_collision.py`: monkey-register TWO entry points under `darnit.stores.attestation` with the same name (`s3`) but from different fake packages. Call `discover_stores` and assert `StoreNameCollision` raised with both package names + the shared key.

- [X] T039 [US3] Add plugin-author documentation section under `docs/plugin-authoring/stores.md` (create the file if it does not exist). Include: how to declare the entry point in `pyproject.toml`, the four groups + which Protocol each maps to, a full worked `AttestationStore` example (mirrors quickstart.md Example 2). SC-005 target: an operator following this doc can produce a working backend in under 30 minutes.

**Checkpoint**: A third-party plugin author can distribute a backend without touching darnit. US3's Independent Test passes.

---

## Phase 6: User Story 4 - Failure semantics are explicit per Protocol (Priority: P2)

**Goal**: Store failures produce distinguishable, actionable errors; failure semantics match the per-Protocol table in FR-011.

**Independent Test**: Fault-injection tests, one per Protocol, prove the WARN/ERROR/best-effort mapping.

### Implementation for US4

- [ ] T040 [DEFERRED - needs control-side integration] [US4] Write `tests/darnit/stores/test_us4_project_read_warn.py`: use a fault-injecting `ProjectStateStore` whose `read_project()` raises `StoreOperationError`. Run an audit that would use project context. Assert affected controls resolve WARN (not FAIL, not silent PASS). Assert the WARN evidence names the store backend and the failure reason.

- [ ] T041 [DEFERRED - blocked on T022 Writer refactor] [US4] Write `tests/darnit/stores/test_us4_project_write_error.py`: use a fault-injecting `ProjectStateStore` whose `write_project()` raises. Run a code path that writes (org-fetch or on-pass project update). Assert the audit run surfaces the error clearly. Assert the framework did NOT silently fall through to the filesystem (spy on `FilesystemProjectStateStore.write_project`).

- [X] T042 [P] [US4] Write `tests/darnit/stores/test_us4_attestation_write_error.py`: use a fault-injecting `AttestationStore` whose `write()` raises. Run an audit that produces an attestation. Assert the error is surfaced to the operator with the backend name, the artifact class, and the `bundle_id`. Assert nothing writes to `.darnit/attestations/` on the filesystem.

- [X] T043 [P] [US4] Write `tests/darnit/stores/test_us4_cache_best_effort.py`: use a fault-injecting `AuditCacheStore` whose `write()` raises. Run an audit. Assert the audit completes successfully and control verdicts are unaffected. Assert a warning is logged naming the cache backend. Then use a fault-injecting store whose `read()` raises: run an audit; assert the read returns cache-miss semantics and the audit re-runs; assert no exception is raised to the caller.

- [ ] T044 [DEFERRED - stub only; no v0 consumer] [US4] Write `tests/darnit/stores/test_us4_report_write_error.py` (guarded by a `pytest.mark.skip` with reason "no v0 consumer; unskip when #341 lands"): shell of the failure path so a future feature knows the assertion shape. Left as a TODO stub.

- [X] T045 [P] [US4] Write `tests/darnit/stores/test_us4_no_silent_fallback.py`: with `[stores.project] backend = "in-memory-broken"` selected (a fault-injecting registered plugin), run an audit. Monkey-spy on `FilesystemProjectStateStore.__init__` and assert it was NOT called. Verifies FR-012 (no silent fallback to filesystem when a selected backend fails).

**Checkpoint**: All four US4 failure paths pass. FR-011 and FR-012 are locked by mechanical tests.

---

## Phase 7: Polish & Cross-Cutting Concerns

**Purpose**: Full workspace verification, structure decision guard, static-import invariant, lint clean, spec-sync validation, product-scope invariant.

- [X] T046 Run the full workspace test sweep from repo root: `uv run pytest tests/ -q --deselect tests/darnit/context/test_dot_project_upstream.py::TestUpstreamSpecSync::test_upstream_spec_unchanged`. Confirm exit code 0 (SC-001).

- [X] T047 [P] Two sub-steps, both MUST pass. **(a) Structure Decision**: verify no file outside `packages/darnit/`, `packages/darnit-baseline/`, and `packages/darnit-testchecks/` under `packages/*/src/` was modified: `git diff --name-only main..HEAD | grep -E 'packages/(darnit-gittuf|darnit-reproducibility|darnit-hello)/src/'` MUST produce zero lines. **(b) FR-014 no-new-runtime-dep guard**: `git diff main..HEAD -- pyproject.toml packages/*/pyproject.toml` MUST NOT add any entry to `[project.dependencies]` for a published product package (except the `darnit-testchecks` update to add the fixture plugin's entry-point registration for the in-memory backends, which lives under its own `[project.entry-points.*]` table and NOT under dependencies).

- [X] T048 [P] Run `uv run ruff check .` on repo root; MUST exit 0. Fix any lint issues in the files this feature touched; do NOT auto-format unrelated files.

- [X] T049 [P] Run `uv run python scripts/validate_sync.py --verbose`; MUST exit 0. Feature introduces no new handlers, so the sync check is untouched. The one-line addition to `framework-design.md` Section 12 (from T003) does not affect the handler-name registry.

- [X] T050 [P] Add the static-import guard test `tests/darnit/stores/test_import_isolation.py` covering SC-008 AND FR-017 via two AST-walking assertions in the same test file.

  **(a) Cross-package guard (SC-008)**: walk `packages/darnit/src/darnit/`, parse each `.py` file's imports via `ast`, assert no import references any `darnit_baseline`, `darnit_gittuf`, `darnit_hello`, `darnit_reproducibility`, or `darnit_testchecks` package. Catches accidental cross-package imports.

  **(b) Intra-package handler-layer guard (FR-017)**: walk `packages/darnit/src/darnit/sieve/` AND `packages/darnit-baseline/src/darnit_baseline/tools.py` (plus any sibling modules that register MCP handlers per baseline's `register_handlers()`). Assert no import references `darnit.stores` or any submodule thereof. FR-017's constraint is negative -- handlers MUST NOT consume the store abstraction directly. Catches the class of well-intentioned refactor that adds `from darnit.stores import AttestationStore` to a sieve handler for symmetry with the audit driver.

  Maintain an explicit audit-boundary-consumer allowlist in the test as a set of module paths that ARE permitted to import `darnit.stores` (initially: `darnit.tools.audit`, `darnit.context.dot_project`, `darnit.context.dot_project_org`, `darnit.core.audit_cache`, `darnit_baseline.attestation.generator`). The allowlist is the reader-facing contract: adding a new consumer requires adding a line here, which shows up in code review.

- [X] T051 Confirm the module docstrings on `packages/darnit/src/darnit/stores/protocols.py`, `discovery.py`, `selection.py`, and each `defaults/*.py` accurately describe the final implementation (Protocol shapes, failure semantics, close-idempotence). Fix any drift. Also confirm the four `contracts/*.md` files' failure-mode tables match every exception the corresponding module raises (cross-read against T015's exception-to-consumer mapping).

- [X] T052 Add a lightweight benchmark note in the plugin-author docs (from T039): entry-point discovery pays a one-time cost at framework-load (measured in single-digit milliseconds via a small `importlib.metadata` scan on a fresh venv); lazy instantiation adds one dict lookup per audit-run per artifact class. This is not a benchmark test task; it is a documentation note that operators expect the numbers, so they can calibrate their fleet's per-audit budget.

---

## Dependencies

```
Phase 1 (T001..T003) ──> Phase 2 (T004..T019) ──> Phase 3 (US1: T020..T025a)
                                                        │
                                                        ├──> Phase 4 (US2: T026..T031) [big test-migration footprint]
                                                        │
                                                        ├──> Phase 5 (US3: T032..T039) [depends on fixture plugin package + install fixture]
                                                        │
                                                        ├──> Phase 6 (US4: T040..T045) [pure-Python fault injection; low-serialization]
                                                        │
                                                        └──> Phase 7 (Polish: T046..T052)
```

Within Phase 2: T004 (env_subst helper) must land before T005 and T006 (helper migrations). T007 (env_subst tests including US1 regression) depends on T004-T006. T008 (Protocol definitions) is independent of T004-T007 and can land in parallel; T009 (Protocol tests) depends on T008. T010 (framework_schema stores) and T011 (user_schema stores) are file-disjoint but T011 imports from T010's `StoresConfig` -- do T010 first. T012 (merger) depends on T010-T011. T013 (config tests) depends on T010-T012. T014 (discovery) depends on T008 (needs Protocol types). T015 (selection) depends on T008 + T014 + T016 (needs discovery + filesystem defaults). T016 (filesystem defaults) depends on T008 (needs Protocol interfaces).

Within Phase 3 (US1): T020 (in-memory backends) depends on T008. T021-T023 (call-site rewrites in dot_project.py, dot_project_org.py, audit.py) touch different files but rely on the T015 `_StoreBundle` and T020 in-memory backends being present. T024-T025 (US1 tests) can run in parallel once implementation lands.

Within Phase 4 (US2): T026-T028 are file-disjoint per-artifact rewrites and can be authored in parallel; T028 is the largest by test-update count. T030-T031 (US2 tests) depend on T026-T028.

Within Phase 5 (US3): T032 (fixture plugin package) is independent; T033 (install fixture) depends on T032; T034-T038 (discovery + selection + failure tests) depend on T033 for the plugin-installed state. T039 (docs) can be authored in parallel with anything.

Within Phase 6 (US4): All five tests are file-disjoint; can run parallel after Phase 2 lands (they don't strictly require Phase 3 code paths to be rewritten first because they fault-inject at the store boundary).

Within Phase 7: T046 (test sweep) is long-running; start first. T047-T050 are fast + parallel. T051-T052 are docs finalization; last.

## Parallel execution examples

After Phase 3 (US1) MVP lands, the four subsequent phases have low inter-phase serialization. A three-stream workflow:

```sh
# Stream 1: US2 test-migration footprint (biggest single work item)
# Complete T026-T028 sequentially (they touch different files but need coordinated review).
# Then run T030-T031 in parallel.

# Stream 2: US3 plugin discovery
# T032 -> T033 -> T034-T038 in parallel.
# T039 (docs) can be done anytime after T032.

# Stream 3: US4 failure semantics
# T040-T045 all [P]; author in parallel; T044 stays skipped until #341.
```

Within Phase 7:

```sh
uv run pytest tests/ -q --deselect ...            # T046 (long-running; start first)
git diff --name-only main..HEAD | grep -E ...     # T047 (fast, [P])
uv run ruff check .                               # T048 (fast, [P])
uv run python scripts/validate_sync.py --verbose  # T049 (fast, [P])
uv run pytest tests/darnit/stores/test_import_isolation.py  # T050 (fast, [P])
# T051-T052 run last, require final state.
```

## Implementation strategy

MVP scope = Phase 1 + Phase 2 + Phase 3 (User Story 1 alone). Landing US1 gets the machinery working end-to-end: a control author selects a non-filesystem backend for one artifact class, the framework respects that selection, control verdicts are equivalent. Everything after that layers safety-net regression coverage.

Incremental delivery order:

1. Land T001..T025 (Setup + Foundational + US1) as the MVP PR. At this point a `.baseline.toml` selection can route project state to a non-filesystem backend and the fixture-driven equivalence test proves the framework respects it.
2. Land T026..T031 (US2 rewrites + backward-compat tests) as a follow-up commit or same PR. Locks the zero-regression invariant. This is the biggest test-migration commit and worth splitting for review.
3. Land T032..T039 (US3 plugin discovery + docs) as a follow-up commit. Proves the ecosystem story via a real installable package.
4. Land T040..T045 (US4 failure-mode tests) as a follow-up commit. Locks FR-011 per Protocol.
5. Land T046..T052 (Polish) as the last commit or squash into the MVP.

All commits belong to the same PR against `main` unless the review size demands a split. If piecewise review is preferred, reviewer order is (foundational + US1 code, US2 rewrites, US3 ecosystem, US4 failure paths, polish) so each commit's contract-level effect is legible independently.
