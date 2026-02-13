## ADDED Requirements

### Requirement: Remediation SHALL skip controls that pass the audit
The remediation orchestrator SHALL run an audit before applying remediations and SHALL only remediate controls whose audit status is not PASS. Controls within a category that already pass MUST be excluded from the remediation candidate list.

#### Scenario: Category with mixed passing and failing controls
- **WHEN** the "dependabot" category has controls VM-05.01 (PASS), VM-05.02 (WARN), VM-05.03 (WARN)
- **THEN** only VM-05.02 and VM-05.03 are considered for remediation, and VM-05.01 is skipped

#### Scenario: All controls in a category pass
- **WHEN** all controls in a category have audit status PASS
- **THEN** the category is skipped entirely and reported as not needing remediation

#### Scenario: User specifies explicit categories
- **WHEN** the user passes specific category names (not "all")
- **THEN** the orchestrator SHALL still run an audit and filter out passing controls within those categories

### Requirement: Audit results SHALL be passed to per-category remediation
The `remediate_audit_findings()` function SHALL extract non-passing control IDs from the audit results and pass them to `_apply_remediation()` so that control-level filtering occurs within each category.

#### Scenario: Non-passing IDs flow to _apply_remediation
- **WHEN** the audit produces results with 3 non-passing controls
- **THEN** `_apply_remediation()` receives those 3 control IDs and only considers them as remediation candidates

### Requirement: Manual handlers in remediation SHALL NOT cause failure
The remediation executor SHALL treat INCONCLUSIVE status from handlers as non-failing. Only FAIL and ERROR statuses SHALL set the remediation result to `success=False`.

#### Scenario: Remediation with file_create and manual handlers
- **WHEN** a remediation has a `file_create` handler (returns PASS) followed by a `manual` handler (returns INCONCLUSIVE)
- **THEN** the overall remediation result is `success=True`

#### Scenario: Remediation with a failing handler
- **WHEN** a remediation has a handler that returns FAIL or ERROR
- **THEN** the overall remediation result is `success=False`

#### Scenario: Remediation with only manual handlers
- **WHEN** a remediation has only `manual` handlers (all return INCONCLUSIVE)
- **THEN** the overall remediation result is `success=True` (manual steps are guidance, not failures)
