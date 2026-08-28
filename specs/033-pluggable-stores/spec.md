# Feature Specification: Pluggable storage backends via per-artifact Protocols

**Feature Branch**: `033-pluggable-stores`

**Created**: 2026-08-25

**Status**: Draft

**Input**: Storage abstraction: per-artifact Protocols with entry-point discovery for pluggable persistence backends. Enables alternative storage (database, KV, cloud) for four artifact classes (project state, attestations, reports, audit cache) without darnit-core adopting any non-filesystem dependency. Blocks issue #391 (datastore backend for project metadata); design conversation on 2026-08-23; see issue #394 for background.

## Clarifications

### Session 2026-08-25

- Q: Do Store Protocols require an explicit teardown method for backends that hold resources? -> A: Yes -- every Protocol MUST declare a `close()` method; framework calls it exactly once at audit-boundary tear-down (matches feature 031's `McpPool.teardown_all()` precedent). Filesystem defaults implement it as a no-op. Backends with real resources (databases, HTTP sessions, cached credentials) release them there. Missing `close()` on a plugin implementation is a Protocol-conformance failure detected at instantiation time.
- Q: How does darnit handle secrets in backend-specific TOML config? -> A: `$VAR` substitution from `os.environ` at load time, reusing the exact pattern feature 025's `exec` handler and feature 031's mcp `env` block already established. Any string value inside a `[stores.<kind>]` block that contains `$VAR` gets substituted; unset variables substitute as empty string (matches `exec` handler semantics). This makes `.baseline.toml` safe to commit -- secrets are named-only, not embedded -- and does not introduce a new config surface plugin authors have to learn.
- Q: When does the framework discover installed backend plugins? -> A: Once at framework-load time (when `FrameworkConfig` is first materialized), matching feature 027's `QuestionResolver` discovery pattern. Name collisions (FR-009) and Protocol-conformance failures (FR-002 / FR-008) surface at that single point, before any control runs. Per-process cache; no runtime refresh mechanism in v0.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Operator chooses a non-filesystem backend for one artifact class (Priority: P1)

An operator running darnit against a fleet of repositories declares in `.baseline.toml` that project state should be read from and written to a custom backend (e.g., a shared database service). No other artifact class is affected: attestations, reports, and audit cache still land on the local filesystem. The audit produces identical control verdicts to running against the same project data stored on disk; the only observable difference is where the data came from and went to.

**Why this priority**: This is the whole reason the feature exists. Without a per-artifact selection knob, fleet operators cannot migrate a subset of state to a shared store; without observable equivalence, they cannot trust that the migration didn't change verdicts.

**Independent Test**: Configure `.baseline.toml` with `[stores.project] backend = "in-memory-test"` (a test backend that ships with the feature). Run `darnit audit` against a fixture repo whose `.project/project.yaml` has been pre-seeded into the in-memory backend. Assert the audit produces the same control verdicts as running against the same data on disk with the default filesystem backend. Assert the local filesystem's `.project/` was not read.

**Acceptance Scenarios**:

1. **Given** `.baseline.toml` selects a non-filesystem backend for the `project` store AND that backend is installed as a plugin AND the audit's context requires project state, **When** the audit runs, **Then** the framework loads project state through the selected backend, produces the same control verdicts it would have produced from equivalent filesystem-stored data, and does not read the local `.project/` directory.
2. **Given** the same configuration but with `[stores.attestation]` NOT set, **When** the audit produces an attestation, **Then** the attestation is written to the local filesystem (default backend), NOT to the selected project-store backend.
3. **Given** a maintainer reading the audit's evidence records, **When** they inspect any control's evidence, **Then** the record is identical in content whether the underlying project data came from the filesystem or from the alternative backend.

---

### User Story 2 - Framework runs unchanged when no backend is selected (Priority: P1)

A user upgrades to a darnit release that includes this feature but does not change their `.baseline.toml`. Their existing audits continue to work exactly as before: every artifact class reads from and writes to the local filesystem, and no new configuration is required.

**Why this priority**: Backward compatibility is a first-class requirement. Any regression in the zero-config path is unacceptable because it affects every existing user of darnit.

**Independent Test**: Run the full existing test suite against a checkout that includes the new abstraction. Assert zero test failures. Assert every artifact ends up in the exact same on-disk location as before the feature landed. Run the existing quickstart from `docs/USAGE_GUIDE.md`; assert identical output.

**Acceptance Scenarios**:

1. **Given** `.baseline.toml` has no `[stores.*]` section, **When** any audit or remediation runs, **Then** every artifact is read from and written to the same filesystem paths as pre-feature (`.project/`, `.darnit/attestations/`, output paths passed to formatters, `.darnit/audit-cache/`).
2. **Given** no code outside of `packages/darnit/` imports any store module, **When** the framework runs, **Then** existing controls, handlers, and remediations produce identical results to pre-feature behavior.
3. **Given** a repo whose CI already exercises the pre-feature test suite, **When** that CI runs against the feature branch, **Then** every previously passing test still passes.

---

### User Story 3 - Plugin author distributes a new backend (Priority: P2)

A plugin author packages a new backend implementation (for example, a Postgres-backed `AttestationStore`) as a separate Python package. Installing that package into an operator's environment makes the backend available for selection in `.baseline.toml` under the correct artifact key. The plugin author does not need to modify darnit-core, submit a PR to darnit, or coordinate a darnit release.

**Why this priority**: This is the ecosystem story. If plugin authors cannot ship backends independently, the abstraction has failed its second-most-important goal (the first being that darnit-core stays filesystem-only).

**Independent Test**: Author a small example plugin in a separate Python package that registers a no-op `AttestationStore` under `darnit.stores.attestation`. `pip install` the plugin. Run darnit against a fixture that produces an attestation, selecting the new backend in `.baseline.toml`. Assert the attestation is dispatched to the plugin's `AttestationStore` (verified by a spy in the test plugin), and that darnit-core did not import the plugin package.

**Acceptance Scenarios**:

1. **Given** a plugin package that registers an `AttestationStore` implementation under the correct entry-point group, **When** the operator sets `[stores.attestation] backend = "<plugin-name>"` and runs an audit that produces an attestation, **Then** the attestation is written via the plugin's implementation, not the filesystem default.
2. **Given** a plugin that fails at import time (broken code) or fails to satisfy the Protocol at instantiation, **When** the operator selects it, **Then** darnit fails fast with a clear error naming the backend key, the plugin package, and the specific failure reason. Darnit does NOT silently fall back to the default backend.
3. **Given** a plugin author reading darnit's documentation, **When** they follow the plugin-authoring guide, **Then** they can produce a working backend implementation without reading darnit's internal source code.

---

### User Story 4 - Failure semantics are explicit per Protocol (Priority: P2)

An operator whose selected backend becomes unreachable mid-audit (network partition, database restart, disk full on the local backend) sees a distinguishable error that names which artifact class failed to persist. The audit's control-verdict pipeline is not corrupted by the failure: reads that succeeded before the failure remain valid; writes that failed do not silently succeed.

**Why this priority**: A store failure with unclear semantics is worse than no store at all -- it produces attestations that lied about being persisted, or reports that half-landed. This aligns with Constitution II ("conservative-by-default").

**Independent Test**: Configure a backend that raises on write. Run an audit. Assert the audit surfaces the failure with the artifact class, the backend name, and the operation that failed. Assert control verdicts are not affected (a failing attestation-store write does not corrupt the audit's per-control PASS/FAIL/WARN judgments; a failing project-store read prevents the affected controls from producing PASS/FAIL and resolves them WARN with a message naming the store failure).

**Acceptance Scenarios**:

1. **Given** an audit whose selected `AttestationStore` raises on write, **When** the audit reaches the attestation-persistence step, **Then** the audit reports the failure with the backend name and the operation, and does NOT report the attestation as successfully persisted.
2. **Given** an audit whose selected `ProjectStateStore` raises on read at audit-start time, **When** the framework attempts to load project context, **Then** the affected controls resolve WARN with a message that names the store failure. The framework does NOT read from the filesystem as a fallback (that would silently mask misconfiguration; user has selected a specific backend and expects it to be used).
3. **Given** an audit whose selected `AuditCacheStore` fails intermittently (write fails, read next audit run succeeds), **When** the write fails, **Then** the audit logs a warning and continues (cache failures are best-effort; they do not affect control verdicts). This differentiates from ProjectStateStore and AttestationStore which have stricter semantics.

---

### Edge Cases

- **Backend name collision**: two installed plugins register the same short name (e.g., "postgres") for the same artifact class. The framework MUST surface the collision at framework-load time with a clear error naming both packages and the shared key. Selection cannot proceed until the operator disambiguates.
- **Selected backend is not installed**: operator selects `[stores.project] backend = "postgres"` but no plugin registered a `postgres` implementation under `darnit.stores.project`. The framework MUST fail fast with a message that names the requested backend, the artifact class, and the installed alternatives.
- **Backend selected but Protocol not satisfied**: a plugin's registered class does not conform to the expected Protocol (missing method, wrong signature). The framework MUST detect this at selection/instantiation time via runtime Protocol checking and fail with a message naming the specific method(s) that failed the check.
- **Mixed backends across artifact classes**: `stores.project` selects "postgres" and `stores.attestation` selects "s3"; other classes use the default. This MUST work; each artifact class is independently selectable.
- **Backend selected but audit runs in a context that never uses that artifact**: e.g., `AuditCacheStore` selected but the invocation is a fresh-cache run. The framework MUST NOT instantiate stores it does not use in the current run (lazy instantiation).
- **Plugin backend that does its own async I/O**: a Postgres backend may want to reuse an async connection pool. The Protocols MUST specify a sync or async surface unambiguously; a mixed-mode Protocol is not accepted.
- **Store failure during a batch write**: an audit produces multiple attestations in one run; the store's third write fails. The framework MUST clearly report which attestations landed and which did not; it MUST NOT report atomic success when only partial success occurred.
- **Downgrade path**: an operator selects a backend, later removes the plugin, and runs darnit against a state file that references the removed backend. The framework MUST NOT silently fall through to the filesystem default; it MUST fail with the "backend not installed" error.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The framework MUST define exactly four persistence Protocols, one per artifact class: `ProjectStateStore`, `AttestationStore`, `ReportStore`, `AuditCacheStore`. No fifth Protocol is introduced in v0.
- **FR-002**: Each Protocol MUST be runtime-checkable (framework can verify at instantiation time that a candidate class satisfies the Protocol).
- **FR-003**: Each Protocol MUST document, in its docstring and in the reader contract, its concurrency model (sync vs async), batch semantics (per-item vs batched), transactional guarantees (all-or-nothing vs eventually-consistent), and the meaning of a failed write (exception vs return value).
- **FR-004**: The framework MUST ship a filesystem-backed default implementation for each Protocol. Defaults MUST reproduce the pre-feature on-disk layout exactly (same paths, same file formats, same naming conventions).
- **FR-005**: The framework MUST discover third-party backend implementations via Python entry points under group names `darnit.stores.project`, `darnit.stores.attestation`, `darnit.stores.report`, `darnit.stores.cache`. Discovery MUST run exactly once per process, at framework-load time (when `FrameworkConfig` is first materialized), matching the pattern feature 027's `QuestionResolver` discovery uses. Name collisions (FR-009) and Protocol-conformance failures MUST surface at that single point, before any control runs. There is no runtime refresh mechanism in v0; late-installed plugins take effect on the next process start.
- **FR-006**: Operator selection of a backend MUST live in `.baseline.toml` (and framework TOML, with the same precedence rule other blocks use) under `[stores.<kind>] backend = "<name>"`. Backend-specific configuration MAY appear under the same block as additional keys (`[stores.attestation] backend = "postgres"; dsn = "$POSTGRES_DSN"`). Any string value inside a `[stores.<kind>]` block that contains a `$VAR` token MUST be substituted from `os.environ` at load time; unset variables MUST substitute as empty string. This matches the substitution semantics feature 025's `exec` handler and feature 031's mcp `env` block use, so plugin authors do not need a new secret-handling convention.
- **FR-007**: When no `[stores.*]` block is present, the framework MUST use the filesystem default for every artifact class, with identical on-disk behavior to the pre-feature state.
- **FR-008**: The framework MUST fail fast (before an audit runs) with a clear error naming the requested backend, the artifact class, and the reason (not installed, does not satisfy Protocol, name collision) if any of the selected backends cannot be resolved.
- **FR-009**: Two plugins registering the same backend name for the same artifact class MUST produce a resolution error at framework-load time. No implicit "last wins" resolution.
- **FR-010**: The framework MUST instantiate a store lazily -- only when the current run's flow actually uses that artifact class. An audit that produces no attestations MUST NOT instantiate the `AttestationStore`. Every store that IS instantiated during a run MUST be closed at audit-boundary tear-down (FR-019).
- **FR-011**: Store failures during an audit MUST be surfaced with the artifact class, the backend name, and the failing operation. Store failures for `ProjectStateStore` reads that block a control's evaluation MUST resolve affected controls WARN (not FAIL, not silent PASS). Store failures for `AttestationStore` writes MUST surface as errors that a downstream consumer can distinguish from "attestation not requested." Store failures for `AuditCacheStore` MUST be logged and treated as best-effort (audit continues; next-run cache miss is acceptable).
- **FR-012**: The framework MUST NOT silently fall back to the filesystem default when a selected backend fails. An operator selected a specific backend; that selection must be honored.
- **FR-013**: The `darnit` core package MUST NOT import any implementation package or any non-filesystem backend implementation. Constitution I (Plugin Separation) applies unchanged.
- **FR-014**: Introducing this feature MUST NOT add any new required runtime dependency to any published darnit package. The Protocol machinery uses only the standard library and existing dependencies.
- **FR-015**: The `Store` Protocols MUST be public API (documented as such); breaking changes require a coordinated release cycle. Non-breaking additive changes MAY happen freely.
- **FR-016**: The plugin-author-facing documentation MUST include: the four Protocols and their contracts, the entry-point group names, a full worked example of an in-memory `AttestationStore` implementation, and the failure-handling expectations from FR-011.
- **FR-017**: Existing sieve handlers, remediation handlers, and MCP tools MUST NOT be modified to consume the store abstraction directly. Store access happens at audit-boundary composition (the same places that today do the hard-coded filesystem calls), preserving the sieve's PASS/FAIL/WARN/ERROR contract (Constitution V).
- **FR-018**: When the framework logs store operations (for debugging), the log messages MUST identify the backend name and the artifact class. Log messages MUST NOT include store-specific secrets (database DSNs, credentials, tokens).
- **FR-019**: Every Store Protocol MUST declare a `close()` method on its interface. The framework MUST call `close()` on every instantiated store exactly once at audit-boundary tear-down, regardless of success or exception in the audit path. Filesystem defaults MAY implement `close()` as a no-op. Backends that hold resources (database connections, HTTP sessions, cached credentials) MUST release them there. `close()` MUST be idempotent -- calling it twice is not an error, though the framework will not do so. A plugin implementation that does not declare `close()` fails the runtime Protocol check (FR-002) at instantiation time and produces the same fail-fast error as any other Protocol conformance failure (FR-008). Matches feature 031's `McpPool.teardown_all()` precedent for per-audit-run resource-holders.

### Key Entities

- **Store Protocol**: a Python typing.Protocol (with `@runtime_checkable`) defining the read/write interface for a specific artifact class. Four instances of this pattern exist in v0. Each Protocol is a public API of darnit.
- **Backend implementation**: a concrete class that satisfies one Store Protocol. Filesystem defaults are shipped in darnit-core; alternative implementations come from third-party plugin packages. Each implementation is registered under exactly one entry-point group.
- **Artifact class**: the abstract category of persistent data. In v0: project state, attestations, reports, audit cache. Each artifact class has exactly one Protocol.
- **Backend selection**: an operator-facing string in `.baseline.toml` (`[stores.<kind>] backend = "<name>"`) that names which registered backend to instantiate for a given artifact class. Missing selection means filesystem default.
- **Filesystem default**: the shipped implementation in darnit-core that reproduces pre-feature on-disk behavior for its artifact class. Provides the backward-compatibility guarantee (User Story 2).

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: The full pre-feature test suite passes on the feature branch without modification. Zero regressions.
- **SC-002**: A configuration with `[stores.project] backend = "in-memory-test"` (a test backend shipped for this purpose) produces identical control verdicts to the same configuration reading from an equivalent on-disk `.project/` tree. Verifiable by a fixture-driven test that runs both paths and diffs the verdict list.
- **SC-003**: An audit with no `[stores.*]` block instantiates only the filesystem-default backends and touches only the same on-disk paths as pre-feature. Verifiable by a spy on all four Store implementations plus a filesystem-touch audit.
- **SC-004**: An audit that produces no attestations does not instantiate an `AttestationStore` of any kind. Verifiable by a spy on the four filesystem defaults' `__init__` methods.
- **SC-005**: An operator following the plugin-authoring guide can produce a working `AttestationStore` plugin in under 30 minutes, verifiable by an in-repo example plugin (implemented as part of this feature) that is <100 lines and covers the full author workflow.
- **SC-006**: A store failure on any Protocol produces an operator-visible message that names the backend, the artifact class, and the failing operation. Verifiable by fault-injection tests, one per Protocol.
- **SC-007**: A `.baseline.toml` selection that names an uninstalled backend produces a fail-fast error before any control runs. Verifiable by an integration test that measures how many controls executed (must be zero).
- **SC-008**: `packages/darnit/` continues to have zero imports of `packages/darnit-baseline/` or any plugin package. Verifiable by the existing static-import guard (`scripts/validate_sync.py` or the equivalent), which MUST pass unchanged.

## Assumptions

- **Sync-first Protocols in v0**: v0 Protocols are synchronous. Async surfaces are a legitimate future extension but require their own spec because they change the calling convention at every audit-boundary composition point.
- **`.baseline.toml` is the sole selection surface**: no environment-variable override, no CLI flag, no per-invocation TOML. Selection is fleet-wide via `.baseline.toml`; that keeps auditing reproducible.
- **Backend-specific config in the same block**: `[stores.attestation] backend = "postgres"; dsn = "..."` is expressed as key-value pairs inside the stores block. The framework passes them to the backend's `__init__` as a dict; each backend documents the keys it accepts.
- **In-memory test backend ships in `darnit-testchecks`**: the reference in-memory implementations used by SC-002 and SC-004's tests are packaged under `darnit-testchecks`, not `darnit`, so they do not bloat the runtime install.
- **Public API stability**: the four Protocols are public API. Breaking changes wait for a major-version release cycle. Additive changes (new optional methods with reasonable defaults) are non-breaking.
- **Storage is orthogonal to the sieve**: sieve handlers, CEL evaluation, and per-control disposition logic do not know about stores. Store operations happen at audit-boundary composition (audit driver, remediation orchestrator, attestation generator, report formatters).
- **Non-goal: cross-artifact atomicity**: a single audit run may write to all four store kinds; the framework does NOT guarantee atomicity across the four. If cross-artifact atomicity is ever needed (unlikely), it would be a separate feature with its own spec.
- **Non-goal: migration tooling**: converting an existing filesystem state to a non-filesystem backend is out of scope. Operators either bring their own migration or start fresh on the new backend.
- **Non-goal: shared caching / connection pooling across store instances**: each Protocol's implementation owns its own resources. If a Postgres backend serves both `ProjectStateStore` and `AttestationStore`, connection sharing is an implementation detail of that specific plugin, not a framework concern.
- **v0 backends are not enumerated as first-party targets**: this feature enables backends; it does not build any non-filesystem backend. The first non-filesystem backend (Postgres for `ProjectStateStore`) is tracked at #391.
