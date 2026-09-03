# Phase 0: Research -- Audit-Cache Store Migration

**Feature**: 035-audit-cache-store-migration | **Date**: 2026-09-02

All three research items resolved by direct source inspection. No NEEDS CLARIFICATION markers survived the /speckit-clarify pass.

## R-001: Wiring gap in `run_sieve_audit`

**Question**: Confirm `stores_bundle` and `stores_config` are both reachable at the cache-write call site in `packages/darnit/src/darnit/tools/audit.py`.

**Decision**: Both are reachable. The driver already computes them at `audit.py:562-564`:

```python
stores_config = _load_merged_stores(local_path, resolved_fw)
stores_bundle = resolve_stores(stores_config, repo_path=Path(local_path))
execution_context.stores = stores_bundle
```

...and the direct cache-write call sits at `audit.py:667-671`, well inside the scope where both bindings are still live. The wiring gap is a purely lexical omission: the current code imports `write_audit_cache` from `core.audit_cache` and calls it with `local_path` only, ignoring the bundle that's already sitting one scope up.

**Rationale**: No plumbing work needed. Reuse the two bindings that feature 033 already set up. `stores_config.cache` (may be `None`) is the signal for "operator has configured a cache backend"; `stores_bundle.cache` (never `None`; lazily instantiated) is the store instance we call `.read` / `.write` on.

**Alternatives considered**: Threading a fifth parameter into `write_audit_cache` from the outside (e.g., `stores_config`). Rejected because the wrapper doesn't need to know the config, only the store instance and the key.

## R-002: Existing test surface at `tests/darnit/core/test_audit_cache.py`

**Question**: Enumerate every existing assertion so we know which tests need adjustment vs which pass unchanged.

**Decision**: 30+ tests across 10 test classes. Under Q1's "byte-for-byte identical default path" answer, the vast majority pass unmodified. Two tests need explicit adjustment:

1. **`TestAtomicWrite::test_no_partial_file_on_error`** (line 280-293) asserts `write_audit_cache` raises `OSError` when `json.dump` fails. FR-007 relaxes this to "log warning, continue." Adjustment: replace `with pytest.raises(OSError):` with a call that must NOT raise, and keep the "no partial file left behind" assertion. The "no partial file" invariant is now enforced by `FilesystemAuditCacheStore.write`'s tempfile-then-rename + tempfile-cleanup logic.

2. **`TestInvalidateCache::test_invalidate_existing`** (line 256-262) asserts `cache_path.exists()` is False after `invalidate_audit_cache`. Under Q3's write-expired-envelope semantics, the file still exists but its timestamp is `1970-01-01T00:00:00Z`. Adjustment: replace with `assert read_audit_cache(str(temp_git_repo)) is None` -- the observable behavior ("the next read misses") is what actually matters to callers.

All other tests use `_get_cache_dir(...)` to compute the expected file path; that helper remains and continues to return `$TMPDIR/darnit/<hash>/`, so those tests remain valid under Q1's byte-for-byte answer.

**Rationale**: The spec's FR-011 already documents "test that asserts write raises on failure" as an intentional exception. R-002 identifies a second exception (`test_invalidate_existing`) that FR-011 doesn't currently name. Recommendation: extend FR-011's exception list at tasks-phase time so the task-list reader knows to touch both tests. (Not treating this as a spec re-clarify -- Q3's answer explicitly said "The cache file remains on disk until the next successful write overwrites it," which is the same behavior change surfacing as a test adjustment.)

**Alternatives considered**: Instead of writing an expired envelope, have `invalidate_audit_cache` seek out the underlying store instance and call a hypothetical `.delete(key)` method. Rejected because Q3 explicitly chose the write-expired approach to avoid adding a Protocol method.

## R-003: Feature 033's `test_us2_zero_config.py::test_filesystem_defaults_use_canonical_darnit_paths`

**Question**: Does changing `resolve_stores`'s default `cache_root` break this test?

**Decision**: YES, it breaks one assertion. Line 76 asserts:

```python
assert bundle.cache._root == tmp_path / ".darnit" / "audit-cache"
```

Post-migration, the default `cache_root` becomes `<system tempdir>/darnit/<sha256(str(tmp_path.resolve()))[:16]>`, NOT `<repo>/.darnit/audit-cache`. Adjustment: the assertion becomes something like:

```python
import hashlib
import tempfile
from pathlib import Path

expected_hash = hashlib.sha256(str(tmp_path.resolve()).encode()).hexdigest()[:16]
expected_root = Path(tempfile.gettempdir()) / "darnit" / expected_hash
assert bundle.cache._root == expected_root
```

The other two assertions in the same test (`bundle.attestation._root == tmp_path / ".darnit" / "attestations"` and `bundle.report._root == tmp_path / ".darnit" / "reports"`) are unchanged; the migration only rebases the cache default.

**Rationale**: This is exactly what spec SC-008 covers: "If a zero-config default location change is chosen (per Clarifications), that test is updated in this feature's PR with a documented reason." Q1 chose "preserve today's default at $TMPDIR/darnit/<hash>" AND "FilesystemAuditCacheStore default aligned to match this scheme," so this test adjustment is required and pre-authorized.

The `test_none_config_yields_filesystem_defaults_for_all_four` and `test_no_plugin_backend_constructed_under_zero_config` tests in the same file continue to pass unchanged -- they only assert the type/lazy behavior, not the specific root path.

**Alternatives considered**: Keep the `<repo>/.darnit/audit-cache` default in `resolve_stores` and have the wrapper skip `bundle.cache` for zero-config runs (constructing its own tempdir store instead). Rejected because it forks the code (wrapper decides "use bundle vs build own" on a config-driven condition), duplicates path composition logic between the wrapper and the store, and makes future audit-driver features that touch `bundle.cache` inconsistent with what `write_audit_cache` does.

## Summary

| ID | Item | Impact | Resolution |
|----|------|--------|------------|
| R-001 | Wiring gap in `run_sieve_audit` | 3-line change at `audit.py:667` | Reuse `stores_bundle.cache` + pick key by `stores_config.cache is None` |
| R-002 | `test_audit_cache.py` adjustments | 2 tests (out of 30+) | `test_no_partial_file_on_error`: no raise. `test_invalidate_existing`: check read result, not file existence. |
| R-003 | `test_us2_zero_config.py` adjustment | 1 assertion (line 76) | Compute expected root as `<tempdir>/darnit/<sha256(str(tmp_path.resolve()))[:16]>` |

All items resolvable in-implementation; no unknowns block Phase 1.
