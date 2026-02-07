## ADDED Requirements

### Requirement: Single audit pipeline function
The framework SHALL provide a single `run_sieve_audit()` function in `darnit.tools.audit` that encapsulates the full sieve verification loop: control iteration, `CheckContext` construction, `SieveOrchestrator.verify()` invocation, and result collection. All code paths that run audits MUST delegate to this function.

#### Scenario: Framework builtin audit delegates to pipeline
- **WHEN** `builtin_audit()` in `darnit/server/tools/builtin_audit.py` is called
- **THEN** it SHALL call `run_sieve_audit()` instead of implementing its own sieve loop
- **AND** the inline `for control in all_controls: ... orchestrator.verify(...)` loop SHALL be removed

#### Scenario: Implementation audit delegates to pipeline
- **WHEN** `audit_openssf_baseline()` in `darnit-baseline/tools.py` is called
- **THEN** it SHALL call `run_sieve_audit()` instead of implementing its own sieve loop
- **AND** the inline summary calculation (lines building `summary` dict) SHALL be removed

#### Scenario: CLI audit delegates to pipeline
- **WHEN** the CLI `cmd_audit()` runs checks
- **THEN** it SHALL reach the pipeline through the existing `run_checks()` → `_run_sieve_checks()` chain (no change needed)

### Requirement: Pipeline accepts pre-loaded controls
The `run_sieve_audit()` function SHALL accept a list of pre-loaded `ControlSpec` objects, so callers that have already loaded and filtered controls do not need to reload them.

#### Scenario: Caller provides controls
- **WHEN** `run_sieve_audit()` is called with a `controls` parameter
- **THEN** it SHALL use those controls directly without loading from TOML or registry

#### Scenario: Caller does not provide controls
- **WHEN** `run_sieve_audit()` is called without a `controls` parameter
- **THEN** it SHALL load controls from the framework TOML and Python registry (existing behavior of `_run_sieve_checks`)

### Requirement: Pipeline supports optional features
The `run_sieve_audit()` function SHALL support optional parameters for features that not all callers need, with sensible defaults.

#### Scenario: User config exclusions
- **WHEN** `apply_user_config=True` (default)
- **THEN** controls excluded in `.baseline.toml` SHALL be marked as `N/A` in results

#### Scenario: UnifiedLocator integration
- **WHEN** the pipeline runs
- **THEN** it SHALL create a `UnifiedLocator` for `.project/` file resolution and pass it to each `CheckContext`

#### Scenario: Tag filtering
- **WHEN** a `tags` parameter is provided
- **THEN** controls SHALL be filtered by the specified tags before sieve execution

#### Scenario: Stop on LLM
- **WHEN** `stop_on_llm=True` (default)
- **THEN** LLM passes SHALL return `PENDING_LLM` for external consultation

### Requirement: Pipeline returns structured results
The `run_sieve_audit()` function SHALL return both the list of result dicts and a summary dict, so callers do not need to recompute summaries.

#### Scenario: Return value structure
- **WHEN** `run_sieve_audit()` completes
- **THEN** it SHALL return a tuple of `(results: list[dict], summary: dict)` where summary contains counts for each status (PASS, FAIL, WARN, ERROR, N/A, PENDING_LLM, total)

### Requirement: Single report formatter
All audit entry points that produce markdown output SHALL use `format_results_markdown()` from `darnit.tools.audit`. No other module SHALL maintain a separate audit report formatter.

#### Scenario: Builtin audit formatting
- **WHEN** `builtin_audit()` formats output
- **THEN** it SHALL call `format_results_markdown()` and the private `_format_audit_report()` function SHALL be deleted

#### Scenario: Implementation audit formatting
- **WHEN** `audit_openssf_baseline()` formats output
- **THEN** it SHALL call `format_results_markdown()` (already does this — no change needed)

### Requirement: No duplicate utility functions
Functions that exist in multiple copies within the same package SHALL be consolidated to a single implementation.

#### Scenario: detect_workflow_checks consolidation
- **WHEN** workflow check detection is needed
- **THEN** callers SHALL use `detect_workflow_checks()` from `darnit.remediation.github`
- **AND** the duplicate in `darnit.remediation.helpers` SHALL be deleted
