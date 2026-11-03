## ADDED Requirements

### Requirement: Attestation module lives in implementation package
The attestation module (predicate builder, generator, signing) SHALL reside in the implementation package, not the framework. The framework SHALL NOT contain hardcoded predicate types, specification URLs, or assessor names.

#### Scenario: Attestation code in darnit-baseline
- **WHEN** the `generate_attestation` MCP tool is invoked
- **THEN** the tool handler in `darnit_baseline/tools.py` SHALL call attestation code from `darnit_baseline/attestation/`
- **AND** SHALL NOT import from `darnit.attestation`

#### Scenario: No attestation module in framework
- **WHEN** searching the `packages/darnit/src/darnit/` source tree
- **THEN** the `attestation/` directory SHALL NOT exist

#### Scenario: Predicate type is implementation-defined
- **WHEN** an attestation is generated
- **THEN** the predicate type URI SHALL come from the implementation package
- **AND** SHALL NOT be hardcoded in the framework

### Requirement: Threat model module lives in implementation package
The threat model module (STRIDE analysis, pattern library, generators) SHALL reside in the implementation package.

#### Scenario: Threat model code in darnit-baseline
- **WHEN** the `generate_threat_model` MCP tool is invoked
- **THEN** the tool handler in `darnit_baseline/tools.py` SHALL call threat model code from `darnit_baseline/threat_model/`
- **AND** SHALL NOT import from `darnit.threat_model`

#### Scenario: No threat model module in framework
- **WHEN** searching the `packages/darnit/src/darnit/` source tree
- **THEN** the `threat_model/` directory SHALL NOT exist

### Requirement: Implementation registers all its MCP tool handlers
All MCP tool handlers specific to an implementation SHALL be registered via the implementation's `register_handlers()` method. The framework SHALL NOT define tool handler functions for implementation-specific features.

#### Scenario: Attestation and threat model tools registered by implementation
- **WHEN** the darnit-baseline implementation's `register_handlers()` is called
- **THEN** handlers for `generate_attestation` and `generate_threat_model` SHALL be registered
- **AND** those handlers SHALL be importable from `darnit_baseline`

#### Scenario: Framework builtin tools remain generic
- **WHEN** the framework's built-in MCP tools are loaded
- **THEN** only generic tools SHALL be present (audit, list_controls, remediate)
- **AND** no implementation-specific tools SHALL be built into the framework

### Requirement: LLM directive prefix on get_pending_data
The `get_pending_data` tool SHALL prepend a plaintext LLM directive block before the JSON payload when the response includes a question batch to constrain calling-LLM behavior.

#### Scenario: Directive prepended to response
- **WHEN** `get_pending_data` returns pending context questions
- **THEN** the response string SHALL start with a plaintext directive block before the JSON when directive output is enabled
- **AND** the directive SHALL instruct the caller to show candidates as unconfirmed and pass `ask_user_batch` to AskUserQuestion without changing its questions or options

#### Scenario: Directive not prepended when no pending context
- **WHEN** `get_pending_data` returns no pending questions (status: "complete")
- **THEN** the response SHALL NOT include the directive block

#### Scenario: Directive includes next-step instruction
- **WHEN** the directive block is prepended
- **THEN** it SHALL instruct the caller to call `confirm_project_data` with the user's answer and the repository's owner and name
- **AND** it SHALL instruct the caller to call `get_pending_data` again for the next batch

### Requirement: Hardened get_pending_data docstring
The MCP tool docstring for `get_pending_data` SHALL define a behavioral contract for LLM callers, not merely describe the return format.

#### Scenario: Docstring defines batch usage
- **WHEN** the `get_pending_data` tool description is read by an LLM
- **THEN** the docstring SHALL state that the tool returns up to four questions per batch by default
- **AND** SHALL state that the caller shows unconfirmed candidates before asking the questions through AskUserQuestion
- **AND** SHALL describe the loop: call `get_pending_data` → present batch → call `confirm_project_data` → repeat

### Requirement: Presentation hint included in question payload
The `get_pending_data` question JSON SHALL include `presentation_hint` when available, so the calling LLM knows the exact format to use.

#### Scenario: Boolean question includes hint
- **WHEN** a pending context item has type `boolean`
- **THEN** the question JSON SHALL include `"presentation_hint": "[y/N]"` (or the explicitly configured hint)
- **AND** the calling LLM SHALL use this hint when formatting the prompt

#### Scenario: Enum question includes hint
- **WHEN** a pending context item has type `enum`
- **AND** the definition has `allowed_values` or `values`
- **THEN** the question JSON SHALL include a `presentation_hint` (explicit or auto-generated)

#### Scenario: Free text question with no hint
- **WHEN** a pending context item has type `string` and no `presentation_hint` is configured
- **THEN** the question JSON SHALL NOT include a `presentation_hint` field (or it SHALL be `null`)
