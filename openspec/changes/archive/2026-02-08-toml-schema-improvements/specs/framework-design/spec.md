## ADDED Requirements

### Requirement: Deterministic handlers can reference locator discovery lists
A deterministic handler invocation MAY use `use_locator = true` instead of specifying `files` directly. When `use_locator = true` is set, the framework SHALL use the control's `locator.discover` list as the handler's `files` parameter.

#### Scenario: Handler uses locator for file existence check
- **WHEN** a control defines `locator = { discover = ["README.md", "README.rst"] }`
- **AND** its deterministic handler defines `{ handler = "file_exists", use_locator = true }`
- **THEN** the framework SHALL check for existence of `["README.md", "README.rst"]`
- **AND** the behavior SHALL be identical to `{ handler = "file_exists", files = ["README.md", "README.rst"] }`

#### Scenario: use_locator without locator config
- **WHEN** a deterministic handler defines `use_locator = true`
- **AND** the control has no `locator` configuration
- **THEN** the framework SHALL log a warning
- **AND** SHALL return INCONCLUSIVE for that handler

#### Scenario: use_locator with explicit files
- **WHEN** a deterministic handler defines both `use_locator = true` and `files = ["OTHER.md"]`
- **THEN** `files` SHALL take precedence
- **AND** `use_locator` SHALL be ignored

### Requirement: Auto-derived on_pass from locator
When a control has a `locator` with `project_path` AND a deterministic `file_exists` handler (or `use_locator = true`), AND the control does NOT have an explicit `on_pass` configuration, the framework SHALL auto-derive an `on_pass.project_update` that sets the `locator.project_path` to the path of the found file.

#### Scenario: Auto-derived on_pass when file found
- **WHEN** a control has `locator.project_path = "documentation.readme"`
- **AND** has a deterministic `file_exists` handler that finds `README.md`
- **AND** has no explicit `on_pass` configuration
- **THEN** the framework SHALL behave as if `on_pass.project_update = { "documentation.readme.path" = "README.md" }`

#### Scenario: Explicit on_pass takes precedence
- **WHEN** a control has both a locator with `project_path` and an explicit `on_pass` configuration
- **THEN** the explicit `on_pass` SHALL be used
- **AND** auto-derivation SHALL NOT occur

### Requirement: Template variables support context references
Template variable substitution SHALL support `${context.<key>}` references that resolve to confirmed context values from `.project/project.yaml`, and `${project.<dotted.path>}` references that resolve to project configuration values.

#### Scenario: Context variable in template
- **WHEN** a template contains `${context.governance_model}`
- **AND** the project context has `governance_model = "bdfl"`
- **THEN** the rendered template SHALL contain `bdfl` in place of the reference

#### Scenario: Unresolved context variable
- **WHEN** a template contains `${context.unknown_key}`
- **AND** the project context does NOT contain `unknown_key`
- **THEN** the rendered template SHALL replace the reference with an empty string
- **AND** SHALL log a debug-level message about the unresolved reference

#### Scenario: Project path variable in template
- **WHEN** a template contains `${project.security.policy.path}`
- **AND** `.project/project.yaml` has `security.policy.path = "SECURITY.md"`
- **THEN** the rendered template SHALL contain `SECURITY.md` in place of the reference

### Requirement: Context informs locators but never overrides verification
Project context from `.project/` SHALL be used to inform WHERE the sieve looks for evidence (via `locator.project_path`), but SHALL NOT be used to determine WHETHER a control passes. Even when context indicates a file exists at a given path, the sieve SHALL still verify the file's existence and content through its normal handler pipeline.

#### Scenario: Context points to file that no longer exists
- **WHEN** `.project/project.yaml` has `security.policy.path = "SECURITY.md"`
- **AND** `SECURITY.md` does not exist in the repository
- **THEN** the deterministic handler SHALL report FAIL (file not found)
- **AND** the context value SHALL NOT cause an automatic PASS

#### Scenario: Context points to file with invalid content
- **WHEN** `.project/project.yaml` has `security.policy.path = "SECURITY.md"`
- **AND** `SECURITY.md` exists but contains only `# placeholder`
- **THEN** the deterministic handler SHALL report PASS (file exists)
- **AND** the pattern handler SHALL evaluate whether the content is valid
- **AND** the pattern handler MAY report FAIL if content patterns do not match

#### Scenario: Locator uses context to prioritize search
- **WHEN** a control has `locator.project_path = "security.policy"`
- **AND** `.project/project.yaml` has `security.policy.path = "docs/SECURITY.md"`
- **THEN** the locator SHALL check `docs/SECURITY.md` first
- **AND** SHALL still fall back to `locator.discover` patterns if the context path fails

### Requirement: Handler registry enables pluggable verification, context gathering, and remediation
The framework SHALL provide a handler registry where handlers are registered by name with a phase affinity. Core SHALL register built-in handlers. Implementations SHALL register domain-specific handlers via the existing `ComplianceImplementation.register_handlers()` method.

#### Scenario: Core registers built-in handlers
- **WHEN** the framework initializes
- **THEN** the handler registry SHALL contain built-in handlers: `file_exists`, `exec`, `regex`, `llm_eval`, `manual_steps`, `file_create`, `api_call`, `project_update`

#### Scenario: Implementation registers custom handler
- **WHEN** an implementation calls `registry.register("scorecard", phase="deterministic", handler_fn=scorecard_handler)`
- **THEN** controls MAY reference `{ handler = "scorecard", ... }` in their deterministic phase

#### Scenario: Handler used in wrong phase
- **WHEN** a control references a handler in a phase different from its registered affinity
- **THEN** the framework SHALL log a warning
- **AND** SHALL still execute the handler (the implementation author may have good reasons)
