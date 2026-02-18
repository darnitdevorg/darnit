## ADDED Requirements

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
