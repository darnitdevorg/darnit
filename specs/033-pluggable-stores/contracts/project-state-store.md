# Contract: `ProjectStateStore` Protocol

**Owner**: `packages/darnit/src/darnit/stores/protocols.py`

**Registered under**: `darnit.stores.project` entry-point group

**Stability**: Public API. v0 methods are stable; additions are non-breaking. Removals or signature changes require a major-version bump.

## Purpose

Persist the darnit-consumed subset of the CNCF `.project/` specification: `project.yaml`, `maintainers.yaml`, and the extensions bag.

## TOML surface

```toml
[stores.project]
backend = "postgres"
dsn = "$PG_DSN"
```

## Methods

### `close(self) -> None`

Inherited from `Store`. See the base contract at [`../data-model.md`](../data-model.md#store-protocol-base-runtime_checkable-in-darnitstoresprotocols).

### `read_project(self) -> ProjectConfig | None`

Load the project configuration.

- **Returns**: `ProjectConfig` instance (see `darnit.context.dot_project.ProjectConfig`), or `None` if no project is stored under this backend's addressing.
- **Raises**: `StoreOperationError` on any backend failure that is not "not found" (e.g., malformed data, transient network failure, permission error).
- **Concurrency**: Sync in v0. Single-caller assumed within an audit run.

### `write_project(self, config: ProjectConfig) -> None`

Persist the project configuration.

- **Preconditions**: `config` is a valid `ProjectConfig` (validated by the caller via Pydantic).
- **Raises**: `StoreOperationError` on backend failure.
- **Atomicity**: Per-call atomic (the write either commits or does not; no partial state). Cross-method atomicity (e.g., "write_project then write_maintainers together") is NOT guaranteed by this Protocol.

### `read_maintainers(self) -> list[MaintainerEntry]`

Load the maintainer entries.

- **Returns**: List of `MaintainerEntry` instances. Empty list if none present.
- **Raises**: `StoreOperationError` on backend failure that is not "not found".

### `write_maintainers(self, entries: list[MaintainerEntry]) -> None`

Persist the maintainer entries. Same atomicity rules as `write_project`.

## Failure semantics

Per FR-011:

| Failure | Consequence |
|---------|-------------|
| `read_project` raises | Caller (`darnit.tools.audit.load_project_context`) resolves affected controls WARN with message identifying the store and the failure reason. Never silent PASS. |
| `write_project` raises | Audit run fails with the store's error. State is not partially updated. |
| `read_maintainers` raises | Same as `read_project`. |
| `write_maintainers` raises | Same as `write_project`. |
| `close()` raises | Logged; framework does NOT re-raise. |

## Consumers

- `packages/darnit/src/darnit/context/dot_project.py` -- `DotProjectReader` and `DotProjectWriter` are the primary consumers.
- `packages/darnit/src/darnit/context/dot_project_org.py` -- org-fetched YAML flows through `write_project` / `write_maintainers`.
- `packages/darnit/src/darnit/tools/audit.py` -- injects the store at ExecutionContext construction.

## Filesystem default

`darnit.stores.defaults.project.FilesystemProjectStateStore(repo_path: Path)`:

- Reads from `<repo_path>/.project/project.yaml` and `<repo_path>/.project/maintainers.yaml`.
- Writes to the same paths.
- `close()` is a no-op.
- Reproduces the pre-feature on-disk layout exactly (SC-003).

## Non-goals for v0

- Read-back of extensions (v0 exposes only `project` and `maintainers`).
- Cross-artifact transactional semantics (e.g., "write project and maintainers atomically").
- Delete operations (project state is written; unwritten keys have no explicit "delete" API).
