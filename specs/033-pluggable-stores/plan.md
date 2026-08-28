# Implementation Plan: Pluggable storage backends via per-artifact Protocols

**Branch**: `033-pluggable-stores` | **Date**: 2026-08-25 | **Spec**: [spec.md](./spec.md)

**Input**: Feature specification from `specs/033-pluggable-stores/spec.md` (with 3 clarifications recorded 2026-08-25: `close()` teardown method required on every Protocol, `$VAR` substitution for secrets in `[stores.*]` blocks, entry-point discovery at framework-load time).

## Summary

Introduce a `darnit.stores` sub-package under `packages/darnit/` that defines four `typing.Protocol`s (`ProjectStateStore`, `AttestationStore`, `ReportStore`, `AuditCacheStore`), each with an explicit `close()` teardown method (FR-019). Ship a filesystem-backed default implementation for each Protocol that reproduces the pre-feature on-disk layout exactly (SC-003, User Story 2). Add `[stores.<kind>]` blocks to `FrameworkConfig` and `UserConfig` for backend selection (FR-006), with `$VAR` substitution for backend-specific string values reusing the pattern from features 025 (`exec` handler) and 031 (mcp `env` block). Discover third-party backend implementations exactly once per process at framework-load time via `importlib.metadata` entry points under `darnit.stores.project` / `.attestation` / `.report` / `.cache` (FR-005), matching feature 027's `QuestionResolver` discovery pattern. Rewrite the ~10 hard-coded filesystem call sites (attestation generator, report formatters, audit-cache reader/writer, `.project/` reader/writer) to consume the Protocol; store operations happen at audit-boundary composition, keeping the sieve pipeline's PASS/FAIL/WARN/ERROR contract intact (Constitution V, FR-017).

Zero new runtime dependencies (`importlib.metadata`, `typing.Protocol`, and `runtime_checkable` are all standard library). Zero product-source additions outside `packages/darnit/` and its tests. First non-filesystem backend (Postgres for `ProjectStateStore`) lands as follow-up #391 once this feature is on `main`.

## Technical Context

**Language/Version**: Python 3.11/3.12 (workspace targets - unchanged).

**Primary Dependencies**: `importlib.metadata` (standard library since Python 3.8, already used by feature 027 for `QuestionResolver` discovery); `typing.Protocol` + `@runtime_checkable` (standard library); Pydantic 2.x (already used for framework schema, adds the new `[stores.*]` block validation). No new pip dependencies.

**Storage**: Filesystem only in v0. Every default implementation shipped by this feature is filesystem-backed and reproduces the pre-feature on-disk layout exactly. Non-filesystem backends are third-party plugin packages; #391 tracks the first one.

**Testing**: pytest, extending existing test layers under `tests/darnit/stores/` (new directory) and touching `tests/darnit_baseline/` where the attestation-generator and report-formatter call sites move. Two categories of test-only fixtures ship with this feature: (a) an in-memory reference backend for each Protocol (under `packages/darnit-testchecks/src/darnit_testchecks/stores/`) that tests substitute for SC-002 equivalence tests; (b) a fixture plugin package (`tests/darnit/stores/fixtures/example_store_plugin_pkg/`) that lives outside the `darnit` namespace and proves at CI time that the entry-point discovery machinery works against a real installable Python package (SC-005, User Story 3).

**Target Platform**: Any platform Python 3.11+ runs on. No platform-specific code paths introduced.

**Project Type**: Library/framework internal change; scoped to `packages/darnit/` core plus its tests. No new packages, no plugin implementations built.

**Performance Goals**: Not a hot path. Store operations happen at audit-boundary composition (once per audit run per artifact class, at most). Filesystem-default I/O cost is unchanged from pre-feature (same files, same paths). Entry-point discovery cost pays once at process start (SC-004 measures this via a spy). Additional lazy-instantiation branch adds one dict lookup + optional `importlib.metadata` fetch per audit run per artifact class -- microseconds. The performance-sensitive property is negative: FR-014 requires zero new pip dependencies; SC-001 requires zero regression on the existing 2815-test workspace.

