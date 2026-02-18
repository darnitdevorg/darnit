## ADDED Requirements

### Requirement: Canonical audit writes to cache
The `run_sieve_audit()` function SHALL write audit results to the cache after completing the sieve pipeline, before returning results to the caller.

#### Scenario: Audit populates cache automatically
- **WHEN** `run_sieve_audit()` completes successfully
- **THEN** it SHALL call `write_audit_cache()` with the `results`, `summary`, `level`, and `framework` name
- **AND** subsequent calls to `read_audit_cache()` from the same repository SHALL return the cached results (assuming no commit change)

#### Scenario: Audit failure does not write cache
- **WHEN** `run_sieve_audit()` raises an exception before completing
- **THEN** it SHALL NOT write to the audit cache
- **AND** any previously cached results SHALL remain unchanged

### Requirement: Builtin remediate consumes cached audit results
The `builtin_remediate` MCP tool SHALL check for cached audit results before running its own sieve audit. If valid cached results exist, it SHALL use them to determine which controls failed, skipping the redundant audit.

#### Scenario: Cache hit — skip audit
- **WHEN** `builtin_remediate()` is called
- **AND** `read_audit_cache(local_path)` returns valid cached results
- **THEN** it SHALL extract failed control IDs from the cached results (entries with `status == "FAIL"`)
- **AND** it SHALL NOT run `SieveOrchestrator.verify()` on any controls
- **AND** it SHALL proceed to remediation using only the failed control IDs

#### Scenario: Cache miss — fallback to audit
- **WHEN** `builtin_remediate()` is called
- **AND** `read_audit_cache(local_path)` returns `None`
- **THEN** it SHALL run the sieve audit as it does today (existing behavior)
- **AND** the audit SHALL populate the cache as a side effect (via `run_sieve_audit`)

#### Scenario: PASS controls excluded from remediation
- **WHEN** `builtin_remediate()` uses cached results
- **AND** a control has `status == "PASS"` in the cached results
- **THEN** that control SHALL NOT appear in the remediation plan
- **AND** it SHALL NOT be passed to the `RemediationExecutor`

### Requirement: Post-remediation cache invalidation
After `builtin_remediate` applies changes to the repository (not a dry run), it SHALL invalidate the audit cache because the repository state has changed.

#### Scenario: Successful remediation invalidates cache
- **WHEN** `builtin_remediate()` completes with `dry_run=False`
- **AND** at least one remediation was applied
- **THEN** it SHALL call `invalidate_audit_cache(local_path)`
- **AND** a subsequent `read_audit_cache()` call SHALL return `None`

#### Scenario: Dry run does not invalidate cache
- **WHEN** `builtin_remediate()` completes with `dry_run=True`
- **THEN** it SHALL NOT call `invalidate_audit_cache()`
- **AND** the cached results SHALL remain valid

### Requirement: Remediate audit findings consumes cached results
The `remediate_audit_findings()` function in the baseline orchestrator SHALL check for cached audit results before running its own audit, following the same cache-hit/miss logic as `builtin_remediate`.

#### Scenario: Orchestrator cache hit
- **WHEN** `remediate_audit_findings()` is called
- **AND** valid cached results exist
- **THEN** it SHALL use the cached results to determine `non_passing_ids`
- **AND** it SHALL NOT call `run_sieve_audit()` redundantly

#### Scenario: Orchestrator post-remediation invalidation
- **WHEN** `remediate_audit_findings()` applies changes with `dry_run=False`
- **THEN** it SHALL call `invalidate_audit_cache(local_path)`
