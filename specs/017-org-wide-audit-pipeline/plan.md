## Context

The `.project/` mapper (`DotProjectMapper`) and org-level resolver (`OrgProjectResolver`) exist but are not called during audits. `run_sieve_audit()` builds `project_context` from `collect_auto_context()` + `load_context()` (lines 424-443 in `audit.py`) and directly constructs `CheckContext` at line 474 without ever invoking the mapper. The mapper's `get_context()` method produces a richer set of `project.*` context variables (security policy paths, maintainer teams, advisory URLs, etc.) that checks can reference but currently never see.

Separately, audits are single-repo: you must provide or auto-detect one `owner/repo` pair. There's no way to enumerate an org's repos and audit them all. CNCF projects typically have dozens of repos under a single org, each inheriting shared metadata from the org `.project` repo.

Remediation currently writes all artifacts (SECURITY.md, CODEOWNERS, `.project/project.yaml`) into the local repo. There's no concept of routing some changes back to the org `.project` repo when the metadata is org-wide.

## Goals / Non-Goals

**Goals:**
- Wire `DotProjectMapper` into `run_sieve_audit()` so `.project/` context variables (including org-level merge) are available to all checks in every audit
- Add an `audit_org` function/tool that enumerates repos in an org, clones each to a temp directory, runs single-repo audits, and produces an aggregated report
- Define a write-back routing scheme that distinguishes org-level metadata (shared `.project` repo) from repo-specific metadata (per-repo `.project/` folder)
- Keep single-repo audit as the default — org-wide mode is purely additive
- Gracefully degrade when `gh` CLI is unavailable (skip org enumeration, warn user)

**Non-Goals:**
- Full org `.project` repo write-back automation (pushing changes to `{owner}/.project`) — this change only classifies and surfaces the routing decision; actual push is deferred
- Parallel/concurrent repo cloning and auditing — sequential is fine for v1
- Supporting non-GitHub forges for org enumeration (GitLab, Bitbucket) — `gh` only for now
- Modifying the sieve orchestrator or check execution model — only the context injection point changes
- Persistent clone caching across sessions — temp directories are cleaned up per invocation

## Decisions

### 1. Inject mapper context into `run_sieve_audit()` (not per-CheckContext)

**Decision:** Call `DotProjectMapper.get_context()` once in `run_sieve_audit()` after `load_context()` and merge the result into `project_context` dict (mapper values as defaults, user-confirmed values take precedence). This happens before the per-control loop, so all controls see the same merged context.

**Rationale:** The mapper is expensive (reads `.project/` files, potentially calls `gh` for org resolution). Calling it once and reusing the result for all controls is efficient and consistent. The existing `inject_project_context()` function works per-CheckContext, which would be redundant since the same repo path and owner apply to every control in a single audit.

**Alternative considered:** Call `inject_project_context()` inside the per-control loop. Rejected — the mapper caches internally, but it would still create N mapper instances and N `get_context()` calls for N controls, all returning identical results.

### 2. Mapper context is lower priority than user-confirmed context

**Decision:** `project_context` merge order is: `collect_auto_context()` → `DotProjectMapper.get_context()` → `load_context()` (user-confirmed). Later values override earlier ones.

**Rationale:** The conservative-by-default principle says user-confirmed values (`load_context`) always win. The mapper reads `.project/` files which are structured project metadata — more authoritative than auto-detection heuristics but less authoritative than explicit user confirmation. This three-layer stack gives us: heuristics < project metadata < user intent.

### 3. Org repo enumeration via `gh repo list`

**Decision:** Use `gh repo list {owner} --json name,isArchived --limit 500` to enumerate repos. Skip archived repos by default (opt-in to include them). Clone each via `gh repo clone {owner}/{repo} {tmpdir}` with `--depth 1` for shallow clones.

**Rationale:** `gh` CLI is already a dependency for org `.project` resolution. `gh repo list` returns JSON with repo metadata, letting us filter archived repos without extra API calls. Shallow clones minimize disk and network usage since audits only need the working tree (no history analysis needed for compliance checks).

**Alternative considered:** Use GitHub REST API directly via `subprocess` + `curl`. Rejected — `gh` handles auth, pagination, and rate limiting transparently.

