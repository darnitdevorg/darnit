# Phase 1 Data Model: Pluggable stores

## Purpose

Enumerate every new type this feature introduces, its fields, its constraints, and its lifecycle. This is the vocabulary the plan phase locks in for the reader contract, the tasks decomposition, and future reconciliation-style diffs.

## New types (public API)

### `Store` (Protocol base, `runtime_checkable`) in `darnit.stores.protocols`

The shared close-contract that every artifact-class Protocol inherits.

```python
@runtime_checkable
class Store(Protocol):
    def close(self) -> None:
        """Release any resources held by this store.

        MUST be idempotent (a second call is a no-op).
        MUST NOT raise on the "already closed" case.
        MAY raise on unrecoverable teardown failure (network partition,
        disk full during flush). Callers wrap the call in try/except and
        log; they do NOT re-raise.

        The framework calls close() exactly once at audit-boundary
        tear-down, regardless of success or exception in the audit path
        (see `darnit.tools.audit._run_audit`'s finally block).
        """
        ...
```

Not intended to be used as a standalone Protocol -- it exists to consolidate the FR-019 `close()` contract in one place. Every subclass Protocol inherits from it.

### `ProjectStateStore` (Protocol, `runtime_checkable`)

Read + write surface for `.project/project.yaml`, `.project/maintainers.yaml`, extensions.

```python
@runtime_checkable
class ProjectStateStore(Store, Protocol):
    def read_project(self) -> ProjectConfig | None:
        """Load the project configuration. Returns None if not present.
        Raises `StoreOperationError` on backend failure."""

    def write_project(self, config: ProjectConfig) -> None:
        """Persist the project configuration.
        Raises `StoreOperationError` on backend failure."""

    def read_maintainers(self) -> list[MaintainerEntry]:
        """Load the maintainer entries. Returns [] if not present."""

    def write_maintainers(self, entries: list[MaintainerEntry]) -> None:
        """Persist the maintainer entries."""
```

Failure semantics per FR-011:
- `read_project` failure -> caller resolves affected controls WARN (see `darnit.tools.audit.load_project_context`).
- `write_project` / `write_maintainers` failure -> caller surfaces the error to the operator; the audit run fails.

### `AttestationStore` (Protocol, `runtime_checkable`)

Write-only surface for attestation bundles.

```python
@runtime_checkable
class AttestationStore(Store, Protocol):
    def write(self, bundle_id: str, bundle_bytes: bytes, content_type: str) -> None:
        """Persist an attestation bundle.

        `bundle_id` is a stable identifier the operator can use to
        correlate the bundle with the audit run that produced it (e.g.,
        <audit-run-id>-<control-id>). Must be filesystem-safe.
        `content_type` names the media type (e.g., "application/vnd.in-toto+json"
        for in-toto statements, "application/vnd.dev.sigstore.bundle+json"
        for Sigstore bundles).
        Raises `StoreOperationError` on backend failure.
        """
```

Read-back is intentionally NOT in v0: attestations are consumed downstream by other tooling (Sigstore, in-toto verifiers), not by darnit itself. If darnit ever needs to enumerate its own attestations, add a `list_bundles()` method as an additive Protocol extension.

### `ReportStore` (Protocol, `runtime_checkable`)

Write surface for audit reports in the three supported formats.

```python
@runtime_checkable
class ReportStore(Store, Protocol):
    def write_markdown(self, report_id: str, content: str) -> None: ...
    def write_json(self, report_id: str, content: str) -> None: ...
    def write_sarif(self, report_id: str, content: str) -> None: ...
```

Format-specific methods (rather than a generic `write(format, content)`) so mypy/pyright can enforce the "three formats, always these three" invariant at the type layer. Adding a fourth format is an additive Protocol change.

