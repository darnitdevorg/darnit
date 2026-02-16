## Context

The MCP tool pipeline flows: `get_pending_context` → `confirm_project_context` → `audit` → `remediate`. Each step writes durable state that subsequent steps read — except audit. Audit results evaporate after the tool returns, so `builtin_remediate` re-runs the entire sieve pipeline from scratch to figure out what failed.

Currently:
- `builtin_audit` calls `run_sieve_audit()`, which returns `(results: list[dict], summary: dict[str, int])`. These are formatted into markdown and returned. The structured data is discarded.
- `builtin_remediate` re-runs `SieveOrchestrator.verify()` on every control to collect `failed_ids: set[str]`, then filters remediations to only those IDs.
- `remediate_audit_findings` (baseline orchestrator) also re-runs the full audit to collect `non_passing_ids`.

The `results` list from `run_sieve_audit()` is already JSON-serializable — each entry comes from `SieveResult.to_legacy_dict()` which produces plain dicts with string/int/float/list values.

## Goals / Non-Goals

**Goals:**
- Audit results persist as pipeline state so remediate can consume them without re-running the sieve
- PASS controls are automatically excluded from remediation via the cached results
- Backward compatible: if no cache exists, remediate falls back to running its own audit
- Cache invalidation is automatic — stale results don't cause wrong remediations

**Non-Goals:**
- Long-term audit history or trend tracking — this is ephemeral cache, not an audit log
- Changing the MCP tool parameter signatures — no new required parameters for LLMs to pass
- Caching within a single audit run (the `SieveOrchestrator._shared_cache` already handles that)

## Decisions

### 1. Cache location: `.darnit/audit-cache.json`

**Decision:** New `.darnit/` directory for framework ephemeral state, separate from `.project/` which is user-facing project configuration.

**Rationale:** `.project/project.yaml` and `.project/darnit.yaml` are committed to version control and represent project identity. Audit cache is ephemeral, machine-specific, and should be gitignored. Mixing cache with config in `.project/` blurs the boundary.

**Alternatives considered:**
- `.project/audit-cache.json` — rejected: mixes ephemeral cache with persistent config that's committed to git
- Temp directory (`/tmp/`) — rejected: not discoverable, cleared on reboot, harder to share across tool calls
- MCP tool parameter — rejected: pushes complexity onto the LLM, requires the model to shuttle data between calls

**`.gitignore` entry:** `.darnit/` should be added to `.gitignore` templates and documented as framework cache.

### 2. Cache format: JSON with metadata envelope

**Decision:** Store the raw `results` list and `summary` dict from `run_sieve_audit()` inside a metadata envelope:

```json
{
  "version": 1,
  "timestamp": "2026-02-16T12:00:00Z",
  "commit": "abc1234",
  "level": 3,
  "framework": "openssf-baseline",
  "local_path": "/path/to/repo",
  "results": [ ... ],
  "summary": { "PASS": 23, "FAIL": 4, "WARN": 35 }
}
```

**Rationale:** The `results` list is already JSON-serializable (comes from `SieveResult.to_legacy_dict()`). JSON is fast to read/write, human-inspectable, and doesn't require new dependencies. The envelope provides staleness metadata.

### 3. Staleness detection: git commit hash

**Decision:** Cache is valid if the current `HEAD` commit matches `cache.commit`. Any commit change (new code, config changes, etc.) invalidates the cache.

**Rationale:** Git commit is the simplest proxy for "has anything changed that could affect audit results." It catches TOML config changes, file additions/deletions, and code changes. It's conservative — some commits won't affect audit results, but a false invalidation just means re-running the audit (safe), while a false cache hit could skip needed remediation (unsafe).

**Edge case:** Uncommitted changes are not reflected in the commit hash. For uncommitted repos or dirty working trees, the cache should include a working-tree indicator (e.g., dirty flag) and invalidate if the dirty state changes.

### 4. Write point: end of `run_sieve_audit()`

**Decision:** The canonical audit pipeline function `run_sieve_audit()` writes the cache after completing the audit, before returning results.

**Rationale:** This is the single chokepoint — both `builtin_audit` and any other caller go through `run_sieve_audit()`. Writing here means every audit automatically populates the cache, regardless of which MCP tool triggered it.

**Alternative considered:** Write in `builtin_audit` — rejected: misses audits triggered by `remediate_audit_findings` or other callers.

### 5. Read point: start of `builtin_remediate` and `remediate_audit_findings`

**Decision:** Both remediation entry points check for a valid cache before running their own audit. If the cache is fresh, they extract `failed_ids` from it and skip the sieve run.

**Flow:**
```
remediate() called
  → load_audit_cache(local_path)
  → if cache exists AND cache.commit == current HEAD:
      failed_ids = {r["id"] for r in cache.results if r["status"] == "FAIL"}
  → else:
      run sieve audit (existing behavior)
      # audit writes cache as side effect
  → proceed with remediation using failed_ids
```

### 6. New module: `darnit.core.audit_cache`

**Decision:** Single module with three public functions:

- `write_audit_cache(local_path, results, summary, level, framework)` — write cache after audit
- `read_audit_cache(local_path) -> dict | None` — read cache if valid, None if stale/missing
- `invalidate_audit_cache(local_path)` — explicitly clear cache (e.g., after remediation changes files)

**Rationale:** Follows the pattern of `context_storage.py` — simple load/save functions, no classes. The module handles all filesystem details (creating `.darnit/`, reading/writing JSON, staleness checks).

### 7. Post-remediation invalidation

**Decision:** After `builtin_remediate` applies changes (not dry-run), it calls `invalidate_audit_cache()` because the repository state has changed and the cached results are no longer accurate.

**Rationale:** Remediation modifies files that auditing checks. A subsequent audit should re-evaluate from scratch rather than returning stale results that say controls still fail.

## Risks / Trade-offs

**[Stale cache on uncommitted changes]** → Git commit hash doesn't capture uncommitted edits. Mitigation: include a `dirty` flag in the cache. If the working tree was dirty when cached, require exact match of dirty state. If tree was clean, invalidate if now dirty. This is imperfect but conservative.

**[Cache file conflicts in multi-tool scenarios]** → If two MCP tool calls run concurrently (unlikely but possible), they could race on the cache file. Mitigation: use atomic write (write to temp file, rename). Read-side tolerance: if JSON is corrupt, treat as cache miss.

**[`.darnit/` directory proliferation]** → Adding a new dotfile directory to repos. Mitigation: only created when audit runs (lazy creation). Document in `.gitignore` templates. Single file for now, expandable later.

**[Remediation changes invalidate cache but not the MCP response]** → After remediation applies fixes, the cache is invalidated, but the LLM still has the old audit results in its conversation. This is existing behavior (not introduced by this change) and is acceptable — the LLM should re-audit after remediation to verify fixes.

## Open Questions

1. **Should `remediate_audit_findings` (baseline orchestrator) also read from cache?** It runs a full `run_sieve_audit()` internally. If `run_sieve_audit` reads cache, both entry points get it for free. But `run_sieve_audit` currently always runs from scratch — making it cache-aware is a larger change than just the remediation tools.

2. **Cache TTL vs commit-only invalidation?** A time-based TTL (e.g., 10 minutes) could catch cases where external state changes without a commit (e.g., GitHub settings modified via web UI). But it adds complexity and may cause unnecessary re-runs.
