# Contract: `ProjectStateStore` Protocol

**Owner**: `packages/darnit/src/darnit/stores/protocols.py`

**Registered under**: `darnit.stores.project` entry-point group

**Stability**: Public API. v0 methods are stable; additions are non-breaking. Removals or signature changes require a major-version bump.

## Purpose

Provide the read surface for the darnit-consumed subset of the CNCF `.project/` specification: `project.yaml`, `maintainers.yaml`, and the extensions bag. Writes to `.project/` are managed exclusively by `darnit.config.context_writes` under feature 042 single-writer rules.

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

### `read_maintainers(self) -> list[MaintainerEntry]`

Load the maintainer entries.

- **Returns**: List of `MaintainerEntry` instances. Empty list if none present.
- **Raises**: `StoreOperationError` on backend failure that is not "not found".

## Failure semantics

Per FR-011:

| Failure | Consequence |
|---------|-------------|
| `read_project` raises | Caller (`darnit.tools.audit.load_project_context`) resolves affected controls WARN with message identifying the store and the failure reason. Never silent PASS. |
| `read_maintainers` raises | Same as `read_project`. |
| `close()` raises | Logged; framework does NOT re-raise. |

## Consumers

- `packages/darnit/src/darnit/context/dot_project.py` -- `DotProjectReader` is the primary consumer.
- `packages/darnit/src/darnit/tools/audit.py` -- injects the store at ExecutionContext construction.

## Filesystem default

`darnit.stores.defaults.project.FilesystemProjectStateStore(repo_path: Path)`:

- Reads from `<repo_path>/.project/project.yaml` and `<repo_path>/.project/maintainers.yaml`.
- `close()` is a no-op.
- Reproduces the pre-feature on-disk layout exactly (SC-003).

## Non-goals for v0

- Read-back of extensions (v0 exposes only `project` and `maintainers`).
- Write operations (writes to `.project/` are managed exclusively by `context_writes` under feature 042).
- Delete operations (project state is read; unwritten keys have no explicit "delete" API).
