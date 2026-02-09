## ADDED Requirements

### Requirement: Passes SHALL be a flat ordered list of handler invocations
The `passes` field on a control SHALL be a flat ordered list of `HandlerInvocation` entries. The orchestrator SHALL iterate the list in order and stop at the first conclusive result. There SHALL NOT be phase-bucketed fields (`deterministic`, `pattern`, `llm`, `manual`) on the passes config.

#### Scenario: Control with multiple handlers in order
- **WHEN** a control defines `passes` as an ordered list with entries for `file_exists`, `exec`, and `manual_steps`
- **THEN** the orchestrator SHALL execute them in list order
- **AND** SHALL stop at the first conclusive (PASS or FAIL) result
- **AND** SHALL only reach `manual_steps` if all preceding handlers were inconclusive

#### Scenario: Single-handler control
- **WHEN** a control defines `passes` with a single handler invocation
- **THEN** the orchestrator SHALL execute that handler and return its result

#### Scenario: Handler reports its own confidence
- **WHEN** a handler returns a result
- **THEN** the result SHALL include a confidence indicator from the handler itself
- **AND** the confidence SHALL NOT be determined by which structural field the handler was placed in

### Requirement: Remediation handlers SHALL be a flat ordered list
The `RemediationConfig` SHALL contain a `handlers` field that is a flat ordered list of `HandlerInvocation` entries. Metadata fields (`requires_context`, `project_update`) SHALL remain as separate fields on `RemediationConfig`.

#### Scenario: Remediation with handler list and metadata
- **WHEN** a control defines `remediation.handlers` as an ordered list alongside `remediation.requires_context`
- **THEN** the executor SHALL check context requirements first
- **AND** SHALL iterate the handler list in order for remediation execution

### Requirement: Legacy typed-pass dispatch SHALL be removed
The orchestrator SHALL NOT contain a legacy typed-pass execution fallback. All verification dispatch SHALL go through the handler invocation list. The legacy typed-pass config models (`DeterministicPassConfig`, `ExecPassConfig`, `PatternPassConfig`, `ManualPassConfig`, `LLMPassConfig`) and their backward compatibility validators SHALL be removed from the schema.

#### Scenario: Control without handler invocations fails gracefully
- **WHEN** a control has no entries in its `passes` list (or no `passes` field)
- **THEN** the orchestrator SHALL return WARN with a message indicating no handler invocations are configured
- **AND** SHALL NOT attempt legacy typed-pass execution

#### Scenario: Legacy typed-pass TOML format is rejected at load time
- **WHEN** a TOML control defines passes in legacy typed format (e.g., `passes.exec = { command = [...] }`)
- **THEN** the schema SHALL reject the config with a validation error
- **AND** the error message SHALL indicate the handler invocation list format is required

#### Scenario: Remediation executor only dispatches handler invocations
- **WHEN** the executor receives a `RemediationConfig` for a control
- **THEN** it SHALL only iterate the `handlers` list via handler dispatch
- **AND** SHALL NOT check legacy typed fields (`file_create`, `api_call`, `manual`, `exec`)

### Requirement: All openssf-baseline controls SHALL use handler invocation format
After migration, all controls in the openssf-baseline implementation TOML SHALL use handler invocation lists for their pass and remediation definitions.

#### Scenario: Full audit uses handler dispatch for all controls
- **WHEN** a full audit is run against the openssf-baseline TOML
- **THEN** every control with pass definitions SHALL have handler invocations in its `passes` list
- **AND** no legacy dispatch path SHALL exist to fall back to

#### Scenario: file_must_exist controls use use_locator
- **WHEN** a control has both `locator.discover` and a `file_exists` handler invocation
- **THEN** the handler invocation SHALL use `use_locator = true` instead of duplicating the file list
- **AND** the `locator.discover` list SHALL be copied into the handler's `files` parameter at load time

### Requirement: Phase-bucketed fields SHALL be removed from PassesConfig and RemediationConfig
The `PassesConfig` model SHALL NOT have separate fields for `deterministic`, `pattern`, `llm`, and `manual`. Instead, `passes` on the control SHALL be `list[HandlerInvocation]`. The `RemediationConfig` model SHALL replace its phase-bucketed fields with a single `handlers: list[HandlerInvocation]` field.

#### Scenario: PassesConfig is a flat list
- **WHEN** the schema parses a control's `passes` field
- **THEN** it SHALL parse it as `list[HandlerInvocation]`
- **AND** SHALL NOT have `deterministic`, `pattern`, `llm`, or `manual` sub-fields

#### Scenario: RemediationConfig uses handlers list
- **WHEN** the schema parses a control's `remediation` field
- **THEN** the handler invocations SHALL be in a `handlers` field as `list[HandlerInvocation]`
- **AND** metadata fields (`requires_context`, `project_update`) SHALL remain as separate fields
