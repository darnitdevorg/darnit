# Phase 1: Data Model -- Audit-Cache Store Migration

**Feature**: 035-audit-cache-store-migration | **Date**: 2026-09-02

No new database schema; this is a code-shape change. The "entities" here are the concrete values and objects flowing through the migrated code path.

## E-001: Cache envelope (unchanged)

The JSON blob written to disk. Structure is identical to the pre-feature `write_audit_cache` output, guaranteed byte-for-byte compatibility with existing on-disk caches.

```python
{
    "version": int,             # CACHE_VERSION = 1
    "timestamp": str,           # datetime.now(UTC).isoformat()
    "commit": str | None,       # git HEAD (None when repo is not a git repo)
    "commit_dirty": bool,       # True if working tree has uncommitted changes
    "level": int,               # Max audit level evaluated
    "framework": str,           # Framework name (e.g. "openssf-baseline")
    "results": list[dict],      # Serialized CheckResults
    "summary": dict[str, int],  # Status counts
}
```

**Invariant**: The envelope is the same shape in both storage paths (default tempdir and configured-root). The store just handles bytes; the wrapper composes and interprets the shape.

## E-002: Cache key

The `cache_key` string the wrapper passes into `AuditCacheStore.read(cache_key)` and `.write(cache_key, envelope)`. Composition depends on which store the wrapper is talking to:

**Default-store case** (`stores_config.cache is None`): `cache_key = "audit-cache"`. The store's root already encodes repo identity (`<tempdir>/darnit/<hash>`), so the key just names the file. Final path: `<tempdir>/darnit/<hash>/audit-cache.json`. Byte-for-byte identical to pre-feature.

**Configured-store case** (`stores_config.cache is not None`): `cache_key = sha256(abspath(repo_path))[:16]`. The store's root is operator-picked and shared across repos, so the key MUST encode repo identity. Final path: `<operator_root>/<hash>.json`.

**Rationale**: Two paths, one wrapper. The driver decides which case it's in and passes the right key. The wrapper is dumb: it does not know or care about `stores_config`.

**Hash function**: `sha256(abspath(repo_path).encode()).hexdigest()[:16]` -- identical to the pre-feature `_get_cache_dir` composition. Preserves per-repo stability across runs.

## E-003: Store instance (`bundle.cache`)

An `AuditCacheStore` Protocol implementer. Exposes exactly three methods:

```python
class AuditCacheStore(Protocol):
    def read(self, cache_key: str) -> dict[str, Any] | None: ...
    def write(self, cache_key: str, envelope: dict[str, Any]) -> None: ...
    def close(self) -> None: ...
```

Neither the Protocol nor any implementation changes in this feature. Only the DEFAULT ROOT that `resolve_stores` passes to `FilesystemAuditCacheStore` moves from `<repo>/.darnit/audit-cache/` to `<tempdir>/darnit/<sha256(str(repo_path.resolve()))[:16]>`.

**Best-effort contract**: `read` returns `None` on any failure (missing, corrupt, unreadable). `write` swallows all `OSError` and logs a warning. Feature 033 FR-011.

## E-004: Expired envelope (for invalidation)

A cache envelope whose timestamp is guaranteed to be older than any reasonable TTL, so the next `read_audit_cache` returns `None` via the existing TTL check.

```python
EXPIRED_ENVELOPE = {
    "version": 1,
    "timestamp": "1970-01-01T00:00:00Z",
    "commit": None,
    "commit_dirty": False,
    "level": 0,
    "framework": "",
    "results": [],
    "summary": {},
}
```

`invalidate_audit_cache(local_path)` calls `store.write(cache_key, EXPIRED_ENVELOPE)`. The file remains on disk (Q3 answer: acceptable, cache path is operator-invisible tempdir), but every read after invalidation misses on TTL until a fresh write overwrites it. No `AuditCacheStore.delete()` method is added.

## E-005: Wrapper API (public)

Three functions, backward-compatible signatures plus two optional kwargs each.

```python
def write_audit_cache(
    local_path: str,
    results: list[CheckResult],
    summary: dict[str, int],
    level: int,
    framework: str,
    *,
    store: AuditCacheStore | None = None,
    cache_key: str | None = None,
) -> None: ...

def read_audit_cache(
    local_path: str,
    ttl_seconds: int = 3600,
    *,
    store: AuditCacheStore | None = None,
    cache_key: str | None = None,
) -> dict[str, Any] | None: ...

def invalidate_audit_cache(
    local_path: str,
    *,
    store: AuditCacheStore | None = None,
    cache_key: str | None = None,
) -> None: ...
```

**Semantics**:

* When both `store` and `cache_key` are `None` (backward-compat, external callers who don't know about the store surface yet): the wrapper builds its own default `FilesystemAuditCacheStore(root=<tempdir>/darnit/<hash>)` and uses `cache_key = "audit-cache"`. Byte-for-byte legacy path shape.
* When both are provided (audit-driver call site): the wrapper uses them as-is. No introspection of `stores_config`.
* Passing one but not the other is a programmer error; wrapper raises `TypeError` at call time. (Cheap consistency check; keeps the driver honest.)

**Invariant**: The wrapper's TTL / HEAD-commit / dirty-state staleness logic runs identically in both cases. Only the store instance and key differ.

## Relationships

```
run_sieve_audit(local_path)  [tools/audit.py]
    -> stores_config       (parsed .baseline.toml + framework TOML)
    -> stores_bundle       (resolve_stores(stores_config, repo_path))
        -> bundle.cache    (AuditCacheStore, lazily instantiated)
    -> write_audit_cache(
           local_path, results, summary, level, framework,
           store=bundle.cache,
           cache_key=(
               "audit-cache"                        # if stores_config.cache is None
               else sha256(abspath(repo_path))[:16] # if configured
           ),
       )
        -> [inside wrapper]
           envelope = build_envelope(results, summary, level, framework, local_path)
           store.write(cache_key, envelope)
```

Symmetric flow for `read_audit_cache` (called from remediate). Symmetric flow for `invalidate_audit_cache` (called from remediate on user-forced re-audit).
