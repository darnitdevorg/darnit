# .project/ Integration - CNCF Spec Updates

## MODIFIED Requirements

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

## ADDED Requirements

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
