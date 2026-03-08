## Why

The `.project/` mapper and org-level `.project` repo resolver we just built (`dot_project_mapper.py`, `dot_project_org.py`, `dot_project_merger.py`) are not wired into the actual audit pipeline. `run_sieve_audit()` in `audit.py` builds `project_context` from `collect_auto_context()` + `load_context()` but never calls `inject_project_context()` or `DotProjectMapper`, so org-level metadata and structured `.project/` data are invisible during audits. Additionally, there's no way to audit all repos in an org in a single invocation — you must run one audit at a time. Finally, when remediation creates artifacts (SECURITY.md, CODEOWNERS), there's no routing logic to decide whether write-back should target the org's upstream `.project` repo or the individual repo's `.project/` folder.

## What Changes

- **Wire `.project/` mapper into audit pipeline**: After `load_context()` in `run_sieve_audit()`, call `DotProjectMapper` (with owner for org resolution) and merge its context variables into `project_context`. Single-repo audits benefit immediately.
- **Add org-wide audit mode**: New MCP tool and core function that enumerates all repos in an org via `gh repo list`, clones each to a temp directory, runs the existing single-repo audit against each, and aggregates results into a combined report.
- **Write-back routing**: When remediation creates or updates files, decide whether the change belongs in the org-level `.project` repo (shared metadata like security contact, maintainers, governance) or in the individual repo's `.project/` folder (repo-specific overrides). Expose this as a routing decision the user confirms.
- **Single-repo audit remains the default**: All existing `audit_openssf_baseline()` and `run_sieve_audit()` call sites continue working unchanged. Org-wide mode is opt-in via a new tool/function.

## Capabilities

### New Capabilities
- `org-wide-audit`: Enumerating repos in an org, cloning to temp directories, running audits per-repo, aggregating results, and routing write-back decisions between org `.project` repo and per-repo `.project/` folders.

### Modified Capabilities
- `audit-pipeline`: Wiring `DotProjectMapper` (including org resolution) into `run_sieve_audit()` so `.project/` context is available during audits.

## Impact

- **Framework package** (`packages/darnit/`):
  - `tools/audit.py` — Add `.project/` mapper call after `load_context()` in `run_sieve_audit()`
  - New module for org-wide audit orchestration (repo enumeration, temp clone, per-repo audit, result aggregation)
- **Implementation package** (`packages/darnit-baseline/`):
  - `tools.py` — New `audit_org` MCP tool handler that calls org-wide audit
  - Remediation write-back routing (org vs repo)
- **MCP server** — New tool registration for org-wide audit
- **Tests** — Integration tests for pipeline wiring, unit tests for org enumeration and aggregation
- **External dependency**: `gh` CLI for repo listing and cloning (graceful degradation if unavailable)
- **No breaking changes** — Single-repo audit API is unchanged; org-wide mode is purely additive
