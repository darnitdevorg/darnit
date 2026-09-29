# Darnit Framework Design Specification

> **Version**: 1.0.0-alpha.8
> **Status**: Authoritative
> **Last Updated**: 2026-09-27

This specification defines the authoritative design of the Darnit framework, including the sieve orchestrator, TOML schema, built-in pass types, remediation actions, and plugin protocol.

---

## 1. Overview

### 1.1 Purpose

Darnit is a pluggable security and compliance auditing framework that:

1. **Orchestrates verification** through a 4-phase sieve pipeline
2. **Defines controls declaratively** via TOML configuration
3. **Supports multiple compliance frameworks** through a plugin architecture
4. **Generates standardized output** in SARIF, JSON, and Markdown formats

### 1.2 Philosophy

| Principle | Description |
|-----------|-------------|
| **Declarative First** | Most controls SHOULD be expressible in TOML without Python code |
| **Progressive Verification** | Sieve model: deterministic → pattern → LLM → manual |
| **Fail to Manual** | When uncertain, always fall back to human verification (WARN) |
| **Plugin-Optional** | Python plugins are an escape hatch for complex logic, not the default |

### 1.3 Architecture Diagram

```
┌─────────────────────────────────────────────────────────────┐
│  DARNIT FRAMEWORK (packages/darnit)                         │
│                                                             │
│  ┌──────────────────┐  ┌─────────────────────────────────┐  │
│  │ Sieve            │  │ TOML Schema                     │  │
│  │ Orchestrator     │  │ - Control structure             │  │
│  │ (4-phase         │  │ - Built-in pass types           │  │
│  │  pipeline)       │  │ - Built-in remediation actions  │  │
│  └──────────────────┘  └─────────────────────────────────┘  │
│                                                             │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ Built-in Capabilities (declarative, no Python)         ││
│  │ - file_must_exist, exec, api_check, pattern, template  ││
│  │ - api_call, file_create (remediation)                  ││
│  └─────────────────────────────────────────────────────────┘│
│                                                             │
│  ┌─────────────────────────────────────────────────────────┐│
│  │ Plugin Protocol (escape hatch for complex logic)       ││
│  └─────────────────────────────────────────────────────────┘│
└─────────────────────────────────────────────────────────────┘
                         ▲
                         │ validates/executes
                         ▼
┌─────────────────────────────────────────────────────────────┐
│  TOML CONFIG (user/AI-generated, from any source)           │
│  - Control definitions + SARIF metadata                     │
│  - Pass configs using built-in types                        │
│  - Optional Python plugin references (complex cases)        │
└─────────────────────────────────────────────────────────────┘
```

---

## 2. TOML Schema

### 2.1 Root Structure

```toml
[metadata]
name = "framework-name"           # REQUIRED: Framework identifier
display_name = "Framework Name"   # REQUIRED: Human-readable name
version = "0.1.0"                 # REQUIRED: Framework version
schema_version = "0.1.0-alpha"    # REQUIRED: TOML schema version
spec_version = "Spec v1.0"        # OPTIONAL: Upstream spec version
description = "..."               # OPTIONAL: Framework description
url = "https://..."               # OPTIONAL: Spec URL

[defaults]
check_adapter = "builtin"         # Default check adapter
remediation_adapter = "builtin"   # Default remediation adapter

[templates]
# Reusable templates for remediation

[context]
# Interactive context collection definitions

[controls]
# Control definitions (main content)
```

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

### 2.3 Schema Requirements

#### Requirement: Control ID Format
- **WHEN** a control is defined
- **THEN** the ID MUST be a quoted string key under `[controls]`
- **AND** the ID SHOULD follow pattern `{PREFIX}-{DOMAIN}-{NUMBER}`

#### Requirement: Minimal Control Definition
- **WHEN** a control is defined
- **THEN** it MUST have `name` and `description` fields
- **AND** it SHOULD have at least one pass defined

#### Requirement: SARIF Metadata
- **WHEN** SARIF output is generated
- **THEN** the framework MUST use `help_md`, `docs_url`, and `security_severity` from TOML
- **AND** the framework MUST NOT require a separate rules catalog

---

## 3. Built-in Pass Types

The sieve orchestrator executes passes in declaration order, dispatching each to its named handler. Execution stops at the first conclusive result. A result is conclusive only when its outcome is in the step's effective set (section 3.0.1): what a step may conclude depends on what it proves about the specific control, not on the kind of step (RFC-0001 September 2026 revision, "Authority is per claim, not per handler").

#### Scenario: Pass execution follows declaration order
- **WHEN** a control has multiple `[[passes]]` entries
- **THEN** the orchestrator MUST execute them in the order they appear in the TOML file
- **AND** the orchestrator MUST stop at the first conclusive result
- **AND** INCONCLUSIVE results, and results whose outcome the step may not conclude, MUST cause the orchestrator to continue to the next pass

### 3.0 Handler Outcomes

A handler returns one of five outcomes. INCONCLUSIVE and ERROR never conclude; PASS, FAIL, and WARN conclude only when the step may conclude them.

| Outcome | Meaning | Concludes the control? |
|---------|---------|------------------------|
| `PASS` | The control is satisfied. | Yes, when `pass` is in the step's effective set |
| `FAIL` | The control is not satisfied. | Yes, when `fail` is in the step's effective set |
| `WARN` | The handler read the evidence, understood it, and determined it is insufficient to pass. | Yes, when `fail` is in the step's effective set |
| `INCONCLUSIVE` | The handler determined nothing. | No -- the pipeline continues |
| `ERROR` | The handler could not measure (platform or API error, missing tool, evaluation error). | No -- the error is recorded and the pipeline continues; if no later step concludes, the control ends ERROR with the first recorded cause |

`WARN` differs from `INCONCLUSIVE` in kind, not in degree. INCONCLUSIVE means a later pass may still determine something. WARN means the answer has been determined and the answer is "not enough". A handler MUST NOT return WARN to mean "I am unsure".

A WARN counts as FAIL for compliance calculations (Constitution Principle II), which is why a WARN concludes under the same permission as FAIL. A WARN carries the handler's own message; it MUST NOT be replaced by a generic string.

#### Scenario: A handler concludes WARN
- **WHEN** a handler returns WARN and `fail` is in the step's effective set
- **THEN** the orchestrator MUST conclude the control as WARN
- **AND** the resulting message MUST be the handler's own message
- **AND** the pass history MUST record the pass outcome as WARN, not INCONCLUSIVE

#### Scenario: A WARN the step may not conclude
- **WHEN** a handler returns WARN and `fail` is not in the step's effective set
- **THEN** the orchestrator MUST NOT conclude the control
- **AND** it MUST attach evidence and continue, or terminate INCONCLUSIVE if this was the last step

### 3.0.1 Step Ceilings and Declarations

Every step type registers a **ceiling**: the set of outcomes (`pass`, `fail`) it can at most conclude. Presence and pattern step types also register an **existence ceiling**, used when a step declares that its control's requirement is literally about existence.

| Step type | Ceiling | Existence ceiling |
|-----------|---------|-------------------|
| `file_exists` | `{fail}` | `{pass, fail}` |
| `regex` / `pattern` | `{fail}` | `{pass, fail}` |
| `exec` | `{pass, fail}` | -- |
| `gh_api` | `{pass, fail}` | -- |
| `mcp` | `{pass, fail}` | -- |
| `llm_eval`, `llm_extract` | `{}` | -- |
| `manual`, `manual_steps` | `{}` | -- |
| remediation handlers (`file_create`, `api_call`, `project_update`, `yaml_inject`) | `{}` | -- |

A plugin handler registers its ceiling with the handler (`registry.register(..., ceiling={"pass", "fail"})`). A plugin handler that registers no ceiling has the ceiling `{}`: its results are evidence only.

**Step fields** (on any `[[controls."ID".passes]]` entry; none are passed to the handler except `fail_on_miss` and `fail_on_status`):

| Field | Type | Description |
|-------|------|-------------|
| `concludes` | `list["pass" \| "fail"]` | Narrows the ceiling for this control. Default: the ceiling. |
| `existence` | `bool` | Presence and pattern steps only. The control's requirement is literally that a file exists (or does not); selects the existence ceiling. |
| `fail_on_miss` | `bool` | Pattern steps only. A pattern miss proves failure (section 3.4). Requires `fail` in the effective set. |
| `fail_on_status` | `list[int]` | `gh_api` steps only. HTTP statuses that prove failure (section 3.8). |
| `promotion` | `{outcome = "pass", corpus = str, note = str}` | Permission to conclude PASS beyond the ceiling, justified by a corpus measurement (section 5.5). |
| `authority` | `str` | Legacy (feature 025). `"suggestive"` is the same as `concludes = []`. `"dispositive"` does not change the effective set and is rejected on a step type whose ceiling is empty. `"asserted"` is rejected: no step type is a human confirmation. |

**Effective set** = (existence ceiling if `existence = true`, else ceiling), intersected with `concludes` when given, union the promoted outcome when a promotion exists.

