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
The `HandlerInvocation` model SHALL have `handler: str` (required), `shared: str | None` (optional reference to shared handler), and SHALL allow extra fields via `extra="allow"`. Handler-specific configuration passes through without framework-level validation.

#### Scenario: Unknown fields pass through
- **WHEN** a handler invocation includes `{ handler = "custom_check", custom_param = "value" }`
- **THEN** the framework SHALL accept the TOML without validation errors
- **AND** SHALL pass `custom_param = "value"` to the handler at execution time

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
