## Why

The remediation orchestrator applies remediations to controls that already pass the audit. This wastes effort and causes false error reports. Specifically, the "dependabot" category errors because it picks the first control with declarative remediation (OSPS-VM-05.01, which may already pass) instead of the control that actually failed (OSPS-VM-05.03). The `manual` handler in the remediation pipeline then poisons `all_success`, causing the entire category to report as an error even though the file creation succeeded.

## What Changes

- Pass non-passing control IDs from the audit into `_apply_remediation()` so it skips controls that already pass
- Only remediate controls within a category that actually need remediation
- Treat `INCONCLUSIVE` from `manual` handlers as non-failing in the remediation executor (manual steps are guidance, not executable actions that can fail)

## Capabilities

### New Capabilities
- `remediation-audit-filtering`: Filter remediation targets using audit results so only non-passing controls are remediated within each category

### Modified Capabilities

## Impact

- `packages/darnit-baseline/src/darnit_baseline/remediation/orchestrator.py` — `remediate_audit_findings()`, `_apply_remediation()`, `_determine_remediable_categories()`
- `packages/darnit/src/darnit/remediation/executor.py` — `_execute_handler_invocations()` success logic
- Tests for both orchestrator and executor
