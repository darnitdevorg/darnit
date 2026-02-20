## ADDED Requirements

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

## MODIFIED Requirements

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
