# Policy Document Templates Specification

## ADDED Requirements

### Requirement: SUPPORT.md template
The implementation SHALL provide a `file_create` remediation for OSPS-DO-03.01 that creates a SUPPORT.md file.

#### Scenario: Create SUPPORT.md
- **WHEN** OSPS-DO-03.01 fails (no SUPPORT.md)
- **AND** the user triggers remediation
- **THEN** the system SHALL create `SUPPORT.md` from the `support_template`
- **AND** the template SHALL include sections for getting help, reporting bugs, and community resources

### Requirement: Support scope documentation template
The implementation SHALL provide a `file_create` remediation for OSPS-DO-04.01 that documents support scope and duration.

#### Scenario: Create support scope documentation
- **WHEN** OSPS-DO-04.01 fails (no support scope documentation)
- **AND** the user triggers remediation
- **THEN** the system SHALL append a support scope section to `SUPPORT.md` or create it if missing
- **AND** the template SHALL include supported versions, support duration, and end-of-life policy sections

### Requirement: End-of-support policy template
The implementation SHALL provide a `file_create` remediation for OSPS-DO-05.01 that documents end-of-support policies.

#### Scenario: Create end-of-support documentation
- **WHEN** OSPS-DO-05.01 fails (no end-of-support policy)
- **AND** the user triggers remediation
- **THEN** the system SHALL create or update documentation with an end-of-support policy section
- **AND** the template SHALL include notification process and migration guidance placeholders

### Requirement: Dependency management policy template
The implementation SHALL provide a `file_create` remediation for OSPS-DO-06.01 that documents the dependency management process.

#### Scenario: Create dependency management documentation
- **WHEN** OSPS-DO-06.01 fails (no dependency management documentation)
- **AND** the user triggers remediation
- **THEN** the system SHALL create `docs/DEPENDENCIES.md` from the `dependency_management_template`
- **AND** the template SHALL include sections for dependency policy, update cadence, and vulnerability response

### Requirement: Vulnerability disclosure process template
The implementation SHALL provide a `file_create` remediation for OSPS-VM-01.01 that documents the vulnerability disclosure process.

#### Scenario: Enhance SECURITY.md with disclosure process
- **WHEN** OSPS-VM-01.01 fails (no disclosure process documented)
- **AND** the user triggers remediation
- **AND** SECURITY.md already exists
- **THEN** the system SHALL provide manual steps to add a disclosure process section
- **AND** SHALL include a `docs_url` pointing to disclosure process best practices

#### Scenario: Create SECURITY.md with disclosure section
- **WHEN** OSPS-VM-01.01 fails
- **AND** SECURITY.md does not exist
- **THEN** the system SHALL create SECURITY.md using the existing `security_policy_standard` template which includes a disclosure section

### Requirement: VEX policy template
The implementation SHALL provide a `file_create` remediation for OSPS-VM-04.02 that documents the VEX (Vulnerability Exploitability eXchange) policy.

#### Scenario: Create VEX policy documentation
- **WHEN** OSPS-VM-04.02 fails (no VEX policy)
- **AND** the user triggers remediation
- **THEN** the system SHALL create `docs/VEX-POLICY.md` from the `vex_policy_template`
- **AND** the template SHALL include VEX statement format, assessment criteria, and publication process

### Requirement: SCA policy template
The implementation SHALL provide a `file_create` remediation for OSPS-VM-05.01 that documents the SCA (Software Composition Analysis) policy.

#### Scenario: Create SCA policy documentation
- **WHEN** OSPS-VM-05.01 fails (no SCA policy)
- **AND** the user triggers remediation
- **THEN** the system SHALL create `docs/SCA-POLICY.md` from the `sca_policy_template`
- **AND** the template SHALL include scanning frequency, severity thresholds, and remediation timelines

### Requirement: SAST policy template
The implementation SHALL provide a `file_create` remediation for OSPS-VM-06.01 that documents the SAST (Static Application Security Testing) policy.

#### Scenario: Create SAST policy documentation
- **WHEN** OSPS-VM-06.01 fails (no SAST policy)
- **AND** the user triggers remediation
- **THEN** the system SHALL create `docs/SAST-POLICY.md` from the `sast_policy_template`
- **AND** the template SHALL include scanning triggers, severity handling, and exception process

### Requirement: Templates use variable substitution
All policy document templates SHALL support `$VARIABLE` substitution for project-specific values.

#### Scenario: Project name substitution
- **WHEN** a template contains `$PROJECT_NAME`
- **THEN** the system SHALL substitute it with the detected or configured project name

#### Scenario: Owner and repo substitution
- **WHEN** a template contains `$OWNER` or `$REPO`
- **THEN** the system SHALL substitute them with the detected repository owner and name

### Requirement: Templates do not overwrite existing files
All `file_create` remediations SHALL default to `overwrite = false`.

#### Scenario: Existing file preserved
- **WHEN** the target file already exists
- **AND** `overwrite = false`
- **THEN** the system SHALL skip file creation
- **AND** SHALL report that the file already exists
