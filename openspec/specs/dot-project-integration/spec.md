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
The framework SHALL map .project/ sections to standardized context variables for use in checks.

#### Scenario: Security section mapping
- **WHEN** `.project/project.yaml` contains a `security` section with `policy.path`
- **THEN** the context variable `project.security.policy_path` SHALL contain that path
- **AND** checks for SECURITY.md SHALL use this path

#### Scenario: Governance section mapping
- **WHEN** `.project/project.yaml` contains a `governance` section
- **THEN** the context SHALL include `project.governance.codeowners_path`, `project.governance.contributing_path`, etc.

#### Scenario: Maintainers mapping
- **WHEN** `.project/project.yaml` or `.project/maintainers.yaml` contains maintainer information
- **THEN** the context variable `project.maintainers` SHALL contain the list of maintainers

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
