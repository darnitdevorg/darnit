# Implementation Plan: Audit-Cache Store Migration

**Branch**: `035-audit-cache-store-migration` | **Date**: 2026-09-02 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/035-audit-cache-store-migration/spec.md`

## Summary

Route `darnit.core.audit_cache` through feature 033's `AuditCacheStore` Protocol so `[stores.cache]` config in `.baseline.toml` actually redirects the on-disk cache location, and close the wiring gap where `tools/audit.py::run_sieve_audit` still calls `write_audit_cache(local_path, ...)` directly (ignoring `execution_context.stores.cache`). TTL / git-HEAD-commit / working-tree-dirty staleness logic stays in the wrapper (FR-005/006). Cache-key composition is `sha256(abspath(repo_path))[:16]` (FR-003 / clarify Q2). Zero-config default preserves today's path byte-for-byte at `$TMPDIR/darnit/<hash>/audit-cache.json` (FR-010 / clarify Q1). Invalidation writes an expired envelope so no new `AuditCacheStore.delete()` method is added (FR-009 / clarify Q3).

Three concrete changes:

1. **Wrapper (`core/audit_cache.py`)**: `write_audit_cache` / `read_audit_cache` / `invalidate_audit_cache` grow two optional kwargs -- `store: AuditCacheStore | None = None` and `cache_key: str | None = None`. External callers that pass neither get a wrapper-built default `FilesystemAuditCacheStore(root=<tempdir>/darnit/<hash>)` with `cache_key = "audit-cache"` (byte-for-byte legacy path). Driver callers pass both explicitly. TTL / HEAD-commit / dirty-state checks live in the wrapper for both paths. Invalidation writes an envelope with `timestamp = "1970-01-01T00:00:00Z"` so the next read misses on TTL.

2. **`stores/selection.py::resolve_stores`**: change the `cache` default factory's `cache_root` from `repo_path / ".darnit" / "audit-cache"` to `<tempdir>/darnit/<sha256(abspath(repo_path))[:16]>`. This is the "aligned to match" clause from clarify Q1: with the default factory now rooted at the per-repo tempdir, the driver's `cache_key = "audit-cache"` picks up the legacy path shape via the existing `<root>/<key>.json` composition in `FilesystemAuditCacheStore._path`. The previous `<repo>/.darnit/audit-cache/` default was never called at runtime (feature 033 shipped `bundle.cache` but never wired it in).

3. **`tools/audit.py::run_sieve_audit`**: replace the direct `write_audit_cache(local_path, ...)` call at line 669 with a store-aware invocation that picks the cache_key based on whether `stores_config.cache` is set:
   * `stores_config.cache is None` -> `cache_key = "audit-cache"` (default store already encodes repo identity in its root).
   * `stores_config.cache is not None` -> `cache_key = "<hash>"` (operator's configured root is shared across repos; per-repo isolation lives in the key).

All feature 033 constitutional guarantees hold: no new Protocol methods, no new runtime dep, `bundle.cache` stays lazy (only touched when the driver actually needs to write; SC-004 unchanged), and per-store `close()` in `close_all()` still runs only on instantiated stores.

## Technical Context

**Language/Version**: Python 3.11 / 3.12 (workspace targets)

**Primary Dependencies**: stdlib only. `hashlib`, `tempfile`, `subprocess` (all already imported by the wrapper). No new packages.

**Storage**: Filesystem via the feature 033 `AuditCacheStore` Protocol. Default backend is `FilesystemAuditCacheStore` rooted at the per-repo tempdir; operator can override to `local-fs` or `user-local` per feature 034.

**Testing**: pytest. Existing surface at `tests/darnit/test_audit_cache.py` anchors backward compat (FR-011); one new integration test at `tests/darnit/test_audit_cache_store_wiring.py` locks the driver-level flow (FR-013 / SC-001 / SC-006).

**Target Platform**: macOS + Linux fully supported. Windows path handling comes for free via `pathlib` + `tempfile.gettempdir()`; no OS-specific branching added.

**Project Type**: Library change inside `packages/darnit/`. No new package.

**Performance Goals**: N/A. One tempfile write per audit, one file read per remediate. Zero cost added to zero-config runs (default store is one lazy construction, identical to feature 033 today).

**Constraints**:
- No new runtime dependency (FR-012).
- No new `AuditCacheStore` Protocol methods (FR-009 workaround via write-expired).
- All existing `tests/darnit/test_audit_cache.py` MUST pass without modification, except any test that asserts the on-disk directory shape (which MAY be updated to match the new default -- but Q1's byte-for-byte answer means such tests shouldn't exist) OR asserts `write_audit_cache` raises on failure (which is intentionally relaxed by FR-007). Concretely: expect zero test-file diffs in the wrapper's own test module.
- Feature 033's `test_us2_zero_config.py` MUST continue to pass. That test asserts default construction of `bundle.cache`; changing the default `cache_root` inside `resolve_stores` is compatible with its assertions, but re-read it before the tasks phase to confirm.

**Scale/Scope**: 3 wrapper functions rewritten, 1 call site in `tools/audit.py` updated, 1 default-factory adjustment in `stores/selection.py`. ~150 lines of implementation net, ~200 lines of new/adjusted tests.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Status | Notes |
|---|---|---|
| I. Plugin Separation | PASS | All changes inside `packages/darnit/` (core + stores + tools). No cross-package imports added; no implementation package touched. |
| II. Conservative-by-Default | PASS with FR-007 note | FR-007 relaxes `write_audit_cache`'s previous "raises on tempfile failure" to feature 033 FR-011's "log warning, continue." Compatible with Principle II because a cache failure never makes an audit **report** incorrect -- it just makes the next remediate slower or forces the sieve loop to re-run. TTL + commit + dirty staleness (the correctness invariants) are preserved verbatim (FR-005, FR-006, SC-004, SC-005). |
| III. TOML-First Architecture | PASS | The whole feature is TOML-driven -- `[stores.cache]` is the surface. |
| IV. Never Guess User Values | N/A | Storage backends don't produce user-judgment values. |
| V. Sieve Pipeline Integrity | N/A | Cache is not a sieve pass; sits above the sieve loop. |

**Initial gate: PASS with an explicit FR-007 note.** No violations. Re-check after Phase 1 design.

## Project Structure

### Documentation (this feature)

```text
specs/035-audit-cache-store-migration/
|-- plan.md              # this file (/speckit-plan output)
|-- research.md          # Phase 0 output
|-- data-model.md        # Phase 1 output
|-- quickstart.md        # Phase 1 output
|-- contracts/
|   `-- audit-cache-wrapper.md  # Phase 1 output
`-- tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
packages/darnit/src/darnit/
|-- core/
|   `-- audit_cache.py            # REWRITTEN: wrapper over AuditCacheStore.
|                                 # Same public surface plus two optional
|                                 # kwargs; TTL/HEAD/dirty logic preserved.
|-- stores/
|   `-- selection.py              # Update default cache_root to
|                                 # <tempdir>/darnit/<hash> so bundle.cache's
|                                 # default backend matches legacy path shape.
`-- tools/
    `-- audit.py                  # Close wiring gap at line 669: route through
                                  # stores_bundle.cache with cache_key selected
                                  # by whether stores_config.cache is set.

