# Feature Specification: Audit-Cache Store Migration

**Feature Branch**: `035-audit-cache-store-migration`

**Created**: 2026-09-02

**Status**: Draft

**Input**: User description: "Migrate darnit.core.audit_cache to route through the feature-033 AuditCacheStore protocol. Today write_audit_cache/read_audit_cache use their own path scheme ($TMPDIR/darnit/<sha256(repo_path)[:16]>/audit-cache.json) that ignores [stores.cache] TOML config. The migration should make [stores.cache] backend/root override the path, preserve TTL and git-commit + dirty-state staleness logic in the wrapper, and pick a sensible default location. Also close the wiring gap so tools/audit.py routes cache writes through bundle.cache rather than calling write_audit_cache directly."

## Clarifications

### Session 2026-09-02

- Q: Where does the cache land when the operator has not configured `[stores.cache]`? → A: Preserve today's default -- `$TMPDIR/darnit/<sha256(repo_path)[:16]>/audit-cache.json`. Zero-config path unchanged; upgrade is transparent. Feature 033's `FilesystemAuditCacheStore` default is aligned to match this scheme (its previous `<repo>/.darnit/audit-cache/` default was an unused artifact -- `resolve_stores` still returned a `FilesystemAuditCacheStore` instance but the audit driver never called it). The `[stores.cache] backend = "local-fs" root = ".darnit/audit-cache"` config still works for operators who prefer the in-repo layout.
- Q: How is the `cache_key` composed for `bundle.cache.read/write` calls? → A: `sha256(abspath(repo_path))[:16]`. Identical to the hash the pre-feature `_get_cache_dir` used for the directory prefix, so per-repo isolation is preserved verbatim under a shared `root`. No framework/level in the key; those are embedded in the envelope, matching today's overwrite-on-mismatch behavior. Filename on disk is `<key>.json` per feature 033's `FilesystemAuditCacheStore` layout.
- Q: How does `invalidate_audit_cache` clear the entry, given `AuditCacheStore` has no `delete` method? → A: Write an expired envelope (timestamp `1970-01-01T00:00:00Z`). The next `read_audit_cache` sees the ancient timestamp and returns miss via the existing TTL check. Zero Protocol change; backwards-compatible with existing store implementations and any future ones (Postgres, S3, etc.). The cache file remains on disk until the next successful write overwrites it -- acceptable because the current cache path is operator-invisible tempdir anyway.

## Context

