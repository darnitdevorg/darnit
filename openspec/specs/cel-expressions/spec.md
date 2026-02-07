# CEL Expressions Specification

## ADDED Requirements

### Requirement: CEL expression field for passes
The framework SHALL support an `expr` field in pass definitions for CEL-based pass/fail evaluation.

#### Scenario: Simple boolean expression
- **WHEN** pass definition contains `expr = "output.status == 'pass'"`
- **THEN** the framework SHALL evaluate the CEL expression against the pass context
- **AND** SHALL return PASS if expression evaluates to true

#### Scenario: Expression evaluates to false
- **WHEN** CEL expression evaluates to `false`
- **THEN** the framework SHALL return FAIL for that pass

#### Scenario: Expression error
- **WHEN** CEL expression has a syntax error or runtime error
- **THEN** the framework SHALL return ERROR status
- **AND** SHALL include the error message in the result

### Requirement: CEL context variables
The framework SHALL provide standard variables in the CEL evaluation context.

#### Scenario: Output variable for exec pass
- **WHEN** an exec pass runs a command
- **THEN** the CEL context SHALL include:
  - `output.stdout` (string)
  - `output.stderr` (string)
  - `output.exit_code` (int)
  - `output.json` (parsed JSON if output is valid JSON, else null)

#### Scenario: File context for pattern pass
- **WHEN** a pattern pass searches files
- **THEN** the CEL context SHALL include:
  - `files` (list of matched file paths)
  - `matches` (list of match objects with file, line, content)

#### Scenario: API response context
- **WHEN** an API check receives a response
- **THEN** the CEL context SHALL include:
  - `response.status_code` (int)
  - `response.body` (parsed JSON)
  - `response.headers` (map)

#### Scenario: Project context available
- **WHEN** any CEL expression is evaluated
- **THEN** the CEL context SHALL include:
  - `project` (from .project/ integration)
  - `context` (from context collection)
  - `repo.path` (repository root path)
  - `repo.owner` (GitHub owner if detectable)
  - `repo.name` (GitHub repo name if detectable)

### Requirement: CEL standard functions
The framework SHALL provide standard CEL functions plus security-focused extensions.

#### Scenario: String functions
- **WHEN** CEL expression uses `contains()`, `startsWith()`, `endsWith()`
- **THEN** the framework SHALL evaluate them per CEL specification

#### Scenario: List functions
- **WHEN** CEL expression uses `size()`, `exists()`, `all()`, `filter()`, `map()`
- **THEN** the framework SHALL evaluate them per CEL specification

#### Scenario: Custom file_exists function
- **WHEN** CEL expression uses `file_exists("SECURITY.md")`
- **THEN** the framework SHALL check if the file exists in the repository
- **AND** SHALL return boolean result

#### Scenario: Custom json_path function
- **WHEN** CEL expression uses `json_path(output.json, "$.status")`
- **THEN** the framework SHALL extract the value at that JSONPath
- **AND** SHALL return the extracted value or null

### Requirement: CEL sandboxing
The framework SHALL sandbox CEL evaluation to prevent security issues.

#### Scenario: No filesystem access
- **WHEN** CEL expression attempts direct filesystem access
- **THEN** the framework SHALL deny the operation
- **AND** SHALL only allow access through provided functions like `file_exists()`

#### Scenario: No network access
- **WHEN** CEL expression attempts network access
- **THEN** the framework SHALL deny the operation

#### Scenario: Execution timeout
- **WHEN** CEL expression takes longer than 1 second to evaluate
- **THEN** the framework SHALL terminate evaluation
- **AND** SHALL return ERROR status with timeout message

#### Scenario: Memory limit
- **WHEN** CEL expression attempts to allocate excessive memory
- **THEN** the framework SHALL terminate evaluation
- **AND** SHALL return ERROR status

### Requirement: Backward compatibility with old fields
The framework SHALL support both old-style fields and CEL expressions during transition.

#### Scenario: Old fields still work
- **WHEN** pass definition uses `pass_if_json_path` and `pass_if_json_value`
- **THEN** the framework SHALL evaluate them as before
- **AND** SHALL log a deprecation warning

#### Scenario: CEL takes precedence
- **WHEN** pass definition contains both `expr` and old-style fields
- **THEN** the framework SHALL use the `expr` field
- **AND** SHALL ignore old-style fields
- **AND** SHALL log a warning about redundant configuration

### Requirement: CEL expression validation
The framework SHALL validate CEL expressions at config load time.

#### Scenario: Syntax validation
- **WHEN** TOML config is loaded
- **THEN** the framework SHALL parse all CEL expressions
- **AND** SHALL report syntax errors with line numbers

#### Scenario: Type checking
- **WHEN** CEL expression references unknown variables
- **THEN** the framework SHALL report the error at config load time
- **AND** SHALL list available variables

### Requirement: CEL expression examples in errors
The framework SHALL provide helpful error messages with examples.

#### Scenario: Migration hint
- **WHEN** user uses old-style `pass_if_json_path` + `pass_if_json_value`
- **THEN** deprecation warning SHALL include equivalent CEL expression
- **Example**: `Migrate to: expr = "json_path(output.json, '$.status') == 'pass'"`