tests/darnit/
|-- test_audit_cache.py                    # EXISTING: MUST pass unchanged
|                                          # (except any test asserting write
|                                          # raises on failure -- FR-007).
`-- test_audit_cache_store_wiring.py       # NEW: driver-level integration
                                           # locking FR-013 / SC-001 / SC-006.
```

**Structure decision**: single-package extension inside `packages/darnit/`. The wrapper stays in `core/audit_cache.py`; the store class stays in `stores/defaults/cache.py` (feature 033, no change to that file); the default-factory rooting is a one-line change in `stores/selection.py`; the driver-side wiring is a one-block change in `tools/audit.py`. No new files in `core/` or `stores/`.

## Complexity Tracking

No constitution violations to justify; table left empty.

| Violation | Why Needed | Simpler Alternative Rejected Because |
|-----------|------------|-------------------------------------|
| n/a       | n/a        | n/a                                  |

## Phase 0: Outline & Research

Three research items resolvable from source; no NEEDS CLARIFICATION markers survived clarify.

1. What's the exact wiring gap the driver has to close? Confirm `stores_bundle` is reachable at the cache-write call site in `run_sieve_audit`, and that `stores_config` (the raw config block, needed to distinguish default vs configured) is available at the same scope.
2. What does the pre-feature `test_audit_cache.py` actually assert? Enumerate every test to know which (if any) need adjustment under FR-007 / FR-011.
3. Does changing `resolve_stores`'s default `cache_root` break feature 033's `test_us2_zero_config.py`? If it asserts a specific path shape (`<repo>/.darnit/audit-cache/`), that assertion is now stale.