**Constraints**:
- Zero product-source additions outside `packages/darnit/` and its tests (FR-013).
- No new required arguments on any public callable that existing internal callers pass without modification (matches feature 030 / 032's discipline).
- Sync Protocols only in v0 (spec Assumptions -- async is an explicit non-goal).
- Every Protocol MUST expose `close()` (FR-019); framework MUST call it exactly once at audit-boundary tear-down.
- No silent fallback to the filesystem default when a selected backend fails (FR-012); fail-fast per FR-008.

**Scale/Scope**: One new sub-package (`darnit.stores`) with ~8 modules (Protocols, discovery, selection, four filesystem defaults, errors). Two new TOML schema fields on `FrameworkConfig` and `UserConfig`. ~10 rewritten call sites (attestation generator, three report formatters, audit-cache reader + writer, `.project/` reader + writer, `.project/` org-fetch writer). Two test-fixture packages. Estimated diff: ~1200 lines of production code, ~1500 lines of test code (Protocol conformance tests + call-site integration tests + fixture plugin package + in-memory backends).

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

The darnit constitution (5 core principles, plus architecture constraints and workflow rules) evaluated against this feature:

| Principle | Applies | Assessment |
|-----------|---------|------------|
| I. Plugin Separation | Yes | PASS. The `darnit.stores` sub-package and its filesystem defaults live in `packages/darnit/` core. Third-party backend implementations live in plugin packages, never imported by core. The entry-point discovery machinery imports plugin packages *only* via `importlib.metadata`, which lazily loads distributions at the point of selection; the discovery mechanism itself is import-cycle-free by construction. Explicit static-import guard (SC-008) proves darnit-core does not import any implementation package. |
| II. Conservative-by-Default | Yes | PASS. FR-011 spells out the WARN/ERROR/best-effort mapping per Protocol so a failing `ProjectStateStore` read resolves affected controls WARN (not silent PASS, not silent FAIL). FR-012 forbids silent fallback to the filesystem default when a selected backend fails; the operator's selection is honored to the point of failure. FR-008 requires fail-fast on unresolvable backend selection *before* any control runs, matching feature 019's "definitive verdicts always beat silent WARN" posture applied to the misconfiguration surface. |
| III. TOML-First Architecture | Yes | PASS. Backend selection is entirely a TOML surface (`[stores.<kind>] backend = "..."` under `.baseline.toml` or the framework TOML). Backend-specific config (dsn, region, etc.) is also TOML-native, with `$VAR` substitution for secrets that reuses features 025/031's existing pattern -- no new config mechanism plugin authors must learn. No Python-code escape hatch for backend selection is introduced. |
| IV. Never Guess User Values | Yes | PASS. This feature does not touch the auto-detect / user-judgment surface at all. Storage backend selection is a fleet-configuration choice, not a per-control judgment. `auto_detect` / `allow_sieve_hints` machinery is untouched. |
| V. Sieve Pipeline Integrity | Yes | PASS. FR-017 forbids modifying sieve handlers, remediation handlers, or MCP tools to consume the store abstraction directly. Store access happens exclusively at audit-boundary composition points (audit driver, remediation orchestrator, attestation generator, report formatters). The sieve orchestrator's PASS/FAIL/WARN/ERROR contract is unchanged; controls do not know stores exist. |

Architecture constraints (three-layer architecture, package structure): PASS. Layer 1 (Checking / sieve handlers) is untouched. Layer 2 (Remediation) receives a small tweak at the audit-driver-facing composition point (writes go through the store instead of a hard-coded path). Layer 3 (MCP Tools) is unchanged. The `darnit.stores` sub-package sits alongside `darnit.sieve` and `darnit.config` -- horizontal to the three layers, not a new layer.

Development workflow (lint, tests, spec sync, no-emoji rules): PASS. Standard workflow. The spec-sync check (`scripts/validate_sync.py`) validates handler names in code against `docs/architecture/framework-design.md`; this feature introduces no new handlers, so the sync check is untouched. One line will be added to Section 12 of `framework-design.md` naming the `darnit.stores` sub-package as a new extension surface, matching how features 027 and 031 documented their extension surfaces.

**Gate result: PASS. Proceed to Phase 0.**

## Project Structure

### Documentation (this feature)

```text
specs/033-pluggable-stores/
├── plan.md              # This file
├── research.md          # Phase 0 output - call-site inventory, discovery pattern reuse, close() ownership, $VAR helper reuse
├── data-model.md        # Phase 1 output - the four Protocols + config schema + selection contract
├── quickstart.md        # Phase 1 output - operator + plugin-author worked examples
├── contracts/
│   ├── project-state-store.md
│   ├── attestation-store.md
│   ├── report-store.md
│   └── audit-cache-store.md
├── checklists/
│   └── requirements.md  # From /speckit-specify (all 16 items pass)
└── tasks.md             # /speckit-tasks output (not created here)
```

### Source Code (repository root)

```text
packages/darnit/src/darnit/stores/
├── __init__.py
├── protocols.py         # NEW. The four typing.Protocol classes + Store base + close() surface.
├── discovery.py         # NEW. importlib.metadata entry-point discovery under `darnit.stores.<kind>`
│                        # groups. Runs once at framework-load; per-process cache.
├── selection.py         # NEW. Resolves `[stores.<kind>]` -> instantiated backend. Handles `$VAR`
│                        # substitution for backend-specific keys. Emits fail-fast errors per FR-008.
├── errors.py            # NEW. StoreError base + StoreNotInstalled, StoreProtocolMismatch,
│                        # StoreNameCollision, StoreOperationError.
├── defaults/            # NEW. Filesystem-backed default implementations.
│   ├── __init__.py
│   ├── project.py       # FilesystemProjectStateStore (reads/writes .project/)
│   ├── attestation.py   # FilesystemAttestationStore (writes .darnit/attestations/)
│   ├── report.py        # FilesystemReportStore (writes Markdown/JSON/SARIF to configured paths)
│   └── cache.py         # FilesystemAuditCacheStore (reads/writes .darnit/audit-cache/)
└── env_subst.py         # NEW. Shared $VAR substitution helper. Extracted from where feature 025's
                          # exec handler and feature 031's mcp env block currently duplicate it, so
                          # the same code runs in all three call sites (also fixes a latent bug where
                          # the two existing copies drifted apart on unset-var behavior; research R-004).

packages/darnit/src/darnit/config/
├── framework_schema.py  # UPDATE. Add StoresConfig + StoreBlock Pydantic models; add
│                        # `stores: StoresConfig` field to FrameworkConfig alongside plugins/mcp_servers.
└── user_schema.py       # UPDATE. Mirror the same `stores` field on UserConfig.

packages/darnit/src/darnit/config/merger.py
                          # UPDATE. Merge `stores` blocks with the same precedence rule other blocks
                          # use (.baseline.toml block for a given <kind> fully replaces the framework
                          # TOML block for that <kind>). One-line addition alongside the mcp_servers
                          # merger from feature 031.

packages/darnit/src/darnit/tools/audit.py
                          # UPDATE. At the ExecutionContext construction site (line ~425), pass the
                          # store bundle. Introduce `_stores_bundle_for_run` helper that resolves all
                          # four Protocols lazily. Wrap the per-audit-run loop in a try/finally that
                          # calls close() on every instantiated store, matching feature 031's mcp
                          # pool teardown pattern.

packages/darnit-baseline/src/darnit_baseline/attestation/generator.py
                          # UPDATE. Replace hard-coded `open(output_path, 'w')` call at line 138 with
                          # store.write(attestation_bundle). Existing output-path argument becomes an
                          # AttestationStore configured with that path.

packages/darnit-baseline/src/darnit_baseline/formatters/  (three formatters)
                          # UPDATE. Each formatter's file-write goes through ReportStore.write().

packages/darnit/src/darnit/core/audit_cache.py
                          # UPDATE. read_audit_cache / write_audit_cache become thin wrappers over
                          # AuditCacheStore.read / .write. Existing atomic-rename semantics move
                          # into the FilesystemAuditCacheStore default implementation.

packages/darnit/src/darnit/context/dot_project.py
                          # UPDATE. DotProjectReader / DotProjectWriter now consume a ProjectStateStore.
                          # The audit driver passes the store; existing .project/ path arguments become
                          # the FilesystemProjectStateStore's on-disk root.

packages/darnit-testchecks/src/darnit_testchecks/stores/
                          # NEW. In-memory reference implementations for each Protocol. Consumed by
                          # SC-002's fixture-equivalence tests. Not shipped as a runtime dependency
                          # of darnit-core; darnit-testchecks is dev-only.
├── __init__.py
├── in_memory_project.py
├── in_memory_attestation.py
├── in_memory_report.py
└── in_memory_cache.py

tests/darnit/stores/
├── test_protocols.py            # NEW. runtime_checkable + close() contract per Protocol.
├── test_discovery.py            # NEW. entry-point discovery: happy path, name collision (FR-009),
│                                # missing plugin (FR-008), Protocol mismatch (FR-002).
├── test_selection.py            # NEW. TOML -> store: $VAR substitution, backend-specific kwargs,
│                                # fail-fast on uninstalled / non-conformant / colliding backends.
├── test_env_subst.py            # NEW. $VAR helper unit tests, plus a regression test asserting
│                                # feature 025 (exec) and feature 031 (mcp) still produce identical
│                                # substitution behavior after the extraction.
├── test_filesystem_defaults.py  # NEW. Round-trip tests for each of the four filesystem defaults.
├── test_lazy_instantiation.py   # NEW. SC-004: an audit that produces no attestations does not
│                                # instantiate an AttestationStore.
├── test_audit_boundary_close.py # NEW. SC-006 + FR-019: close() called exactly once per instantiated
│                                # store, on every exit path (success, control failure, exception).
└── fixtures/
    └── example_store_plugin_pkg/  # NEW. A minimal installable Python package that registers a no-op
        │                          # backend under darnit.stores.attestation. Consumed by SC-005 /
        │                          # User Story 3 discovery-through-a-real-entry-point test.
        ├── pyproject.toml
        ├── README.md
        └── src/example_store_plugin/
            ├── __init__.py
            └── backend.py

tests/darnit_baseline/attestation/  (updates)
                          # Existing attestation-generator tests get one-line updates to inject the
                          # in-memory AttestationStore. No new tests unless a call-site regression
                          # surfaces.

tests/darnit_baseline/formatters/  (updates)
                          # Existing formatter tests get the same shape as above for ReportStore.

tests/darnit/core/test_audit_cache.py  (updates)
                          # Existing audit-cache tests get the in-memory backend swap.

tests/darnit/context/  (updates)
                          # Existing dot-project reader/writer tests get the in-memory backend swap.
                          # This is the biggest test-side change footprint; expected ~50 test updates
                          # across the .project/ suite.

docs/architecture/framework-design.md
                          # One-line addition to Section 12 naming `darnit.stores` as the persistence
                          # extension surface, alongside `darnit.frameworks` and
                          # `darnit.question_resolvers`.
```

**Structure Decision**: Introduce `darnit.stores` as a sibling sub-package under `packages/darnit/src/darnit/`, horizontal to `darnit.sieve` and `darnit.config`. The four Protocols live in a single module (`protocols.py`) because their contracts are read together and independently changed rarely; splitting per Protocol would fragment the reader contract. Filesystem defaults live under `darnit.stores.defaults` (not scattered across `attestation/`, `context/`, etc.) so a plugin author can find the entire reference implementation in one place. The `$VAR` substitution helper is extracted from where it's currently duplicated in features 025 and 031 into `darnit.stores.env_subst` (accepting the mild irony that a "stores" module owns a helper both handlers use; the alternative is a `darnit.core.env_subst` which is also fine -- research R-004 evaluates the placement). Test-only in-memory backends live in `darnit-testchecks` so they never appear in the runtime install; the fixture plugin package lives under `tests/` because it exists exclusively to prove discovery works and is not something an end user would install.

## Complexity Tracking

No constitution violations to justify. This section is intentionally short.

## Phase 0: Research

Research questions surfaced by Technical Context and the spec's Assumptions/Edge Cases:

1. **R-001: Enumerate the current hard-coded filesystem call sites per artifact class.** The plan's "Source Code" tree lists ~10 rewrites; that count is from a first read. Phase 0 grep-audit produces the authoritative list and its groupings so the tasks decomposition knows exactly what to touch. Decision: run the enumeration and record it in research.md as a table `{artifact-class, module:line, current-shape}`. Alternatives considered: defer to tasks phase (rejected -- the tasks phase needs the count locked to write per-call-site tasks).

2. **R-002: `close()` teardown ownership at the audit-boundary.** Every instantiated store must be closed exactly once on every exit path (success, control failure, exception). Feature 031's `SieveOrchestrator.verify_batch` uses a try/finally around the per-control loop for its MCP-pool teardown; the same pattern applies here, but at a slightly wider boundary because reports and attestations are written by post-loop composition, not by the sieve itself. Decision: introduce `_StoreBundle` in `darnit.stores.selection` that owns all instantiated stores for the run; `darnit.tools.audit._run_audit` wraps the whole audit-scoped block in a try/finally that calls `bundle.close_all()`. Alternatives considered: (a) per-Protocol context managers threaded through every consumer (rejected -- fragments teardown across N call sites); (b) `atexit` handlers on individual stores (rejected -- fires too late, misses the "close at audit boundary" contract).

3. **R-003: `importlib.metadata` entry-point discovery pattern (reuse from feature 027).** Feature 027's `resolver_discovery.py` uses `importlib.metadata.entry_points(group="darnit.question_resolvers")` and lazy-loads each entry point at discovery time, wrapping ImportError / other exceptions per entry point so a broken plugin does not blank the whole discovery result. Decision: copy that shape into `darnit.stores.discovery.discover_stores(group)`, adapt for the four groups, add name-collision detection (FR-009). Alternatives considered: (a) roll a fresh pattern (rejected -- codebase should have one entry-point discovery convention); (b) share a helper module between the two features (rejected for v0 -- factor after the third consumer, per YAGNI).

4. **R-004: `$VAR` substitution helper -- extract or duplicate.** Features 025 (`exec` handler) and 031 (mcp `env` block) each carry a `$VAR` substitution routine. Reading both: they differ subtly on the "unset variable" case (031 substitutes empty string; 025 substitutes empty string BUT logs a debug line; both use the same regex). Decision: extract to `darnit.stores.env_subst.substitute_dollar_vars(template, env, *, missing_ok=True)`. Both existing call sites migrate to it. Regression test asserts identical behavior on the previous inputs to both features. Alternatives considered: (a) leave the two copies alone and add a third for stores (rejected -- three copies is worse than two); (b) move to a `darnit.core` module (considered -- `darnit.stores` slightly awkward, `darnit.core.env_subst` would be more natural; deferred to tasks phase, low-stakes).

5. **R-005: Config schema addition (StoresConfig / StoreBlock).** Feature 031 added `mcp_servers: dict[str, McpServerConfig]` on `FrameworkConfig` with `extra="forbid"` on the block model (its own T005 lesson). Decision: mirror exactly. `StoreBlock(BaseModel)` with `backend: str` required and `extra="allow"` so backend-specific keys pass through to the backend's `__init__`. `StoresConfig` groups the four artifact-class-keyed blocks (`project`, `attestation`, `report`, `cache`). Merger adds one line alongside the `mcp_servers` merger (T007 of feature 031). Alternatives considered: (a) one flat `stores: dict[str, StoreBlock]` at the top level (rejected -- the fixed set of four artifact classes is a schema invariant, not a runtime one); (b) require an explicit `backend = "filesystem"` in every default TOML (rejected -- undermines User Story 2 zero-config path).

6. **R-006: In-memory reference backend placement.** Test-only backends could live under `tests/` or under `packages/darnit-testchecks/`. Decision: place under `darnit-testchecks` because that package's charter (matches the sieve's `testchecks` implementation) is exactly "reference implementations useful for testing." They are importable from any test suite; they are not shipped in the runtime install of darnit-core. Alternatives considered: (a) place under `tests/darnit/stores/fixtures/` (rejected -- makes cross-test reuse awkward, requires PYTHONPATH manipulation); (b) place under a fresh `darnit-testkit` package (rejected -- new package cost for what fits in existing `darnit-testchecks`).

