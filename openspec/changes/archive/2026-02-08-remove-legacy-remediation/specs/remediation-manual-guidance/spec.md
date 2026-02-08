## MODIFIED Requirements

### Requirement: Manual remediation type exists
The framework SHALL support a `manual` remediation type in TOML control definitions. A manual remediation provides structured human-readable guidance for controls that cannot be automated. This includes controls that require external tool installation (e.g., GitHub Apps) or platform-level configuration not accessible via API.

#### Scenario: Manual remediation defined in TOML
- **WHEN** a control defines `[controls."ID".remediation.manual]` with `steps` and optional `docs_url`
- **THEN** the framework SHALL parse it into a `ManualRemediationConfig` with fields: `steps` (list of strings), `docs_url` (optional string), and `context_hints` (optional list of strings)

#### Scenario: Manual remediation coexists with automated types
- **WHEN** a control defines both `manual` and another remediation type (e.g., `file_create`)
- **THEN** the executor SHALL attempt the automated type first and fall back to manual guidance only if the automated type is not present or not applicable

#### Scenario: DCO enforcement as manual guidance
- **WHEN** a control for DCO enforcement defines `remediation.manual` with steps covering GitHub App installation and `.github/dco.yml` creation
- **THEN** the executor SHALL return the manual steps including both the app installation URL and the configuration file format

## ADDED Requirements

### Requirement: Template variable substitution in manual steps
Manual remediation steps SHALL support `${owner}` and `${repo}` template variable substitution, enabling steps to include repo-specific URLs (e.g., direct links to GitHub settings pages).

#### Scenario: Manual step with repo-specific URL
- **WHEN** a manual remediation step contains `https://github.com/${owner}/${repo}/settings/branches`
- **THEN** the orchestrator SHALL substitute `${owner}` and `${repo}` with the actual repository owner and name before presenting the step to the user

#### Scenario: Manual step without variables
- **WHEN** a manual remediation step contains no `${...}` variables
- **THEN** the step SHALL be returned unchanged

### Requirement: Manual guidance covers previously automated controls
Controls that were previously remediated by Python functions but cannot be fully automated via TOML declarative types SHALL use `manual` remediation with comprehensive step-by-step guidance.

#### Scenario: Manual remediation replaces Python function
- **WHEN** a control previously dispatched to a legacy Python remediation function is converted to manual guidance
- **THEN** the manual steps SHALL cover all actions the Python function performed
- **AND** the manual steps SHALL include any prerequisite actions (e.g., installing a GitHub App) that the Python function could not perform
