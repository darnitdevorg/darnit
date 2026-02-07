## Why

The sieve verification loop — load controls, iterate, call `orchestrator.verify()`, collect results — is implemented 3 separate times in the codebase. Bugs fixed in one path don't reach the others. User config exclusions and UnifiedLocator support only exist in one path. The `detect_workflow_checks()` function is also duplicated within the same package. This creates maintenance burden and inconsistent behavior across entry points.

## What Changes

- Extract a single `run_sieve_audit()` function in `darnit/tools/audit.py` that encapsulates: control loading, registration, sieve iteration, result collection, and summary calculation
- Refactor `audit_openssf_baseline()` in `darnit-baseline/tools.py` to delegate to the new function instead of reimplementing the loop
- Refactor `builtin_audit()` in `darnit/server/tools/builtin_audit.py` to delegate to the new function
- Delete `_format_audit_report()` from `builtin_audit.py` — use the existing `format_results_markdown()` instead
- Delete the duplicate `detect_workflow_checks()` from `darnit/remediation/helpers.py` — keep the more complete version in `github.py`
- Update framework-design spec to codify the single-pipeline rule so future code (by humans or LLMs) doesn't re-introduce duplication

## Capabilities

### New Capabilities
- `audit-pipeline`: A unified audit pipeline function that all entry points use. Supports optional parameters for tag filtering, user config exclusions, UnifiedLocator integration, and stop-on-LLM behavior.

### Modified Capabilities
- `framework-design`: Add requirement that all audit entry points MUST delegate to the canonical audit pipeline. No module SHALL reimplement the sieve verification loop.

## Impact

- **`darnit/tools/audit.py`**: New `run_sieve_audit()` extracted from existing `_run_sieve_checks()` + `run_checks()`, broadened to accept pre-loaded controls
- **`darnit/server/tools/builtin_audit.py`**: Simplified to ~30 lines — loads config, calls `run_sieve_audit()`, formats with `format_results_markdown()`
- **`darnit-baseline/tools.py`**: `audit_openssf_baseline()` simplified — delegates to `run_sieve_audit()` instead of inline loop
- **`darnit/remediation/helpers.py`**: `detect_workflow_checks()` deleted (~80 lines)
- **`darnit-baseline/remediation/orchestrator.py`**: `_run_baseline_checks()` already delegates correctly, no change needed
- **`openspec/specs/framework-design/spec.md`**: New section on audit pipeline requirements