7. **R-007: Fixture plugin package registration.** The example plugin package under `tests/darnit/stores/fixtures/example_store_plugin_pkg/` must be `pip install`-able so its entry point actually registers. The CI job that runs the discovery tests must `pip install -e tests/darnit/stores/fixtures/example_store_plugin_pkg/` before running. Decision: add a session-scoped pytest fixture that installs it (using `subprocess` + `pip install -e`) at the start of the discovery test session, and uninstalls at the end. Alternatives considered: (a) statically add the fixture package to the workspace `pyproject.toml` (rejected -- pollutes the runtime environment for every test, not just discovery tests); (b) use `sys.path` gymnastics to fake an entry point (rejected -- feature 027 rejected this same shortcut for the same reason: the whole point is proving discovery works against a REAL entry point).

**Output**: `research.md` with each decision + rationale + rejected alternatives per the template.

## Phase 1: Design & Contracts

**Prerequisites**: `research.md` complete.

### Data Model (`data-model.md`)

New schema types:

- **`Store` (Protocol base, `runtime_checkable`)** in `darnit.stores.protocols`. Defines the `close(self) -> None` method every subclass Protocol inherits. Not intended to be used as a standalone Protocol -- it exists to consolidate the FR-019 `close()` contract in one place.
- **`ProjectStateStore` (Protocol, `runtime_checkable`)**. Reader + writer surface for `.project/project.yaml`, `.project/maintainers.yaml`, extensions. Methods: `read_project() -> ProjectConfig | None`, `write_project(config: ProjectConfig) -> None`, `read_maintainers() -> list[MaintainerEntry]`, `write_maintainers(entries: list[MaintainerEntry]) -> None`. Inherits `close()` from `Store`.
- **`AttestationStore` (Protocol, `runtime_checkable`)**. Write-only surface for attestation bundles. Methods: `write(bundle_id: str, bundle_bytes: bytes, content_type: str) -> None`, `close() -> None`. Read-back is intentionally NOT in v0: attestations are consumed downstream by other tooling (Sigstore, in-toto verifiers) not by darnit itself. If darnit ever needs to enumerate its own attestations, add a `list_bundles()` method as an additive Protocol extension.
- **`ReportStore` (Protocol, `runtime_checkable`)**. Write surface for audit reports in the three supported formats. Methods: `write_markdown(report_id: str, content: str) -> None`, `write_json(report_id: str, content: str) -> None`, `write_sarif(report_id: str, content: str) -> None`. Format-specific methods (rather than a generic `write(format, content)`) so the Protocol makes the invariant "three formats, always these three" enforceable by mypy/pyright.
- **`AuditCacheStore` (Protocol, `runtime_checkable`)**. Read + write surface for the per-audit-run cache. Methods: `read(cache_key: str) -> dict | None`, `write(cache_key: str, envelope: dict) -> None`. Existing TTL semantics (from `core/audit_cache.py`) stay in the caller; the store is a dumb read-through/write-through KV.
- **`StoresConfig`** (Pydantic model in `framework_schema.py`). Fixed keys `project`, `attestation`, `report`, `cache`, each optional and each a `StoreBlock`.
- **`StoreBlock`** (Pydantic model). `backend: str` required. `extra="allow"` so backend-specific keys pass through to the backend's `__init__`. String values are passed through `substitute_dollar_vars` at load time.
- **`_StoreBundle`** (runtime-only dataclass in `selection.py`). Holds the four resolved store instances plus a `close_all()` method that calls `close()` on every store that was actually instantiated. Owned by `darnit.tools.audit._run_audit`'s try/finally.

