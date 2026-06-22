# .project/ Integration Specification

## ADDED Requirements

### Requirement: Read .project/ metadata
The framework SHALL read project metadata from `.project/project.yaml` following the CNCF .project/ specification.

#### Scenario: Valid .project/ file exists
- **WHEN** a repository contains `.project/project.yaml`
- **THEN** the framework SHALL parse it and make all fields available in the sieve context

#### Scenario: No .project/ file exists
- **WHEN** a repository does not contain `.project/project.yaml`
- **THEN** the framework SHALL continue with heuristic-based context detection
- **AND** SHALL NOT fail or error

#### Scenario: Invalid .project/ file
- **WHEN** `.project/project.yaml` exists but contains invalid YAML
- **THEN** the framework SHALL log a warning
- **AND** SHALL continue with heuristic-based context detection

### Requirement: Map .project/ sections to check context
The framework SHALL map .project/ sections to standardized context variables for use in checks, including new variables for structured security contact and maintainer team data.

#### Scenario: Security section mapping
- **WHEN** `.project/project.yaml` contains a `security` section with `policy.path`
- **THEN** the context variable `project.security.policy_path` SHALL contain that path
- **AND** checks for SECURITY.md SHALL use this path

#### Scenario: Governance section mapping
- **WHEN** `.project/project.yaml` contains a `governance` section
- **THEN** the context SHALL include `project.governance.codeowners_path`, `project.governance.contributing_path`, etc.

#### Scenario: Maintainers mapping
- **WHEN** `.project/project.yaml` or `.project/maintainers.yaml` contains maintainer information
- **THEN** the context variable `project.maintainers` SHALL contain the flat list of maintainer handles
- **AND** the context variable `project.maintainer_teams` SHALL contain team names when teams-based format is used
- **AND** the context variable `project.maintainer_org` SHALL contain the org identifier when present
- **AND** the context variable `project.maintainer_project_id` SHALL contain the project ID when present

#### Scenario: Struct security contact mapping
- **WHEN** `security.contact` is a struct with `email` and `advisory_url` fields
- **THEN** the context variable `project.security.contact` SHALL contain the email address
- **AND** the context variable `project.security.contact_email` SHALL contain the email address
- **AND** the context variable `project.security.advisory_url` SHALL contain the advisory URL

#### Scenario: String security contact mapping (backward compat)
- **WHEN** `security.contact` is a plain string
- **THEN** the context variable `project.security.contact` SHALL contain that string
- **AND** `project.security.advisory_url` SHALL NOT be set

### Requirement: Parse security contact as struct or string
The .project/ reader SHALL support `security.contact` as either a CNCF struct (with `email` and `advisory_url` fields) or a legacy plain string.

#### Scenario: Contact is a struct
- **WHEN** `.project/project.yaml` contains `security.contact` as a mapping with `email` and `advisory_url`
- **THEN** the framework SHALL parse it into a `SecurityContact` dataclass
- **AND** the `email` field SHALL contain the email address
- **AND** the `advisory_url` field SHALL contain the advisory URL

#### Scenario: Contact is a plain string
- **WHEN** `.project/project.yaml` contains `security.contact` as a plain string
- **THEN** the framework SHALL preserve it as a string
- **AND** existing behavior SHALL be unchanged

#### Scenario: Contact struct has unknown fields
- **WHEN** `security.contact` struct contains fields beyond `email` and `advisory_url`
- **THEN** the framework SHALL preserve unknown fields in `_extra`
- **AND** SHALL NOT fail

### Requirement: Parse teams-based maintainers.yaml
The .project/ reader SHALL support the CNCF teams-based `maintainers.yaml` format alongside existing flat-list and dict-with-handle formats.

#### Scenario: Teams-based format
- **WHEN** `maintainers.yaml` contains `teams` with nested `members` arrays
- **THEN** the framework SHALL parse `MaintainerTeam` objects with name and members
- **AND** each member SHALL be a `MaintainerEntry` with handle, email, role, title, and name fields
- **AND** the flat `maintainers` list SHALL contain deduplicated handles from all teams

#### Scenario: Teams format with project metadata
- **WHEN** `maintainers.yaml` contains `project_id` and `org` fields alongside `teams`
- **THEN** the framework SHALL populate `maintainer_project_id` and `maintainer_org` on the config

#### Scenario: Teams with string members
- **WHEN** a team's `members` array contains plain strings instead of dicts
- **THEN** the framework SHALL treat each string as a handle
- **AND** SHALL create `MaintainerEntry` objects with only the handle populated

