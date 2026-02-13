## Context

The remediation orchestrator (`orchestrator.py`) runs an audit to determine which categories need remediation, but only uses the audit results for category-level filtering. Within a category, it iterates all controls and picks the first one with declarative remediation — regardless of whether that specific control already passes.

This causes two problems:
1. A passing control gets remediated unnecessarily (e.g., VM-05.01 is remediated when VM-05.03 is the one failing)
2. The `manual` handler in a remediation pipeline returns INCONCLUSIVE, which the executor treats as failure, causing the whole category to report "error"

The audit results (`non_passing`) are already computed at line 821 of `remediate_audit_findings()` but are discarded after category-level filtering. They need to flow into `_apply_remediation()`.

## Goals / Non-Goals

**Goals:**
- Only remediate controls that actually fail the audit
- Treat `manual` handlers in remediation as informational (not failure-inducing)
- Preserve existing behavior for explicit category lists (user-specified categories should still run an audit to filter controls)

**Non-Goals:**
- Changing the TOML remediation schema
- Remediating multiple controls per category in a single pass (current "first match" behavior is fine once filtering is correct)
- Adding new remediation categories or handlers

## Decisions

### 1. Pass non-passing control IDs into `_apply_remediation()`

**Approach**: Extract the set of non-passing control IDs from the audit results and pass it as a `non_passing_ids: set[str]` parameter to `_apply_remediation()`. Filter `applicable_controls` to the intersection of currently-applicable controls AND non-passing controls.

**Why not filter at the category level only?** Categories group multiple controls. The "dependabot" category has 3 controls (VM-05.01, VM-05.02, VM-05.03). Category-level filtering keeps the category if ANY control fails, but we need control-level filtering to avoid remediating the ones that pass.

**Edge case — explicit categories**: When the user passes specific categories (not `["all"]`), the audit hasn't been run yet. In this case, run the audit inside `_apply_remediation()` or accept `non_passing_ids=None` to mean "remediate all applicable controls" (current behavior). The cleaner approach is to always run the audit in `remediate_audit_findings()` and pass results down, even for explicit categories.

### 2. Treat INCONCLUSIVE as non-failing in the remediation executor

**Approach**: In `executor.py:_execute_handler_invocations()`, change line 406 from:
```python
if handler_result.status != HandlerResultStatus.PASS:
    all_success = False
```
to:
```python
if handler_result.status in (HandlerResultStatus.FAIL, HandlerResultStatus.ERROR):
    all_success = False
```

This means INCONCLUSIVE (from `manual` handlers) no longer poisons the result. The remediation succeeds if no handler explicitly fails or errors.

**Why this is safe**: Manual handlers in remediation are guidance steps ("Add an SCA section to SECURITY.md"). They can't fail — they just provide instructions. Treating them as failures makes every remediation with manual follow-up steps report as an error.

### 3. Always run audit before remediation

**Approach**: Move the audit call to always execute in `remediate_audit_findings()`, even when the user passes explicit categories. This ensures `non_passing_ids` is always available. Currently the audit is skipped when `categories` is explicitly provided (line 813: `if not categories or categories == ["all"]`).

**Why**: Without audit results, we can't filter controls. Running the audit is cheap (already cached) and ensures consistent behavior.

## Risks / Trade-offs

- **[Remediation runs audit even for explicit categories]** → Minor perf cost; audit is already fast and results are useful for filtering. Mitigated by the fact that audit results are needed for correctness.
- **[INCONCLUSIVE treated as success could mask real issues]** → Only `manual` handlers return INCONCLUSIVE in remediation context. If a future handler misuses INCONCLUSIVE to mean "something went wrong", it would be silently treated as success. Mitigated by the handler contract: INCONCLUSIVE means "needs human review", not "failed".
- **[Changing `_apply_remediation()` signature]** → Adding `non_passing_ids` parameter is a private function change with no external callers. Low risk.