**Validation** runs when controls are loaded, on every control-loading path (framework-only and effective/merged), after plugin handlers register. It rejects, naming the framework, control, step index, and outcome:

1. `existence` on a step type without an existence ceiling;
2. `fail_on_miss` on a non-pattern step, or without `fail` in the effective set;
3. `fail_on_status` on a step type other than `gh_api`, or without `fail` in the effective set;
4. any `concludes` outcome outside the (existence) ceiling without a promotion for that outcome;
5. a promotion whose outcome is not `pass`, or that lacks `corpus`.

The orchestrator computes the effective set from the registry at dispatch time as well, so a step that escaped validation still cannot conclude an outcome outside its ceiling without a promotion.

#### Scenario: Presence proves only absence
- **WHEN** a `file_exists` step without `existence = true` finds the file
- **THEN** its PASS MUST be recorded as evidence and evaluation MUST continue
- **AND** when it finds no file, its FAIL MUST conclude the control

#### Scenario: Existence requirement
- **WHEN** a `file_exists` step declares `existence = true` and finds the file
- **THEN** it MUST conclude the control PASS

#### Scenario: Widening without a promotion
- **WHEN** a step declares `concludes = ["pass"]` on a step type whose ceiling does not include `pass`, without a promotion
- **THEN** loading the framework configuration MUST fail with an error naming the framework, control, step index, and outcome

### 3.0.2 Step Disposition Table

The disposition applied to each step, by handler outcome and whether the outcome is in the step's effective set:

| Handler outcome | In effective set | Not in effective set, not last | Not in effective set, last step |
|-----------------|------------------|--------------------------------|---------------------------------|
| `ERROR` | RECORD_ERROR_AND_CONTINUE (TERMINATE_ERROR on the last step) | RECORD_ERROR_AND_CONTINUE | TERMINATE_ERROR |
| `PASS` | CONCLUDE_PASS | ATTACH_EVIDENCE_AND_CONTINUE | TERMINATE_INCONCLUSIVE |
| `FAIL` | CONCLUDE_FAIL | ATTACH_EVIDENCE_AND_CONTINUE | TERMINATE_INCONCLUSIVE |
| `WARN` | CONCLUDE_WARN (when `fail` is in the set) | ATTACH_EVIDENCE_AND_CONTINUE | TERMINATE_INCONCLUSIVE |
| `INCONCLUSIVE` | ATTACH_EVIDENCE_AND_CONTINUE | ATTACH_EVIDENCE_AND_CONTINUE | TERMINATE_INCONCLUSIVE |

A step that concludes within its effective set records authority `dispositive` and `concluded_by` = the step's handler name. A control no step concludes, and in which no step erred, is WARN with authority `suggestive` and `concluded_by = "none"`, carrying the evidence gathered.

**Errors.** An ERROR step never concludes the control, and in particular never concludes FAIL. The orchestrator records the first ERROR (its class and cause) and runs the remaining steps. If a later step concludes, its result wins; the earlier error stays in the pass history. If no later step concludes, the control is ERROR with `error = {class, cause}` from the first recorded error (class `evaluation` when the handler named none), `concluded_by` and `resolving_pass_index` naming the step that erred. A recorded ERROR takes precedence over ending WARN and over stopping for a model judgment (`PENDING`, section 5.4): a control with a broken measurement does not wait for a judgment.

`inferred_from` (a control that passes when another control passed) follows the same rule: the inferred PASS is produced only when the source control's PASS was itself concluded (authority `dispositive` or `asserted`), and it records `concluded_by = "inferred_from"`.

The CEL post-step (section 3.7) does not modify a WARN result. Its transition table is defined for PASS and FAIL only; there is no "CEL disagrees with WARN" cell, because WARN already asserts that the evidence is incomplete.

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

**Ceiling**: `{fail}`; `{pass, fail}` with `existence = true` (section 3.0.1). A file being present says nothing about its content, so a presence step concludes PASS only for a control whose requirement is literally that the file exists.

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
| `expr` | `str` | CEL expression for pass logic (see Section 3.7; full context/function reference in [docs/CEL_CONTEXT.md](../CEL_CONTEXT.md)) |
| `timeout` | `int` | Timeout in seconds (default: 300) |
| `env` | `dict` | Additional environment variables |

**Security**:
- Commands are executed as a list (no shell interpolation)
- Variable substitution only replaces whole tokens or substrings safely

**Broken measurements**: a command whose binary is not installed is ERROR, class `missing_tool`; a timeout is ERROR, class `timeout`. Neither is FAIL.

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
fail_on_miss = false
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `handler` | `str` | MUST be `"regex"` |
| `files` | `list[str]` | File patterns to search |
| `patterns` | `dict[str, str]` | Named patterns (name → regex) |
| `pass_if_any` | `bool` | PASS if any pattern matches (default: true) |
| `fail_on_miss` | `bool` | FAIL instead of INCONCLUSIVE on no match (default: false). Step field; requires `fail` in the step's effective set. |

**Ceiling**: `{fail}`; `{pass, fail}` with `existence = true` (section 3.0.1). A keyword match is evidence that a document mentions something, not that it satisfies the control.

**Behavior** (match mode):
1. Match per `pass_if_any` -> PASS
2. No match -> INCONCLUSIVE, unless `fail_on_miss = true` -> FAIL
3. No files resolved -> INCONCLUSIVE

Exclude mode (`exclude_files`) is unchanged: no files found -> PASS, files found -> FAIL, usually refined by `expr`.

#### Scenario: Pattern match found
- **WHEN** a `regex` handler is invoked with `pass_if_any = true`
- **AND** at least one pattern matches in any file
- **THEN** the handler MUST return PASS

#### Scenario: No match without fail_on_miss
- **WHEN** a `regex` handler is invoked without `fail_on_miss`
- **AND** no patterns match in any file
- **THEN** the handler MUST return INCONCLUSIVE and evaluation MUST continue

#### Scenario: No match with fail_on_miss
- **WHEN** a `regex` handler is invoked with `fail_on_miss = true`
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
| `files_to_include` | `list[str]` | Files to include in LLM context. Supports `$FOUND_FILE` to reference the file discovered by a preceding `file_exists` handler. |
| `analysis_hints` | `list[str]` | Hints to guide analysis |
| `confidence_threshold` | `float` | Passed to the model with the consultation. Since feature 041 a judgment's confidence is recorded with it but is never a decision input: a judgment never concludes a control. |

**`files_to_include` resolution**: The handler MUST resolve `$FOUND_FILE` entries by looking up `found_file` in `context.gathered_evidence`. Each resolved file path MUST be read (up to 10KB per file, max 5 files) and included as `file_contents` in the `consultation_request`. File paths that are not absolute MUST be resolved relative to `context.local_path`. Files that cannot be read MUST be silently skipped.

**Ceiling**: `{}`. The handler returns INCONCLUSIVE with a `consultation_request`; with `stop_on_llm` the control becomes `PENDING` with `pending.kind = "llm_judgment"` (section 5.4). A model judgment never concludes PASS. No promotion to conclude PASS exists for a model judgment.

**Judged content and evidence digest.** The content a judgment is checked against is the step's `file_contents` (the files it read, as capped above). The evidence digest is `sha256:` followed by the SHA-256 of a canonical JSON encoding of that content together with the step's rubric (`prompt` and `analysis_hints`), so a confirmation lapses when either the files or the rubric change. Other gathered evidence (earlier steps' outputs, other controls' statuses) is not part of the digest.

**Citations.** A judgment carries `cited_evidence`: verbatim excerpts of the judged content. An excerpt is found when, after collapsing every run of whitespace to one space in both, it occurs in one of the judged files. A positive judgment MUST cite at least one excerpt. Any cited excerpt that is not found makes the judgment invalid, whatever its verdict.

#### Scenario: Positive judgment
- **WHEN** a model judgment says the evidence satisfies the control
- **AND** it cites at least one excerpt and every excerpt it cites appears verbatim (whitespace-normalized) in the content it was given
- **THEN** the control MUST be `PENDING` with `pending.kind = "confirmation"` and a `candidate` block (a PASS candidate)
- **AND** it MUST count as non-compliant until an operator confirms it

#### Scenario: Unverifiable citation
- **WHEN** a judgment cites an excerpt not present in the content it was given, or a positive judgment cites nothing
- **THEN** no PASS candidate MUST be produced, nothing MUST be stored, and the control MUST be WARN, naming the excerpts not found

#### Scenario: Negative judgment
- **WHEN** a model judgment says the evidence does not satisfy the control
- **THEN** the control MUST be FAIL with authority `suggestive` and `concluded_by = "llm_judgment"`

#### Scenario: Inconclusive judgment
- **WHEN** a model judgment says the evidence is insufficient to decide
- **THEN** the control MUST be WARN

