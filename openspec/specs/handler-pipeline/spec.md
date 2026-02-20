## ADDED Requirements

### Requirement: The sieve pipeline is a confidence gradient with four phases
The verification pipeline SHALL consist of four phases executed in order: deterministic, pattern, llm, manual. Each phase represents a confidence tier. The orchestrator SHALL iterate phases in order and stop at the first conclusive result.

#### Scenario: Deterministic phase produces conclusive result
- **WHEN** a control's deterministic phase produces a PASS or FAIL result
- **THEN** the orchestrator SHALL NOT execute the pattern, llm, or manual phases
- **AND** SHALL return the deterministic result

#### Scenario: Deterministic inconclusive, pattern resolves
- **WHEN** a control's deterministic phase produces INCONCLUSIVE
- **AND** the pattern phase produces a PASS result
- **THEN** the orchestrator SHALL return the pattern result
- **AND** SHALL NOT execute the llm or manual phases

#### Scenario: All phases inconclusive
- **WHEN** all phases produce INCONCLUSIVE
- **THEN** the orchestrator SHALL return WARN with a message indicating manual verification is needed

### Requirement: Each phase contains a list of handler invocations
Each phase in the pipeline SHALL be an optional list of handler invocations. Each invocation names a registered handler and provides handler-specific configuration via pass-through fields.

#### Scenario: Multiple handlers in one phase
- **WHEN** a control's deterministic phase defines two handler invocations: `[{ handler = "file_exists", files = ["README.md"] }, { handler = "exec", command = ["gh", "api", "..."] }]`
- **THEN** the orchestrator SHALL execute both handlers within the deterministic phase
- **AND** SHALL stop on the first conclusive result within the phase

#### Scenario: Handler-specific config passes through
- **WHEN** a handler invocation specifies `{ handler = "exec", command = ["ls"], timeout = 60 }`
- **THEN** the `command` and `timeout` fields SHALL be passed to the handler as its configuration
- **AND** the framework schema SHALL NOT need to enumerate every handler's fields

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

### Requirement: The same confidence gradient applies to context gathering
Context definitions in the TOML MAY specify a `detect` pipeline following the same phase ordering. The framework SHALL process detection handlers through the confidence gradient to auto-detect context values.

#### Scenario: Context detection via deterministic handler
- **WHEN** a context definition has `detect = [{ phase = "deterministic", handler = "exec", command = ["gh", "api", "/repos/$OWNER/$REPO/collaborators"] }]`
- **THEN** the framework SHALL execute the handler to detect the context value
- **AND** SHALL use the result as the auto-detected value

#### Scenario: Context detection falls through to pattern
- **WHEN** a context definition's deterministic detection produces INCONCLUSIVE
- **AND** a pattern-phase detection handler is configured
- **THEN** the framework SHALL try the pattern handler next

#### Scenario: Context detection with manual confirmation
- **WHEN** a context definition has `confirm = "manual"`
- **THEN** the framework SHALL prompt the user to confirm detected values before writing to `.project/`

### Requirement: The same confidence gradient applies to remediation
Remediation configuration MAY use the same phased handler invocation lists. Unlike verification (which stops at first conclusive result), remediation SHALL execute all handlers in the deterministic phase, then fall to pattern/llm/manual phases only if explicitly configured by the implementation author.

#### Scenario: Deterministic remediation handlers all execute
- **WHEN** a control's remediation defines `deterministic = [{ handler = "file_create", ... }, { handler = "project_update", ... }]`
- **THEN** the framework SHALL execute both handlers (file creation AND project update)
- **AND** SHALL NOT stop after the first handler succeeds

#### Scenario: LLM remediation for complex cases
- **WHEN** a control's remediation defines an llm phase: `llm = [{ handler = "llm_update", prompt = "Update all docs mentioning maintainers" }]`
- **THEN** the framework SHALL invoke the LLM handler
- **AND** the handler SHALL produce a diff for user review rather than auto-applying changes