### 4. Sequential audit execution for v1

**Decision:** Audit repos one at a time in a loop. Each repo gets: clone → audit → collect results → cleanup temp dir.

**Rationale:** Simplicity. The audit is I/O-bound (file reads, `gh` API calls) not CPU-bound, so parallelism gains are modest. Sequential execution keeps error handling straightforward and output ordering deterministic. Can add concurrency later if users need it.

### 5. Aggregated report format

**Decision:** The org-wide audit returns a combined markdown report with: (a) org-level summary table (repo × compliance status), (b) per-repo detail sections that match the existing single-repo format. JSON output returns an array of per-repo results with an org-level summary object.

**Rationale:** Reuses the existing `format_results_markdown()` for per-repo sections. The summary table gives a quick org-wide compliance overview. JSON format enables programmatic consumption for dashboards.

### 6. Write-back routing classification (not execution)

**Decision:** After org-wide audit, classify each remediation action as `org` or `repo`:
- **Org-level** (goes to `{owner}/.project`): security contact, maintainers list, governance model, shared security policy template
- **Repo-level** (goes to `{repo}/.project/`): repo-specific overrides, repo-specific SECURITY.md/CODEOWNERS paths, build/CI config
- Surface this classification in the report. Do not auto-push to any remote.

**Rationale:** The conservative-by-default principle means we classify and inform, not auto-execute. Pushing to the org `.project` repo affects all repos in the org — that's a high-blast-radius action that needs explicit user approval. The classification heuristic is simple: if a field exists in the org `.project` repo and the remediation would set the same field, route to org; otherwise route to repo.

### 7. New module placement

**Decision:**
- `packages/darnit/src/darnit/tools/audit_org.py` — Org-wide audit orchestration (repo enumeration, clone, audit loop, aggregation). Lives in `tools/` because it orchestrates the audit tool.
- `packages/darnit-baseline/src/darnit_baseline/tools.py` — New `audit_org` tool handler function (thin wrapper that calls the framework's org-wide audit).
- Write-back routing classification logic lives in `packages/darnit-baseline/src/darnit_baseline/remediation/routing.py` — implementation-specific since routing rules depend on which controls produce which artifacts.

**Rationale:** The framework (`darnit`) owns the generic audit orchestration (enumerate, clone, run audit, aggregate). The implementation (`darnit-baseline`) owns the tool handler and remediation routing because those are OpenSSF Baseline-specific decisions.

## Risks / Trade-offs

**[Risk] `gh repo list` may hit rate limits for large orgs** → Mitigation: Use `--limit 500` cap. For orgs with 500+ repos, warn the user and suggest filtering with `--topic` or `--language` flags in a future iteration.

**[Risk] Shallow clones may miss data needed by some checks** → Mitigation: Current OSPS checks only examine the working tree (file existence, content patterns). No check currently requires git history. If a future check needs history, it can be flagged as needing full clone depth.

**[Risk] Temp directory disk usage for large orgs** → Mitigation: Clone and audit one repo at a time, cleaning up the temp directory before cloning the next. Peak disk usage = size of one repo, not the entire org.

**[Risk] Mapper context could conflict with existing `project_context` keys** → Mitigation: The mapper uses `project.*` namespaced keys. `collect_auto_context()` uses non-prefixed keys (`ci_provider`, `language`). No overlap. `load_context()` uses `project.*` keys from `.project.yaml` — these take precedence by merge order.

**[Trade-off] Sequential vs. parallel repo auditing** → Sequential is simpler and sufficient for v1. Users with 100+ repos may want parallelism; that can be a follow-up change.

**[Trade-off] Write-back classification without execution** → Users must manually apply org-level changes. This is intentionally conservative — auto-pushing to org repos is high-risk. A future change could add a `--apply-org` flag with explicit confirmation.

## Open Questions

- Should the org-wide audit tool accept a `repos` filter parameter (list of specific repo names to audit) in addition to auditing all repos? Likely yes for usability, but can be added later.
- Should we cache the repo list across invocations within a session (like `_org_cache` in `dot_project_org.py`)? Probably not — repo lists change more frequently than `.project` metadata.
