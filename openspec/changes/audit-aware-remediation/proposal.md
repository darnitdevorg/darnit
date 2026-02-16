## Why

The MCP tool pipeline is designed to flow step-by-step: `get_pending_context` → `confirm_project_context` → `audit` → `remediate`. But the pipeline breaks between audit and remediate — audit results evaporate after the tool returns, forcing `builtin_remediate` and `remediate_audit_findings` to re-run the entire audit from scratch. This wastes time, can produce inconsistent results, and — most importantly — means remediation has no way to know what already passes. The result: remediation proposes changes to files that already exist and pass their checks (e.g., overwriting a valid SECURITY.md or dependabot config with template content).

## What Changes

- Audit results become **cached pipeline state** that persists across tool calls, similar to how `.project/project.yaml` persists context confirmations
- The `builtin_remediate` tool reads cached audit results automatically — if fresh results exist, it skips re-running the audit and only remediates controls that actually failed
- Controls with PASS status are excluded from remediation without requiring the LLM to pass data between tool calls
- The audit tool writes results to a well-known cache location after each run
- Staleness detection ensures remediate doesn't act on outdated results (falls back to re-running audit if cache is stale)

## Capabilities

### New Capabilities
- `audit-result-cache`: Audit result persistence and retrieval — write/read/staleness for cached audit results that flow between MCP tool calls

### Modified Capabilities
- `framework-design`: The builtin `remediate` tool specification changes to consume cached audit results before deciding what to remediate. The `audit` tool specification changes to write results to the cache after each run.

## Impact

- `packages/darnit/src/darnit/server/tools/builtin_remediate.py` — read from cache instead of always re-auditing
- `packages/darnit/src/darnit/server/tools/builtin_audit.py` — write results to cache after audit completes
- `packages/darnit-baseline/src/darnit_baseline/remediation/orchestrator.py` — read from cache in `remediate_audit_findings()`
- New module for audit result cache (read/write/staleness)
- `openspec/specs/framework-design/spec.md` — document cache behavior in builtin tool specs
- Cache location decision: `.project/` directory (alongside project.yaml) or separate ephemeral location
