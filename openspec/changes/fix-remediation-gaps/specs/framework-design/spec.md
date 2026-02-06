## MODIFIED Requirements

### Requirement: Manual remediation type in RemediationConfig
The `RemediationConfig` schema SHALL include an optional `manual` field of type `ManualRemediationConfig`, alongside the existing `file_create`, `exec`, and `api_call` fields.

#### Scenario: Manual field in schema
- **WHEN** a TOML control defines `[controls."ID".remediation.manual]`
- **THEN** the framework SHALL parse it into `RemediationConfig.manual` as a `ManualRemediationConfig` instance

#### Scenario: Manual type in executor dispatch
- **WHEN** the executor's `execute()` method processes a `RemediationConfig`
- **THEN** it SHALL check for `config.manual` after checking `file_create`, `exec`, `api_call`, and before the legacy `handler` fallback
- **AND** if `config.manual` is present, return a successful result with guidance

### Requirement: FileCreateRemediation existing-file messaging
The `file_create` executor SHALL return `success=True` with `remediation_type="file_create_skipped"` when the target file already exists and `overwrite=false`, instead of returning `success=False`.

#### Scenario: File exists and overwrite is false
- **WHEN** a `file_create` remediation targets a path that already exists
- **AND** `overwrite` is `false`
- **THEN** the executor SHALL return `RemediationResult` with `success=True`, `remediation_type="file_create_skipped"`, and message "File already exists — control may already be satisfied"
- **AND** the `details` dict SHALL include `path`, `overwrite`, and `note` fields

#### Scenario: File exists and overwrite is true
- **WHEN** a `file_create` remediation targets a path that already exists
- **AND** `overwrite` is `true`
- **THEN** the executor SHALL overwrite the file and return `success=True` with `remediation_type="file_create"` (unchanged behavior)

## ADDED Requirements

### Requirement: ManualRemediationConfig schema
The framework SHALL define a `ManualRemediationConfig` Pydantic model with the following fields.

#### Scenario: Schema fields
- **WHEN** a `ManualRemediationConfig` is instantiated
- **THEN** it SHALL have: `steps` (required `list[str]`), `docs_url` (optional `str`, default `None`), and `context_hints` (optional `list[str]`, default empty list)

### Requirement: generate_threat_model file writing
The `generate_threat_model` MCP tool SHALL accept an optional `output_path` parameter that, when provided, writes the generated content to the specified file path.

#### Scenario: output_path provided
- **WHEN** `generate_threat_model` is called with `output_path="THREAT_MODEL.md"`
- **THEN** the tool SHALL write the generated threat model content to `{local_path}/{output_path}`
- **AND** return a confirmation message indicating the file was written and its path

#### Scenario: output_path not provided
- **WHEN** `generate_threat_model` is called without `output_path`
- **THEN** the tool SHALL return the generated content as a string (unchanged behavior)

#### Scenario: output_path file already exists
- **WHEN** `generate_threat_model` is called with `output_path` pointing to an existing file
- **THEN** the tool SHALL overwrite the file, since the threat model is a generated analysis, not a user-authored document

### Requirement: New file_create remediation templates
The TOML configuration SHALL define templates and `file_create` remediation blocks for controls where the fix is creating a standard project file.

#### Scenario: README template
- **WHEN** control `OSPS-DO-01.01` (HasReadme) fails
- **THEN** a `file_create` remediation SHALL be available that creates `README.md` from a minimal template containing the project name and placeholder sections

#### Scenario: LICENSE template
- **WHEN** control `OSPS-LE-01.01` (HasLicense) fails
- **THEN** a `file_create` remediation SHALL be available that creates `LICENSE` from an MIT template using `$YEAR` and `$OWNER` substitution

#### Scenario: THREAT_MODEL template
- **WHEN** control `OSPS-SA-03.02` (ThreatModel) fails
- **THEN** a `file_create` remediation SHALL be available that creates `THREAT_MODEL.md` from a minimal STRIDE-based template with placeholder sections

#### Scenario: Gitignore secrets template
- **WHEN** control `OSPS-BR-07.01` (GitignoreSecrets) fails
- **THEN** a `file_create` remediation SHALL be available that creates or augments `.gitignore` with common secret file patterns (`.env`, `*.pem`, `*.key`, `credentials.json`)

### Requirement: Status checks remediation via api_call
Control `OSPS-QA-03.01` (RequiredStatusChecks) SHALL have a declarative `api_call` remediation that configures required status checks on the default branch.

#### Scenario: Status checks with context
- **WHEN** the `ci.required_checks` context key is confirmed
- **THEN** the remediation SHALL call the GitHub branch protection API to set the confirmed check names as required status checks

#### Scenario: Status checks without context
- **WHEN** the `ci.required_checks` context key is not confirmed
- **THEN** the remediation SHALL be skipped with a message indicating that check names are required as context
