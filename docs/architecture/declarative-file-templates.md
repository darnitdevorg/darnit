### Requirement: File creation templates for governance documents
The framework SHALL support TOML-based `file_create` remediation templates for all governance documents: SECURITY.md, CONTRIBUTING.md, CODEOWNERS, GOVERNANCE.md, MAINTAINERS.md, and SUPPORT.md. Each template SHALL use `${context.*}` and `${project.*}` template variables for dynamic content.

#### Scenario: SECURITY.md template with VEX policy
- **WHEN** a control with `remediation.file_create` targeting SECURITY.md is executed
- **THEN** the executor SHALL create a SECURITY.md file containing vulnerability reporting instructions and a VEX policy section
- **AND** the template SHALL substitute `${owner}`, `${repo}`, and `${context.security_contact}` variables

#### Scenario: CONTRIBUTING.md template
- **WHEN** a control with `remediation.file_create` targeting CONTRIBUTING.md is executed
- **THEN** the executor SHALL create a CONTRIBUTING.md file with contributor guidelines
- **AND** the template SHALL substitute `${owner}` and `${repo}` variables

#### Scenario: CODEOWNERS template with maintainers
- **WHEN** a control with `remediation.file_create` targeting CODEOWNERS is executed
- **THEN** the executor SHALL create a CODEOWNERS file listing project maintainers
- **AND** the template SHALL substitute `${context.maintainers}` with the confirmed maintainer list

#### Scenario: GOVERNANCE.md template
- **WHEN** a control with `remediation.file_create` targeting GOVERNANCE.md is executed
- **THEN** the executor SHALL create a GOVERNANCE.md describing the project governance model
- **AND** the template SHALL substitute `${context.maintainers}` and `${context.governance_model}` variables

#### Scenario: MAINTAINERS.md template
- **WHEN** a control with `remediation.file_create` targeting MAINTAINERS.md is executed
- **THEN** the executor SHALL create a MAINTAINERS.md listing project maintainers with roles
- **AND** the template SHALL substitute `${context.maintainers}` variable

#### Scenario: SUPPORT.md template
- **WHEN** a control with `remediation.file_create` targeting SUPPORT.md is executed
- **THEN** the executor SHALL create a SUPPORT.md with support channels and resources
- **AND** the template SHALL substitute `${owner}` and `${repo}` variables

### Requirement: File creation template for issue templates
The framework SHALL support a TOML-based `file_create` remediation template for GitHub issue templates.

#### Scenario: Bug report template
- **WHEN** a control with `remediation.file_create` targeting `.github/ISSUE_TEMPLATE/bug_report.md` is executed
- **THEN** the executor SHALL create a bug report issue template with structured sections for reproduction steps, expected behavior, and environment details

### Requirement: File creation template for dependency scanning config
The framework SHALL support a TOML-based `file_create` remediation template for dependency scanning configuration.

#### Scenario: Dependabot config with common ecosystems
- **WHEN** a control with `remediation.file_create` targeting `.github/dependabot.yml` is executed
- **THEN** the executor SHALL create a dependabot configuration covering common package ecosystems (pip, npm, github-actions at minimum)
- **AND** the generated file SHALL include comments indicating users should customize the ecosystem list for their project

### Requirement: Platform setting remediation for branch protection
Branch protection remediation SHALL be declared as a `platform_setting` requirement on the `branch_protection` target (framework-design.md 4.5), never as an API payload.

#### Scenario: Branch protection requirement
- **WHEN** a control with a `branch_protection` requirement is remediated
- **THEN** the platform engine SHALL read the default branch's current protection and rulesets, change only the settings the requirement tightens, and never weaken an existing setting

#### Scenario: Branch protection preview
- **WHEN** such a control is remediated in preview (the default)
- **THEN** the system SHALL report each field to change with its value before and after, and the change-set digest to approve, without writing anything

### Requirement: Context requirements in TOML
Controls that require confirmed project context for remediation SHALL declare `requires_context` in their TOML `[remediation]` section. The orchestrator SHALL validate context requirements from TOML before attempting remediation.

#### Scenario: Maintainers context required
- **WHEN** a control declares `requires_context = [{ key = "maintainers" }]` in TOML
- **AND** maintainers have not been confirmed in `.project.yaml`
- **THEN** the orchestrator SHALL return a context prompt requesting maintainer confirmation before proceeding

#### Scenario: Context satisfied from project config
- **WHEN** a control declares `requires_context = [{ key = "maintainers" }]` in TOML
- **AND** maintainers have been confirmed in `.project.yaml`
- **THEN** the orchestrator SHALL proceed with remediation and the template SHALL have access to the confirmed maintainer values

### Requirement: No legacy Python remediation fallback
After migration, the orchestrator SHALL NOT have a legacy Python function fallback path. All remediation dispatch SHALL go through TOML declarative steps (file_create, exec, platform_setting, project_update, yaml_inject) or TOML manual guidance.

#### Scenario: Control without TOML remediation
- **WHEN** a control has no `[remediation]` section in TOML
- **THEN** the orchestrator SHALL report that no remediation is available for that control
- **AND** the orchestrator SHALL NOT attempt to look up a Python function

#### Scenario: All previously legacy controls have TOML remediation
- **WHEN** the audit finds failures in controls that previously used legacy Python remediation
- **THEN** all such controls SHALL have TOML-based remediation (file_create, platform_setting, or manual) defined
