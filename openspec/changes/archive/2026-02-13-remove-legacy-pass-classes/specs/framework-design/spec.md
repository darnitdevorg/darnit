## MODIFIED Requirements

### 2.2 Control Definition

Each control is defined under `[controls."CONTROL-ID"]`:

```toml
[controls."OSPS-AC-03.01"]
# REQUIRED fields
name = "PreventDirectCommits"
description = "Prevent direct commits to primary branch"

# OPTIONAL framework-specific fields
level = 1                         # Maturity level (1, 2, 3)
domain = "AC"                     # Domain code
security_severity = 8.0           # CVSS-like severity (0.0-10.0)

# SARIF metadata (used for report generation)
help_md = """
**Remediation:**
1. Go to Repository Settings → Branches
2. Add branch protection rule for main/master
3. Enable 'Require a pull request before merging'
"""
docs_url = "https://baseline.openssf.org/..."

# Flexible tags for filtering
tags = { "branch-protection" = true, "code-review" = true }

# Verification passes (ordered array — see Section 3)
[[controls."OSPS-AC-03.01".passes]]
handler = "exec"
command = ["gh", "api", "/repos/$OWNER/$REPO/branches/$BRANCH/protection"]
pass_exit_codes = [0]
output_format = "json"
expr = 'output.json.required_pull_request_reviews != null'

[[controls."OSPS-AC-03.01".passes]]
handler = "manual"
steps = ["Verify branch protection in repository settings"]

# Remediation configuration
[controls."OSPS-AC-03.01".remediation]
# See Section 4: Built-in Remediation Actions
```

#### Scenario: Passes defined as ordered array
- **WHEN** a control defines verification passes
- **THEN** they MUST be declared as a TOML array of tables using `[[controls."ID".passes]]`
- **AND** each entry MUST have a `handler` field naming the handler to dispatch to
- **AND** the orchestrator MUST execute passes in declaration order

#### Scenario: Handler field required on each pass
- **WHEN** a pass entry is defined in the `[[passes]]` array
- **THEN** it MUST include a `handler` field with a string value
- **AND** the value MUST match a registered handler name (built-in or plugin-provided)

### 3. Built-in Pass Types

The sieve orchestrator executes passes in declaration order, dispatching each to its named handler. Execution stops at the first conclusive result.

#### Scenario: Pass execution follows declaration order
- **WHEN** a control has multiple `[[passes]]` entries
- **THEN** the orchestrator MUST execute them in the order they appear in the TOML file
- **AND** the orchestrator MUST stop at the first conclusive result (PASS, FAIL, or ERROR)
- **AND** INCONCLUSIVE results MUST cause the orchestrator to continue to the next pass

### 3.1 Pass Execution Order

```
Passes execute in TOML declaration order. Typical ordering:
  file_must_exist / exec  →  regex  →  llm_eval  →  manual
       ↓                      ↓          ↓            ↓
  Exact checks            Heuristics   AI eval    Human review
  (high conf)             (med conf)              (fallback)
```

The framework does not enforce a particular phase ordering. Controls MAY declare passes in any order. The convention above reflects decreasing confidence and increasing cost.

#### Scenario: Declaration order respected regardless of handler type
- **WHEN** a control declares passes in non-conventional order (e.g., `manual` before `exec`)
- **THEN** the orchestrator MUST still execute them in declaration order
- **AND** the handler type MUST NOT affect execution order

### 3.2 file_must_exist Handler

**Purpose**: High-confidence file existence checks with binary outcomes

