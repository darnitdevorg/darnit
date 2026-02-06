## ADDED Requirements

### Requirement: Manual remediation type exists
The framework SHALL support a `manual` remediation type in TOML control definitions. A manual remediation provides structured human-readable guidance for controls that cannot be automated.

#### Scenario: Manual remediation defined in TOML
- **WHEN** a control defines `[controls."ID".remediation.manual]` with `steps` and optional `docs_url`
- **THEN** the framework SHALL parse it into a `ManualRemediationConfig` with fields: `steps` (list of strings), `docs_url` (optional string), and `context_hints` (optional list of strings)

#### Scenario: Manual remediation coexists with automated types
- **WHEN** a control defines both `manual` and another remediation type (e.g., `file_create`)
- **THEN** the executor SHALL attempt the automated type first and fall back to manual guidance only if the automated type is not present or not applicable

### Requirement: Executor returns guidance for manual remediations
The remediation executor SHALL return a successful result containing the manual guidance steps when a `manual` remediation block is the active remediation type for a control.

#### Scenario: Executor processes manual remediation
- **WHEN** the executor encounters a control with only a `manual` remediation block
- **THEN** it SHALL return a `RemediationResult` with `success=True`, `remediation_type="manual"`, and `details` containing the `steps`, `docs_url`, and `context_hints` from the config

#### Scenario: Dry run of manual remediation
- **WHEN** the executor processes a manual remediation in dry-run mode
- **THEN** it SHALL return the same result as non-dry-run mode, since manual remediations do not modify the system

### Requirement: Manual remediations appear in MCP tool output
The `remediate_audit_findings` MCP tool SHALL include manual remediations in its output, clearly distinguished from automated remediations.

#### Scenario: MCP tool surfaces manual guidance
- **WHEN** `remediate_audit_findings` processes a control with a manual remediation
- **THEN** the output SHALL include the control ID, the manual steps, the docs URL, and a marker indicating `type: manual`

#### Scenario: MCP tool distinguishes manual from automated
- **WHEN** `remediate_audit_findings` returns results for a mix of automated and manual remediations
- **THEN** each result SHALL include a `remediation_type` field that is either an automated type name (e.g., `file_create`, `api_call`) or `manual`

### Requirement: Context hints document automation path
Manual remediation blocks MAY include a `context_hints` field listing context keys that, if confirmed, would enable future automation of the control.

#### Scenario: Context hints present
- **WHEN** a manual remediation includes `context_hints = ["ci.required_checks", "ci.provider"]`
- **THEN** the executor SHALL include these hints in the result details under `context_hints`
- **AND** the MCP tool MAY use these hints to suggest context collection to the AI

#### Scenario: No context hints
- **WHEN** a manual remediation omits `context_hints`
- **THEN** the executor SHALL treat it as an empty list and not include the field in output
