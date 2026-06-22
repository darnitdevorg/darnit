## ADDED Requirements

### Requirement: Shared handler definitions avoid redundant execution
The TOML schema SHALL support a `[shared_handlers]` section where named handler configurations can be defined once and referenced by multiple controls. When multiple controls reference the same shared handler, the framework SHALL execute the handler once and cache the result for all referencing controls within the same audit run.

#### Scenario: Two controls reference the same shared handler
- **WHEN** `[shared_handlers.branch_protection]` defines `handler = "exec"` and `command = ["gh", "api", "/repos/$OWNER/$REPO/branches/$BRANCH/protection"]`
- **AND** control OSPS-AC-03.01 defines `deterministic = [{ shared = "branch_protection", expr = "has(output.json.required_pull_request_reviews)" }]`
- **AND** control OSPS-AC-03.02 defines `deterministic = [{ shared = "branch_protection", expr = "output.json.allow_deletions.enabled == false" }]`
- **THEN** the framework SHALL execute the handler exactly once
- **AND** both controls SHALL evaluate their `expr` against the same cached output

#### Scenario: Shared handler fails to execute
- **WHEN** a shared handler returns an error (non-zero exit code not in pass or fail lists)
- **THEN** all controls referencing that shared handler SHALL receive an ERROR result
- **AND** the error message SHALL identify the shared handler by name

#### Scenario: Shared handler is not referenced
- **WHEN** a `[shared_handlers]` entry exists but no control references it
- **THEN** the framework SHALL NOT execute that shared handler

### Requirement: Shared handler definition schema
A shared handler entry SHALL contain a `handler` field naming the registered handler to invoke, plus any handler-specific configuration fields. The `expr` field SHALL NOT appear in the shared definition — each referencing control provides its own expression.

#### Scenario: Shared handler with output format
- **WHEN** `[shared_handlers.repo_info]` defines `handler = "exec"`, `command = ["gh", "api", "/repos/$OWNER/$REPO"]`, and `output_format = "json"`
- **THEN** the cached result SHALL include parsed JSON accessible via `output.json`
- **AND** each referencing control's `expr` SHALL evaluate against the parsed output

#### Scenario: Referencing control provides its own expr
- **WHEN** a control's deterministic handler has `shared = "repo_info"` and `expr = "output.json.private == false"`
- **THEN** the framework SHALL use the control's `expr`, not look for one in the shared definition

#### Scenario: Referencing control overrides handler-specific fields
- **WHEN** a shared handler defines `timeout = 300`
- **AND** a referencing control specifies `timeout = 60`
- **THEN** the control's value SHALL take precedence for that invocation
- **AND** the cached result from the original execution SHALL still be used (override applies only to evaluation, not re-execution)

### Requirement: Cache is scoped to a single audit run
Shared handler results SHALL be cached only for the duration of one audit invocation. The cache SHALL NOT persist across separate audit runs.

#### Scenario: Two consecutive audits
- **WHEN** an audit completes with cached shared handler results
- **AND** a second audit is started
- **THEN** the second audit SHALL re-execute all shared handlers fresh
