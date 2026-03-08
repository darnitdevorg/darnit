## MODIFIED Requirements

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

#### Scenario: .project/ mapper context injection
- **WHEN** the pipeline runs and `owner` is available
- **THEN** it SHALL call `DotProjectMapper(local_path, owner=owner).get_context()` once before the control loop
- **AND** SHALL merge the mapper's context variables into `project_context`
- **AND** mapper values SHALL be overridden by user-confirmed values from `load_context()`

#### Scenario: .project/ mapper context without owner
- **WHEN** the pipeline runs and `owner` is empty or None
- **THEN** it SHALL still call `DotProjectMapper(local_path).get_context()` for local `.project/` data
- **AND** org-level resolution SHALL be skipped

#### Scenario: .project/ mapper failure is non-fatal
- **WHEN** `DotProjectMapper.get_context()` raises an exception
- **THEN** the pipeline SHALL log a warning
- **AND** SHALL continue the audit with whatever context was available before the mapper call
