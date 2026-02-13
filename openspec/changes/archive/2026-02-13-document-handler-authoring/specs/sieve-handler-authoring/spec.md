## ADDED Requirements

### Requirement: Documentation SHALL explain the sieve handler function signature
The Implementation Guide SHALL document that a sieve handler is a Python function with signature `(config: dict[str, Any], context: HandlerContext) -> HandlerResult`. The documentation SHALL explain that `config` contains all pass-through fields from the TOML `[[passes]]` entry (excluding the `handler` key itself) and `context` is provided by the framework.

#### Scenario: Author reads handler signature documentation
- **WHEN** an implementation author reads the sieve handler authoring section
- **THEN** they SHALL find the complete function signature with type annotations
- **AND** a minimal working example that returns a `HandlerResult`

#### Scenario: Author understands config pass-through
- **WHEN** an implementation author reads about the config parameter
- **THEN** they SHALL understand that TOML fields like `files`, `command`, `timeout` are passed as dict keys
- **AND** that their handler receives only its own fields (the framework strips `handler` and `shared`)

### Requirement: Documentation SHALL describe all HandlerContext fields
The Implementation Guide SHALL document each field of `HandlerContext` with its type, purpose, and when it is populated. Fields: `local_path` (str), `owner` (str), `repo` (str), `default_branch` (str), `control_id` (str), `project_context` (dict), `gathered_evidence` (dict), `shared_cache` (dict), `dependency_results` (dict).

#### Scenario: Author uses gathered_evidence for pipeline chaining
- **WHEN** an implementation author reads the `gathered_evidence` documentation
- **THEN** they SHALL understand that evidence from earlier handlers in the same control's pipeline is accumulated here
- **AND** that their handler can read keys like `found_file` set by a preceding `file_exists` handler

#### Scenario: Author uses shared_cache for cross-control sharing
- **WHEN** an implementation author reads the `shared_cache` documentation
- **THEN** they SHALL understand that shared handler results are cached by name and available to all controls referencing the same shared handler

### Requirement: Documentation SHALL explain HandlerResult construction
The Implementation Guide SHALL document how to construct a `HandlerResult` with appropriate `status`, `message`, `confidence`, `evidence`, and `details` fields. It SHALL explain the semantics of each `HandlerResultStatus` value (PASS, FAIL, INCONCLUSIVE, ERROR) and when to use each.

#### Scenario: Author returns PASS with evidence
- **WHEN** an implementation author writes a handler that finds a passing condition
- **THEN** the documentation SHALL show returning `HandlerResult(status=HandlerResultStatus.PASS, message="...", confidence=1.0, evidence={"key": "value"})`

#### Scenario: Author returns INCONCLUSIVE to allow pipeline continuation
- **WHEN** an implementation author writes a handler that cannot determine compliance
- **THEN** the documentation SHALL explain that returning INCONCLUSIVE allows the next handler in the pipeline to try
- **AND** SHALL distinguish INCONCLUSIVE from ERROR (which indicates a handler malfunction)

### Requirement: Documentation SHALL explain handler registration with phase affinity
The Implementation Guide SHALL document how to register a custom sieve handler using `SieveHandlerRegistry.register()` with a name, phase affinity, handler function, and optional description. It SHALL explain the four phases (deterministic, pattern, llm, manual) and that phase affinity is advisory (the framework warns but still executes if a handler is used in a different phase).

#### Scenario: Author registers a custom checking handler
- **WHEN** an implementation author wants to add a handler named `scorecard`
- **THEN** the documentation SHALL show calling `registry.register("scorecard", phase="deterministic", handler_fn=scorecard_handler, description="...")`
- **AND** SHALL show obtaining the registry via `get_sieve_handler_registry()`

#### Scenario: Author registers from a plugin with plugin context
- **WHEN** an implementation author registers handlers from within an implementation's `register_handlers()` method
- **THEN** the documentation SHALL show setting plugin context via `registry.set_plugin_context(self.name)` before registration and clearing it after
- **AND** SHALL explain that plugin handlers override core built-in handlers of the same name

### Requirement: Documentation SHALL explain TOML wiring for custom handlers
The Implementation Guide SHALL document how to reference a custom handler from a TOML control definition's `[[passes]]` block. It SHALL show the complete TOML syntax with `handler = "my_handler"` and pass-through configuration fields.

#### Scenario: Author wires a custom handler into a control
- **WHEN** an implementation author has registered a handler named `scorecard`
- **THEN** the documentation SHALL show a TOML example:
  ```toml
  [[controls."MY-01.01".passes]]
  phase = "deterministic"
  handler = "scorecard"
  threshold = 7
  categories = ["security", "maintenance"]
  ```
- **AND** SHALL explain that `threshold` and `categories` arrive in the handler's `config` dict

### Requirement: Documentation SHALL explain evidence propagation between handlers
The Implementation Guide SHALL document how evidence flows between handlers in a single control's pipeline. When a handler returns evidence in its `HandlerResult.evidence` dict, those key-value pairs are merged into `HandlerContext.gathered_evidence` for subsequent handlers.

#### Scenario: Author chains file_exists with a custom content checker
- **WHEN** an implementation author wants a two-pass pipeline (find file, then check content)
- **THEN** the documentation SHALL show a TOML example with two `[[passes]]` entries where the second handler reads `context.gathered_evidence["found_file"]` set by the first

### Requirement: Documentation SHALL cover remediation handler differences
The Implementation Guide SHALL document how remediation handlers differ from checking handlers. Key differences: all handlers in the deterministic remediation phase execute (not stop-on-first-conclusive), and remediation results use the same `HandlerResult` type but with different semantic expectations (PASS means remediation succeeded).

#### Scenario: Author writes a remediation handler
- **WHEN** an implementation author reads the remediation handler section
- **THEN** they SHALL understand that their handler will always execute even if a prior remediation handler in the same phase succeeded
- **AND** SHALL see an example remediation handler that creates a file or makes an API call

#### Scenario: Author understands dry-run support
- **WHEN** an implementation author reads about dry-run support
- **THEN** they SHALL understand the convention that handlers check for a `dry_run` config flag
- **AND** SHALL return a PASS result with a descriptive message instead of performing the action

### Requirement: Documentation SHALL provide a complete end-to-end example
The Implementation Guide SHALL include a complete worked example showing a custom handler from Python function through registration to TOML usage. The example SHALL be a realistic domain handler (not a trivial stub) that demonstrates config parsing, evidence production, and proper error handling.

#### Scenario: Author follows the end-to-end example
- **WHEN** an implementation author reads the complete example
- **THEN** they SHALL find: (1) the handler function with docstring, (2) registration call with phase affinity, (3) TOML control definition referencing the handler, (4) expected audit output for both pass and fail cases
