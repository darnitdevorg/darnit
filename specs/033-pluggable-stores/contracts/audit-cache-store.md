# Contract: `AuditCacheStore` Protocol

**Owner**: `packages/darnit/src/darnit/stores/protocols.py`

**Registered under**: `darnit.stores.cache` entry-point group

**Stability**: Public API. v0 methods are stable; additions non-breaking.

## Purpose

Persist the per-audit-run cache. Cache lets remediation runs skip re-executing the audit when the cache is fresh. Existing TTL logic (`darnit.core.audit_cache`) stays in the caller; the Protocol is a dumb KV.

## TOML surface

```toml
[stores.cache]
backend = "redis"
url = "$REDIS_URL"
ttl_seconds = 3600
```

## Methods

### `close(self) -> None`

Inherited from `Store`.

### `read(self, cache_key: str) -> dict | None`

Load a cache envelope.

- **`cache_key`**: Opaque string the caller chose. Framework recommends `<owner>-<repo>-<framework_name>-<level>` shape but does not enforce.
- **Returns**: The `dict` envelope written by a previous `write` call, or `None` on cache miss OR on any backend failure.
- **Raises**: MUST NOT raise. Backend failures during `read` MUST be swallowed and treated as cache miss.

### `write(self, cache_key: str, envelope: dict) -> None`

Persist a cache envelope.

- **`envelope`**: The `dict` to store. Framework guarantees JSON-serializable values.
- **Raises**: MUST NOT raise. Backend failures during `write` MUST be logged and swallowed. The audit continues; next-run cache miss is acceptable.

## Failure semantics

Per FR-011: `AuditCacheStore` is the "best-effort" Protocol. Both `read` and `write` MUST NOT raise. This differs from `ProjectStateStore` and `AttestationStore`, which surface failures explicitly.

Rationale: cache is a performance optimization, not a correctness requirement. A failing cache write leads to an extra audit run; that's a slowdown, not a compliance error. Constitution II demands loud failure on correctness errors, but cache failures are not correctness errors.

## Consumers

- `packages/darnit/src/darnit/core/audit_cache.py` -- `read_audit_cache` / `write_audit_cache` become thin wrappers over `store.read` / `store.write`. TTL check (envelope timestamp comparison) stays in the wrapper.
- `packages/darnit-baseline/src/darnit_baseline/remediation/orchestrator.py` -- reads the cache to skip re-audits.

## Filesystem default

`darnit.stores.defaults.cache.FilesystemAuditCacheStore(root: Path)`:

- Reads from `<root>/<sanitized_cache_key>.json`.
- Writes via tempfile-then-rename for atomicity (existing behavior in `core/audit_cache.py:130-150` moves here).
- `close()` is a no-op.
- `root` defaults to `.darnit/audit-cache/`.

## Non-goals for v0

- TTL logic in the store (stays in the caller).
- Enumeration of cached keys.
- Explicit invalidation / delete (callers write over the key or wait for TTL).
- Cross-key atomicity.
