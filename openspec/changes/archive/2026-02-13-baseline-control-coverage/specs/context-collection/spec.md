# Context Collection — Delta Specification

## ADDED Requirements

### Requirement: SBOM tool context definition
The implementation SHALL define a `[context.sbom_tool]` entry for the user's preferred SBOM generation tool.

#### Scenario: SBOM tool context definition in TOML
- **WHEN** the TOML config is loaded
- **THEN** it SHALL contain a `[context.sbom_tool]` definition with:
  - `type = "enum"`
  - `values` including `syft`, `cyclonedx`, `trivy`, `other`
  - `store_as = "tooling.sbom_tool"`
  - `affects` referencing OSPS-QA-02.02

#### Scenario: SBOM tool context used in workflow template
- **WHEN** the `sbom_tool` context has been confirmed by the user
- **AND** the SBOM workflow template is rendered
- **THEN** the template SHALL use the confirmed tool in the generated workflow

### Requirement: SAST tool context definition
The implementation SHALL define a `[context.sast_tool]` entry for the user's preferred SAST tool.

#### Scenario: SAST tool context definition in TOML
- **WHEN** the TOML config is loaded
- **THEN** it SHALL contain a `[context.sast_tool]` definition with:
  - `type = "enum"`
  - `values` including `codeql`, `semgrep`, `sonarqube`, `other`
  - `store_as = "tooling.sast_tool"`
  - `affects` referencing OSPS-VM-06.02

#### Scenario: SAST tool context used in workflow template
- **WHEN** the `sast_tool` context has been confirmed by the user
- **AND** the SAST workflow template is rendered
- **THEN** the template SHALL use the confirmed tool in the generated workflow

### Requirement: Preferred license context definition
The implementation SHALL define a `[context.preferred_license]` entry for the project's license identifier.

#### Scenario: License context definition in TOML
- **WHEN** the TOML config is loaded
- **THEN** it SHALL contain a `[context.preferred_license]` definition with:
  - `type = "string"`
  - `store_as = "legal.license"`
  - `affects` referencing OSPS-LE-01.01 and OSPS-LE-02.01
  - `auto_detect = true` (detect from existing LICENSE file)

#### Scenario: License context auto-detection
- **WHEN** auto-detection runs for `preferred_license`
- **AND** a LICENSE file exists in the repository
- **THEN** the system SHALL attempt to identify the SPDX license identifier from the file content