Existing types touched:

- `FrameworkConfig.stores: StoresConfig` added alongside `plugins` and `mcp_servers`.
- `UserConfig.stores: StoresConfig` added alongside `mcp_servers`.
- `merger.py` per-name replacement rule for `stores.<kind>` (one line, mirroring the `mcp_servers` merger).

### Contracts (`contracts/`)

Four files, one per Protocol:

- `contracts/project-state-store.md`
- `contracts/attestation-store.md`
- `contracts/report-store.md`
- `contracts/audit-cache-store.md`

Each contract covers: method signatures, contracts on inputs (raises what, when), concurrency model (sync in v0, single-caller), transactional guarantees (per-write, no cross-method atomicity), close-idempotence + close-safety, and the specific WARN/ERROR/best-effort mapping FR-011 defines for that Protocol's failure modes. Contracts are the file plugin authors read first.

### Quickstart (`quickstart.md`)

Three worked examples:

1. **Operator selects a backend.** Add three lines to `.baseline.toml`. Verify with `darnit audit` that the store's `write()` was called (via the backend's own diagnostics).
2. **Plugin author distributes a backend.** Author a minimal `AttestationStore` implementation in a new Python package, register the entry point, `pip install -e .`, verify discovery via `python -c "from darnit.stores.discovery import discover_stores; print(discover_stores('darnit.stores.attestation'))"`.
3. **Backing out.** Remove the `[stores.attestation]` block from `.baseline.toml`. Confirm the framework reverts to the filesystem default and reads/writes on the same paths as pre-feature.

