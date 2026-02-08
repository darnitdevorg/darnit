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