#### Scenario: Model service failure
- **WHEN** the model service times out or errors
- **THEN** the control MUST be ERROR with the cause (class `unavailable`, or `evaluation` when the model's answer could not be used), never WARN or FAIL

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

### 3.8 gh_api Handler

**Purpose**: Status-aware platform API checks. `gh api` exits 1 for 401, 403, 404, and 429 alike, so an `exec` step cannot tell "does not exist" from "not permitted to see". `gh_api` sees the HTTP status and only statuses the step declares in `fail_on_status` may prove failure.

**TOML Schema**:
```toml
[[controls."EXAMPLE".passes]]
handler = "gh_api"
endpoint = "/repos/$OWNER/$REPO/branches/$BRANCH/protection"
fail_on_status = [404]
expr = 'has(response.body.required_pull_request_reviews)'
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `handler` | `str` | MUST be `"gh_api"` |
| `endpoint` | `str` | API path (supports `$OWNER`, `$REPO`, `$BRANCH`) |
| `fail_on_status` | `list[int]` | HTTP statuses that prove failure (step field) |
| `expr` | `str` | CEL over `response.status_code` and `response.body` (the parsed JSON body); `true` -> PASS, `false` -> FAIL. Evaluated by the handler, not by the post-step of section 3.7, so `output.*` is not bound. Response headers are not available (`gh api` does not expose them). |

**Ceiling**: `{pass, fail}`.

**Behavior**:
1. 2xx: `expr` decides (no `expr`: PASS); an `expr` that cannot be evaluated over the response -> ERROR, class `evaluation`
2. 429, or a 403 whose message is a rate limit -> ERROR, class `rate_limit`, even when the status is in `fail_on_status` (a rate limit never proves failure)
3. A status in `fail_on_status` -> FAIL
4. 401 / 403 -> ERROR, class `auth`
5. 5xx, transport failure, or any other status not declared -> ERROR, class `unavailable`
6. `gh` not installed -> ERROR, class `missing_tool`

A response that is ambiguous between "not found" and "not permitted to see" is ERROR unless the step declares otherwise.

**Evidence**: `endpoint` (after substitution), `response` (`status_code`, `body`), and on a non-2xx answer the `gh` error text.

**Recorded responses**: the handler calls the platform through `darnit.core.utils.gh_api_with_status`. `set_gh_api_responder(responder)` routes every such call (including the `github_branch_protection` plugin handler's) through a responder instead of `gh`; `RecordedGhApi({path: {status, body, error}})` serves recorded responses keyed by API path, answers an unrecorded path as a transport failure (status 0), and with `gh_missing = True` answers as if `gh` were not installed. Tests and the adversarial corpus (section 5.5) use it to run platform checks offline and deterministically.

#### Scenario: Declared status proves failure
- **WHEN** a `gh_api` step with `fail_on_status = [404]` receives 404
- **THEN** the handler MUST return FAIL

#### Scenario: Undeclared status is a broken measurement
- **WHEN** a `gh_api` step receives 404 without declaring it, or receives 401, 403, 429, or 5xx
- **THEN** the handler MUST return ERROR with the cause

#### Scenario: A rate limit never proves failure
- **WHEN** a `gh_api` step declares `fail_on_status = [403]` and receives a rate-limit 403
- **THEN** the handler MUST return ERROR, class `rate_limit`

---

## 4. Built-in Remediation Actions

### 4.1 Overview

Remediations can be:
1. **Declarative** - Defined entirely in TOML using built-in actions
2. **Hybrid** - TOML config with Python handler reference
3. **Custom** - Full Python implementation via plugin

### 4.2 FileCreateRemediation

**Purpose**: Create files from templates

```toml
[controls."OSPS-VM-02.01".remediation]
[controls."OSPS-VM-02.01".remediation.file_create]
path = "SECURITY.md"
template = "security_policy_standard"  # References [templates.security_policy_standard]
overwrite = false
create_dirs = true
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `path` | `str` | Target file path (relative to repo root) |
| `template` | `str` | Template name from `[templates]` section |
| `content` | `str` | Inline content (alternative to template) |
| `overwrite` | `bool` | Overwrite existing files (default: false) |
| `create_dirs` | `bool` | Create parent directories (default: true) |
| `llm_enhance` | `str` | Optional prompt for AI-assisted customization of the created file |

#### Scenario: file_create with llm_enhance
- **WHEN** a `file_create` handler succeeds
- **AND** the handler config includes an `llm_enhance` field
- **THEN** the remediation result MUST include the enhancement prompt and file path in the result details
- **AND** the MCP layer MAY use this prompt to offer AI-assisted customization of the generated file

### 4.3 ExecRemediation

**Purpose**: Execute commands for remediation

```toml
[controls."OSPS-AC-03.01".remediation]
[controls."OSPS-AC-03.01".remediation.exec]
command = ["gh", "api", "-X", "PUT", "/repos/$OWNER/$REPO/branches/$BRANCH/protection"]
stdin_template = "branch_protection_payload"
success_exit_codes = [0]
timeout = 300
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `command` | `list[str]` | Command and arguments |
| `stdin_template` | `str` | Template name for stdin input |
| `stdin` | `str` | Inline stdin content |
| `success_exit_codes` | `list[int]` | Exit codes indicating success |
| `timeout` | `int` | Timeout in seconds |
| `env` | `dict` | Environment variables |

### 4.4 ApiCallRemediation

**Purpose**: GitHub API calls via `gh` CLI

```toml
[controls."OSPS-AC-03.01".remediation]
[controls."OSPS-AC-03.01".remediation.api_call]
method = "PUT"
endpoint = "/repos/$OWNER/$REPO/branches/$BRANCH/protection"
payload_template = "branch_protection"
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `method` | `str` | HTTP method (default: PUT) |
| `endpoint` | `str` | API endpoint with variable substitution |
| `payload_template` | `str` | Template name for JSON payload |
| `payload` | `dict` | Inline JSON payload |
| `jq_filter` | `str` | JQ filter for response |

### 4.5 Templates

Templates support variable substitution and can source their content from inline strings or external files:

```toml
# Inline content
[templates.security_policy_standard]
description = "Standard SECURITY.md template"
content = """
# Security Policy

## Reporting a Vulnerability

Please report security vulnerabilities to security@$OWNER.github.io
or use GitHub's "Report a vulnerability" feature.

### Response Timeline
- **Initial Response**: Within 48 hours
- **Status Update**: Within 7 days
- **Resolution Target**: Within 90 days
"""

# External file
[templates.contributing_standard]
description = "Standard CONTRIBUTING.md template"
file = "templates/contributing_standard.tmpl"
```

**Template fields**:

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `content` | `str` | One of `content` or `file` | Inline template content |
| `file` | `str` | One of `content` or `file` | Path to external template file, resolved relative to the TOML file's directory |
| `description` | `str` | No | Human-readable description of the template |

A template entry SHALL have exactly one of `content` or `file`. Having both or neither is a validation error.

The `file` path SHALL be resolved relative to the directory containing the framework TOML file. Absolute paths SHALL be used as-is.

**Variables**:

| Variable | Description |
|----------|-------------|
| `$OWNER` | Repository owner |
| `$REPO` | Repository name |
| `$BRANCH` | Default branch |
| `$YEAR` | Current year |
| `$DATE` | Current date (ISO format) |
| `$MAINTAINERS` | Detected maintainers (if available) |

Variable substitution SHALL apply identically to both inline `content` and file-sourced templates.

**Variable Resolution**: `$OWNER`, `$REPO`, and `$BRANCH` MUST be resolved
using `detect_repo_from_git()` from `darnit.core.utils` — the canonical repo
identity detector. This function prefers the `upstream` git remote over
`origin` so that audits on forks evaluate the upstream project. No other
module SHALL implement repo identity detection logic (parsing git remotes,
calling `gh repo view`, etc.).

#### Scenario: Template with inline content
- **WHEN** a `[templates.foo]` entry has `content = "# Header\n..."`
- **THEN** the executor SHALL use the inline string as the template body

#### Scenario: Template with external file
- **WHEN** a `[templates.foo]` entry has `file = "templates/foo.tmpl"`
- **THEN** the executor SHALL read the file relative to the TOML directory and use its contents as the template body

#### Scenario: Variable substitution on file-sourced template
- **WHEN** a template loaded from file contains `$OWNER` and `${context.maintainers}`
- **THEN** the executor SHALL substitute variables identically to inline templates

---

## 5. Sieve Orchestrator

### 5.1 Execution Model

The orchestrator dispatches handler invocations sequentially, stopping at the first result the step may conclude:

```python
for invocation in control.metadata["handler_invocations"]:
    handler = registry.get(invocation.handler)
    result = handler(invocation.config, context)
    allowed = effective_set(handler, invocation)   # section 3.0.1

    if result.outcome == ERROR:
        first_error = first_error or (result.error_class, result.message)
        continue                                      # never concludes FAIL
    if result.outcome == PASS and "pass" in allowed:
        return SieveResult(status="PASS", authority="dispositive", concluded_by=invocation.handler)
    if result.outcome in (FAIL, WARN) and "fail" in allowed:
        return SieveResult(status=result.outcome, authority="dispositive", concluded_by=invocation.handler)
    # anything else is evidence -> continue to next handler
    # (a model step stops here with PENDING only when no error was recorded)

# No step concluded
if first_error:
    return SieveResult(status="ERROR", error={"class": first_error[0] or "evaluation", "cause": first_error[1]})
return SieveResult(status="WARN", authority="suggestive", concluded_by="none")
```

#### Scenario: Handler dispatch replaces pass execution
- **WHEN** the orchestrator evaluates a control
- **THEN** it MUST iterate `metadata["handler_invocations"]` (not a `passes` field on the control object)
- **AND** each invocation MUST be dispatched to its registered handler via the `SieveHandlerRegistry`

#### Scenario: LLM config read from handler invocations
- **WHEN** `verify_with_llm_response` processes a model judgment that leaves the control WARN
- **THEN** it MUST read `verification_steps` from the `manual` handler invocation config
- **AND** it MUST NOT use the judgment's confidence to decide the result (section 3.5)

### 5.2 Result Statuses

| Status | Description | Compliant |
|--------|-------------|-----------|
| `PASS` | Control verified compliant, by a step allowed to conclude PASS or by a confirmed PASS candidate | Yes |
| `N/A` | Not applicable (control `when` false, or an honored not-applicable claim, feature 040) | Excluded |
| `FAIL` | Control verified non-compliant, or a negative model finding | No |
| `WARN` | Needs verification: no step concluded, or a step concluded the evidence is insufficient | No |
| `ERROR` | Broken measurement: platform or API error, missing tool, evaluation error | No |
| `PENDING` | Awaiting a model judgment (`pending.kind = "llm_judgment"`) or an operator confirmation of a PASS candidate (`pending.kind = "confirmation"`) | No |

`PENDING` replaces the former `PENDING_LLM` status.

Result fields beyond `status`:

| Field | Description |
|-------|-------------|
| `authority` | `dispositive` (a step concluded within its effective set), `suggestive` (no step concluded, or a model finding), `asserted` (a person confirmed it) |
| `concluded_by` | Step handler name, `llm_judgment`, `confirmation`, `inferred_from`, or `none` |
| `error` | `{class, cause}`; present on every ERROR. Classes include `auth`, `rate_limit`, `unavailable`, `missing_tool`, `evaluation`, and the feature 036 classes |
| `pending` | `{kind}`; present on every PENDING |
| `candidate` | Present with `pending.kind = "confirmation"`: `verdict = "pass"`, `reasoning`, `cited_evidence`, `model`, `model_version`, `evidence_digest`, `source` (`harness` or `mcp_agent`) |
| `confirmation` | Present on a PASS from a confirmed candidate: `confirmed_by`, `confirmed_at`, `expires_at` |

**Compliance** is computed in one place (`calculate_compliance`) for every driver, report format, and attestation: a level is compliant only if every applicable control is PASS (N/A excluded per feature 040). FAIL, WARN, ERROR, and PENDING, including a PASS candidate, are non-compliant.

**Reports and attestations** carry these fields and label them for a reader: an ERROR's class and cause as a broken measurement, not a finding about the project; a PENDING result's kind; a PASS candidate as not compliant until confirmed, with its model and number of cited excerpts; a model finding; and a confirmed candidate as asserted, with the confirmer, time, and expiry. A PASS candidate MUST NOT be rendered or attested as PASS: an attestation keeps its status `PENDING` and labels its `candidate` with `confirmed = false` and no verdict. Attestation fields are additive within the current predicate version.

#### Scenario: ERROR is never FAIL
- **WHEN** a step could not measure (API authorization or rate-limit error, missing tool, evaluation error)
- **THEN** the result MUST be ERROR with `error.class` and `error.cause`
- **AND** it MUST NOT be reported as FAIL

#### Scenario: A later step concludes after an ERROR
- **WHEN** a step returns ERROR and a later step concludes within its effective set
- **THEN** the control MUST take the later step's result
- **AND** the ERROR MUST remain in the pass history

#### Scenario: A required MCP server is missing
- **WHEN** an `mcp` step's server is marked required (`optional = false`) and its binary is absent, its handshake fails, or it is unusable
- **THEN** the step MUST return ERROR (class `missing_tool` for an absent binary, `network` otherwise), not FAIL

### 5.3 Evidence Accumulation

Evidence from each pass accumulates and is available to subsequent passes:

```python
context.gathered_evidence["api_check_result"] = {...}
context.gathered_evidence["file_found"] = "/path/to/SECURITY.md"
```

### 5.4 LLM Consultation Protocol

When an LLM pass is reached and `stop_on_llm=True`:

1. Orchestrator returns `PENDING` with `pending.kind = "llm_judgment"` and the consultation request in `evidence.llm_consultation`
2. A judgment arrives from the headless harness's model step or from a coding agent through the `submit_judgment` MCP tool; both paths apply the same rules
3. A positive judgment with verified citations becomes a PASS candidate (`PENDING`, `pending.kind = "confirmation"`), stored operator-side in the feature 040 confirmation store with claim `pass_candidate`; a negative judgment is a suggestive FAIL; an unverifiable citation leaves the control WARN; a model-service failure is ERROR (section 3.5)
4. An operator confirms a candidate through the confirmation flow; later audits report PASS with authority `asserted`, `concluded_by = "confirmation"`, and the confirmer and time, until the evidence digest changes or the confirmation expires

No driver records a verdict for a judgment-requiring control by any other path; the ActionPlan audit step does not accept client-supplied per-control statuses.

**Stored candidates and confirmations.** The confirmation store (`<data root>/trust/confirmations.json`) holds candidates beside confirmations. A candidate is keyed by canonical repository identity, control, claim `pass_candidate`, and evidence digest; it is stored only when the repository identity was named by the operator or CI metadata (never from the checkout's remotes), replaces an earlier candidate for the same repository and control, and removes that control's `pass_candidate` confirmations that no longer apply to its digest. A stored candidate is never a confirmation. When an audit leaves a control `PENDING` (`llm_judgment`), the audit pipeline computes the current evidence digest and applies the store:

| Store holds, for this repository, control, and current digest | Result |
|---|---|
| An unexpired `pass_candidate` confirmation | PASS, authority `asserted`, `concluded_by = "confirmation"`, `confirmation` block (and the `candidate` it confirmed) |
| Only an expired confirmation, or a confirmation for a different digest | `PENDING` (`llm_judgment`): the confirmation lapsed; a new judgment is needed |
| A candidate and no confirmation | `PENDING` (`confirmation`) with the `candidate` block |
| Nothing | `PENDING` (`llm_judgment`) |

**MCP tools.** Every framework server registers, beside `run_next_action` and `submit_action_result`:

```
submit_judgment(
  control_id: str, verdict: "pass" | "fail", reasoning: str,
  cited_evidence: list[str], model: str, model_version: str,
  owner: str, repo: str, host: str = "github.com", local_path: str = "."
) -> {status: "candidate" | "finding" | "rejected" | "error", candidate | finding | rejection | error}
```

It re-runs the audit for `local_path` to re-gather the control's judged content (the client's copy is never trusted), applies section 3.5, and for a valid positive judgment records the candidate (`source = "mcp_agent"`). A negative judgment returns a suggestive FAIL finding and stores nothing; an invalid one returns a rejection naming the excerpts not found and stores nothing. A control that does not reach its model step is rejected.

```
confirm_pass_candidate(
  control_ids: list[str], owner: str, repo: str,
  host: str = "github.com", local_path: str = "."
) -> str
```

An operator confirms candidates through `confirm_pass_candidate`, registered on every framework server beside `submit_judgment` (OpenSSF Baseline also accepts `confirm_project_data(confirm_pass_candidate=[...])`, which runs the same confirmation). It re-gathers the evidence and confirms only a stored candidate whose digest matches the current evidence, recording `confirmed_by`, `confirmed_at`, and `expires_at` (operator policy `confirmation_expiry_days`). An agent calls it only on the operator's explicit instruction.

**ActionPlan.** For the `audit` step, `submit_action_result` accepts no client payload: the server runs the audit itself and records only the results the engine produced. In-process drivers submit the engine's result object (`run_audit_step`); a plain mapping carrying audit results is rejected with `ResultSchemaMismatch`.

### 5.5 Adversarial Fixture Corpus

A corpus of small fixture repositories with human-labelled expected outcomes per control (`tests/darnit_baseline/corpus/<fixture>/labels.toml`: `PASS`, `FAIL`, `NOT_PASS`, or `N/A`) measures every step. A corpus run reports, per step and outcome, the correct and incorrect conclusions against the labels, and fails if any step allowed to conclude PASS produces a false PASS, naming the step and fixture. A step not allowed to conclude PASS is eligible for a `promotion` (section 3.0.1) only with zero false PASS results; the promotion's `corpus` field records the corpus version that justified it. Adding a fixture requires only its files and labels.

---

## 6. Plugin Protocol

### 6.1 When to Use Plugins

Plugins are appropriate when:
- Logic cannot be expressed with built-in pass types
- External tool integration requires custom parsing
- Framework-specific semantics need encoding

### 6.2 Entry Point Registration

```toml
# pyproject.toml
[project.entry-points."darnit.implementations"]
openssf-baseline = "darnit_baseline:register"
```

> **For third-party plugin authors**: a step-by-step packaging guide lives at [`docs/packaging-plugins.md`](../../../docs/packaging-plugins.md), and a minimum-viable copy-paste starter at [`packages/darnit-hello/`](../../../packages/darnit-hello/). Both are kept in sync with this spec by CI (`plugin_discovery_smoke` job in `.github/workflows/ci.yml`).

### 6.3 Implementation Protocol

```python
from darnit.core.plugin import ComplianceImplementation, ControlSpec

class MyImplementation:
    @property
    def name(self) -> str:
        return "my-framework"

    @property
    def display_name(self) -> str:
        return "My Framework"

    @property
    def version(self) -> str:
        return "1.0.0"

    @property
    def spec_version(self) -> str:
        return "MySpec v1.0"

    def get_all_controls(self) -> list[ControlSpec]:
        # Return control definitions
        ...

    def get_framework_config_path(self) -> Path | None:
        # Return path to TOML config
        return Path(__file__).parent / "my-framework.toml"

    def register_controls(self) -> None:
        # No-op. Control definitions MUST come from TOML.
        # This method exists for protocol compatibility only.
        pass

    def register_handlers(self) -> None:
        # Register custom sieve/remediation handlers
        ...
```

The `register_controls()` method SHALL be a no-op. Implementations MUST NOT use this method to register `ControlSpec` objects with `passes` fields populated. All control definitions MUST originate from TOML configuration files and be loaded via the framework's TOML control loader. The only supported extension point for custom checking logic is `register_handlers()`, which registers named handler functions callable from TOML pass definitions.

#### Scenario: Implementation calls register_controls
- **WHEN** the audit pipeline calls `impl.register_controls()`
- **THEN** no `ControlSpec` objects SHALL be registered in the global registry
- **AND** no side-effect imports of control definition modules SHALL occur

#### Scenario: Plugin extends checking with custom handler
- **WHEN** a plugin needs custom checking logic beyond built-in pass types
- **THEN** it SHALL register a named handler via `register_handlers()`
- **AND** the TOML control definition SHALL reference the handler by name in its `passes` configuration

### 6.3.1 No Hardcoded Control IDs in Framework

The `packages/darnit/src/darnit/` source tree SHALL NOT contain hardcoded control definitions registered at module import time. The framework's `sieve/registry.py` module SHALL only provide the `ControlRegistry` class and `register_control()` function — it SHALL NOT call `register_control()` at module scope with hardcoded `ControlSpec` instances.

#### Scenario: Framework registry module is imported
- **WHEN** `darnit.sieve.registry` is imported
- **THEN** zero `register_control()` calls SHALL execute as module-level side effects
- **AND** the global registry SHALL contain zero controls until TOML loading occurs

#### Scenario: Searching framework source for control IDs
- **WHEN** the `packages/darnit/src/darnit/` source tree is searched for patterns like `OSPS-AC-03.01`
- **THEN** no hardcoded OSPS control ID patterns SHALL exist in executable code
- **AND** no `ControlSpec(control_id=...)` constructor calls SHALL exist outside of test files

### 6.4 Handler Registration

Implementations can register handlers by short name for TOML reference:

```python
def register_handlers(self) -> None:
    from darnit.core.handlers import get_handler_registry
    from . import tools

    registry = get_handler_registry()
    registry.set_plugin_context(self.name)

    registry.register_handler("my_audit", tools.my_audit)
    registry.register_handler("my_remediate", tools.my_remediate)

    registry.set_plugin_context(None)
```

TOML can then reference handlers by short name:

```toml
[mcp.tools.my_audit]
handler = "my_audit"  # Short name instead of "my_plugin.tools:my_audit"
```

### 6.5 Function Reference Security

TOML can reference Python functions via `module:function` syntax:

```toml
api_check = "darnit_baseline.checks:check_branch_protection"
```

**Security Rules**:
- Only whitelisted module prefixes are allowed
- Base whitelist: `darnit.`, `darnit_baseline.`, `darnit_plugins.`
- Additional prefixes discovered from registered entry points

### 6.6 Plugin Verification with Sigstore

Plugins can be verified using Sigstore-based attestations. Plugin trust is operator configuration (Section 14); it is never read from the audited repository:

```toml
# operator configuration (e.g. ~/.config/darnit/config.toml)
[plugins]
allow_unsigned = false
trusted_publishers = [
    "https://github.com/kusari-oss",
    "https://github.com/openssf",
]

[plugins."darnit-baseline"]
version = ">=1.0.0"
```

**Configuration Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `allow_unsigned` | `bool` | Allow plugins without Sigstore signatures (default: false in production) |
| `trusted_publishers` | `list[str]` | OIDC identities to trust (GitHub org URLs, email addresses) |

**Default Trusted Publishers**:
- `https://github.com/kusari-oss`
- `https://github.com/kusaridev`

**Verification Flow**:
1. Plugin loaded via entry point
2. Check for Sigstore attestation on PyPI
3. Verify signature against trusted publishers
4. Cache verification result (24h TTL)
5. If unsigned and `allow_unsigned = false`, reject plugin

---

## 7. Context Detection

### 7.1 Context Definition

Interactive context collection for accurate audits:

```toml
[context.maintainers]
type = "list_or_path"
prompt = "Who are the project maintainers?"
hint = "Provide GitHub usernames or path to MAINTAINERS.md"
examples = ["@user1, @user2", "MAINTAINERS.md"]
affects = ["OSPS-GV-01.01", "OSPS-GV-04.01"]
store_as = "governance.maintainers"
auto_detect = false
hint_sources = ["CODEOWNERS", "MAINTAINERS.md"]
allow_sieve_hints = true
validity_days = 365          # optional; see 7.6
```

- `auto_detect = false` marks a **user-judgment key**: its value requires a person's decision. `auto_detect = true` marks an observable key whose value MAY be concluded from a detection that ran to completion.
- `allow_sieve_hints = true` lets detection propose a candidate for a judgment key. It never makes the candidate usable.
- `values` is the key's only vocabulary (enum keys). `examples` are format hints only and SHALL NOT be offered as answers.
- `validity_days` (optional, positive integer) limits how long a confirmation of this key stays valid, measured from its `last_validated` time (7.6).

### 7.2 Context Types

| Type | Description | Example Values |
|------|-------------|----------------|
| `boolean` | True/false | `true`, `false` |
| `string` | Free text | `security@example.com` |
| `enum` | Predefined choices | `bdfl`, `foundation` |
| `list` | Multiple values | `["@user1", "@user2"]` |
| `path` | File path | `MAINTAINERS.md` |
| `list_or_path` | Values or path reference | `["@user1"]` or `CODEOWNERS` |

### 7.3 Context Requirements for Remediation

```toml
[controls."OSPS-GV-04.01".remediation]
handler = "create_codeowners"

[[controls."OSPS-GV-04.01".remediation.requires_context]]
key = "maintainers"
required = true
confidence_threshold = 0.9
prompt_if_auto_detected = true
warning = "GitHub collaborators are not necessarily project maintainers"
```

A requirement is met by the key's standing (7.4): a `confirmed` value is ready (unless it only names one of the key's `hint_sources` files); a `concluded` value is ready unless `prompt_if_auto_detected` is set or its detection confidence is below `confidence_threshold`; a `candidate` or `unknown` key is never ready, and its candidate is shown for review only. `requires_context` decides when to ask up front; it does not limit which keys a template may read (7.11).

