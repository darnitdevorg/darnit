# Context Collection Specification

## ADDED Requirements

### Requirement: Define context schema in TOML
The framework SHALL support a `[context]` section in the TOML config for defining context variables that may require user input.

#### Scenario: Context definition with prompt
- **WHEN** TOML contains:
  ```toml
  [context.maintainers]
  description = "List of project maintainers"
  type = "list[string]"
  prompt = "Who are the maintainers of this project?"
  ```
- **THEN** the framework SHALL recognize this as a context variable that may need user input

#### Scenario: Context definition with file source
- **WHEN** TOML contains:
  ```toml
  [context.maintainers]
  description = "List of project maintainers"
  type = "list[string]"
  source = "MAINTAINERS.md"
  parser = "markdown_list"
  ```
- **THEN** the framework SHALL attempt to parse maintainers from that file

#### Scenario: Context definition with presentation metadata
- **WHEN** TOML contains:
  ```toml
  [context.ci_provider]
  description = "CI/CD system"
  type = "enum"
  prompt = "What CI/CD system does this project use?"
  values = ["github", "gitlab", "jenkins", "circleci", "azure", "travis", "none", "other"]
  presentation_hint = "[github/gitlab/jenkins/...]"
  allowed_values = ["github", "gitlab", "jenkins", "other"]
  ```
- **THEN** the framework SHALL store `presentation_hint` and `allowed_values` on the `ContextDefinition`
- **AND** both fields SHALL be optional (existing definitions without them SHALL continue to work)

### Requirement: Context resolution priority
The framework SHALL resolve context values in a defined priority order.

#### Scenario: .project/ provides value
- **WHEN** a context variable can be resolved from `.project/project.yaml`
- **THEN** that value SHALL be used without prompting the user

#### Scenario: File source provides value
- **WHEN** a context variable has a `source` file that exists and can be parsed
- **THEN** that value SHALL be used without prompting the user

#### Scenario: Fallback to user prompt
- **WHEN** a context variable cannot be resolved from .project/ or file sources
- **AND** the variable has a `prompt` defined
- **THEN** the framework SHALL prompt the user for the value

#### Scenario: No value available
- **WHEN** a context variable cannot be resolved and has no prompt
- **THEN** the framework SHALL set the variable to `null`
- **AND** SHALL log a debug message

### Requirement: Context types
The framework SHALL support typed context variables.

#### Scenario: String type
- **WHEN** context type is `string`
- **THEN** the value SHALL be stored as a string

#### Scenario: List type
- **WHEN** context type is `list[string]`
- **THEN** the value SHALL be stored as a list of strings
- **AND** user prompts SHALL accept comma-separated or multi-line input

#### Scenario: Boolean type
- **WHEN** context type is `boolean`
- **THEN** the value SHALL be stored as true/false
- **AND** user prompts SHALL accept yes/no/true/false

#### Scenario: Email type
- **WHEN** context type is `email`
- **THEN** the value SHALL be validated as an email address

### Requirement: Context flows to remediation
Context variables SHALL be available as template variables in remediation actions.

#### Scenario: Use context in template
- **WHEN** remediation uses template with `$maintainers` variable
- **AND** `context.maintainers` has been resolved
- **THEN** the template SHALL substitute the maintainers list

#### Scenario: Missing context blocks remediation
- **WHEN** remediation requires a context variable that is `null`
- **AND** the variable is marked `required = true`
- **THEN** the remediation SHALL fail with a clear error message

### Requirement: User confirmation for auto-detected context
The framework SHALL allow user confirmation of auto-detected context values.

#### Scenario: Confirm auto-detected maintainers
- **WHEN** maintainers are auto-detected from CODEOWNERS
- **AND** context definition has `confirm = true`
- **THEN** the framework SHALL show the detected value and ask for confirmation

#### Scenario: User overrides auto-detected value
- **WHEN** user is prompted to confirm an auto-detected value
- **AND** user provides a different value
- **THEN** the user-provided value SHALL be used

### Requirement: Persist collected context
The framework SHALL persist user-provided context to avoid repeated prompts.