**TOML Schema**:
```toml
[[controls."EXAMPLE".passes]]
handler = "file_must_exist"
files = ["SECURITY.md", ".github/SECURITY.md"]
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `handler` | `str` | MUST be `"file_must_exist"` |
| `files` | `list[str]` | Paths/globs where ANY match passes |

**Behavior**:
1. If any file in `files` matches → PASS
2. If no file matches → FAIL

#### Scenario: File found
- **WHEN** a `file_must_exist` handler is invoked
- **AND** at least one path in `files` matches an existing file
- **THEN** the handler MUST return PASS

#### Scenario: No file found
- **WHEN** a `file_must_exist` handler is invoked
- **AND** no path in `files` matches an existing file
- **THEN** the handler MUST return FAIL

### 3.3 exec Handler

**Purpose**: Execute external commands for verification

**TOML Schema**:
```toml
[[controls."EXAMPLE".passes]]
handler = "exec"
command = ["kusari", "repo", "scan", "$PATH", "HEAD"]
pass_exit_codes = [0]
fail_exit_codes = [1]
output_format = "json"
expr = 'output.json.status == "pass" && size(output.json.issues) == 0'
timeout = 300
env = { "TOOL_VERBOSE" = "true" }
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `handler` | `str` | MUST be `"exec"` |
| `command` | `list[str]` | Command and arguments (supports `$PATH`, `$OWNER`, `$REPO`, `$BRANCH`, `$CONTROL`) |
| `pass_exit_codes` | `list[int]` | Exit codes that indicate PASS (default: `[0]`) |
| `fail_exit_codes` | `list[int]` | Exit codes that indicate FAIL |
| `output_format` | `str` | Output format: `text`, `json`, `sarif` |
| `pass_if_output_matches` | `str` | Regex pattern - if matches stdout → PASS |
| `fail_if_output_matches` | `str` | Regex pattern - if matches stdout → FAIL |
| `pass_if_json_path` | `str` | JSONPath to extract value |
| `pass_if_json_value` | `str` | Expected value at JSON path for PASS |
| `expr` | `str` | CEL expression for pass logic (see Section 3.7) |
| `timeout` | `int` | Timeout in seconds (default: 300) |
| `env` | `dict` | Additional environment variables |

**Security**:
- Commands are executed as a list (no shell interpolation)
- Variable substitution only replaces whole tokens or substrings safely

#### Scenario: CEL expression evaluated
- **WHEN** an `exec` handler has an `expr` field
- **THEN** the CEL expression MUST be evaluated after command execution
- **AND** `expr` returning `true` MUST result in PASS
- **AND** `expr` returning `false` MUST result in INCONCLUSIVE (not FAIL)
- **AND** CEL evaluation errors MUST fall through to exit code evaluation

#### Scenario: Exit code evaluation
- **WHEN** an `exec` handler does not have an `expr` field or CEL evaluation is inconclusive
- **THEN** the handler MUST evaluate the exit code against `pass_exit_codes` and `fail_exit_codes`

### 3.4 regex Handler

**Purpose**: Regex-based content analysis

**TOML Schema**:
```toml
[[controls."EXAMPLE".passes]]
handler = "regex"
files = ["SECURITY.md", "README.md", "docs/*.md"]
patterns = {
    "has_email" = "[\\w.-]+@[\\w.-]+",
    "has_disclosure" = "(?i)disclos|report|vulnerabilit"
}
pass_if_any = true
fail_if_no_match = false
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `handler` | `str` | MUST be `"regex"` |
| `files` | `list[str]` | File patterns to search |
| `patterns` | `dict[str, str]` | Named patterns (name → regex) |
| `pass_if_any` | `bool` | PASS if any pattern matches (default: true) |
| `fail_if_no_match` | `bool` | FAIL instead of INCONCLUSIVE on no match |

#### Scenario: Pattern match found
- **WHEN** a `regex` handler is invoked with `pass_if_any = true`
- **AND** at least one pattern matches in any file
- **THEN** the handler MUST return PASS

#### Scenario: No match with fail_if_no_match
- **WHEN** a `regex` handler is invoked with `fail_if_no_match = true`
- **AND** no patterns match in any file
- **THEN** the handler MUST return FAIL

### 3.5 llm_eval Handler

**Purpose**: AI-assisted verification for ambiguous cases

**TOML Schema**:
```toml
[[controls."EXAMPLE".passes]]
handler = "llm_eval"
prompt = """
Evaluate whether the SECURITY.md file adequately explains:
1. How to report vulnerabilities
2. Expected response timeline
3. Disclosure policy
"""
prompt_file = "prompts/security_policy_eval.txt"
files_to_include = ["SECURITY.md", "README.md"]
analysis_hints = ["Look for contact information", "Check for timeline mentions"]
confidence_threshold = 0.8
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `handler` | `str` | MUST be `"llm_eval"` |
| `prompt` | `str` | Inline prompt template |
| `prompt_file` | `str` | Path to prompt file (alternative to inline) |
| `files_to_include` | `list[str]` | Files to include in LLM context |
| `analysis_hints` | `list[str]` | Hints to guide analysis |
| `confidence_threshold` | `float` | Minimum confidence for conclusive result (default: 0.8) |

