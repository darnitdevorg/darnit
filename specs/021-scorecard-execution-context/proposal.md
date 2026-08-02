# Proposal: Wire OpenSSF Scorecard to `ExecutionContext.get_or_run_tool` (evidence-only, via scorecard-mcp)

**Feature Branch**: `021-scorecard-execution-context` (proposed)

**Created**: 2026-08-02

**Status**: Proposal — Draft (pre-spec; graduates to `spec.md`/`plan.md` when scheduled)

**Tracking issue**: [darnitdevorg/darnit#194](https://github.com/darnitdevorg/darnit/issues/194)

**Depends on**: [#189](https://github.com/darnitdevorg/darnit/pull/189) (shared `ExecutionContext`)

**Input**: "Scorecard now has an [unofficial] MCP server. How would we begin to solve #194?" — wire at least one heavy tool through `ExecutionContext` so the caching infrastructure from #189 gains a real consumer.

---

## 1. Summary

Issue #194 asks us to give the `ExecutionContext.get_or_run_tool()` caching infrastructure (added by #189 but currently latent — no consumer) a first real consumer, using OpenSSF Scorecard as the motivating heavy tool: one JSON output that can inform many controls (branch protection, signed releases, token permissions, security policy, …) but is wasteful to run once per control.

This proposal wires Scorecard as a **sieve handler** in `darnit-baseline` that:

1. fetches Scorecard data **once per repo per audit** through the shared `ExecutionContext`, and
2. attaches the result as **evidence only** to each mapped control — never asserting a verdict — so the control proceeds to its normal verification passes, now enriched.

The Scorecard signal is obtained through the **`uwu-tools/scorecard-mcp`** server (MCP over stdio), accessed behind a swappable backend seam so a live-scan CLI backend can be added later without touching the caching or mapping logic.

## 2. Two confirmed decisions

Both were decided by the maintainer (Stephen Augustus) on 2026-08-02:

| Decision | Choice | Rationale |
|---|---|---|
| **Invocation backend** | `scorecard-mcp`, behind a seam | MCP-native, aligns with darnit's architecture, no local binary or `GITHUB_TOKEN` needed. Ship the MCP backend now; keep a CLI backend as a future drop-in behind the same `Protocol`. |
| **Verdict policy** | **Evidence-only** | Scorecard never changes a control's status; it only attaches evidence/hints that later passes can use. Most conservative option — and it matches both darnit's constitution and scorecard-mcp's own framing. |

### Why evidence-only is the correct default

The `scorecard-mcp` server (status: *incubating*) currently reads **pre-computed** results from the public Scorecard REST API (`api.scorecard.dev`). That data is:

- **opt-in only** — covers only public repos that set `publish_results: true` via scorecard-action;
- **potentially stale** — weekly cached scans, not a live scan of the audited HEAD;
- **partial** — the weekly public scan omits some checks (e.g., CI-Tests, Contributors, Dependency-Update-Tool).

The server's own README states results are *"heuristic signals to inform a human decision, not a verdict"* and *"never asserts that a repository 'is secure' or 'is insecure.'"*

This aligns exactly with darnit's **Conservative-by-Default** principles (`CLAUDE.md`): a control not *explicitly verified as passing* is not compliant; when in doubt, WARN, never a false PASS. Treating a cached, opt-in, possibly-stale heuristic as a conclusive PASS would be a false positive — the single worst failure mode for a compliance tool. Evidence-only sidesteps this entirely: Scorecard enriches the audit without ever concluding it.

## 3. Background — what already exists

Verified against the tree at proposal time:

- **`ExecutionContext.get_or_run_tool(key, run_func)`** — thread-safe, fine-grained per-tool locking (`packages/darnit/src/darnit/core/models.py:105`). Instantiated once per audit (`packages/darnit/src/darnit/tools/audit.py:424`) and threaded through `CheckContext` → orchestrator (`packages/darnit/src/darnit/sieve/orchestrator.py:232`) → `HandlerContext.execution_context` (`packages/darnit/src/darnit/sieve/handler_registry.py:104`). **The plumbing already reaches every sieve handler.**
- **`normalize_scorecard_output(raw, check_name)`** — maps Scorecard's `{checks: [{name, score, reason}]}` shape to pass/fail/inconclusive (threshold 8, `score == -1` → inconclusive) at `packages/darnit/src/darnit/locate/normalizer.py:274`. **The parser already exists** and matches the `scorecard-mcp` `get_repo_score` output shape.
- **`AdapterCapability.cache_key`** — defined (`packages/darnit/src/darnit/core/models.py:66`) but **read by nothing**.
- **Evidence-on-INCONCLUSIVE is supported** — a handler returning `INCONCLUSIVE` with `evidence` has that evidence merged into `accumulated_evidence`, `handler_ctx.gathered_evidence`, and `context.gathered_evidence`, and the control falls through to its next pass (`orchestrator.py:348-351`). No framework change is needed to make evidence-only work.

What's missing: **nothing runs Scorecard.** This proposal adds that consumer.

## 4. Design

### 4.1 Backend seam (the crux)

```python
# packages/darnit-baseline/src/darnit_baseline/scorecard/backend.py
from typing import Protocol

class ScorecardBackend(Protocol):
    def get_repo_score(self, platform: str, org: str, repo: str) -> dict | None:
        """Return Scorecard result ({checks:[{name,score,reason}], ...}) or None if unavailable."""
        ...

class ScorecardMcpBackend:      # ships now — fastmcp.Client over stdio to `scorecard-mcp`
    ...

# class ScorecardCliBackend    # future — same Protocol, `scorecard --format=json`, no caller changes
```

The MCP backend uses `fastmcp`'s client (already a darnit dependency) to spawn/connect to the `scorecard-mcp` stdio server and call its `get_repo_score` tool.

### 4.2 Handler behavior (evidence-only)

```python
# packages/darnit-baseline/src/darnit_baseline/scorecard/handlers.py
def scorecard_handler(config, ctx) -> HandlerResult:
    ec = ctx.execution_context
    if ec is None or not ctx.owner or not ctx.repo:
        return HandlerResult(INCONCLUSIVE, "No Scorecard identity/context available")

    def fetch():
        return _backend.get_repo_score("github.com", ctx.owner, ctx.repo)

    data = ec.get_or_run_tool(f"scorecard:{ctx.owner}/{ctx.repo}", fetch)  # <-- shared, one fetch
    if data is None:
        return HandlerResult(INCONCLUSIVE, "No cached Scorecard data for this repo", evidence={...caveat...})

    check = config["check"]                       # e.g. "Branch-Protection"
    normalized = normalize_scorecard_output(data, check)
    return HandlerResult(
        status=INCONCLUSIVE,                      # evidence-only: never conclusive
        message=f"Scorecard {check}: {normalized.message}",
        evidence={f"scorecard.{check}": {...score, reason, provenance, caveats...}},
    )
```

- **Cache key** is per-repo (`scorecard:{owner}/{repo}`), so all mapped controls in one audit share exactly one fetch, and an org-wide/`compare_repos` path stays correct across repos.
- The handler is inserted as the **first pass** of each mapped control, ahead of the existing exec/manual passes.

### 4.3 Control → check mapping

Insert a `scorecard` pass (with a `check = "..."` arg) as the first pass on ≥2 controls. Candidate mappings (all controls already present in `packages/darnit-baseline/openssf-baseline.toml`):

| Scorecard check | OSPS control(s) | TOML anchor |
|---|---|---|
| `Branch-Protection` | `PreventDirectCommits` (+ related branch-protection controls) | ~line 601 |
| `Token-Permissions` | `ExplicitWorkflowPermissions`, `ScopedPermissions` | ~2210 / ~2761 |
| `Signed-Releases` | `SignReleases` | ~1170 |
| `Security-Policy` | `HasSecurityPolicy` | ~2129 |

Exact set to be locked in during spec/implementation; a minimum of two is required for a meaningful "N controls → 1 invocation" test.

### 4.4 Graceful degradation (baked in)

Any of the following yields `INCONCLUSIVE` with an explanatory caveat in evidence — never `ERROR`, never a status change:

- repo not in `api.scorecard.dev` (private, or not opted-in via `publish_results`);
- no `owner`/`repo` (local-path-only audit);
- server unreachable / tool error / malformed payload.

## 5. Acceptance criteria (from #194) and how this maps

| # | Issue acceptance criterion | This proposal |
|---|---|---|
| 1 | An adapter/handler reads tool output via `handler_ctx.execution_context.get_or_run_tool(key, run_func)` | ✅ The `scorecard` sieve handler does exactly this. |
| 2 | `AdapterCapability.cache_key` (from #189) is consumed by the dispatch layer | ⚠️ **Open** — see §7. The live audit flow runs through the **sieve handler** path, not the `CheckAdapter` dispatch path, which appears vestigial. Proposed resolution: amend this bullet (handler path is the real consumer) rather than force-wire an unused path. |
| 3 | Integration test: N controls using the same tool ⇒ exactly 1 tool invocation | ✅ Integration test mocks the backend seam and asserts a single call across all Scorecard-mapped controls in one audit. |

## 6. Constitution alignment

- **Never assume compliance** — Scorecard never emits PASS; controls still require their own conclusive pass. ✔
- **Err on the side of caution** — all Scorecard uncertainty resolves to INCONCLUSIVE/WARN, never a verdict. ✔
- **Never guess user-specific values** — Scorecard supplies posture signals, not user-judgment keys (maintainers, security contacts, governance); it touches none of them. ✔
- **Prompt safety** — evidence is attached as data; no guessed values are placed in executable snippets. ✔

## 7. Open questions

1. **Acceptance-criterion #2 (`cache_key` in dispatch).** Prefer to amend the bullet (handler path is the real consumer) or also teach `CheckAdapter` dispatch to route `cache_key` through `ExecutionContext` for completeness? *Recommendation: amend, with a note on the issue.*
2. **Exact control set.** Which of the §4.3 mappings ship in the first cut (minimum two)?
3. **Dependency policy.** `scorecard-mcp` is a Go binary (`go install github.com/uwu-tools/scorecard-mcp/cmd/scorecard-mcp@latest`). Treat as an **optional** external tool discovered at runtime (like the `gittuf`/`kusari` binaries) with graceful degradation when absent — confirm this is the desired posture vs. bundling config.
4. **Provenance surfacing.** `scorecard-mcp` returns provenance (commit SHA, scan date, Scorecard version, source) and CDLA-Permissive-2.0 attribution. Confirm formatters should surface these caveats in report evidence (recommended, for honesty about staleness).

## 8. Phased implementation plan

1. **Backend** — `ScorecardBackend` Protocol + `ScorecardMcpBackend` (fastmcp stdio client); unit-tested against a fake MCP server.
2. **Handler** — `scorecard_handler` + unit tests (evidence attached, returns INCONCLUSIVE, graceful degrade paths).
3. **Registration + wiring** — register `scorecard` on the sieve handler registry in `implementation.py` (mirrors `generate_threat_model` at `implementation.py:202-214`); add `scorecard` first-pass to the chosen TOML controls.
4. **Integration test** — audit over N Scorecard-mapped controls asserts the backend seam is invoked exactly once (criterion #3).
5. **Docs** — expand `docs/HANDLER_AUTHORING.md` "Shared Execution Context" section with the real example; document `scorecard-mcp` as an optional dependency + `.mcp.json` snippet.
6. **Sync/lint** — `uv run python scripts/validate_sync.py --verbose`, `uv run ruff check .`, `uv run pytest tests/ -v`.

## 9. Non-goals

- No live on-demand Scorecard scanning in this cut (the CLI backend is future work behind the seam).
- No change to how any control ultimately concludes — Scorecard is purely additive evidence.
- No new required runtime dependency in any darnit Python package (`scorecard-mcp` is an optional external tool).

## References

- Issue: https://github.com/darnitdevorg/darnit/issues/194
- Infrastructure PR: https://github.com/darnitdevorg/darnit/pull/189
- Scorecard MCP server: https://github.com/uwu-tools/scorecard-mcp
- OpenSSF Scorecard: https://github.com/ossf/scorecard
- Docs: `docs/HANDLER_AUTHORING.md` (Shared Execution Context)
- Conservative-by-default principles: `CLAUDE.md`
