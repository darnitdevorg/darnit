## MODIFIED Requirements

### Requirement: Canonical audit function
The framework SHALL provide a single canonical function `run_sieve_audit()` as the entry point for all sieve-based verification workflows. The report formatter SHALL accept implementation-provided branding and remediation mappings.

#### Scenario: Canonical audit function exists
- **WHEN** any code path needs to run sieve verification
- **THEN** it SHALL call `run_sieve_audit()` from `darnit.tools.audit`
- **AND** SHALL NOT duplicate the sieve loop inline

#### Scenario: No duplicate audit loops
- **WHEN** searching the codebase for `SieveOrchestrator` usage
- **THEN** only `run_sieve_audit()` SHALL instantiate and use it

#### Scenario: Report formatter is parameterized
- **WHEN** `format_results_markdown()` is called
- **THEN** it SHALL accept optional `report_title` and `remediation_map` parameters
- **AND** SHALL NOT contain hardcoded implementation-specific control IDs or branding

### Requirement: Framework contains no implementation-specific code
The darnit framework package SHALL NOT contain code, modules, or string literals specific to any particular compliance implementation.

#### Scenario: No OSPS control IDs in framework
- **WHEN** the `packages/darnit/src/darnit/` source tree is searched
- **THEN** no hardcoded OSPS control ID patterns (e.g., `OSPS-AC-03.01`) SHALL exist in executable code

#### Scenario: No attestation or threat model modules in framework
- **WHEN** the `packages/darnit/src/darnit/` directory listing is checked
- **THEN** `attestation/` and `threat_model/` directories SHALL NOT exist

#### Scenario: No hardcoded implementation preference in discovery
- **WHEN** `get_default_implementation()` is called
- **THEN** it SHALL return the first discovered implementation
- **AND** SHALL NOT hardcode a preference for any specific implementation name