### 7.4 Context Value Standing

The framework SHALL resolve project context through one resolver (`darnit.config.context_resolve.resolve_context`) that gives every context key exactly one standing (see `specs/042-candidate-integrity/`):

| Standing | Meaning | Usable |
|----------|---------|--------|
| `confirmed` | A person confirmed this exact value; a confirmation record (7.5) matches the current value and has not lapsed | Yes |
| `concluded` | An `auto_detect = true` key whose detection ran to completion in this run with confidence at or above `[context].auto_accept_confidence` | Yes, for this run only; never persisted |
| `candidate` | A value with an origin (`detector`, `sieve_hint`, `stored_unconfirmed`, `expired_confirmation`, `answer`) that no person has confirmed | No |
| `unknown` | No value | No |

- A judgment key (`auto_detect = false`) SHALL NOT be `concluded` by any detection route, confidence threshold, or framework setting.
- A value stored in `.project/` without a matching confirmation record is a `candidate` with origin `stored_unconfirmed` and the file and field it was read from. It is never silently upgraded to `confirmed`.
- Consumers (control applicability and verification, compliance calculation, remediation inputs, attestations, the harness answer source) SHALL read values only from the resolver's usable mapping: confirmed values plus concluded values of `auto_detect = true` keys. A candidate is shown to a person, labelled unconfirmed with its origin; it is never consumed as the key's value. An unusable key is unverified, and unverified counts as FAIL.