#### Scenario: Save to .project/
- **WHEN** user provides context via prompt
- **AND** the context can be represented in .project/ format
- **THEN** the framework SHALL offer to save it to `.project/project.yaml`

#### Scenario: Save to .baseline.toml
- **WHEN** user provides context that is darnit-specific
- **THEN** the framework SHALL save it to `.baseline.toml` under `[context]`

### Requirement: Context validation
The framework SHALL validate context values against defined constraints.

#### Scenario: Required context missing
- **WHEN** a context variable is marked `required = true`
- **AND** the value cannot be resolved
- **THEN** the framework SHALL report an error

#### Scenario: Pattern validation
- **WHEN** context definition includes `pattern = "^@[\\w-]+$"`
- **AND** user provides a value not matching the pattern
- **THEN** the framework SHALL reject the value and re-prompt

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

### Requirement: Presentation hints for context definitions
The framework SHALL support optional presentation metadata on context definitions to control how prompts are displayed to users or rendered by LLM-based tools.

#### Scenario: Context definition with presentation_hint
- **WHEN** TOML contains:
  ```toml
  [context.has_releases]
  type = "boolean"
  prompt = "Does this project make official releases?"
  presentation_hint = "[y/N]"
  ```
- **THEN** the framework SHALL store the `presentation_hint` value on the `ContextDefinition` model
- **AND** the hint SHALL be available to tools that format user-facing prompts

#### Scenario: Context definition with allowed_values
- **WHEN** TOML contains:
  ```toml
  [context.ci_provider]
  type = "enum"
  prompt = "What CI/CD system does this project use?"
  allowed_values = ["github", "gitlab", "jenkins", "other"]
  ```
- **THEN** the framework SHALL store the `allowed_values` list on the `ContextDefinition` model
- **AND** the values SHALL be available to tools that format user-facing prompts

#### Scenario: Presentation hint defaults for boolean type
- **WHEN** a context definition has `type = "boolean"`
- **AND** no explicit `presentation_hint` is set
- **THEN** the framework SHALL default `presentation_hint` to `[y/N]`

#### Scenario: Presentation hint defaults for enum type
- **WHEN** a context definition has `type = "enum"`
- **AND** `values` or `allowed_values` is set
- **AND** no explicit `presentation_hint` is set
- **THEN** the framework SHALL auto-generate a `presentation_hint` from the values list (e.g., `[github/gitlab/jenkins/other]`)

#### Scenario: No presentation_hint specified and type is not boolean or enum
- **WHEN** a context definition does not specify `presentation_hint`
- **AND** the type is not `boolean` or `enum`
- **THEN** `presentation_hint` SHALL be `null`

### Requirement: Single-item pagination for pending context
The implementation-layer `get_pending_context` tool SHALL return context items one at a time by default.

#### Scenario: Default pagination returns one item
- **WHEN** `get_pending_context` is called without a `limit` parameter
- **THEN** the response SHALL contain at most one pending context question
- **AND** the question SHALL be the highest-priority missing item

#### Scenario: Explicit limit overrides default
- **WHEN** `get_pending_context` is called with `limit=5`
- **THEN** the response SHALL contain at most 5 pending context questions
- **AND** they SHALL be sorted by priority (highest first)

#### Scenario: Limit of zero returns all items
- **WHEN** `get_pending_context` is called with `limit=0`
- **THEN** the response SHALL contain all pending context questions
- **AND** they SHALL be sorted by priority (highest first)

### Requirement: Progress indicator for pending context
The `get_pending_context` response SHALL include progress information so callers can display position in the sequence.

#### Scenario: Progress included in response
- **WHEN** `get_pending_context` returns pending questions
- **THEN** the response SHALL include a `progress` object with `current` and `total` fields
- **AND** `total` SHALL reflect the total number of pending items (not just the returned slice)
- **AND** `current` SHALL reflect the position of the first returned item in the full sequence

#### Scenario: Progress on final question
- **WHEN** only one pending context item remains
- **AND** `get_pending_context` is called
- **THEN** `progress.current` SHALL equal `progress.total`