### Agent Context Update

Update the reference between `<!-- SPECKIT START -->` and `<!-- SPECKIT END -->` markers in `CLAUDE.md` to point at `specs/033-pluggable-stores/plan.md`.

## Post-Design Constitution Recheck

The design phase artifacts do not introduce any new principle-touching decisions:

- **I. Plugin Separation**: reinforced by the module layout -- `darnit.stores` sub-package under `packages/darnit/src/darnit/`, no imports of implementation packages. The static-import guard (SC-008) is the mechanical enforcement.
- **II. Conservative-by-Default**: reinforced by FR-011's per-Protocol failure-mode mapping (`ProjectStateStore` -> WARN, `AttestationStore` -> ERROR, `AuditCacheStore` -> best-effort, `ReportStore` -> ERROR-with-note); no silent fallback (FR-012).
- **III. TOML-First**: reinforced by the `StoresConfig` schema addition + the `$VAR` substitution helper being TOML-native.
- **IV. Never Guess User Values**: not touched; storage backend selection is a fleet-config choice, not a per-control judgment.
- **V. Sieve Pipeline Integrity**: reinforced by the FR-017 constraint that no sieve/remediation/MCP handler consumes stores directly; the audit-boundary composition points are the only touchpoints, and the sieve's PASS/FAIL/WARN/ERROR contract is unchanged.

**Post-design gate: PASS.**