#### Scenario: Manual remediation fallback
- **WHEN** a control's remediation defines a manual phase: `manual = [{ handler = "manual_steps", steps = ["Review generated file", "Verify content"] }]`
- **THEN** the framework SHALL present the steps to the user as remediation instructions

### Requirement: Handlers are registered with phase affinity
Each handler SHALL be registered in the handler registry with a name, phase affinity (deterministic, pattern, llm, or manual), and a callable. The framework SHALL warn (not error) if a handler is used in a phase different from its registered affinity.

#### Scenario: Handler registered for deterministic phase
- **WHEN** a handler is registered with `phase = "deterministic"`
- **AND** a control uses it in the deterministic phase
- **THEN** no warning SHALL be logged

#### Scenario: Handler used in different phase
- **WHEN** a handler registered with `phase = "deterministic"` is used in the pattern phase
- **THEN** the framework SHALL log a warning
- **AND** SHALL still execute the handler

### Requirement: Three tiers of handler providers
Handlers SHALL come from three tiers: core framework (built-in), library packages (pip-installable), and implementation-specific (registered via plugin system). Core built-in handlers SHALL include: `file_exists`, `exec`, `regex`, `llm_eval`, `manual_steps`, `file_create`, `api_call`, `project_update`.

#### Scenario: Implementation registers domain-specific handler
- **WHEN** an implementation registers a handler named `scorecard` via `register_handlers()`
- **THEN** controls in that implementation's TOML MAY use `{ handler = "scorecard", ... }`
- **AND** the handler SHALL be available for the duration of the audit

#### Scenario: Handler name collision between tiers
- **WHEN** an implementation registers a handler with the same name as a core built-in
- **THEN** the implementation's handler SHALL take precedence
- **AND** the framework SHALL log a debug message about the override

### Requirement: Post-handler CEL evaluation step
The sieve orchestrator SHALL evaluate CEL expressions as a post-handler step after any handler returns a result. This step SHALL be transparent to handler implementations.

#### Scenario: Handler returns, expr present
- **WHEN** a handler returns a `HandlerResult` and the pass definition contains an `expr` field
- **THEN** the orchestrator SHALL build a CEL context from the handler's evidence: `{"output": handler_result.evidence}`
- **AND** SHALL evaluate the `expr` against this context
- **AND** the CEL result SHALL override the handler's own pass/fail verdict

#### Scenario: Handler returns, no expr
- **WHEN** a handler returns a `HandlerResult` and the pass definition does NOT contain an `expr` field
- **THEN** the orchestrator SHALL use the handler's verdict as-is
- **AND** no CEL evaluation SHALL occur

#### Scenario: CEL true overrides handler FAIL
- **WHEN** a handler returns FAIL but `expr` evaluates to true
- **THEN** the orchestrator SHALL return PASS
- **AND** SHALL include both the handler evidence and the CEL expression in the result

#### Scenario: CEL false overrides handler PASS
- **WHEN** a handler returns PASS but `expr` evaluates to false
- **THEN** the orchestrator SHALL return INCONCLUSIVE
- **AND** the pipeline SHALL continue to the next pass

#### Scenario: CEL error falls through to handler verdict
- **WHEN** `expr` evaluation fails (syntax error, runtime error, evaluator unavailable)
- **THEN** the orchestrator SHALL log the error at debug level
- **AND** SHALL use the handler's own verdict as the final result

#### Scenario: Handler returns ERROR, expr is skipped
- **WHEN** a handler returns ERROR status
- **THEN** the orchestrator SHALL NOT evaluate `expr`
- **AND** SHALL propagate the ERROR as-is

#### Scenario: Handler returns INCONCLUSIVE, expr is skipped
- **WHEN** a handler returns INCONCLUSIVE status
- **THEN** the orchestrator SHALL NOT evaluate `expr`
- **AND** SHALL propagate the INCONCLUSIVE as-is

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