#### Scenario: Flat list format (backward compat)
- **WHEN** `maintainers.yaml` contains a flat list of strings
- **THEN** the framework SHALL parse it the same as before
- **AND** `maintainer_teams` SHALL be empty

#### Scenario: Dict-with-handle format (backward compat)
- **WHEN** `maintainers.yaml` contains a list of dicts with `handle` fields
- **THEN** the framework SHALL parse handles into the flat `maintainers` list
- **AND** SHALL populate `maintainer_entries` with structured data including email, name, role, and title

#### Scenario: Handle deduplication across teams
- **WHEN** the same handle appears in multiple teams
- **THEN** the flat `maintainers` list SHALL contain that handle only once

### Requirement: Pydantic schema supports struct contact
The Pydantic config schema SHALL accept `security.contact` as either a `SecurityContactModel` struct, an `EmailStr`, or a plain string.

#### Scenario: Pydantic parses struct contact
- **WHEN** a `.project.yaml` is loaded via Pydantic with `security.contact` as a mapping
- **THEN** it SHALL be parsed as a `SecurityContactModel` with `email` and `advisory_url` fields

#### Scenario: Pydantic parses string contact
- **WHEN** a `.project.yaml` is loaded via Pydantic with `security.contact` as a string
- **THEN** it SHALL be accepted as an `EmailStr` or plain string

#### Scenario: get_security_contact accessor
- **WHEN** `get_security_contact()` is called on a `ProjectConfig` with a struct contact
- **THEN** it SHALL return the `email` field from the `SecurityContactModel`

### Requirement: Tolerate unknown fields
The .project/ reader SHALL tolerate unknown fields for forward compatibility with spec evolution.

#### Scenario: Unknown top-level field
- **WHEN** `.project/project.yaml` contains a field not in the known schema
- **THEN** the framework SHALL parse successfully
- **AND** SHALL preserve the unknown field in the parsed data

#### Scenario: Unknown nested field
- **WHEN** a known section contains an unknown nested field
- **THEN** the framework SHALL parse successfully without error

### Requirement: Support extension mechanism
The framework SHALL support the .project/ extension mechanism for tool-specific configuration.

#### Scenario: Darnit extension present
- **WHEN** `.project/project.yaml` contains `extensions.darnit` section
- **THEN** the framework SHALL read tool-specific configuration from that section
- **AND** SHALL make it available as `project.extensions.darnit`

#### Scenario: No extension present
- **WHEN** `.project/project.yaml` does not contain an `extensions` section
- **THEN** the framework SHALL use default configuration

### Requirement: Write-back after remediation
The framework SHALL update `.project/project.yaml` when remediation creates artifacts that should be tracked.

#### Scenario: SECURITY.md created
- **WHEN** remediation creates `SECURITY.md`
- **THEN** the framework SHALL update `.project/project.yaml` to set `security.policy.path = "SECURITY.md"`
- **AND** SHALL preserve existing content and comments

#### Scenario: CODEOWNERS created
- **WHEN** remediation creates `.github/CODEOWNERS`
- **THEN** the framework SHALL update `.project/project.yaml` to set `governance.codeowners.path = ".github/CODEOWNERS"`

#### Scenario: .project/ does not exist for write-back
- **WHEN** remediation wants to write back but `.project/project.yaml` does not exist
- **THEN** the framework SHALL create `.project/project.yaml` with the relevant fields
- **AND** SHALL include `schema_version` field

### Requirement: Validate against upstream schema
The framework SHALL validate .project/ files against the CNCF specification.

#### Scenario: Required fields missing
- **WHEN** `.project/project.yaml` is missing required fields (name, repositories)
- **THEN** the framework SHALL log a warning with specific missing fields
- **AND** SHALL continue with available data

#### Scenario: Valid file
- **WHEN** `.project/project.yaml` contains all required fields with valid values
- **THEN** the framework SHALL parse without warnings

### Requirement: Track upstream spec changes
The project SHALL monitor the upstream CNCF .project/ specification for changes.

#### Scenario: CI check for spec changes
- **WHEN** CI runs on a schedule (weekly)
- **THEN** it SHALL check if `types.go` in cncf/automation has changed
- **AND** SHALL create an issue if changes are detected

#### Scenario: Document targeted spec version
- **WHEN** the framework is released
- **THEN** documentation SHALL specify which .project/ spec version is supported