#### Scenario: Detected maintainers are only proposed
- **WHEN** `maintainers` (`auto_detect = false`, `allow_sieve_hints = true`) is detected from MAINTAINERS.md at confidence 0.95
- **THEN** its standing is `candidate` with origin `sieve_hint`, and it is absent from the usable mapping

#### Scenario: Legacy stored value
- **WHEN** `.project/darnit.yaml` has `context.maintainers` and no `confirmations.maintainers`
- **THEN** `maintainers` is a `candidate` with origin `stored_unconfirmed` and location `.project/darnit.yaml:context.maintainers`

### 7.5 Confirmation Records

A confirmation records a person's decision on one key's value: `value_digest`, `confirmed_by`, `confirmed_at`, `last_validated`, optional `expires_at`, and optional `basis` (the candidate value and origin it was based on; absent when the person typed the value).

- **Value digest**: `"sha256:" + sha256(canonical JSON of the normalized value)`, where normalization applies the canonical vocabulary (7.8) and sorts list values whose order is not meaningful (`maintainers`). A record applies only while the digest of the current value equals its `value_digest`.
- **In-repository records** live in `.project/darnit.yaml` under a top-level `confirmations:` map keyed by context key; the confirmed value lives under `context:`. They count as confirmed whether or not the operator trusts the repository: they are the project's own statement.
- **Operator-side records** live in the feature 040 store (`trust/confirmations.json` under the darnit data root) as confirmations with claim `context_value`, `control_id` = the context key, and `evidence_digest` = the value digest; the confirmed value and basis are kept in a sibling `context_bases` section. They apply only to that operator's runs and only for the repository identity they name.
- **Location**: a confirmation is written in-repository when the operator trusts the target repository (14.2) at confirmation time; otherwise operator-side, which requires a repository identity from the operator's target or CI metadata. Nothing is written into a repository the operator does not trust.
- **Precedence**: when both an in-repository and an operator-side record match the current value, the in-repository record is reported.
- Only an explicit confirmation by a person creates a record: the `confirm_project_data` tool (on the person's explicit instruction) and answers a person types into `darnit run` (basis origin `answer`). Answers a coding agent submits to an ActionPlan `collect_context` step and harness answers are used for that run only and are never persisted.

```yaml
# .project/darnit.yaml
context:
  maintainers: ["@alice", "@bob"]
confirmations:
  maintainers:
    value_digest: "sha256:..."
    confirmed_by: "alice"
    confirmed_at: "2026-09-29T15:00:00Z"
    last_validated: "2026-09-29T15:00:00Z"
    expires_at: "2027-09-29T00:00:00Z"     # optional
    basis:                                   # optional
      value: ["@alice", "@bob"]
      origin: {kind: sieve_hint, method: MAINTAINERS.md}
```

#### Scenario: Hand edit
- **WHEN** a confirmed value is edited by hand
- **THEN** the key is a `candidate` (origin `stored_unconfirmed`) and the earlier record is reported as lapsed

### 7.6 Confirmation Lapse

A confirmation lapses at the earliest of its `expires_at` and `last_validated + validity_days` (the key's framework setting). With neither it does not lapse. Unparseable timestamps count as lapsed. A lapsed confirmation makes the key a `candidate` with origin `expired_confirmation` and the previous value; re-confirming updates `last_validated` and keeps a recorded `expires_at` unless a new one is supplied. Operator-local settings (for example `policy.confirmation_expiry_days`, which governs feature 040 claims and feature 041 PASS candidates) SHALL NOT change when a context confirmation lapses.

### 7.7 Detection Fallbacks

A detection step's `value_if_fail` applies only when the step ran to completion and answered negatively and no earlier step failed to run. A step that errored or could not decide produces no value. Release status is never `false` unless a successful platform answer showed no releases.

### 7.8 Canonical Key Names and Vocabularies

Each context key has one canonical name and one vocabulary, taken from the framework TOML. Stored legacy names and spellings are read as the canonical form (`ci.provider` and bare `provider` read as `ci_provider`; `github_actions` -> `github`, `gitlab_ci` -> `gitlab`, `azure_pipelines` -> `azure`, `bitbucket_pipelines` -> `other`, `unknown` -> no value). The framework writes only canonical names and values.

### 7.9 Reads Never Write; One Writer

- Auditing (every driver), listing pending data, report generation, remediation in dry run, the remediation context guard in every mode, and the harness collect phase SHALL NOT create, modify, or delete any file in the audited repository.
- `darnit.config.context_writes` is the only code that writes context values and in-repository confirmation records. It writes only `.project/darnit.yaml` (never `.project/project.yaml`), preserves sections and comments it does not change (including feature 040 `controls:` claims), and refuses every write, returning the errors, when `.project/project.yaml` or `.project/darnit.yaml` is present but unparseable or invalid. The loader distinguishes absent, valid, and invalid files (`load_project_config_checked`).
- `init_project_config` (MCP) creates only an empty `.project/darnit.yaml` when `.project/` is absent, and reports instead of overwriting when it is present.

### 7.10 Confirmation Tool Contract

The observable payloads of `get_pending_data` and `confirm_project_data` are defined in `specs/042-candidate-integrity/contracts/context-confirmation-tools.md`:

- `get_pending_data` is read-only. Each question carries its candidate as data (`candidate: {value, origin, digest, label}`); no `command_template` or answer mapping contains a candidate value or a configuration example; enum questions list every allowed value in `allowed_values`; the response lists `stored_unconfirmed` values with their locations.
- `confirm_project_data` takes a parameter for every context key the framework defines (generated from the definitions), plus `accept_candidates` (`{key: candidate digest}`; confirms the current candidate only if its digest still matches, recording it as the basis), `confirm_stored` and `reject_stored` (review of stored values: a rejected `.project/darnit.yaml` value is deleted; a rejected `.project/project.yaml` value is reported with its file and field and the file is left unchanged), `expires_at` (`{key: date}`), and `owner`, `repo`, `host`, which are required and decide the record location (7.5).

### 7.11 Consumers of Context Values

Every consumer reads context values from the resolver's usable mapping (7.4) and nothing else:

- **Audit applicability** (`when` clauses): this run's filesystem detections of keys that are not judgment keys, then `.project/project.yaml` mapper values, then usable values. The audit resolves without running the framework's detection pipelines; its only detections are those filesystem detections. Only usable values confirmed in the repository count as repository data for not-applicable claims (14.3).
- **Remediation**: templates and remediation `when` clauses see this run's detections of keys that are not judgment keys, overlaid with usable values. The `context` namespace is guarded: reading a defined context key that has no usable value (by attribute, index, `get`, or membership test) raises `ConfirmationRequired`, so a template `default()` cannot stand in for it, and the same applies to a key named in a handler's `when`. Templates and `when` clauses are evaluated for every handler before any handler runs; a `ConfirmationRequired` becomes that control's result, `confirmation required: <key>`, and nothing is written. This applies whether or not the control lists the key in `requires_context`. Keys that are not context keys render as empty.
- **Tool parameters that are judgment values** have no default. An omitted parameter is taken from confirmed context only; otherwise the tool writes nothing and reports `confirmation required: <key>` (for example `remediate_community_spec`, whose parameters map to the CSL `csl_*` keys).
- **Attestations** carry no context values.
- **Detection helpers** (`collect_auto_context`) return canonical key names, drop a detection of any key its definition marks as a judgment key, and overlay only usable values.

#### Scenario: Unconfirmed security contact in a remediation template
- **WHEN** a remediation template reads `<< context.security_contact | default('security@example.org') >>` and `security_contact` has no usable value
- **THEN** that control's remediation returns `confirmation required: security_contact` and writes nothing

---

## 8. Output Formats

### 8.1 SARIF Generation

The framework generates SARIF 2.1.0 output using metadata from TOML:

| SARIF Field | TOML Source |
|-------------|-------------|
| `rule.id` | Control ID (e.g., `OSPS-AC-03.01`) |
| `rule.name` | `controls.*.name` |
| `rule.shortDescription` | `controls.*.description` |
| `rule.fullDescription` | `controls.*.description` |
| `rule.help.markdown` | `controls.*.help_md` |
| `rule.helpUri` | `controls.*.docs_url` |
| `rule.defaultConfiguration.level` | Derived from `security_severity` |
| `rule.properties.security-severity` | `controls.*.security_severity` |
| `rule.properties.tags` | `controls.*.tags` keys |

### 8.2 Severity Mapping

| security_severity | SARIF level |
|-------------------|-------------|
| >= 9.0 | error |
| >= 7.0 | error |
| >= 4.0 | warning |
| < 4.0 | note |

---

## 9. Sync Enforcement

### 9.1 Schema Validation

All TOML configs MUST validate against the framework schema:
- Required fields present
- Field types correct
- Pass configurations valid

### 9.2 Spec-Implementation Sync

Framework code changes MUST match this specification:
- Built-in pass types implement documented behavior
- TOML schema matches documented structure
- Output formats follow documented mappings

### 9.3 Validation Script

```bash
# Validate sync
uv run python scripts/validate_sync.py

# Exit codes:
# 0 = Pass
# 1 = Critical (blocks merge)
# 2 = Warning
```

---

## Appendix A: Complete Control Example

```toml
[controls."OSPS-AC-03.01"]
name = "PreventDirectCommits"
description = "Prevent direct commits to primary branch"
level = 1
domain = "AC"
security_severity = 8.0
tags = { "branch-protection" = true, "code-review" = true }

help_md = """
Enable branch protection to require pull requests.

**Remediation:**
1. Go to Repository Settings → Branches
2. Add branch protection rule for main/master
3. Enable 'Require a pull request before merging'

**References:**
- [GitHub Branch Protection](https://docs.github.com/en/repositories/configuring-branches-and-merges-in-your-repository/managing-protected-branches/about-protected-branches)
"""
docs_url = "https://baseline.openssf.org/..."

[[controls."OSPS-AC-03.01".passes]]
handler = "exec"
command = ["gh", "api", "/repos/$OWNER/$REPO/branches/$BRANCH/protection"]
pass_exit_codes = [0]
output_format = "json"
expr = 'output.json.required_pull_request_reviews != null'

[[controls."OSPS-AC-03.01".passes]]
handler = "manual"
steps = ["Verify branch protection in repository settings"]

[controls."OSPS-AC-03.01".remediation]
requires_api = true

[controls."OSPS-AC-03.01".remediation.api_call]
method = "PUT"
endpoint = "/repos/$OWNER/$REPO/branches/$BRANCH/protection"
payload_template = "branch_protection_payload"
```

---

## Appendix B: Migration from Rules Catalog

The `rules/catalog.py` file is deprecated. Migrate metadata to TOML:

```python
# OLD: rules/catalog.py
OSPS_RULES = {
    "OSPS-AC-01.01": {
        "name": "MFARequired",
        "short": "MFA required",
        "help_md": "...",
        "security_severity": 9.0,
    }
}
```

```toml
# NEW: openssf-baseline.toml
[controls."OSPS-AC-01.01"]
name = "MFARequired"
description = "MFA required for repository access"
security_severity = 9.0
help_md = "..."
```

---

## 10. Audit Pipeline

### 10.1 Canonical Audit Function

All code that runs sieve-based compliance audits MUST delegate to the canonical `run_sieve_audit()` function in `darnit.tools.audit`. No other module SHALL reimplement the sieve verification loop (iterating controls, constructing `CheckContext`, calling `SieveOrchestrator.verify()`).

#### Requirement: Single audit pipeline
- **WHEN** a developer (human or LLM) adds a new MCP tool or CLI command that runs compliance audits
- **THEN** it MUST call `run_sieve_audit()` from `darnit.tools.audit`
- **AND** it MUST NOT contain its own `for control in controls: orchestrator.verify(control, context)` loop

#### Requirement: Implementation-specific audit tools delegate
- **WHEN** an implementation package (e.g., `darnit-baseline`) provides its own audit MCP tool
- **THEN** it MUST delegate to `run_sieve_audit()` for the sieve execution
- **AND** it MAY add implementation-specific pre-processing (config loading, tag filtering) and post-processing (attestation, custom formatting)

### 10.2 No Duplicate Utility Functions

A given function signature and purpose MUST NOT appear more than once within the `darnit` framework package. When a utility function is needed in multiple modules, it SHALL be defined in one canonical location and imported elsewhere.

#### Requirement: Identifying duplication
- **WHEN** two functions in `packages/darnit/` have the same name and similar behavior
- **THEN** one SHALL be deleted and callers SHALL import from the canonical location

### 10.3 Single Report Formatter

All audit entry points that produce markdown output SHALL use `format_results_markdown()` from `darnit.tools.audit`. No other module SHALL maintain a separate audit report formatter.

#### Requirement: Report formatter is parameterized
- **WHEN** `format_results_markdown()` is called
- **THEN** it SHALL accept optional `report_title` and `remediation_map` parameters
- **AND** SHALL NOT contain hardcoded implementation-specific control IDs or branding

### 10.4 Audit Result Cache

The canonical `run_sieve_audit()` function SHALL write audit results to a cache file after completing the sieve pipeline. The `remediate_audit_findings()` function SHALL check for cached results before running its own audit, using the cache to skip redundant audit passes.

Cache files are stored in the system temp directory (`$TMPDIR/darnit/<repo-hash>/audit-cache.json`), keyed by a hash of the repository's absolute path. This avoids writing any files into the repository itself.

#### Requirement: Canonical audit writes to cache
- **WHEN** `run_sieve_audit()` completes successfully
- **THEN** it SHALL call `write_audit_cache()` with the `results`, `summary`, `level`, and `framework` name
- **AND** subsequent calls to `read_audit_cache()` from the same repository SHALL return the cached results (assuming no commit change)
- **AND** audit failure (exception before completing) SHALL NOT write to the cache

#### Requirement: Only FAIL controls are remediated
- **WHEN** remediation tools consume audit results (cached or fresh)
- **THEN** they SHALL extract only controls with `status == "FAIL"`
- **AND** controls with `status == "WARN"` SHALL NOT be remediated (WARN means automated verification was inconclusive, not that the control is non-compliant)
- **AND** controls with `status == "PASS"` SHALL NOT be remediated

#### Requirement: Remediation consumes cached audit results
- **WHEN** `remediate_audit_findings()` is called and `read_audit_cache()` returns valid cached results
- **THEN** it SHALL extract failed control IDs from the cached results (entries with `status == "FAIL"`)
- **AND** it SHALL NOT run a redundant audit
- **WHEN** `read_audit_cache()` returns `None` (cache miss)
- **THEN** it SHALL run the sieve audit as normal (existing behavior)
- **AND** it SHALL iterate all remediation categories, letting per-control filtering exclude categories where no controls failed

#### Requirement: Post-remediation cache invalidation
- **WHEN** `remediate_audit_findings()` completes with `dry_run=False` and at least one remediation was applied
- **THEN** it SHALL call `invalidate_audit_cache(local_path)`
- **WHEN** `remediate_audit_findings()` completes with `dry_run=True`
- **THEN** it SHALL NOT call `invalidate_audit_cache()`

### 10.5 Framework Contains No Implementation-Specific Code

The darnit framework package SHALL NOT contain code, modules, or string literals specific to any particular compliance implementation.

#### Requirement: No OSPS control IDs in framework
- **WHEN** the `packages/darnit/src/darnit/` source tree is searched
- **THEN** no hardcoded OSPS control ID patterns (e.g., `OSPS-AC-03.01`) SHALL exist in executable code

#### Requirement: No attestation or threat model modules in framework
- **WHEN** the `packages/darnit/src/darnit/` directory listing is checked
- **THEN** `attestation/` and `threat_model/` directories SHALL NOT exist
- **AND** these modules SHALL reside in the implementation package

#### Requirement: Explicit implementation selection
- **WHEN** callers need a compliance implementation
- **THEN** they SHALL use `get_implementation(name)` with an explicit name
- **AND** the name SHALL be resolved from `.baseline.toml` `extends` field,
  an explicit parameter, or `discover_implementations()` to list available options
- **AND** a repository may name a framework only by registered name (never by file path), and the operator's choice (Section 14) takes precedence

---

## 11. Locator and Context Integration

### 11.1 use_locator for File Existence Checks

A deterministic handler invocation MAY use `use_locator = true` instead of specifying `files` directly. When `use_locator = true` is set, the framework SHALL use the control's `locator.discover` list as the handler's `files` parameter.

- If the control has no `locator` configuration, the framework SHALL log a warning and return INCONCLUSIVE
- If both `use_locator = true` and explicit `files` are specified, `files` takes precedence

### 11.2 Auto-derived on_pass from Locator

When a control has a `locator` with `project_path` AND a deterministic `file_exists` handler (or `use_locator = true`), AND the control does NOT have an explicit `on_pass` configuration, the framework SHALL auto-derive an `on_pass.project_update` that sets the `locator.project_path` to the path of the found file.

Explicit `on_pass` configurations always take precedence over auto-derivation.

### 11.3 Template Variable Context References

Template variable substitution SHALL support:
- `${context.<key>}` -- resolves to usable context values (7.4); reading a defined context key without a usable value stops the remediation with "confirmation required" (7.11)
- `${project.<dotted.path>}` — resolves to project configuration values

Unresolved references SHALL be replaced with an empty string and logged at debug level.

### 11.4 Context Informs But Never Overrides Verification

Project context from `.project/` SHALL be used to inform WHERE the sieve looks for evidence (via `locator.project_path`), but SHALL NOT determine WHETHER a control passes. Even when context indicates a file exists, the sieve SHALL still verify through its normal handler pipeline.

## 12. Handler Registry

The framework SHALL provide a handler registry where handlers are registered by name with a phase affinity. Core SHALL register built-in handlers: `file_exists`, `exec`, `regex`, `llm_eval`, `manual_steps`, `file_create`, `api_call`, `project_update`. Implementations SHALL register domain-specific handlers via the existing `ComplianceImplementation.register_handlers()` method.

Implementation-registered sieve handlers (non-exhaustive): `github_branch_protection` (registered by `darnit-baseline`, encapsulates the classic-branch-protection + repository-rulesets two-surface check for `OSPS-AC-03.01`, `OSPS-AC-03.02`, `OSPS-QA-03.01`, `OSPS-QA-07.01`; see `specs/032-ruleset-branch-protection/contracts/github-branch-protection-handler.md`).

A handler used in a phase different from its registered affinity SHALL trigger a warning but still execute.

## 13. Persistence Extension Surface

The framework SHALL provide four per-artifact persistence Protocols under `darnit.stores`, alongside the existing extension surfaces `darnit.frameworks` (compliance implementations) and `darnit.question_resolvers` (feature 027). Third-party persistence backends register under Python entry-point groups `darnit.stores.project`, `darnit.stores.attestation`, `darnit.stores.report`, `darnit.stores.cache`. Filesystem-backed default implementations ship in `darnit-core` and reproduce the pre-feature on-disk layout exactly (feature 033); alternative backends are opt-in via operator configuration `[stores.<kind>] backend = "..."` blocks (Section 14). See `specs/033-pluggable-stores/contracts/` for per-Protocol contracts.

## 14. Operator Configuration and Trust Boundary

Design principle: **the audited repository is untrusted input in its entirety, including any configuration it contains.** A repository may supply assertions about itself, which are recorded and reported as its own; it may not change what darnit executes, how steps conclude, or which plugins, servers, integrations, or stores are trusted. See `specs/040-operator-config-trust/` for the full contracts.

### 14.1 Operator configuration

- Tool configuration is owned by the operator (whoever runs darnit) and lives in one user-level file: `$XDG_CONFIG_HOME/darnit/config.toml` (absolute values only) or `~/.config/darnit/config.toml` on Linux and macOS, `%APPDATA%\darnit\config.toml` on Windows. `--operator-config PATH` at launch overrides the location for every driver.
- Precedence: built-in defaults, then operator configuration, then per-run flags. Nothing from the audited repository enters this chain.
- The framework SHALL refuse operator configuration whose resolved path lies inside the audited repository, SHALL reject unknown keys, and SHALL check file permissions (warn by default; refuse in strict mode, which is enabled at launch or by default in CI and can only be turned on, not off, by the file).
- There is no environment variable that grants trust to repository content.
- Every report records the operator configuration source and a digest of its content.

### 14.2 Trusted repositories and CI

- The operator lists trusted repositories by canonical identity (`host/namespace/name`). The identity used for a trust decision comes from the operator's audit target or CI metadata, never solely from the checkout's own version-control configuration.
- CI trust is opt-in per rule; the initial rule trusts pushes to the default branch of a listed repository. Pull requests from forks and unrecognized events are never trusted.

### 14.3 Project assertions

- Project assertions (for example "this control is not applicable, reason X") live in `.project/` (darnit's extension file for anything upstream `.project/` cannot express). Project data that changes a control's applicability is treated as an assertion. For a context value that is only a value confirmed in the repository (7.5): an unconfirmed stored value is a candidate and has no effect (7.4), and a value the operator confirmed operator-side is the operator's decision, not a repository assertion.
- An assertion-backed not-applicable result is **honored** only for a trusted repository with a reason and no contradicting evidence; otherwise it is **pending** (non-compliant until the operator confirms it) or **contradicted** (ignored, with the evidence reported). Controls MAY declare `contradicted_by` evidence in framework TOML.
- Confirmations are stored on the operator side, keyed by repository identity, claim, and evidence digest, and lapse on expiry or when the evidence changes. Confirmations of project context values follow Section 7.5 instead.
- Reports and attestations label every assertion-backed N/A as asserted, with the asserter and any confirmer.

### 14.4 Repository-level .baseline.toml

The repository-level `.baseline.toml` is deprecated. During the deprecation release only its per-control status and reason are read, as assertions under 14.3; every other setting is ignored with a warning naming its new home. `darnit config migrate` moves assertions into `.project/` and proposes an operator configuration fragment.

## Appendix C: Removed Requirements

The following requirements have been superseded by the handler dispatch architecture.

### Removed: VerificationPassProtocol
**Reason**: Replaced by handler dispatch architecture. Pass classes that implemented this protocol (`DeterministicPass`, `PatternPass`, `LLMPass`, `ManualPass`, `ExecPass`) are superseded by handler functions registered in `SieveHandlerRegistry`.
**Migration**: Define verification logic as handler functions matching `Callable[[dict, HandlerContext], HandlerResult]` and register via `SieveHandlerRegistry.register()`. Reference handlers by name in TOML `[[passes]]` entries.

#### Scenario: Protocol no longer used
- **WHEN** a plugin needs to define custom verification logic
- **THEN** it MUST register a handler function via `SieveHandlerRegistry`
- **AND** it MUST NOT implement `VerificationPassProtocol`

### Removed: ControlSpec.passes field
**Reason**: The `passes` field stored instantiated pass class objects. All pass configuration is now stored as `HandlerInvocation` objects in `ControlSpec.metadata["handler_invocations"]`, loaded from TOML.
**Migration**: Access pass configuration via `control_spec.metadata["handler_invocations"]` instead of `control_spec.passes`.

#### Scenario: Field removed from ControlSpec
- **WHEN** code accesses a `ControlSpec` object
- **THEN** it MUST NOT reference a `.passes` attribute
- **AND** it MUST use `metadata["handler_invocations"]` for pass configuration

### Removed: ControlSpec.__post_init__ phase-order validation
**Reason**: The `__post_init__` method validated that pass objects followed the recommended phase ordering (DETERMINISTIC → PATTERN → LLM → MANUAL). With handler dispatch, execution order is determined by TOML declaration order, and no phase-order enforcement is needed.
**Migration**: Rely on TOML declaration order for pass execution sequence. No validation replacement needed.

#### Scenario: Phase ordering not enforced
- **WHEN** a control defines passes in any order
- **THEN** the framework MUST NOT emit warnings about phase ordering
- **AND** passes MUST execute in declaration order regardless of handler type

### Removed: DeterministicPass api_check and config_check callable fields
**Reason**: The `api_check` and `config_check` fields referenced Python callables (`"module:function"` strings) for deterministic verification. This pattern is replaced by custom sieve handlers registered in `SieveHandlerRegistry`.
**Migration**: Convert `api_check`/`config_check` callables to handler functions and register them via `SieveHandlerRegistry.register()`. Reference by handler name in TOML.

#### Scenario: Python callable references removed from TOML schema
- **WHEN** a control needs Python-based verification logic
- **THEN** it MUST use a custom handler referenced by name (e.g., `handler = "my_custom_check"`)
- **AND** it MUST NOT use `api_check` or `config_check` fields with `"module:function"` references

### Removed: Legacy pass class instantiation
**Reason**: The classes `DeterministicPass`, `PatternPass`, `LLMPass`, `ManualPass`, and `ExecPass` in `sieve/passes.py` are removed. All verification logic is implemented as handler functions in `builtin_handlers.py`.
**Migration**: Replace `DeterministicPass(config_check=...)` with a custom sieve handler. Replace `ManualPass(verification_steps=[...])` with a TOML `[[passes]]` entry using `handler = "manual"`. See `IMPLEMENTATION_GUIDE.md` Section 5 for the handler authoring pattern.

#### Scenario: Pass classes unavailable for import
- **WHEN** plugin code attempts to import pass classes from `darnit.sieve.passes`
- **THEN** the import MUST raise `ImportError`
- **AND** the migration path MUST be documented in `IMPLEMENTATION_GUIDE.md`

### Removed: Legacy pass re-exports from sieve package
**Reason**: The `darnit.sieve` package previously re-exported pass class constructors (`DeterministicPass`, `PatternPass`, `LLMPass`, `ManualPass`) for convenience. These re-exports have been removed from `sieve/__init__.py`. The pass dataclass definitions in `sieve/passes.py` remain available via direct import.
**Migration**: Import directly from `darnit.sieve.passes` if needed (e.g., `from darnit.sieve.passes import DeterministicPass`). However, new code SHOULD NOT construct pass instances directly — define passes in TOML instead.

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0-alpha.9 | 2026-09-29 | Context value standing, confirmation records, lapse, canonical keys, reads never write, confirmation tool contract (Sections 7.4-7.10, feature 042) |
| 1.0.0-alpha.8 | 2026-02-16 | Added audit result cache (Section 10.4): audit writes cache, remediate reads cache, post-remediation invalidation |
| 1.0.0-alpha.7 | 2026-02-13 | Migrated to handler dispatch architecture: pass classes replaced by named handlers, passes use TOML array-of-tables syntax, register_controls() becomes no-op, removed legacy pass classes (Appendix C) |
| 1.0.0-alpha.5 | 2026-02-08 | Added locator integration (Section 11), handler registry (Section 12) |
| 1.0.0-alpha.4 | 2026-02-07 | Added framework purity requirements (Section 10.5), report parameterization |
| 1.0.0-alpha.3 | 2026-02-06 | Added audit pipeline requirements (Section 10) |
| 1.0.0-alpha.2 | 2026-02-05 | Added CEL expressions, handler registration, Sigstore verification |
| 1.0.0-alpha | 2026-02-04 | Initial authoritative specification |
