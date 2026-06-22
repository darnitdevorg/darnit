# CEL Expressions Specification

### Requirement: CEL expression field for passes
The framework SHALL support an `expr` field in pass definitions for CEL-based pass/fail evaluation. CEL evaluation SHALL be performed by the sieve orchestrator as a post-handler step, not by individual handlers.

#### Scenario: Simple boolean expression
- **WHEN** pass definition contains `expr = "output.any_match == true"`
- **THEN** the orchestrator SHALL evaluate the CEL expression after the handler returns
- **AND** SHALL return PASS if expression evaluates to true

#### Scenario: Expression evaluates to false
- **WHEN** CEL expression evaluates to `false`
- **THEN** the orchestrator SHALL return INCONCLUSIVE for that pass
- **AND** the pipeline SHALL continue to the next pass

#### Scenario: Expression error
- **WHEN** CEL expression has a syntax error or runtime error
- **THEN** the orchestrator SHALL log the error
- **AND** SHALL fall through to the handler's own verdict

#### Scenario: Expr on exec handler
- **WHEN** an exec pass definition contains `expr`
- **THEN** the orchestrator SHALL evaluate the expression with `output.*` mapped from the handler's evidence
- **AND** existing expressions like `expr = 'output.exit_code == 0'` SHALL continue to work unchanged

#### Scenario: Expr on pattern handler
- **WHEN** a pattern pass definition contains `expr = '!(output.any_match)'`
- **THEN** the orchestrator SHALL evaluate the expression against the pattern handler's evidence
- **AND** SHALL return PASS when the pattern was NOT found in any file

#### Scenario: Expr on any handler
- **WHEN** any handler (built-in or plugin) returns a result and the pass definition contains `expr`
- **THEN** the orchestrator SHALL evaluate the expression with `{"output": handler_result.evidence}`
- **AND** the handler itself SHALL NOT need to implement CEL support

### Requirement: CEL context variables
The framework SHALL provide standard variables in the CEL evaluation context. The context SHALL always be `{"output": <handler evidence dict>}`. Each handler defines its evidence shape.

#### Scenario: Output variable for exec pass
- **WHEN** an exec pass runs a command
- **THEN** the CEL context SHALL include:
  - `output.stdout` (string)
  - `output.stderr` (string)
  - `output.exit_code` (int)
  - `output.json` (parsed JSON if output is valid JSON, else null)

#### Scenario: Output variable for pattern pass
- **WHEN** a pattern pass searches files
- **THEN** the CEL context SHALL include:
  - `output.files_checked` (int: number of files examined)
  - `output.any_match` (bool: true if any pattern matched in any file)
  - `output.results` (list of match result objects with file, pattern_name, match_count, matched)
  - `output.patterns_checked` (list of pattern names)

#### Scenario: Output variable for pattern exclude mode
- **WHEN** a pattern pass uses `exclude_files` globs
- **THEN** the CEL context SHALL include:
  - `output.files_found` (int: number of files matching the exclude globs)
  - `output.found_files` (list of matched file paths)

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

### Requirement: Migration from old fields
The `must_not_match`, `mode = "exclude_must_not_exist"`, `pass_if_json_path`, and `pass_if_json_value` fields have been removed and replaced by `expr`. The schema is `0.1.0-alpha` with no backwards compatibility guarantee.

#### Scenario: Migration paths
- `must_not_match = true` → `expr = '!(output.any_match)'`
- `mode = "exclude_must_not_exist"` → `expr = 'output.files_found == 0'`
- `pass_if_json_path` + `pass_if_json_value` → `expr = 'json_path(output.json, "<path>") == "<value>"'`
