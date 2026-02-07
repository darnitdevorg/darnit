## ADDED Requirements

### Requirement: Canonical Audit Pipeline
All code that runs sieve-based compliance audits MUST delegate to the canonical `run_sieve_audit()` function in `darnit.tools.audit`. No other module SHALL reimplement the sieve verification loop (iterating controls, constructing `CheckContext`, calling `SieveOrchestrator.verify()`).

This requirement prevents the duplication pattern where multiple entry points independently implement the audit loop, causing feature drift and inconsistent behavior.

#### Scenario: New audit entry point
- **WHEN** a developer (human or LLM) adds a new MCP tool or CLI command that runs compliance audits
- **THEN** it MUST call `run_sieve_audit()` from `darnit.tools.audit`
- **AND** it MUST NOT contain its own `for control in controls: orchestrator.verify(control, context)` loop

#### Scenario: Implementation-specific audit tool
- **WHEN** an implementation package (e.g., `darnit-baseline`) provides its own audit MCP tool
- **THEN** it MUST delegate to `run_sieve_audit()` for the sieve execution
- **AND** it MAY add implementation-specific pre-processing (config loading, tag filtering) and post-processing (attestation, custom formatting)

### Requirement: No duplicate utility functions within a package
A given function signature and purpose MUST NOT appear more than once within the `darnit` framework package. When a utility function is needed in multiple modules, it SHALL be defined in one canonical location and imported elsewhere.

#### Scenario: Identifying duplication
- **WHEN** two functions in `packages/darnit/` have the same name and similar behavior
- **THEN** one SHALL be deleted and callers SHALL import from the canonical location
