## MODIFIED Requirements

### Requirement: When clause supports boolean, string equality, and list membership
The `when` clause SHALL support: boolean context values (`when = { key = true }`), string equality (`when = { key = "value" }`), list membership for string context values (`when = { key = ["val1", "val2"] }` meaning key must be one of the listed values), containment for list context values (`when = { key = "value" }` meaning value must be in the context list), and subset checking for list-to-list comparisons (`when = { key = ["val1", "val2"] }` meaning all listed values must be in the context list).

#### Scenario: Boolean condition
- **WHEN** a `when` clause declares `{ is_library = true }`
- **AND** project context has `is_library = true`
- **THEN** the condition SHALL evaluate to true

#### Scenario: String equality condition
- **WHEN** a `when` clause declares `{ ci_provider = "github" }`
- **AND** project context has `ci_provider = "github"`
- **THEN** the condition SHALL evaluate to true

#### Scenario: List membership condition (string context, list when)
- **WHEN** a `when` clause declares `{ ci_provider = ["github", "gitlab"] }`
- **AND** project context has `ci_provider = "gitlab"`
- **THEN** the condition SHALL evaluate to true

#### Scenario: Containment condition (list context, string when)
- **WHEN** a `when` clause declares `{ languages = "go" }`
- **AND** project context has `languages = ["go", "typescript"]`
- **THEN** the condition SHALL evaluate to true

#### Scenario: Containment fails when value not in list
- **WHEN** a `when` clause declares `{ languages = "rust" }`
- **AND** project context has `languages = ["go", "typescript"]`
- **THEN** the condition SHALL evaluate to false

#### Scenario: Subset condition (list context, list when)
- **WHEN** a `when` clause declares `{ languages = ["go", "typescript"] }`
- **AND** project context has `languages = ["go", "typescript", "python"]`
- **THEN** the condition SHALL evaluate to true

#### Scenario: Subset fails when not all values present
- **WHEN** a `when` clause declares `{ languages = ["go", "rust"] }`
- **AND** project context has `languages = ["go", "typescript"]`
- **THEN** the condition SHALL evaluate to false

#### Scenario: Multiple conditions are AND-ed
- **WHEN** a `when` clause declares `{ has_releases = true, is_library = true }`
- **AND** project context has `has_releases = true` and `is_library = false`
- **THEN** the condition SHALL evaluate to false

#### Scenario: Empty list context matches nothing
- **WHEN** a `when` clause declares `{ languages = "go" }`
- **AND** project context has `languages = []`
- **THEN** the condition SHALL evaluate to false
