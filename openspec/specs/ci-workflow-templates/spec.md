# CI Workflow Templates Specification

### Requirement: CI test workflow template
The implementation SHALL provide a `file_create` remediation for OSPS-QA-06.01 that creates a basic CI test workflow.

#### Scenario: Create CI test workflow
- **WHEN** OSPS-QA-06.01 fails (no CI testing configured)
- **AND** the user triggers remediation
- **THEN** the system SHALL create `.github/workflows/ci.yml` from the `ci_test_workflow` template
- **AND** the workflow SHALL include steps for checkout and a placeholder test command
- **AND** the file SHALL NOT overwrite an existing workflow

#### Scenario: CI check detects existing workflow
- **WHEN** OSPS-QA-06.01 is evaluated
- **THEN** the system SHALL check for `.github/workflows/*.yml` or `.github/workflows/*.yaml` files using a `file_exists` pass
- **AND** SHALL use a `pattern` pass to verify the workflow contains a test-related step

### Requirement: SBOM generation workflow template
The implementation SHALL provide a `file_create` remediation for OSPS-QA-02.02 that creates an SBOM generation workflow.

#### Scenario: Create SBOM workflow
- **WHEN** OSPS-QA-02.02 fails (no SBOM generation)
- **AND** the user triggers remediation
- **THEN** the system SHALL create `.github/workflows/sbom.yml` from the `sbom_workflow` template
- **AND** the template SHALL default to `syft` but support substitution via `$SBOM_TOOL` context variable

#### Scenario: SBOM tool preference from context
- **WHEN** the `sbom_tool` context value is set (e.g., `cyclonedx`)
- **AND** the SBOM workflow remediation executes
- **THEN** the generated workflow SHALL use the user's preferred SBOM tool

### Requirement: SAST workflow template
The implementation SHALL provide a `file_create` remediation for OSPS-VM-06.02 that creates a SAST scanning workflow.

#### Scenario: Create SAST workflow
- **WHEN** OSPS-VM-06.02 fails (no SAST in CI)
- **AND** the user triggers remediation
- **THEN** the system SHALL create `.github/workflows/sast.yml` from the `sast_workflow` template
- **AND** the template SHALL default to `codeql` but support substitution via `$SAST_TOOL` context variable

#### Scenario: SAST check detects existing workflow
- **WHEN** OSPS-VM-06.02 is evaluated
- **THEN** the system SHALL use a `pattern` pass to check for SAST-related steps in existing workflows (e.g., `codeql`, `semgrep`, `sonarqube` in workflow files)

### Requirement: SCA workflow template
The implementation SHALL provide a `file_create` remediation for OSPS-VM-05.02 that creates a pre-release SCA check workflow.

#### Scenario: Create SCA workflow
- **WHEN** OSPS-VM-05.02 fails (no pre-release SCA)
- **AND** the user triggers remediation
- **THEN** the system SHALL create `.github/workflows/sca.yml` from the `sca_workflow` template
- **AND** the workflow SHALL run dependency scanning on pull requests

### Requirement: Release signing workflow template
The implementation SHALL provide a `file_create` remediation for OSPS-BR-06.01 that creates a release signing workflow.

#### Scenario: Create release signing workflow
- **WHEN** OSPS-BR-06.01 fails (releases not signed)
- **AND** the user triggers remediation
- **THEN** the system SHALL create `.github/workflows/release-signing.yml` from the `release_signing_workflow` template
- **AND** the workflow SHALL use GitHub's artifact attestation for signing

### Requirement: Workflow templates are minimal and generic
All CI workflow templates SHALL be language-agnostic and minimal, providing a functional starting point that users can customize.

#### Scenario: Template does not assume language
- **WHEN** any CI workflow template is created
- **THEN** the template SHALL NOT hardcode a specific programming language build system
- **AND** SHALL include comments indicating where users should customize

#### Scenario: Templates use stable action versions
- **WHEN** a CI workflow template references a GitHub Action
- **THEN** the action reference SHALL use a major version tag (e.g., `actions/checkout@v4`) rather than `@latest` or a full SHA

### Requirement: Remediation templates must not introduce security findings
All CI workflow templates SHALL be hardened so that generated files do not introduce high-severity findings when scanned by workflow security tools (e.g., zizmor, actionlint).

#### Scenario: Templates use persist-credentials false
- **WHEN** any CI workflow template includes an `actions/checkout` step
- **THEN** the step SHALL include `persist-credentials: false` to prevent credential leakage via artifacts

#### Scenario: Templates do not use expressions in run blocks
- **WHEN** any CI workflow template includes a `run:` block
- **THEN** the block SHALL NOT contain `${{ }}` expressions referencing user-controllable GitHub contexts (e.g., `github.event.issue`, `github.event.pull_request`, `github.head_ref`)
- **AND** if dynamic values are needed in `run:` blocks, the template SHALL use `env:` intermediary variables

#### Scenario: Remediation does not worsen compliance
- **WHEN** the remediation tool generates a workflow file for one control
- **THEN** the generated file SHALL NOT introduce failures for other controls in the same audit
- **AND** the generated file SHALL NOT increase the total finding count from workflow security scanners

### Requirement: Zizmor exec pass declares valid exit codes
The BR-01.01 zizmor exec pass SHALL declare `pass_exit_codes` covering all valid zizmor exit codes so the CEL expression can evaluate the JSON output.

#### Scenario: Zizmor returns findings
- **WHEN** zizmor runs and returns a non-zero exit code indicating findings (exit codes 10-14)
- **THEN** the exec handler SHALL treat the exit code as valid (not INCONCLUSIVE)
- **AND** the CEL expression SHALL evaluate the JSON output to determine pass/fail based on finding types

#### Scenario: Zizmor is not installed
- **WHEN** zizmor is not available on the system
- **THEN** the exec handler SHALL return INCONCLUSIVE
- **AND** the pipeline SHALL fall through to the pattern-based fallback pass