#### Scenario: LLM confidence above threshold
- **WHEN** an `llm_eval` handler receives an LLM response
- **AND** the confidence score meets or exceeds `confidence_threshold`
- **THEN** the handler MUST return the LLM's pass/fail determination

#### Scenario: LLM confidence below threshold
- **WHEN** an `llm_eval` handler receives an LLM response
- **AND** the confidence score is below `confidence_threshold`
- **THEN** the handler MUST return INCONCLUSIVE

### 3.6 manual Handler

**Purpose**: Fallback for human verification

**TOML Schema**:
```toml
[[controls."EXAMPLE".passes]]
handler = "manual"
steps = [
    "Review contributor vetting process",
    "Verify maintainer identity verification",
    "Check access control documentation"
]
docs_url = "https://baseline.openssf.org/..."
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `handler` | `str` | MUST be `"manual"` |
| `steps` | `list[str]` | Verification steps for human reviewer |
| `docs_url` | `str` | Link to verification documentation |

**Behavior**: The manual handler always returns INCONCLUSIVE (resulting in WARN status), providing verification steps for human reviewers.

#### Scenario: Manual handler always inconclusive
- **WHEN** a `manual` handler is invoked
- **THEN** it MUST return INCONCLUSIVE
- **AND** the verification steps MUST be included in the result details

### 3.7 CEL Expressions

Handler types that support CEL expressions use Common Expression Language for flexible result evaluation.

**Purpose**: Replace multiple `pass_if_*` fields with a single declarative expression.

**TOML Schema**:
```toml
[[controls."EXAMPLE".passes]]
handler = "exec"
command = ["gh", "api", "/orgs/{org}/settings"]
expr = 'response.two_factor_requirement_enabled == true'

[[controls."EXAMPLE2".passes]]
handler = "exec"
command = ["kusari", "scan"]
output_format = "json"
expr = 'output.json.status == "pass" && size(output.json.issues) == 0'
```

**Context Variables**:

| Variable | Handler | Description |
|----------|---------|-------------|
| `output.stdout` | exec | Command stdout |
| `output.stderr` | exec | Command stderr |
| `output.exit_code` | exec | Command exit code |
| `output.json` | exec | Parsed JSON from stdout (if `output_format = "json"`) |
| `response.status_code` | api_check | HTTP status code |
| `response.body` | api_check | Response body |
| `response.headers` | api_check | Response headers |
| `files` | regex | List of matched file paths |
| `matches` | regex | Dict of pattern name → match results |
| `project.*` | all | Values from `.project/` context |

**Custom Functions**:

| Function | Description |
|----------|-------------|
| `file_exists(path)` | Check if file exists |
| `json_path(obj, path)` | Extract value from JSON using JSONPath |

**Behavior**:
- `expr` takes precedence over legacy fields (`pass_if_json_path`, etc.)
- Expression must return `true` for PASS, `false` for FAIL
- Expressions are sandboxed with 1s timeout
- CEL is non-Turing complete, preventing infinite loops

#### Scenario: CEL expression precedence
- **WHEN** both `expr` and legacy fields (e.g., `pass_if_json_path`) are defined
- **THEN** the `expr` field MUST take precedence

### 5.1 Execution Model

The orchestrator dispatches handler invocations sequentially, stopping at first conclusive result:

```python
for invocation in control.metadata["handler_invocations"]:
    handler = registry.get(invocation.handler)
    result = handler(invocation.config, context)

    if result.outcome == PASS:
        return SieveResult(status="PASS", ...)
    elif result.outcome == FAIL:
        return SieveResult(status="FAIL", ...)
    elif result.outcome == ERROR:
        return SieveResult(status="ERROR", ...)
    # INCONCLUSIVE → continue to next handler