Note: v0 has no existing report-writing call site to migrate. The Protocol + filesystem default exist to enable follow-up features (starting with #341) to write through the Protocol without having to introduce the abstraction retroactively.

### `AuditCacheStore` (Protocol, `runtime_checkable`)

Read + write surface for the per-audit-run cache.

```python
@runtime_checkable
class AuditCacheStore(Store, Protocol):
    def read(self, cache_key: str) -> dict | None:
        """Load a cache envelope. Returns None on miss or on any backend failure."""

    def write(self, cache_key: str, envelope: dict) -> None:
        """Persist a cache envelope. Best-effort: backend failures MUST NOT
        raise; caller logs and continues."""
```

Failure semantics per FR-011: cache is best-effort. A failing `write` is logged and the audit run continues (next-run cache miss is acceptable). A failing `read` returns `None` (cache miss). Existing TTL semantics (from `core/audit_cache.py`) stay in the caller; the store is a dumb KV.

## New types (config-schema)

### `StoreBlock` (Pydantic model) in `darnit.config.framework_schema`

One `[stores.<kind>]` TOML block.

| Field | Type | Default | Constraint |
|-------|------|---------|------------|
| `backend` | `str` | required | Must match a registered entry point under `darnit.stores.<kind>` (validated at selection time, not schema time; discovery is a runtime concern). |
| (extras) | `str \| int \| bool \| list \| dict` | -- | Passed through to the backend's `__init__` as kwargs. String values are passed through `darnit.core.env_subst.substitute_dollar_vars(value)` at load time. |

```python
class StoreBlock(BaseModel):
    backend: str
    model_config = ConfigDict(extra="allow")
```

### `StoresConfig` (Pydantic model)

The four artifact-class-keyed store blocks.

| Field | Type | Default | Constraint |
|-------|------|---------|------------|
| `project` | `StoreBlock \| None` | `None` | -- |
| `attestation` | `StoreBlock \| None` | `None` | -- |
| `report` | `StoreBlock \| None` | `None` | -- |
| `cache` | `StoreBlock \| None` | `None` | -- |

`model_config = ConfigDict(extra="forbid")` -- catches typos like `[stores.audit_log]` at schema-load time.

```python
class StoresConfig(BaseModel):
    project: StoreBlock | None = None
    attestation: StoreBlock | None = None
    report: StoreBlock | None = None
    cache: StoreBlock | None = None
    model_config = ConfigDict(extra="forbid")
```

## New types (runtime-only, not public API)

### `_StoreBundle` (dataclass) in `darnit.stores.selection`

Runtime holder for the four resolved store instances of a single audit run.

```python
@dataclass
class _StoreBundle:
    project: ProjectStateStore
    attestation: AttestationStore
    report: ReportStore
    cache: AuditCacheStore

    def close_all(self) -> None:
        """Call close() on every store. Idempotent; safe to call multiple
        times (each store's close() is required to be idempotent per FR-019).
        Exceptions during one store's close() are logged and swallowed so
        a failure in one does not prevent the others from being closed."""
```

## Existing types touched

### `FrameworkConfig` (in `framework_schema.py`)

Add:

```python
stores: StoresConfig = Field(default_factory=StoresConfig)
```

Placed alongside `plugins` and `mcp_servers` so the three extension surfaces sit together in the schema.

### `UserConfig` (in `user_schema.py`)

Mirror:

```python
stores: StoresConfig = Field(default_factory=StoresConfig)
```

### `merge_configs()` (in `merger.py`)

Add per-kind replacement for each of the four store blocks. `.baseline.toml`'s `[stores.<kind>]` for a given kind fully replaces the framework TOML block for that kind; disjoint kinds coexist. Pseudocode:

```python
for kind in ("project", "attestation", "report", "cache"):
    if getattr(user.stores, kind) is not None:
        setattr(framework.stores, kind, getattr(user.stores, kind))
```

Mirrors the existing `mcp_servers` merger from feature 031.

### `darnit.core.env_subst.substitute_dollar_vars` (new, extracted per research R-004)

Public helper. Two existing call sites migrate to it: feature 025's `exec_handler` and feature 031's `mcp_pool._substitute_env`. Regression tests assert identical behavior on both call sites.

## Constants introduced

- `STORE_ENTRY_POINT_GROUPS = ("darnit.stores.project", "darnit.stores.attestation", "darnit.stores.report", "darnit.stores.cache")` in `darnit.stores.discovery`.
- `_STORE_KINDS = ("project", "attestation", "report", "cache")` in `darnit.stores.selection` (used for iterating the four artifact classes).

## State transitions

### Store lifecycle

```
[ DISCOVERED ] -- selection --> [ INSTANTIATED ] -- audit runs --> [ CLOSED ]
       ^                                                                |
       |                                                                v
       +--- next process starts -----------------------------  [ GARBAGE COLLECTED ]
```

Discovery happens once per process at framework-load time (FR-005). Instantiation happens lazily on first use per artifact class within an audit run (FR-010). Close happens exactly once at audit-boundary tear-down (FR-019).

### Failure semantics per Protocol

| Protocol | Read failure | Write failure |
|----------|--------------|---------------|
| `ProjectStateStore` | Caller resolves affected controls WARN. Never silent PASS. | Surface as audit-run error; abort the run. |
| `AttestationStore` | n/a (write-only) | Surface as audit-run error; the attestation is NOT reported as persisted. |
| `ReportStore` | n/a (write-only) | Surface as audit-run error with format name. |
| `AuditCacheStore` | Return `None` (cache miss); log warning. | Log warning; audit continues. Best-effort. |

## Non-model concerns

Everything else about this feature reuses machinery that already exists: TOML parsing (Pydantic), entry-point discovery (`importlib.metadata`, per feature 027's pattern), config merging (per feature 031's pattern), `try/finally` teardown (per feature 031's `verify_batch` pattern). No new pydantic models beyond `StoreBlock` and `StoresConfig`; no schema migrations; no persistent state changes beyond the four filesystem defaults reproducing the pre-feature on-disk layout.
