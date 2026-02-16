## 1. Audit Cache Module

- [x] 1.1 Create `packages/darnit/src/darnit/core/audit_cache.py` with git helper functions (`_get_head_commit`, `_is_working_tree_dirty`) using subprocess calls to `git rev-parse HEAD` and `git status --porcelain`
- [x] 1.2 Implement `write_audit_cache(local_path, results, summary, level, framework)` — create `.darnit/` dir, build envelope with version/timestamp/commit/commit_dirty/level/framework/results/summary, atomic write via tempfile+rename
- [x] 1.3 Implement `read_audit_cache(local_path) -> dict | None` — read JSON, validate version field, compare commit hash and dirty state against current git state, return None on any mismatch/error/corruption
- [x] 1.4 Implement `invalidate_audit_cache(local_path)` — delete `.darnit/audit-cache.json` if exists, no-op if missing
- [x] 1.5 Add unit tests for `audit_cache` module: write/read round-trip, stale commit detection, dirty tree detection, corrupt JSON handling, non-git repo handling, unknown version handling, atomic write behavior

## 2. Wire Audit to Write Cache

- [x] 2.1 In `packages/darnit/src/darnit/tools/audit.py`, import `write_audit_cache` and call it at the end of `run_sieve_audit()` after results are assembled, before the return statement — pass `local_path`, `results`, `summary`, `level`, and framework name
- [x] 2.2 Wrap the cache write in try/except so cache failures never break the audit pipeline (log warning, continue)
- [x] 2.3 Add test: verify `run_sieve_audit()` produces a `.darnit/audit-cache.json` file with correct envelope structure after completing

## 3. Wire Builtin Remediate to Read Cache

- [x] 3.1 In `packages/darnit/src/darnit/server/tools/builtin_remediate.py`, import `read_audit_cache` and `invalidate_audit_cache`
- [x] 3.2 At the start of `builtin_remediate()`, call `read_audit_cache(local_path)` — if it returns valid results, extract `failed_ids = {r["id"] for r in cache["results"] if r["status"] == "FAIL"}` and skip the sieve audit loop
- [x] 3.3 If cache miss, keep existing behavior (run sieve audit, which now writes cache as side effect)
- [x] 3.4 After successful non-dry-run remediation, call `invalidate_audit_cache(local_path)` — skip invalidation for dry runs
- [x] 3.5 Add tests: cache hit skips audit, cache miss falls back to audit, PASS controls excluded from remediation plan, dry run preserves cache, non-dry-run invalidates cache

## 4. Wire Baseline Orchestrator to Read Cache

- [x] 4.1 In `packages/darnit-baseline/src/darnit_baseline/remediation/orchestrator.py`, import `read_audit_cache` and `invalidate_audit_cache`
- [x] 4.2 In `remediate_audit_findings()`, check cache before calling `run_sieve_audit()` — if valid, extract `non_passing_ids` from cached results (entries where `status != "PASS"`)
- [x] 4.3 After successful non-dry-run remediation, call `invalidate_audit_cache(local_path)`
- [x] 4.4 Add tests: orchestrator cache hit skips audit, orchestrator invalidates after applying changes

## 5. Spec Sync and Documentation

- [x] 5.1 Update `openspec/specs/framework-design/spec.md` with the new requirements from `specs/framework-design/spec.md` delta (audit writes cache, remediate reads cache, post-remediation invalidation)
- [x] 5.2 Run `uv run python scripts/validate_sync.py --verbose` and fix any sync issues
- [x] 5.3 Run `uv run python scripts/generate_docs.py` and commit any doc changes

## 6. Verification

- [x] 6.1 `uv run ruff check .` — no lint errors
- [x] 6.2 `uv run pytest tests/ --ignore=tests/integration/ -q` — all tests pass
- [x] 6.3 Manual end-to-end test: run audit via MCP tool, verify `.darnit/audit-cache.json` is created, then run remediate and verify it uses cache (no second audit in logs), verify PASS controls are skipped
