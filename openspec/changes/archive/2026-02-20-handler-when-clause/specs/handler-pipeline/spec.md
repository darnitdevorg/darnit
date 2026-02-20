## MODIFIED Requirements

### Requirement: HandlerInvocation schema uses extra="allow" for pass-through
The `HandlerInvocation` model SHALL have `handler: str` (required), `shared: str | None` (optional reference to shared handler), `when: dict[str, Any] | None` (optional applicability condition), and SHALL allow extra fields via `extra="allow"`. Handler-specific configuration passes through without framework-level validation. The `when` field SHALL NOT be passed to handlers as configuration — it is consumed by the orchestrator/executor before dispatch.

#### Scenario: Unknown fields pass through
- **WHEN** a handler invocation includes `{ handler = "custom_check", custom_param = "value" }`
- **THEN** the framework SHALL accept the TOML without validation errors
- **AND** SHALL pass `custom_param = "value"` to the handler at execution time

#### Scenario: when field is not passed to handler
- **WHEN** a handler invocation includes `{ handler = "exec", command = ["ls"], when = { primary_language = "go" } }`
- **THEN** the framework SHALL evaluate the `when` clause before dispatch
- **AND** SHALL NOT include `when` in the handler's configuration dictionary
- **AND** SHALL pass only `command` to the handler

## ADDED Requirements

### Requirement: Handler invocations support conditional dispatch via when clause
A handler invocation MAY declare a `when` clause that specifies project context conditions under which the handler is applicable. When the condition evaluates to false, the handler SHALL be skipped without execution.

#### Scenario: Handler skipped when language does not match
- **WHEN** a handler invocation declares `when = { primary_language = "go" }`
- **AND** the project context has `primary_language = "python"`
- **THEN** the handler SHALL be skipped
- **AND** the orchestrator/executor SHALL continue to the next handler in the list

#### Scenario: Handler runs when language matches
- **WHEN** a handler invocation declares `when = { primary_language = "go" }`
- **AND** the project context has `primary_language = "go"`
- **THEN** the handler SHALL be dispatched normally

#### Scenario: Handler with no when clause always runs
- **WHEN** a handler invocation does NOT declare a `when` clause
- **THEN** the handler SHALL be dispatched unconditionally
- **AND** behavior SHALL be identical to the pre-change behavior

#### Scenario: Handler skipped when context key is missing
- **WHEN** a handler invocation declares `when = { primary_language = "go" }`
- **AND** the project context does NOT contain `primary_language`
- **THEN** the handler SHALL be skipped
- **AND** a debug-level log message SHALL note the missing context key

#### Scenario: Multiple when conditions are AND-ed
- **WHEN** a handler invocation declares `when = { primary_language = "go", platform = "github" }`
- **AND** the project context has `primary_language = "go"` and `platform = "gitlab"`
- **THEN** the handler SHALL be skipped

#### Scenario: Sieve pass handler with when clause
- **WHEN** a sieve pass handler invocation declares `when = { ci_provider = "github" }`
- **AND** the project context has `ci_provider = "gitlab"`
- **THEN** the sieve orchestrator SHALL skip that handler
- **AND** SHALL continue to the next handler in the phase

#### Scenario: Remediation handler with when clause
- **WHEN** a remediation handler invocation declares `when = { primary_language = "python" }`
- **AND** the project context has `primary_language = "python"`
- **THEN** the remediation executor SHALL dispatch the handler normally

### Requirement: Remediation config supports handler selection strategy
The `RemediationConfig` model SHALL support a `strategy` field with values `"all"` (default) and `"first_match"`. The strategy controls how the executor iterates remediation handlers.

#### Scenario: Default strategy runs all matching handlers
- **WHEN** a remediation config has no `strategy` field (or `strategy = "all"`)
- **AND** the handler list contains three handlers, two of which have matching `when` clauses
- **THEN** the executor SHALL dispatch both matching handlers in order
- **AND** behavior SHALL be identical to the pre-change behavior for handlers without `when` clauses

#### Scenario: first_match strategy stops after first matching handler
- **WHEN** a remediation config has `strategy = "first_match"`
- **AND** the handler list contains `[{ handler = "file_create", when = { primary_language = "go" }, path = "go.mod" }, { handler = "file_create", when = { primary_language = "python" }, path = "pyproject.toml" }]`
- **AND** the project context has `primary_language = "go"`
- **THEN** the executor SHALL dispatch the first handler (go.mod)
- **AND** SHALL NOT dispatch the second handler (pyproject.toml)

#### Scenario: first_match with no when clause acts as catch-all
- **WHEN** a remediation config has `strategy = "first_match"`
- **AND** the handler list ends with `{ handler = "manual", steps = ["Create dependency manifest"] }`
- **AND** no preceding handler's `when` clause matched
- **THEN** the executor SHALL dispatch the manual handler as a fallback

#### Scenario: first_match with no matching handlers
- **WHEN** a remediation config has `strategy = "first_match"`
- **AND** no handler's `when` clause matches the project context
- **AND** no handler lacks a `when` clause
- **THEN** the executor SHALL return a result indicating no applicable remediation
- **AND** the result message SHALL list the unmatched conditions

### Requirement: when evaluation uses a shared evaluate_when function
The framework SHALL provide a single `evaluate_when(when_clause, context)` function that is used by both the sieve orchestrator and the remediation executor. This function SHALL live in the `config` package to avoid cross-layer imports between `sieve` and `remediation`.

#### Scenario: Sieve and remediation use same evaluation logic
- **WHEN** a sieve pass handler declares `when = { platform = "github" }`
- **AND** a remediation handler declares `when = { platform = "github" }`
- **THEN** both SHALL be evaluated by the same `evaluate_when` function
- **AND** SHALL produce identical results for the same context