# All handlers inconclusive
return SieveResult(status="WARN", verification_steps=manual_steps)
```

#### Scenario: Handler dispatch replaces pass execution
- **WHEN** the orchestrator evaluates a control
- **THEN** it MUST iterate `metadata["handler_invocations"]` (not a `passes` field on the control object)
- **AND** each invocation MUST be dispatched to its registered handler via the `SieveHandlerRegistry`

#### Scenario: LLM config read from handler invocations
- **WHEN** `verify_with_llm_response` processes an LLM evaluation
- **THEN** it MUST read `confidence_threshold` from the `llm_eval` handler invocation config
- **AND** it MUST read `verification_steps` from the `manual` handler invocation config
- **AND** it MUST default `confidence_threshold` to `0.8` when not specified

## REMOVED Requirements

### Requirement: VerificationPassProtocol
**Reason**: Replaced by handler dispatch architecture. Pass classes that implemented this protocol (`DeterministicPass`, `PatternPass`, `LLMPass`, `ManualPass`, `ExecPass`) are superseded by handler functions registered in `SieveHandlerRegistry`.
**Migration**: Define verification logic as handler functions matching `Callable[[dict, HandlerContext], HandlerResult]` and register via `SieveHandlerRegistry.register()`. Reference handlers by name in TOML `[[passes]]` entries.

#### Scenario: Protocol no longer used
- **WHEN** a plugin needs to define custom verification logic
- **THEN** it MUST register a handler function via `SieveHandlerRegistry`
- **AND** it MUST NOT implement `VerificationPassProtocol`

### Requirement: ControlSpec.passes field
**Reason**: The `passes` field stored instantiated pass class objects. All pass configuration is now stored as `HandlerInvocation` objects in `ControlSpec.metadata["handler_invocations"]`, loaded from TOML.
**Migration**: Access pass configuration via `control_spec.metadata["handler_invocations"]` instead of `control_spec.passes`.

#### Scenario: Field removed from ControlSpec
- **WHEN** code accesses a `ControlSpec` object
- **THEN** it MUST NOT reference a `.passes` attribute
- **AND** it MUST use `metadata["handler_invocations"]` for pass configuration

### Requirement: ControlSpec.__post_init__ phase-order validation
**Reason**: The `__post_init__` method validated that pass objects followed the recommended phase ordering (DETERMINISTIC → PATTERN → LLM → MANUAL). With handler dispatch, execution order is determined by TOML declaration order, and no phase-order enforcement is needed.
**Migration**: Rely on TOML declaration order for pass execution sequence. No validation replacement needed.

#### Scenario: Phase ordering not enforced
- **WHEN** a control defines passes in any order
- **THEN** the framework MUST NOT emit warnings about phase ordering
- **AND** passes MUST execute in declaration order regardless of handler type

### Requirement: DeterministicPass api_check and config_check callable fields
**Reason**: The `api_check` and `config_check` fields referenced Python callables (`"module:function"` strings) for deterministic verification. This pattern is replaced by custom sieve handlers registered in `SieveHandlerRegistry`.
**Migration**: Convert `api_check`/`config_check` callables to handler functions and register them via `SieveHandlerRegistry.register()`. Reference by handler name in TOML.

#### Scenario: Python callable references removed from TOML schema
- **WHEN** a control needs Python-based verification logic
- **THEN** it MUST use a custom handler referenced by name (e.g., `handler = "my_custom_check"`)
- **AND** it MUST NOT use `api_check` or `config_check` fields with `"module:function"` references

### Requirement: Legacy pass class instantiation
**Reason**: The classes `DeterministicPass`, `PatternPass`, `LLMPass`, `ManualPass`, and `ExecPass` in `sieve/passes.py` are removed. All verification logic is implemented as handler functions in `builtin_handlers.py`.
**Migration**: Replace `DeterministicPass(config_check=...)` with a custom sieve handler. Replace `ManualPass(verification_steps=[...])` with a TOML `[[passes]]` entry using `handler = "manual"`. See `IMPLEMENTATION_GUIDE.md` Section 5 for the handler authoring pattern.

#### Scenario: Pass classes unavailable for import
- **WHEN** plugin code attempts to import pass classes from `darnit.sieve.passes`
- **THEN** the import MUST raise `ImportError`
- **AND** the migration path MUST be documented in `IMPLEMENTATION_GUIDE.md`
