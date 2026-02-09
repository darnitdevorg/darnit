## ADDED Requirements

### Requirement: Controls can declare applicability conditions
A control MAY declare a `when` clause that specifies project context conditions under which the control is applicable. When the condition evaluates to false, the control SHALL be reported as N/A (not applicable) without running any handler pipeline phases.

#### Scenario: Control skipped when condition is false
- **WHEN** control OSPS-BR-02.01 declares `when = { has_releases = true }`
- **AND** the project context has `has_releases = false`
- **THEN** the control SHALL produce an N/A result
- **AND** the result message SHALL indicate the condition that was not met

#### Scenario: Control runs when condition is true
- **WHEN** control OSPS-BR-02.01 declares `when = { has_releases = true }`
- **AND** the project context has `has_releases = true`
- **THEN** the control SHALL run its handler pipeline normally

#### Scenario: Control runs when context key is missing
- **WHEN** control OSPS-BR-02.01 declares `when = { has_releases = true }`
- **AND** the project context does NOT contain `has_releases`
- **THEN** the control SHALL run its handler pipeline normally
- **AND** SHALL NOT be marked N/A
- **AND** a debug-level log message SHALL note the missing context key

### Requirement: When clause supports boolean, string equality, and list membership
The `when` clause SHALL support: boolean context values (`when = { key = true }`), string equality (`when = { key = "value" }`), and list membership (`when = { key = ["val1", "val2"] }` meaning key must be one of the listed values).

#### Scenario: Boolean condition
- **WHEN** a control declares `when = { is_library = true }`
- **AND** project context has `is_library = true`
- **THEN** the control SHALL run normally

#### Scenario: String equality condition
- **WHEN** a control declares `when = { ci_provider = "github" }`
- **AND** project context has `ci_provider = "github"`
- **THEN** the control SHALL run normally

#### Scenario: List membership condition
- **WHEN** a control declares `when = { ci_provider = ["github", "gitlab"] }`
- **AND** project context has `ci_provider = "gitlab"`
- **THEN** the control SHALL run normally

#### Scenario: Multiple conditions are AND-ed
- **WHEN** a control declares `when = { has_releases = true, is_library = true }`
- **AND** project context has `has_releases = true` and `is_library = false`
- **THEN** the control SHALL produce an N/A result

### Requirement: When clause determines applicability, not correctness
The `when` clause SHALL only determine whether a control is relevant to the project. It SHALL NOT be used to bypass verification. Context values used in `when` clauses are about project characteristics (has releases, is a library, CI provider), not about compliance state.

#### Scenario: Context says file exists but when is about project type
- **WHEN** a control has `when = { has_releases = true }`
- **AND** the project has `has_releases = true`
- **THEN** the control SHALL still run its full handler pipeline
- **AND** SHALL NOT auto-PASS based on any context value

### Requirement: N/A results from when clauses are reported separately
When controls are marked N/A due to `when` conditions, the audit report SHALL list them in a separate "Not Applicable" section distinct from PASS, FAIL, and WARN results.

#### Scenario: Audit report shows N/A controls
- **WHEN** an audit produces results with some controls marked N/A
- **THEN** the markdown report SHALL include a "Not Applicable" section
- **AND** each N/A control SHALL show the unmet condition