All three resolvable by grep + read. Consolidated in [research.md](research.md).

## Phase 1: Design & Contracts

### Data model

See [data-model.md](data-model.md). Four entities:

* **Cache envelope** -- unchanged from pre-feature `write_audit_cache`: `{version, timestamp, commit, commit_dirty, level, framework, results, summary}`.
* **Cache key** -- `sha256(abspath(repo_path))[:16]` when passed by the driver in the configured-store case. Literal `"audit-cache"` in the default-store case (the tempdir root already encodes repo identity).
* **Store-selection rule** (driver-side) -- if `stores_config.cache is None`, driver uses `cache_key = "audit-cache"`; else `cache_key = sha256(abspath(repo_path))[:16]`.
* **Expired envelope** for invalidation -- `{"version": 1, "timestamp": "1970-01-01T00:00:00Z", "commit": null, "commit_dirty": false, "level": 0, "framework": "", "results": [], "summary": {}}` such that the next `read_audit_cache` TTL check misses.

### Contracts

See [contracts/audit-cache-wrapper.md](contracts/audit-cache-wrapper.md). Enumerates:

* Public signatures of `write_audit_cache`, `read_audit_cache`, `invalidate_audit_cache` (backward-compat plus new optional `store` and `cache_key` kwargs).
* Store-selection rule per clarify Q1 (driver picks; wrapper is dumb).
* Cache-key composition per clarify Q2.
* Invalidation via expired-envelope per clarify Q3.
* TTL / commit / dirty staleness enforcement locations (wrapper, not store).
* Error semantics per FR-007 (writes are best-effort; documented change from pre-feature "raises on tempfile failure").

### Quickstart

See [quickstart.md](quickstart.md). Three worked examples:

1. **CI operator** configures `[stores.cache] backend = "local-fs" root = "$RUNNER_CACHE_DIR/darnit"`, runs an audit twice, sees a cache hit on run 2 because the runner restored `$RUNNER_CACHE_DIR` between jobs. This is the story that was broken pre-feature and works post-feature.
2. **Zero-config user** upgrades darnit; their audit lands its cache at the same `$TMPDIR/darnit/<hash>/audit-cache.json` as before; nothing changes on disk.
3. **Multi-repo operator** runs audits against two repos with the same shared `[stores.cache] root = "..."`; cache files are `<hash1>.json` and `<hash2>.json` under that root, no collision.

### Agent context update

CLAUDE.md's `<!-- SPECKIT START -->` marker currently points at an older feature's plan. Update to point at this feature's plan at end of Phase 1.

## Constitution re-check (post-design)

| Principle | Status |
|---|---|
| I. Plugin Separation | PASS -- three files touched, all inside `packages/darnit/`, no cross-package imports. |
| II. Conservative-by-Default | PASS with FR-007 note -- documented in Constitution Check above and repeated in the contracts doc. |
| III. TOML-First Architecture | PASS |
| IV. Never Guess User Values | N/A |
| V. Sieve Pipeline Integrity | N/A |

**Final gate: PASS.** Ready for `/speckit-tasks`.