Feature 033 (PR #396) landed the `AuditCacheStore` Protocol and the `FilesystemAuditCacheStore` default. Feature 034 (PR #412) added the `local-fs` and `user-local` backends. Both features gave operators the vocabulary to configure `[stores.cache]` in `.baseline.toml`. The catch: **nothing wires that configuration into the actual audit-cache read/write path today.**

The truth on disk (verified by inspection of `packages/darnit/src/darnit/core/audit_cache.py` and `packages/darnit/src/darnit/tools/audit.py`):

- `tools/audit.py::run_sieve_audit` calls `core.audit_cache.write_audit_cache(local_path, ...)` directly after the sieve loop.
- `core/audit_cache.py::_get_cache_dir(local_path)` computes `$TMPDIR/darnit/<sha256(repo_path)[:16]>/audit-cache.json`. No store, no `[stores.cache]` awareness.
- `bundle.cache` (the `AuditCacheStore` from feature 033's `resolve_stores`) IS instantiated per audit run but never read from or written to by the driver.
- An operator who writes `[stores.cache] backend = "local-fs" root = "/mnt/x"` in `.baseline.toml` today gets ZERO effect on where their cache goes.

Feature 033 explicitly deferred this migration (T026 in its tasks.md); this feature closes the loop. The complexity is not the plumbing (small) but the default-location question: today's default is system tempdir per-repo-hash; feature 033's `FilesystemAuditCacheStore` expects `<repo>/.darnit/audit-cache/`; those are different places and the choice is user-visible.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Operator configures `[stores.cache]` and the cache actually moves (Priority: P1)

An operator running a CI pipeline sets:

```toml
[stores.cache]
backend = "local-fs"
root    = "$RUNNER_CACHE_DIR/darnit"
```

...and expects the audit-cache file to land under `$RUNNER_CACHE_DIR/darnit/`, not in a hashed system tempdir. Second-run cache hits work because the runner restored `$RUNNER_CACHE_DIR` between jobs.

**Why this priority**: This is the concrete gap operators are hitting today. The vocabulary shipped in features 033 and 034 doesn't do anything for cache until this lands. Highest user-visible impact.

**Independent Test**: Configure `[stores.cache] backend = "local-fs" root = "<tmp_path>/cache"`, run an audit twice against the same commit + clean tree. Verify: (a) `<tmp_path>/cache/<something>.json` exists after the first run; (b) the second run's cache read hits (audit skips the sieve loop); (c) no cache file lands under `$TMPDIR/darnit/`.

**Acceptance Scenarios**:

1. **Given** `[stores.cache] backend = "local-fs" root = "/tmp/x/cache"` and no prior cache, **When** the audit runs, **Then** the cache file lands under `/tmp/x/cache/` and NOT under `$TMPDIR/darnit/`.
2. **Given** the same config with a fresh cache miss on run 1, **When** run 2 executes against the same commit + working-tree state, **Then** the cache read HITS and the sieve loop is skipped.
3. **Given** the same config but git HEAD changed between runs, **When** run 2 executes, **Then** the cache read MISSES (staleness detection preserved) and the sieve loop runs.
4. **Given** `[stores.cache] backend = "user-local"`, **When** the audit runs on Linux with default XDG paths, **Then** the cache file lands under `~/.cache/darnit/audit-cache/`.

---

### User Story 2 - Zero-config default is documented and predictable (Priority: P1)

An operator who never touches `.baseline.toml` gets a deterministic cache location. Cross-audit-run behavior (hit/miss) is unchanged from the current implementation. If the default location changes as part of this migration, the release notes call it out.

**Why this priority**: Even users who never configure `[stores.cache]` are affected because the default path is a decision this feature MUST make. Getting it wrong (surprise-moving cache without documentation) breaks user trust.

**Independent Test**: Run an audit with no `[stores.*]` block. Locate the on-disk cache file. Confirm the path matches the documented default AND is stable (same path on repeat runs).

**Acceptance Scenarios**:

1. **Given** no `[stores.*]` block, **When** the audit runs, **Then** the cache file lands at the documented default location.
2. **Given** two successive audits with no config change, **When** they both run, **Then** the cache location is identical (no per-audit variability).
3. **Given** an operator upgrades from a pre-feature-035 darnit to a post-feature-035 darnit and runs the same audit, **When** the audit runs, **Then** the operator can find the release-notes entry naming the default cache location (whether unchanged or moved).

---

### User Story 3 - TTL and staleness detection preserved (Priority: P1)

Existing cache-invalidation semantics MUST work through the store: 3600-second TTL, git HEAD commit hash change invalidates, and working-tree dirty state change invalidates. These live in the wrapper (`core/audit_cache.py`), NOT in the store; the store is a plain read-through/write-through KV.

**Why this priority**: A cache with correctness gaps (stale hits) is worse than no cache. The existing invalidation logic is trusted; this feature MUST preserve it byte-for-byte.

**Independent Test**: Reuse the existing test surface at `tests/darnit/test_audit_cache.py` (or equivalent). All existing tests MUST pass unchanged. Add one new test that exercises invalidation over a `local-fs` cache backend to prove the wrapper still gates the store's raw reads.

**Acceptance Scenarios**:

1. **Given** a cache write followed by a read within 3600 seconds, no git changes, **When** the read runs, **Then** it HITS.
2. **Given** a cache write, then `git commit --allow-empty` (HEAD changes), **When** a subsequent read runs, **Then** it MISSES.
3. **Given** a cache write with clean tree, then dirtying the tree, **When** a subsequent read runs, **Then** it MISSES.
4. **Given** a cache write more than 3600 seconds ago, **When** a read runs, **Then** it MISSES.
5. Same acceptance scenarios (1)-(4) hold when the store is `local-fs` with an explicit `root`, not just the default backend.

---

### User Story 4 - Public API of `write_audit_cache` / `read_audit_cache` preserved (Priority: P2)

Any code that today calls `from darnit.core.audit_cache import write_audit_cache, read_audit_cache, invalidate_audit_cache` continues to work with the same call signatures. The functions become thin wrappers over `bundle.cache.read` / `.write` but their public surface is unchanged.

**Why this priority**: Backward compatibility. External consumers (tests, other darnit subsystems, third-party tools) may import these names.

**Independent Test**: `grep -rn "from darnit.core.audit_cache import"` before and after the migration produces the same import list. Every consumer's tests continue to pass.

**Acceptance Scenarios**:

1. **Given** existing test `tests/darnit/test_audit_cache.py::*`, **When** it runs against the migrated implementation, **Then** it passes without modification.
2. **Given** the darnit-baseline package's use of the cache (if any), **When** it runs, **Then** its behavior is unchanged.

---

### Edge Cases

- **First-run miss**: `bundle.cache.read` returns `None` for a nonexistent key. `read_audit_cache` translates that to "cache miss" cleanly (already the pre-feature behavior).
- **Concurrent audits of the same repo** with the same configured `root`: two processes racing on the same cache_key. Cache is best-effort per feature 033 FR-011; the tempfile-then-rename in `FilesystemAuditCacheStore` handles this without corruption, but the "loser" race silently overwrites the "winner". Acceptable per the best-effort contract.
- **`bundle.cache` swallows write errors** (FR-011). Legacy `write_audit_cache` did not — it raised on tempfile / rename failures. The migration MUST reconcile: does the wrapper adopt best-effort semantics, or does it re-surface errors from the store? Chosen behavior: wrapper adopts best-effort. Existing writes that raised now log-and-continue. Existing callers that caught the exception now see silent success (with a warning log).
- **`stores.cache` selection fails at `resolve_stores` time** (`StoreNotInstalled`, `StoreProtocolMismatch`): the audit tool already dies at startup before the sieve loop begins. No change here; feature 033's fail-fast contract holds.
- **Legacy per-repo-hash cache dir left over**: if this feature changes the default location, old `$TMPDIR/darnit/<hash>/` directories are orphaned. Cleanup is out of scope; document that operators can remove them safely.
- **Cache-cache-key collision across repos**: today's key is a fixed filename `audit-cache.json` under a per-repo-hash directory. Post-migration, if all repos share one `root` (US1 CI case) the store needs a per-repo cache_key so they don't overwrite each other. The wrapper MUST compose a cache_key that includes the repo identity.

## Requirements *(mandatory)*

### Functional Requirements

- **FR-001**: The audit driver (`tools/audit.py::run_sieve_audit`) MUST route cache writes through `bundle.cache.write(cache_key, envelope)` -- NOT through a direct call to `core.audit_cache.write_audit_cache(local_path, ...)`.
- **FR-002**: `core.audit_cache.write_audit_cache` and `core.audit_cache.read_audit_cache` MUST become thin wrappers over the store. They accept a `store: AuditCacheStore` parameter (with backward-compat default from a helper that resolves it lazily if not passed). Their public call signatures do NOT otherwise change.
- **FR-003**: The cache_key composed by the wrapper MUST be `sha256(abspath(repo_path))[:16]` -- identical to the hash the pre-feature `_get_cache_dir` used for the tempdir prefix. This guarantees per-repo isolation under a shared `root` and preserves stability across runs on the same repo path. Framework and level are NOT included in the key; they remain in the envelope, matching today's overwrite-on-mismatch behavior.
- **FR-004**: When an operator sets `[stores.cache] backend = "local-fs" root = "..."`, cache writes MUST land under that root and reads MUST see them. Verified end-to-end via an audit, not just at the store layer.
- **FR-005**: TTL enforcement (default 3600 seconds) MUST live in the wrapper. The store MUST NOT know about TTL. Existing TTL semantics MUST be preserved verbatim.
- **FR-006**: Git-HEAD-commit and working-tree-dirty-state staleness detection MUST live in the wrapper. Existing detection logic MUST be preserved verbatim.
- **FR-007**: `bundle.cache.write` failures MUST NOT propagate to the audit-run's exit code. The legacy `write_audit_cache` behavior of raising on tempfile failure is REPLACED with feature 033 FR-011's best-effort semantics: log a warning, continue. This is a documented behavior change.
- **FR-008**: `bundle.cache.read` returning `None` MUST be treated as cache miss (audit runs fresh). No change from today.
- **FR-009**: The public function `invalidate_audit_cache(local_path)` MUST continue to work as `bundle.cache.write(cache_key, <expired-envelope>)`. The expired envelope carries `timestamp = "1970-01-01T00:00:00Z"` so the next `read_audit_cache` misses via the existing TTL check. No `AuditCacheStore.delete()` method is added; the Protocol surface is unchanged.
- **FR-010**: The default cache location when no `[stores.cache]` block is configured MUST be `$TMPDIR/darnit/<sha256(repo_path)[:16]>/audit-cache.json` -- byte-for-byte identical to today's path. Release notes may mention that the wrapper is now store-routed under the hood, but no on-disk behavior change lands for zero-config users. `FilesystemAuditCacheStore`'s in-code default constructor arg is updated in this feature's PR to match; the previous `<repo>/.darnit/audit-cache/` value was an unused-in-practice artifact of feature 033's `resolve_stores`.
- **FR-011**: All existing tests under `tests/darnit/core/test_audit_cache.py` (and the equivalent test surface for `write_audit_cache` / `read_audit_cache`) MUST pass without modification, except tests that fall into one of these three intentionally-relaxed categories:
  1. Tests asserting the on-disk path shape MAY be updated to match the new default (if the default location changes).
  2. Tests asserting `write_audit_cache` raises on tempfile / rename failure MUST be updated to expect no-raise (intentionally relaxed by FR-007).
  3. Tests asserting `invalidate_audit_cache` removes the on-disk cache file MUST be updated to check `read_audit_cache(...) is None` instead (intentionally relaxed by FR-009's write-expired-envelope semantics; the file remains on disk with an expired timestamp).
- **FR-012**: The wrapper MUST NOT introduce any new runtime dependency. It uses only the existing `darnit.stores` surface + `subprocess` (already used) for git introspection.
- **FR-013**: A test MUST exercise the end-to-end `[stores.cache] backend = "local-fs" root = "..."` flow via a real audit invocation (or a driver-level fixture), not just the store layer in isolation. This locks the wiring gap fix.
- **FR-014**: The `bundle.cache` property from `resolve_stores` is lazy-instantiated (per feature 033 SC-004). An audit that never touches the cache -- e.g., one with `stop_on_llm=True` and a first-time run that never gets to `write_audit_cache` -- MUST NOT construct the cache backend. The migration preserves this invariant.

### Key Entities

- **`bundle.cache`**: the `AuditCacheStore` instance the wrapper reads/writes through. Resolved once per audit run from `[stores.cache]` config; `FilesystemAuditCacheStore` when unset.
- **`cache_key`**: string uniquely identifying (repo, framework, level) so two different audit shapes against the same repo, and two different repos against the same `root`, don't collide. Composition rule established in this feature (see Clarifications).
- **Cache envelope**: existing JSON shape at `core/audit_cache.py` -- version, timestamp, commit, commit_dirty, level, framework, results, summary. Unchanged by this feature.
- **Default cache root**: the path where cache lands when no `[stores.cache]` is set. Subject to a clarify question.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: An operator configuring `[stores.cache] backend = "local-fs" root = "<X>"` in `.baseline.toml`, running an audit twice back-to-back with no code change between runs, sees a cache hit on run 2 AND the cache file located under `<X>`. Verified by a driver-level integration test.
- **SC-002**: An operator running with no `[stores.*]` block sees the cache land at the documented default location. Verified by a test that captures the actual write path.
- **SC-003**: All existing `tests/darnit/test_audit_cache.py` tests pass on the migrated implementation, except the one test (if any) documented in the release notes as being intentionally relaxed by FR-007's best-effort semantics.
- **SC-004**: A repository whose git HEAD changes between two consecutive audits MUST see a cache miss on the second audit. Verified by an end-to-end test that mutates HEAD between reads.
- **SC-005**: A repository whose working tree becomes dirty between two audits MUST see a cache miss on the second audit.
- **SC-006**: Two different repos configured against the same `[stores.cache] root = "<X>"` MUST NOT overwrite each other's cache files. Verified by a test that runs two audits with distinct `repo_path` values against a shared root.
- **SC-007**: A single `cache.write` failure (e.g., disk full at the target root) MUST NOT propagate to the audit's exit code. The audit completes successfully; a warning is logged. Verified by fault-injection unit test.
- **SC-008**: No test module named `tests/darnit/stores/test_us2_zero_config.py` (feature 033's zero-config witness) fails because of this migration. If a zero-config default location change is chosen (per Clarifications), that test is updated in this feature's PR with a documented reason.
- **SC-009**: The migration lands within the file-scope boundary: `packages/darnit/src/darnit/core/audit_cache.py`, `packages/darnit/src/darnit/tools/audit.py`, `packages/darnit/src/darnit/stores/defaults/cache.py` (if the default location change requires updating `FilesystemAuditCacheStore`'s init default), `tests/darnit/test_audit_cache.py`, and one new integration test file. No plugin-package or implementation-package modifications.

## Assumptions

- The store instance for the current audit is available to the wrapper via the `execution_context.stores` bundle already threaded through `tools/audit.py` in feature 033 T023. The wrapper does NOT need to re-run `resolve_stores` itself.
- `bundle.cache.write` swallowing failures per the Protocol is acceptable operator behavior. Loud failure was a nice-to-have but not a documented contract of the pre-feature `write_audit_cache`.
- The `AuditCacheStore` Protocol does NOT currently expose a `delete(key)` method. Clarify Q3 declined adding one; invalidation uses a write-expired-envelope workaround. The Protocol surface remains unchanged.
- Feature 034 (#412) is already merged before this feature ships. If it isn't, this feature's PR body notes the dependency.
- The default cache location's dependency on `repo_path` (per-repo isolation) is a core requirement, not a nice-to-have. Operators should be able to run darnit on multiple repos from the same machine without cache poisoning.

## Dependencies

- Feature 033 (PR #396, merged): the `AuditCacheStore` Protocol, `FilesystemAuditCacheStore`, `_StoreBundle`, `resolve_stores`, `execution_context.stores`.
- Feature 034 (PR #412, review pending): the `local-fs` and `user-local` backends. This feature's US1 depends on `local-fs` being routable end-to-end.
- No external service dependencies.

## Out of Scope

- **Audit-cache format change**. The JSON envelope shape (version, timestamp, commit, commit_dirty, level, framework, results, summary) is unchanged. Adding fields is a separate spec.
- **Cache retention / rotation / eviction policy** beyond the existing TTL. Operators manage cleanup of their configured `root`.
- **A new `AuditCacheStore.delete(key)` method**. Clarify resolved: invalidation uses a write-expired-envelope workaround (spec Q3), so the Protocol stays unchanged.
- **Migration of old cache files** from the current `$TMPDIR/darnit/<hash>/` layout to whatever the new default is. Operators can `rm -rf` those manually.
- **Wiring of `bundle.attestation` and `bundle.report`** into the audit driver. Those are separate follow-ups (from the same audit driver but different call sites).
- **Cross-process cache locking**. Two darnit processes writing to the same cache_key at the same time is the store's problem to solve via tempfile-then-rename; no new locking layer.
