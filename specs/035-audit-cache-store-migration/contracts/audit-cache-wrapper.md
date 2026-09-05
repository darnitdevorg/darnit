# Contract: `darnit.core.audit_cache` wrapper (post-feature-035)

**Feature**: 035-audit-cache-store-migration

This contract enumerates the observable behavior every consumer of `write_audit_cache` / `read_audit_cache` / `invalidate_audit_cache` may rely on after this feature ships. Anything not stated here is unspecified.

## 1. Public signatures

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

### 1.1 Backward-compat call form

An external caller who invokes any of these three functions passing only positional args (no `store=`, no `cache_key=`) MUST observe the same on-disk cache path as the pre-feature implementation:

```text
<tempdir>/darnit/<sha256(abspath(local_path))[:16]>/audit-cache.json
```

...where `<tempdir>` is `tempfile.gettempdir()`. Byte-for-byte identical to today's `_get_cache_dir(...) / CACHE_FILENAME`.

### 1.2 Driver call form

`tools/audit.py::run_sieve_audit` MUST call the wrapper with both `store=` and `cache_key=` provided. See section 4.

### 1.3 Partial-kwarg call is an error

If exactly one of `store` and `cache_key` is `None`, the wrapper raises `TypeError("store and cache_key must be passed together")`. This catches driver bugs at call time rather than silently defaulting.

## 2. Cache-key composition rule

* **Default-store case**: literal string `"audit-cache"`. The store's root already encodes repo identity via the wrapper's default-store construction. Final on-disk path: `<tempdir>/darnit/<hash>/audit-cache.json`.
* **Configured-store case**: `sha256(abspath(local_path).encode()).hexdigest()[:16]`. The store's root is operator-picked and may be shared across repos; per-repo isolation lives in the key. Final on-disk path: `<operator_root>/<hash>.json`.

## 3. Staleness enforcement (wrapper, not store)

The wrapper MUST enforce these staleness checks on read, in this order. First `None`-returning check short-circuits.

1. **Missing / corrupt / non-dict**: `store.read(cache_key)` returned `None`, or the returned value isn't a `dict`. Wrapper returns `None`.
2. **Version check**: envelope's `version` is missing, not an `int`, or greater than `CACHE_VERSION` (currently 1). Wrapper returns `None`.
3. **TTL**: envelope's `timestamp` is missing, unparseable, or more than `ttl_seconds` in the past (default 3600). Wrapper returns `None`.
4. **Null commit**: envelope's `commit` is `None` (means it was written in a non-git repo -- treat as always stale to force a fresh audit). Wrapper returns `None`.
5. **Commit mismatch**: envelope's `commit` differs from the current git HEAD of `local_path`. Wrapper returns `None`.
6. **Dirty-state mismatch**: envelope's `commit_dirty` differs from the current working-tree dirty state. Wrapper returns `None`.

If all checks pass, wrapper returns the full envelope dict. Callers may inspect `envelope["results"]`, `envelope["summary"]`, etc.

**Store MUST NOT know about TTL, commit, or dirty state.** Those are wrapper concerns. The store is a plain read-through / write-through KV over `dict[str, Any]`.

## 4. Driver call-site rule (`tools/audit.py`)

`run_sieve_audit` MUST call `write_audit_cache` (and mirror for `read_audit_cache` if a read call site is added later) with both `store` and `cache_key` derived from local scope:

```python
if stores_config is None or stores_config.cache is None:
    cache_key = "audit-cache"
else:
    cache_key = hashlib.sha256(
        str(Path(local_path).resolve()).encode()
    ).hexdigest()[:16]

write_audit_cache(
    local_path, all_results, summary, level, resolved_fw or "",
    store=stores_bundle.cache,
    cache_key=cache_key,
)
```

The `stores_bundle.cache` property fires the lazy factory on first access; feature 033's `is_instantiated("cache")` becomes True after this call. Feature 033 SC-004 (no ghost construction) is preserved for any audit path that never reaches this line -- e.g., early-exit failure modes.

## 5. Error semantics

### 5.1 `write_audit_cache`

MUST NOT raise on backend failure. If `store.write(cache_key, envelope)` raises (which the default `FilesystemAuditCacheStore` avoids -- it catches `OSError` internally and logs a warning), the wrapper catches and logs at warning level, then returns normally.

**Change from pre-feature**: the previous implementation raised `OSError` on `tempfile.mkstemp` / `os.replace` failure. Post-feature 035, the audit run completes successfully even when the cache write fails. This is documented in the release notes as an intentional relaxation; the fault-injection test at `TestAtomicWrite::test_no_partial_file_on_error` is updated to expect no-raise.

### 5.2 `read_audit_cache`

MUST NOT raise on any failure mode (missing file, corrupt JSON, unreadable, non-dict, git command failure, etc.). Returns `None` for all failure modes.

### 5.3 `invalidate_audit_cache`

MUST NOT raise. Writes an expired-envelope via `store.write(cache_key, EXPIRED_ENVELOPE)`. If that write fails, logs a warning and returns. Subsequent reads on a still-fresh cache file will fail the TTL check anyway once the expired envelope lands; if the write itself failed, subsequent reads may succeed on the pre-invalidation cache -- caller MUST NOT rely on invalidation being observable in the face of write failure.

## 6. Concurrency

Two darnit processes writing to the same `cache_key` at the same time is the store's problem. `FilesystemAuditCacheStore.write` uses tempfile-then-rename for atomicity; the "loser" of the race silently overwrites the "winner." Acceptable per feature 033 FR-011 / best-effort contract.

The wrapper itself is stateless -- no locks, no shared mutable state.

## 7. Test surface

Tests validating this contract live at:

* `tests/darnit/core/test_audit_cache.py` (existing; 2 tests adjusted per research.md R-002).
* `tests/darnit/test_audit_cache_store_wiring.py` (new; locks driver-level integration per SC-001 / SC-006).
* `tests/darnit/stores/test_us2_zero_config.py::test_filesystem_defaults_use_canonical_darnit_paths` (feature 033 test; 1 assertion updated per research.md R-003).

No plugin-package or implementation-package tests touched.
