# Darnit Framework Design Specification

> **Version**: 1.0.0-alpha.12
> **Status**: Authoritative
> **Last Updated**: 2026-10-04

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
│  │ - file_exists, exec, gh_api, regex, pattern, template  ││
│  │ - file_create, exec, platform_setting, project_update, ││
│  │   yaml_inject (remediation)                            ││
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

#### Requirement: No Unknown Control Keys
- **WHEN** a control declares a key the control schema does not define
- **THEN** loading the framework file MUST fail with an error naming the file, the control, and the key (feature 044; step keys are checked as in section 3.0.3)
- **AND** an operator custom control's unknown key MUST fail loading the operator configuration (section 14)

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
| remediation handlers (`file_create`, `platform_setting`, `project_update`, `yaml_inject`) | `{}` | -- |

A plugin handler registers its ceiling with the handler (`registry.register(..., ceiling={"pass", "fail"})`). A plugin handler that registers no ceiling has the ceiling `{}`: its results are evidence only. A step type that decides from text or file-presence signals registers `{fail}`; the reproducibility framework's five step types (`repro_deps_pinned`, `repro_build_env_declared`, `repro_hermetic_build`, `repro_provenance_exists`, `repro_bit_for_bit`) do, so they conclude PASS only with a promotion, and their signals reach the control's later steps as evidence (feature 044, section 12).

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

Unknown step keys, unregistered step types, and expression references are checked at the same point (section 3.0.3).

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

### 3.0.3 Step Registration and Strict Loading

A step type is registered once, with the outcomes it may conclude (3.0.1), the settings it reads, and the names its expression may use (feature 044):

```python
registry.register(
    "my_check",
    phase="deterministic",
    handler_fn=my_check,
    ceiling={"fail"},
    settings=frozenset({"files", "threshold"}),
    expression_names=frozenset({"output", "project"}),
)
```

| Registration field | Default | Meaning |
|--------------------|---------|---------|
| `settings` | `None` | The step keys this step type reads, beyond the common step fields. `None` means not declared, which only a plugin step type may leave: it loads with one warning per step type that its settings are not checked. Every core step type, check and remediation, declares its settings. |
| `expression_names` | `{}` | The top-level names an `expr` on this step type may reference (section 3.7). Empty means the step type does not accept `expr`. |

**Common step fields**, accepted on every step: `handler`, `when`, `shared`, `use_locator`, `authority`, `existence`, `concludes`, `fail_on_miss`, `fail_on_status`, `promotion` (3.0.1), `description` (documentation only), `expr` (only when the step type declares expression names), and `expr_decides` (only with `expr`, on a step type whose expression the orchestrator evaluates, section 3.7).

**Name collisions.** Core step types register before any plugin. A registration is refused, logged at WARNING naming both registrants, and recorded in the registry's `refused_registrations` when the following apply. `darnit list` shows every refusal; an audit's warnings show those attempted by a plugin of the audited framework or of a framework it composes, since only those change what the audit runs:

1. a plugin registers a name a core step type uses; the core step type is unchanged;
2. a plugin registers a name a different plugin registered; the first registration is unchanged.

The same plugin registering its own name again is allowed. No setting lets a plugin replace a step type: a replacement could widen a ceiling, for example make `manual` conclude PASS.

**Strict loading.** Loading a framework file fails, naming the framework file and control, and for a step the step (`pass[i]:<handler>`) and the offending key or name, when:

1. a step, a verification pass or a remediation handler, has a key that is neither a common step field nor in its step type's declared `settings`;
2. a step names a step type that is not registered;
3. a step has `expr` and its step type declares no expression names, the expression does not compile, or it references a name its step type does not provide (section 3.7), or a step sets `expr_decides` without `expr` or on a step type that evaluates its own expression or accepts none;
4. a `gh_api` step reads a personal record without `evidence_fields`, or an `exec` step runs `gh api` against a personal record (section 3.8).

Unknown control keys fail loading as well (section 2.3). These checks run where 3.0.1's validation runs: on every control-loading path, after plugin step types register. The plugin step types registered for a control are those of the framework being loaded and, for a control a composite takes from another framework (`[[compose]]`, feature 013), those of that source framework. No step is silently skipped. The one exception to rule 2 is a step from operator configuration (a pass override or custom control, section 14.1) that names the step type of a plugin that is not installed: that control loads, and the audit reports it ERROR, class `missing_tool`, with the cause "step type X is not registered".

#### Scenario: A plugin redefines a core step type
- **WHEN** a plugin registers a step type named `manual` with ceiling `{pass}`
- **THEN** the registration MUST be refused and reported at WARNING naming the plugin and core
- **AND** a control whose only step is `manual` MUST NOT conclude PASS

#### Scenario: Two plugins register the same name
- **WHEN** a second plugin registers a step type name another plugin registered
- **THEN** the second registration MUST be refused and reported naming both plugins

#### Scenario: Misspelled step setting
- **WHEN** a step declares `fail_on_mis = true`
- **THEN** loading MUST fail naming the framework file, control, step, and key

#### Scenario: Plugin step type without declared settings
- **WHEN** a framework uses a plugin step type registered without `settings`
- **THEN** it MUST load, with one warning per step type that its settings are not checked

#### Scenario: Unregistered step type
- **WHEN** a framework file names `handler = "file_must_exst"`
- **THEN** loading MUST fail naming the control and the step type

#### Scenario: Operator-supplied control names a missing plugin step type
- **WHEN** an operator custom control names the step type of a plugin that is not installed
- **THEN** the control MUST be reported ERROR, class `missing_tool`, naming the step type

### 3.1 Pass Execution Order

```
Passes execute in TOML declaration order. Typical ordering:
  file_exists / exec  →  regex  →  llm_eval  →  manual
          ↓                 ↓          ↓           ↓
    Exact checks       Heuristics   AI eval   Human review
    (high conf)        (med conf)              (fallback)
```

The framework does not enforce a particular phase ordering. Controls MAY declare passes in any order. The convention above reflects decreasing confidence and increasing cost.

#### Scenario: Declaration order respected regardless of handler type
- **WHEN** a control declares passes in non-conventional order (e.g., `manual` before `exec`)
- **THEN** the orchestrator MUST still execute them in declaration order
- **AND** the handler type MUST NOT affect execution order

### 3.2 file_exists Handler

**Purpose**: High-confidence file existence checks with binary outcomes

**TOML Schema**:
```toml
[[controls."EXAMPLE".passes]]
handler = "file_exists"
files = ["SECURITY.md", ".github/SECURITY.md"]
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `handler` | `str` | MUST be `"file_exists"` |
| `files` | `list[str]` | Paths/globs where ANY match passes |
| `max_depth` | `int` | Search subdirectories up to this depth for non-glob entries (default: 0, repository root only) |

**Behavior**:
1. If any file in `files` matches → PASS
2. If no file matches → FAIL

**Ceiling**: `{fail}`; `{pass, fail}` with `existence = true` (section 3.0.1). A file being present says nothing about its content, so a presence step concludes PASS only for a control whose requirement is literally that the file exists.

#### Scenario: File found
- **WHEN** a `file_exists` handler is invoked
- **AND** at least one path in `files` matches an existing file
- **THEN** the handler MUST return PASS

#### Scenario: No file found
- **WHEN** a `file_exists` handler is invoked
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
| `command` | `list[str]` | Command and arguments (supports `$PATH`, `$OWNER`, `$REPO`, `$BRANCH`) |
| `pass_exit_codes` | `list[int]` | Exit codes that indicate PASS (default: `[0]`) |
| `fail_exit_codes` | `list[int]` | Exit codes that indicate FAIL |
| `output_format` | `str` | `text` (default) or `json`; with `json`, stdout is parsed into `output.json` |
| `expr` | `str` | CEL expression over `output` and `project` (section 3.7) |
| `expr_decides` | `bool` | Common step field: on a handler PASS, `expr` alone decides, true PASS and false FAIL (section 3.7) |
| `timeout` | `int` | Timeout in seconds (default: 300) |
| `env` | `dict` | Additional environment variables |
| `cwd` | `str` | Working directory (default: the repository) |
| `effects`, `offline` | | Remediation steps only: preview declarations (section 4.4) |

These are the step type's declared `settings` (section 3.0.3); any other key fails loading.

**Security**:
- Commands are executed as a list (no shell interpolation)
- Variable substitution only replaces whole tokens or substrings safely

**Broken measurements**: a command whose binary is not installed is ERROR, class `missing_tool`; a timeout is ERROR, class `timeout`. Neither is FAIL.

#### Scenario: CEL expression evaluated
- **WHEN** an `exec` step has an `expr` field and the exit code gives PASS or FAIL
- **THEN** the expression MUST be evaluated after the command, and the step result MUST follow the outcome rules of section 3.7
- **AND** an expression that cannot be evaluated, or is not boolean, MUST make the step ERROR, class `evaluation`

#### Scenario: Exit code evaluation
- **WHEN** an `exec` handler runs
- **THEN** the handler MUST evaluate the exit code against `pass_exit_codes` and `fail_exit_codes`
- **AND** an exit code in neither list MUST NOT give PASS or FAIL

### 3.4 regex Handler

**Purpose**: Regex-based content analysis

**TOML Schema**:
```toml
[[controls."EXAMPLE".passes]]
handler = "regex"
files = ["SECURITY.md", "README.md", "docs/*.md"]
pattern = { patterns = { has_email = '[\w.-]+@[\w.-]+', has_disclosure = '(?i)disclos|report|vulnerabilit' } }
pass_if_any = true
fail_on_miss = false
```

**Fields** (`regex` and its alias `pattern`):

| Field | Type | Description |
|-------|------|-------------|
| `handler` | `str` | `"regex"` or `"pattern"` |
| `files` | `list[str]` | File paths/globs to search |
| `file` | `str` | Legacy single file; `"$FOUND_FILE"` names the file a preceding `file_exists` step found |
| `pattern` | `str` or `{patterns = dict[str, str]}` | One regex, or named regexes (name -> regex) under `patterns` |
| `pass_if_any` | `bool` | PASS if any pattern matches (default: true); false requires every file and pattern to match |
| `min_matches` | `int` | Matches needed per pattern per file (default: 1) |
| `exclude_files` | `list[str]` | Exclude mode: globs whose presence is reported (see below) |
| `max_depth` | `int` | Search subdirectories up to this depth for non-glob entries (default: 0) |
| `fail_on_miss` | `bool` | FAIL instead of INCONCLUSIVE on no match (default: false). Step field; requires `fail` in the step's effective set. |
| `expr` | `str` | CEL expression over `output` (the handler's evidence) and `project` (section 3.7) |

These are the step type's declared `settings` and common step fields (section 3.0.3); any other key, such as a top-level `patterns`, fails loading.

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
files_to_include = ["SECURITY.md", "README.md"]
analysis_hints = ["Look for contact information", "Check for timeline mentions"]
confidence_threshold = 0.8
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `handler` | `str` | MUST be `"llm_eval"` |
| `prompt` | `str` | Inline prompt template |
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

A step may carry an `expr`: a Common Expression Language condition that must hold for the step's result to stand.

**TOML Schema**:
```toml
[[controls."EXAMPLE".passes]]
handler = "exec"
command = ["kusari", "scan"]
output_format = "json"
expr = 'output.json.status == "pass" && size(output.json.issues) == 0'
```

**Names by step type.** Each step type declares the names its expressions may use (`expression_names`, section 3.0.3). A step type with none does not accept `expr`.

| Step type | Names | Evaluated by |
|-----------|-------|--------------|
| `exec` | `output` (`stdout`, `stderr`, `exit_code`, `json`), `project` | the orchestrator, after the handler |
| `regex`, `pattern` | `output` (the handler's evidence, e.g. `any_match`, `files_found`, `results`), `project` | the orchestrator, after the handler |
| `gh_api` | `response` (`status_code`, `body`) | the handler (section 3.8) |
| `mcp` | `result` (the tool's response) | the handler |

`project` holds the usable project context values the driver resolved (section 7.4): confirmed values, plus values concluded by detection only when the driver ran detection, which an audit does not, keyed by canonical name (for example `project.ci_provider`), and nothing else. It is not the context `when` clauses read: that context also holds this run's detections and the values read from `.project/project.yaml`, which have their own trust rules (section 14) and are not usable values. Reading a key that is not usable, such as an unconfirmed candidate or a raw `.project/project.yaml` value, is an evaluation error, never an absent value that happens to make the expression true. A driver that supplies no usable values binds `project` to an empty mapping.

**Functions**:

| Function | Description |
|----------|-------------|
| `file_exists(path)` | Whether `path`, relative to the audited repository, exists |
| `json_path(obj, path)` | Value at a JMESPath expression in `obj` |

**Outcome rules** for an expression evaluated by the orchestrator. It runs only when the handler returns PASS or FAIL; a WARN, INCONCLUSIVE, or ERROR result is unchanged.

| Expression result | Handler result | Step result |
|-------------------|----------------|-------------|
| true | PASS | PASS |
| false | PASS | INCONCLUSIVE |
| false | FAIL | FAIL |
| true | FAIL | INCONCLUSIVE |
| does not compile, cannot be evaluated, or is not boolean | PASS or FAIL | ERROR, class `evaluation` |

**An expression that decides.** A step may set `expr_decides = true` when its handler's own PASS means only that the measurement ran, and the expression reads the verdict from its output. A scanner that exits with an accepted code whether or not it found anything is the usual case. When the handler returns PASS, the expression alone decides:

| Expression result | Handler result | Step result |
|-------------------|----------------|-------------|
| true | PASS | PASS |
| false | PASS | FAIL |
| does not compile, cannot be evaluated, or is not boolean | PASS | ERROR, class `evaluation` |
| (not evaluated) | FAIL, WARN, INCONCLUSIVE, or ERROR | unchanged |

The step's effective set (section 3.0.1) still applies: a PASS or FAIL concludes only when the step may conclude it. `expr_decides` requires `expr`, and is accepted only on step types whose expression the orchestrator evaluates (`exec`, `regex`, `pattern`); `gh_api` and `mcp` evaluate their own expression, which already decides. OSPS-BR-01.01 and OSPS-AC-04.02 set it on their zizmor steps, so a matching finding is FAIL (feature 044, FR-015).

On ERROR the step's evidence keeps the handler's evidence and adds `expr` and `expr_error`. A broken expression is a broken measurement: it is neither PASS nor FAIL (section 3.0), whatever the handler returned.

**Load-time check.** When controls load, each `expr` is compiled and its free names are collected (names bound by the comprehension macros `exists`, `all`, `exists_one`, `map`, and `filter`, and function names, are not free). Loading fails, naming the control, the step, and the name, when the expression does not compile, when it uses a name its step type does not provide (for example `response` on an `exec` step, or a misspelled `ouput`), or when the step type accepts no `expr` (section 3.0.3).

**Limits**: evaluation is sandboxed with a 1 second timeout; CEL is not Turing complete.

#### Scenario: An expression cannot be evaluated
- **WHEN** a step's handler returns PASS and its expression cannot be evaluated (for example `output.json` is missing because the command printed no JSON)
- **THEN** the step result MUST be ERROR, class `evaluation`, and it MUST NOT conclude the control

#### Scenario: A non-boolean expression
- **WHEN** a step's expression evaluates to a value that is not `true` or `false`
- **THEN** the step result MUST be ERROR, class `evaluation`

#### Scenario: An expression reads an unconfirmed project value
- **WHEN** an expression reads `project.<key>` and the key holds only a candidate
- **THEN** the step result MUST be ERROR, class `evaluation`

#### Scenario: An expression that decides finds a failure
- **WHEN** a step with `expr_decides = true` has a handler PASS and its expression evaluates false
- **THEN** the step result MUST be FAIL

#### Scenario: expr_decides on a step type without expressions
- **WHEN** a `file_exists` step sets `expr_decides = true`
- **THEN** loading MUST fail naming the control and the step

#### Scenario: An expression names data its step type does not provide
- **WHEN** an `exec` step declares `expr = 'response.body.x'`
- **THEN** loading MUST fail naming the control, the step, and `response`

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
| `expr` | `str` | CEL over `response.status_code` and `response.body` (the parsed JSON body); `true` -> PASS, `false` -> FAIL. Evaluated by the handler, not by the post-step of section 3.7, so `output.*` and `project.*` are not bound. Response headers are not available (`gh api` does not expose them). |
| `evidence_fields` | `list[str]` | Top-level `response.body` keys kept in the stored evidence. When set, every other body key is dropped from evidence, and so from reports and attestations; `expr` still evaluates against the full response. |

**Ceiling**: `{pass, fail}`.

**Behavior**:
1. 2xx: `expr` decides (no `expr`: PASS); an `expr` that cannot be evaluated over the response -> ERROR, class `evaluation`
2. 429, or a 403 whose message is a rate limit -> ERROR, class `rate_limit`, even when the status is in `fail_on_status` (a rate limit never proves failure)
3. A status in `fail_on_status` -> FAIL
4. 401 / 403 -> ERROR, class `auth`
5. 5xx, transport failure, or any other status not declared -> ERROR, class `unavailable`
6. `gh` not installed -> ERROR, class `missing_tool`

A response that is ambiguous between "not found" and "not permitted to see" is ERROR unless the step declares otherwise.

**Evidence**: `endpoint` (after substitution), `response` (`status_code`, `body`, limited to `evidence_fields` when declared), and on a non-2xx answer the `gh` error text.

**Personal records**: an endpoint that returns people's account records is a personal record. These are the endpoints (and every path under them; the query string is ignored), where `*` is any one path segment, a literal or a variable such as `$OWNER` or `{org}`:

| Endpoint | Returns |
|----------|---------|
| `/user` | the auditor's own account (and, under it, for example `/user/emails`) |
| `/users/*` | a named person's account |
| `/orgs/*/members` | an organization's members |
| `/orgs/*/outside_collaborators` | an organization's outside collaborators |
| `/orgs/*/teams/*/members` | a team's members |
| `/repos/*/*/collaborators` | a repository's collaborators (and, under it, a collaborator's permission record) |

A `gh_api` step reading a personal record MUST declare `evidence_fields`, listing only the fields its check needs; loading fails otherwise (section 3.0.3). An `exec` step whose command runs `gh api` against a personal record fails loading: its output would carry the whole record, so the check belongs in a `gh_api` step with `evidence_fields`. OSPS-AC-01.01 reads `/user` with `evidence_fields = ["login", "two_factor_authentication"]`, so the auditor's email, location, company, and biography never reach evidence, JSON output, or attestations (feature 044).

**Recorded responses**: the handler calls the platform through `darnit.core.utils.gh_api_with_status`. `set_gh_api_responder(responder)` routes every such call (including the `github_branch_protection` plugin handler's) through a responder instead of `gh`; `RecordedGhApi({path: {status, body, error}})` serves recorded responses keyed by API path, answers an unrecorded path as a transport failure (status 0), and with `gh_missing = True` answers as if `gh` were not installed. Tests and the adversarial corpus (section 5.5) use it to run platform checks offline and deterministically. Platform writes (`gh_api_write`, section 4.5) go through the same seam: the responder is called with `(method, endpoint, body)` and returns `(body, status, error)`; GET-only responders keep working, and `RecordedGhApi` also serves keys of the form `"PUT /repos/o/r/branches/main/protection"` and records each request body in `.calls`.

#### Scenario: Declared status proves failure
- **WHEN** a `gh_api` step with `fail_on_status = [404]` receives 404
- **THEN** the handler MUST return FAIL

#### Scenario: Undeclared status is a broken measurement
- **WHEN** a `gh_api` step receives 404 without declaring it, or receives 401, 403, 429, or 5xx
- **THEN** the handler MUST return ERROR with the cause

#### Scenario: A rate limit never proves failure
- **WHEN** a `gh_api` step declares `fail_on_status = [403]` and receives a rate-limit 403
- **THEN** the handler MUST return ERROR, class `rate_limit`

#### Scenario: Personal record without evidence_fields
- **WHEN** a `gh_api` step reads `/user`, `/user/emails`, `/users/someone`, `/orgs/$OWNER/members`, or `/repos/$OWNER/$REPO/collaborators` and declares no `evidence_fields`
- **THEN** loading MUST fail naming the control and the step

#### Scenario: exec reading a personal record
- **WHEN** an `exec` step's command is `["gh", "api", "/orgs/$OWNER/members"]`
- **THEN** loading MUST fail naming the control and the step, and directing the author to `gh_api` with `evidence_fields`

#### Scenario: Evidence limited to declared fields
- **WHEN** a `gh_api` step with `evidence_fields = ["login", "two_factor_authentication"]` receives a body that also has `email` and `bio`
- **THEN** the stored evidence MUST contain only `login` and `two_factor_authentication` in `response.body`

---

## 4. Built-in Remediation Actions

### 4.1 Overview

Remediations can be:
1. **Declarative** - Defined entirely in TOML using built-in actions
2. **Hybrid** - TOML config with Python handler reference
3. **Custom** - Full Python implementation via plugin

A control's remediation is an ordered list of handler invocations under `[controls."ID".remediation]`. The built-in remediation handlers are `file_create` (4.3), `exec` (4.4), `platform_setting` (4.5), `project_update` and `yaml_inject` (4.6), and `manual` (4.7).

```toml
[controls."OSPS-VM-02.01".remediation]
safe = true

[[controls."OSPS-VM-02.01".remediation.handlers]]
handler = "file_create"
path = "SECURITY.md"
template = "security_policy_standard"
project_reference = "security.policy"
```

**Remediation fields** (on `[controls."ID".remediation]`):

| Field | Type | Description |
|-------|------|-------------|
| `handlers` | array of tables | Ordered handler invocations. Each has `handler`, the handler's declared settings (section 3.0.3; any other key fails loading), and an optional `when` |
| `strategy` | `"all"` \| `"first_match"` | `all` (default) runs every handler whose `when` matches; `first_match` stops after the first |
| `requires_context` | list | Context requirements (section 7.3) |
| `safe` | `bool` | Default `true`. `false` means every step of this remediation requires individual approval in a batch apply, under every remediation policy (section 15.3) |
| `requires_api` | `bool` | Descriptive metadata: the remediation needs platform API access. It changes no behavior |

**Removed** (feature 043): the `api_call` handler (replaced by `platform_setting`), `requires_confirmation` (replaced by `safe = false`), `dry_run_supported` and `dry_run_command` (replaced by plan mode, 4.2, and the exec `effects`/`offline` fields, 4.4). Every remediation property that concerns safety, confirmation, or preview is enforced; a property that would not be enforced is not part of the schema.

#### Scenario: Removed remediation property
- **WHEN** a framework TOML declares a remediation handler `api_call`, or `requires_confirmation`, `dry_run_supported`, or `dry_run_command` on a remediation
- **THEN** loading the framework configuration MUST fail with an error naming the control and the replacement (`platform_setting`, `safe = false`, or plan mode with exec `effects`/`offline`)
- **AND** `validate_sync` MUST reject the property in shipped framework TOML

### 4.2 Plan/Apply Protocol

Every remediation runs in one of two modes. The executor passes the mode to each handler as `HandlerContext.mode` (`Literal["plan", "apply"]`, default `"apply"`).

| Mode | Purpose | Writes |
|------|---------|--------|
| `plan` | Preview: compute, against the current state, exactly what an apply would change | Nothing: no repository file, no platform setting, no run manifest |
| `apply` | Carry out the plan | Only the planned changes: files by the executor, platform settings by the platform engine (4.5) |

**Handler outputs.** In both modes a remediation handler returns its planned changes in its result evidence and does not write them itself:

- `evidence["file_changes"]`: a list of `FileChange`;
- `evidence["change_sets"]`: a list of `ChangeSet` (`platform_setting` only, 4.5).

`FileChange` (models in `specs/043-remediation-safety/data-model.md`):

| Field | Type | Description |
|-------|------|-------------|
| `path` | `str` | Repository-relative path |
| `action` | `"create"` \| `"modify"` \| `"none"` | `none` carries a `reason`: `already_exists`, `user_changes_present`, or `when_not_met` |
| `ignored` | `bool` | The path matches the repository's ignore rules: it is written but never staged or committed (15.7) |
| `content` | `str \| None` | Resulting content for `create` and `modify` |
| `before_digest`, `after_digest` | `str \| None` | Content digests before and after |
| `project_reference` | `str \| None` | Project field to record after a successful create (4.3) |

**Single writer.** The remediation executor (`RemediationExecutor`) is the only component that writes repository files for a declarative remediation. In apply mode it computes the plan against the current state, then writes each `FileChange` whose action is `create` or `modify`, atomically, and records it in the run manifest (15.6). Before writing a path it checks:

- a path with uncommitted user changes is not written; its `FileChange` becomes `action = "none"`, `reason = "user_changes_present"`, and the outcome reports the conflict;
- a path matched by the repository's ignore rules is written with `ignored = true` and is never staged.

A preview runs the same two checks, read-only, on every planned `FileChange` of a `file_create`, `yaml_inject`, or `project_update` step, of a declared `project_reference`, and of the remediation's `project_update`, so it reports these paths exactly as the apply will. Outside a git work tree neither check applies. A file written earlier in the same apply is not a user change.

Platform settings are written only by the platform engine (4.5). An `exec` step writes through its command in apply mode (4.4); the executor records what it changed when the step succeeded cleanly.

**Plan support.** Handler registration takes a flag `supports_plan` (default `False`): `registry.register(..., supports_plan=True)`. The built-in `file_create`, `project_update`, `yaml_inject`, `manual`, and `platform_setting` handlers register with `supports_plan=True`; `exec` is previewable only as section 4.4 describes. A step whose handler did not register `supports_plan=True` is not run in plan mode; it is reported as "cannot be previewed exactly" (`previewable = False`) and requires individual approval (15.3). A plugin handler without plan support that writes files itself is outside the run manifest, so the git tools never commit those files (15.7).

**Preview contents.** A preview is a list of `PlanItem`s, one per remediation step:

| Field | Type | Description |
|-------|------|-------------|
| `control_id` | `str` | |
| `step` | `str` | Handler name and index |
| `file_changes` | `list[FileChange]` | Every file to be created or changed, with its resulting content |
| `change_sets` | `list[ChangeSet]` | Every platform field to be changed, with before and after (4.5) |
| `commands` | `list[list[str]]` | Every command that will run |
| `previewable` | `bool` | `False`: "cannot be previewed exactly" |
| `requires_individual_approval` | `bool` | `safe = false`, not previewable, or a high-impact change set under `prompt` (15.3) |
| `digest` | `str` | Digest of the item, used to approve it individually (15.2) |

Templates and `when` clauses are evaluated in plan mode exactly as in apply mode (section 7.11), so a `confirmation required: <key>` stop appears in the preview.

**Preview equals apply.** A preview is computed by the same handler logic as the apply. With no intervening change, the changes an apply makes equal the changes the immediately preceding preview listed. A contract test runs every remediation in every shipped framework TOML in plan mode against a fixture repository with a filesystem snapshot and a recording platform responder, asserts zero writes, then applies and asserts that the applied changes equal the planned ones.

#### Scenario: A preview writes nothing
- **WHEN** a remediation runs with `HandlerContext.mode = "plan"`
- **THEN** no file in the repository, no platform setting, and no run manifest MUST change
- **AND** every handler that registered `supports_plan=True`, including `yaml_inject`, MUST return its planned changes without writing

#### Scenario: Target file already present
- **WHEN** a `file_create` step targets a file that exists and `overwrite` is false
- **THEN** its `FileChange` MUST have `action = "none"` and `reason = "already_exists"`
- **AND** the step MUST NOT count as a change

#### Scenario: Handler without plan support
- **WHEN** a remediation step's handler did not register `supports_plan=True`
- **THEN** the step MUST NOT run in plan mode
- **AND** its `PlanItem` MUST have `previewable = False` and `requires_individual_approval = True`
- **AND** it MUST NOT run in a batch apply unless its `PlanItem.digest` was approved

#### Scenario: Target file has uncommitted user changes
- **WHEN** a planned `FileChange` targets a path with uncommitted user changes
- **THEN** the executor MUST NOT write the path
- **AND** the `FileChange` MUST be reported with `action = "none"` and `reason = "user_changes_present"`, in the preview and in the apply

### 4.3 file_create

**Purpose**: Create files from templates

```toml
[[controls."OSPS-VM-02.01".remediation.handlers]]
handler = "file_create"
path = "SECURITY.md"
template = "security_policy_standard"  # References [templates.security_policy_standard]
overwrite = false
project_reference = "security.policy"
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `path` | `str` | Target file path (relative to repo root) |
| `template` | `str` | Template name from `[templates]` section |
| `content` | `str` | Inline content (alternative to template) |
| `overwrite` | `bool` | Overwrite existing files (default: false) |
| `llm_enhance` | `str` | Optional prompt for AI-assisted customization of the created file |
| `project_reference` | `str` | Optional dotted project field (`<section.field>`) that describes the created file, recorded after the file is created |

Parent directories of `path` are always created; there is no setting for it (the former `create_dirs` fails loading, section 3.0.3).

**Plan output**: one `FileChange`: `create` (or `modify` with `overwrite = true`) with the rendered content, or `none` with `already_exists`.

**Project references.** A reference to a created file is recorded in project data only from a `project_reference` declared on the `file_create` step that creates it; no control-to-field table exists outside the framework TOML. After apply, the executor records the reference only if the file was created in this run (it is in the run manifest) and the field is empty or already holds the same path, through the round-trip writer (section 7.9). Otherwise the field is unchanged and the outcome says why. A remediation that creates no file records no reference. An implementation validates each declared `project_reference` against the field's known file locations, so a reference field always describes the kind of file created (a bug report template is never recorded as the security policy).

#### Scenario: file_create with llm_enhance
- **WHEN** a `file_create` handler succeeds
- **AND** the handler config includes an `llm_enhance` field
- **THEN** the remediation result MUST include the enhancement prompt and file path in the result details
- **AND** the MCP layer MAY use this prompt to offer AI-assisted customization of the generated file

An implementation that customizes a created file itself (for example `remediate_audit_findings(enhance_with_llm=True)`) changes only a file whose `FileChange` in this apply has `action = "create"`, writes the new content through the executor's single writer with the same user-changes check (section 4.2), and records the new content's digest in the run manifest, so the file stays committable. A file that existed before the run is never changed. A model's output cannot be computed in advance (FR-023), so each such customization is its own `PlanItem`: `step = "llm_enhance[<path>] of <after_digest of the planned create>"`, `previewable = False`, `requires_individual_approval = True`, listed in the preview as "cannot be previewed exactly". Its digest covers the path and the content the file is created with. At apply, the file is customized only when that item's digest is approved (or a terminal item approver says yes); the approval is recorded with the run's approvals. Otherwise the model is not called, the file keeps the content it was created with (recorded and committable), and the control's outcome names the item as needing individual approval.

#### Scenario: Customization not approved
- **WHEN** AI-assisted customization is requested for a created file and the apply does not carry the digest of its `llm_enhance` plan item
- **THEN** the model MUST NOT be called and the file MUST keep the content it was created with, recorded in the run manifest
- **AND** the outcome MUST name the `llm_enhance` item as needing individual approval

#### Scenario: Customizing a file that already existed
- **WHEN** a `file_create` step's target already existed (`action = "none"`, `already_exists`) and AI-assisted customization is requested
- **THEN** the file MUST NOT be changed

#### Scenario: Existing reference is kept
- **WHEN** `file_create` creates a file whose `project_reference` field already holds a different reference
- **THEN** the field MUST be unchanged
- **AND** the outcome MUST say that the new file was not recorded and why

#### Scenario: Skipped file records nothing
- **WHEN** a `file_create` step's `FileChange` has `action = "none"`
- **THEN** no project reference MUST be recorded for it

### 4.4 exec (remediation)

**Purpose**: Run a local tool that fixes files in the working tree

```toml
[[controls."OSPS-BR-01.01".remediation.handlers]]
handler = "exec"
command = ["zizmor", "--fix=all", "--offline", "$PATH"]
pass_exit_codes = [0, 11, 12, 13, 14]
timeout = 60
effects = "working_tree"
offline = true
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `command` | `list[str]` | Command and arguments (variables as in section 3.3) |
| `pass_exit_codes` | `list[int]` | Exit codes that indicate success (default: `[0]`) |
| `timeout` | `int` | Timeout in seconds |
| `env` | `dict` | Additional environment variables |
| `effects` | `"working_tree"` | Declares that the command changes only files in the working tree. Required for the step to be previewable |
| `offline` | `bool` | Declares that the command needs no network. `true` is required for a scratch-copy preview |

**An exec remediation never changes platform state.** It may change only files in the working tree. Platform settings change only through `platform_setting` (4.5), which reads first, never weakens, and requires approval under the remediation policy. A shipped exec remediation whose command is `gh`, `curl`, `wget`, or `git push` fails `validate_sync`.

**Preview.** A step that declares both `effects = "working_tree"` and `offline = true` is previewable: in plan mode the executor copies the tracked files and the untracked files that are not ignored into a scratch directory, runs the command there, and records the difference as `FileChange`s; the checkout is not touched. A step without both declarations is "cannot be previewed exactly": it is not run in plan mode, its `PlanItem` lists the command with `previewable = False`, and it requires individual approval (15.3).

A step is not run in a scratch copy when any file it would see is a symbolic link whose target is absolute, or is or passes through a symbolic link and resolves outside the repository. Each path is resolved as the operating system resolves it (`realpath`), so a chain of links is followed (for example `sub/inner/d -> ../..` and `a -> sub/inner/d/../x`, which reads as inside the repository but is not): a command writing through such a link would change files outside the scratch copy. Because a relative link can resolve inside the checkout yet outside the copy (for example `../<checkout folder>/SECURITY.md` when the copy is made beside the checkout), the same check is repeated on the scratch copy after copying and before the command runs. The preview is then an error, the step is `previewable = False`, and it requires individual approval (15.3). A relative link that stays inside the repository is copied as a link.

A file the command creates that the checkout's ignore rules exclude is not part of the preview (and is not recorded at apply). A preview whose run does not succeed (an exit code outside `pass_exit_codes`, a missing binary, a timeout), or whose difference a `FileChange` cannot express (a deleted file, a non-text file), is an error, and the step is `previewable = False`.

**Apply.** The command runs in the checkout. The executor compares what the command created or modified with the preview, and records those files in the run manifest only when the step succeeded cleanly: the exit code is in `pass_exit_codes`, the result equals the preview (for a previewable step), no changed file had uncommitted user changes, and the command deleted no file and wrote no non-text file. Otherwise the step is an error, nothing it changed is recorded (so the git tools never commit it), the files stay in the working tree as the command left them, and the outcome (`error`) lists every file the step changed, as written but not recorded, for a person to review by hand; the audit cache is invalidated as for any write. A file the step changed that an earlier step of the same run recorded no longer holds what remediation wrote: it is removed from the run manifest and the outcome says so, so the commit tool commits the run's other files and leaves that one in the working tree. A previewed path that has uncommitted user changes is a conflict: the command is not run and the outcome names the path. A file the command changed that had uncommitted user changes before the step is reported as a conflict. An exit code outside `pass_exit_codes` is an error; a missing binary is ERROR, class `missing_tool`; a timeout is ERROR, class `timeout`.

#### Scenario: Exec apply that differs from its preview
- **WHEN** an applied exec step's changes differ from its preview, or its command exits outside `pass_exit_codes` after writing files
- **THEN** the step MUST be an error and none of the files it changed MUST be recorded in the run manifest
- **AND** the outcome MUST list those files as written but not recorded, and `commit_remediation_changes` MUST NOT commit them

#### Scenario: Failed exec step over a file recorded earlier in the run
- **WHEN** an exec step changes a file an earlier step of the same run wrote and recorded, and then fails
- **THEN** that file MUST be removed from the run manifest and the outcome MUST name it
- **AND** `commit_remediation_changes` MUST commit the run's other recorded files and not that one

#### Scenario: Exec remediation calling a platform command
- **WHEN** a shipped framework TOML declares an exec remediation whose command is `gh`, `curl`, `wget`, or `git push`
- **THEN** `validate_sync` MUST fail, naming the control

#### Scenario: Symbolic link leaving the repository
- **WHEN** a previewable exec step's visible files include a symbolic link whose target is absolute or resolves outside the repository or outside the scratch copy, directly or through a chain of links
- **THEN** the step MUST NOT run in the scratch copy, and the link's target MUST NOT change during the preview
- **AND** its `PlanItem` MUST have `previewable = False` and `requires_individual_approval = True`

#### Scenario: Exec step without preview declarations
- **WHEN** an exec remediation step lacks `effects = "working_tree"` or `offline = true`
- **THEN** the preview MUST label it "cannot be previewed exactly", with its command
- **AND** a batch apply MUST NOT run it unless its `PlanItem.digest` was approved

### 4.5 platform_setting

**Purpose**: Change a hosting-platform setting by the smallest change that satisfies a requirement, never weakening anything already configured

A `platform_setting` step declares a **requirement** on a named **target**, not a payload. One core platform engine (`darnit.remediation.platform`) serves every platform write: it reads the target's current state, decides whether the requirement already holds, plans the minimal operations, applies them under the remediation policy (section 15.1), and reads the result back.

```toml
[[controls."OSPS-QA-07.01".remediation.handlers]]
handler = "platform_setting"
target = "branch_protection"          # branch_protection | repository | vulnerability_reporting
require = { require_approvals = 1 }
branch = "release"                    # optional; default = the repository's default branch
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `handler` | `str` | MUST be `"platform_setting"` |
| `target` | `str` | `branch_protection`, `repository`, or `vulnerability_reporting` |
| `require` | `dict` | Requirement keys for the target (table below). Unknown keys are rejected when the framework configuration loads |
| `branch` | `str` | `branch_protection` only. Default: the repository's default branch as reported by the platform |

**Targets and requirement keys**:

| Target | Impact | Requirement keys | Stricter direction |
|--------|--------|------------------|--------------------|
| `branch_protection` | `platform` | `require_pull_request = true`, `require_approvals = N` (N >= 1), `prevent_deletion = true`, `prevent_force_push = true`, `enforce_admins = true`, `require_status_checks = [contexts]` | Booleans toward the required value; `require_approvals` is a minimum; status-check contexts must be a superset of the current set (existing ones are kept) |
| `repository` | `high_impact` | `visibility = "public"` | Toward the required value |
| `vulnerability_reporting` | `platform` | `enabled = true` | Toward the required value |

The impact class is fixed by the target kind: repository visibility and any organization-scoped target are `high_impact`; the others are `platform`. Requirement names match the `github_branch_protection` check handler's, so a control's check and its fix use the same vocabulary.

**`ChangeSet`** (one per target in a run; models in `specs/043-remediation-safety/data-model.md`):

| Field | Type | Description |
|-------|------|-------------|
| `target` | `PlatformTarget` | `kind`, `impact`, `owner`, `repo`, `branch` |
| `requirements` | `list[Requirement]` | Every requirement on this target in the run, merged |
| `observed_digest` | `str` | Digest of the `ObservedState` (`fields`, `rules`, `exists`) the plan was computed from |
| `operations` | `list[ChangeOperation]` | `method` (`PUT`, `PATCH`, `POST`), fully substituted `endpoint`, the exact JSON `body`, and `changes`: `{field, before, after}` for every field the operation changes. Empty when already satisfied |
| `satisfied_by` | `"already"` \| `"ruleset"` \| `None` | Why no operation is needed |
| `impact_notes` | `list[str]` | High-impact consequences shown in the preview |
| `digest` | `str` | Digest of `{target, observed_digest, operations}` (section 15.2) |

**Rules** (every remediation policy):

1. **Read first.** The engine reads the target's current state before planning. If any read fails (missing permission, not found, rate limit, network), it plans nothing, writes nothing, and the step is ERROR with the feature 041 `error.class` and `cause`.
2. **Never weaken.** Every `FieldChange.after` is equal to or stricter than its `before`. A setting already equal to or stricter than the requirement is left exactly as it is; a setting the requirement does not name is never removed, loosened, or reset.
3. **Already satisfied, no write.** When the current state, or an active repository or organization ruleset, satisfies the requirement, the change set has no operations and `satisfied_by` says why.
4. **One change set per target.** All requirements on one target in a run (for example `require_pull_request`, `prevent_deletion`, and `require_approvals` on the same branch) are planned together into one change set, so no write undoes another.
5. **Default branch.** The branch is the repository's default branch as reported by the platform, unless a branch is named. If it cannot be read, the step is ERROR.
6. **Read back.** After a write the engine reads the target again and derives the result from comparing the read-back with the requirement, never from response text. A partial write reports exactly the fields that changed.
7. **Supported platforms.** Platform remediation exists for GitHub only. For a repository whose canonical identity is on another platform, the outcome is `manual` with the steps, and no platform call is made.

**Branch protection writes**:

1. `GET /repos/{o}/{r}` for the default branch; `GET .../branches/{b}`: a missing branch is ERROR; `protected = false` is the unprotected state; `protected = true` is followed by `GET .../protection`. Active rules come from `GET /repos/{o}/{r}/rules/branches/{b}`.
2. Unprotected: one `PUT .../protection` that sets only the required settings; every other field is sent at its platform default, which equals the current, unprotected state.
3. Protected: review requirements through `PATCH .../required_pull_request_reviews` with only the fields that must tighten (the approval count is raised to the minimum, never lowered), when pull request reviews are already required; `enforce_admins` through `POST .../enforce_admins` only when it is off; missing status-check contexts through `POST .../required_status_checks/contexts`, keeping existing `contexts` and `checks`, when status checks are already required. The granular endpoints of a sub-protection answer 404 when that sub-protection is not enabled, so a requirement whose sub-protection is absent from the protection GET (no `required_pull_request_reviews`, or no `required_status_checks`), and `prevent_deletion` and `prevent_force_push`, which have no granular endpoint, are applied through one full `PUT` built by translating the current protection into the PUT shape with every existing value preserved and only the required settings added or tightened.
4. The translator is total over a known field list. A protection response containing a field it does not know makes the step ERROR, "cannot preserve unknown protection setting <field>", and nothing is planned.

**Platform calls.** Writes go through `darnit.core.utils.gh_api_write(method, endpoint, payload) -> (body, status, error)`, which sends the JSON body with `gh api -X METHOD --input -` and reads the status. It uses the same responder seam as `gh_api_with_status` (section 3.8).

**`enable_branch_protection`** (MCP tool) is a thin wrapper over the engine: its parameters become `branch_protection` requirements, it defaults to `dry_run = True` (preview only) and `branch = None` (the default branch), and it takes `approve` (a change-set digest). `required_approvals`, `require_pull_request`, `enforce_admins`, `require_status_checks`, and `status_checks` only tighten: existing values are never lowered and existing checks are never removed. A fix declared in TOML and the tool for the same setting produce the same change set; there is no second write path.

#### Scenario: Stricter existing protection is preserved
- **WHEN** the default branch already requires two approvals, required status checks, push restrictions, code-owner review, and linear history
- **AND** a run plans `require_pull_request`, `prevent_deletion`, and `require_approvals = 1` for it
- **THEN** the change set MUST change only the fields the requirements tighten (here at most `allow_deletions: true -> false`)
- **AND** any full `PUT` body MUST preserve every other existing value
- **AND** the read-back MUST show every pre-existing setting unchanged

#### Scenario: Sub-protection not enabled
- **WHEN** the branch is protected but its protection has no `required_pull_request_reviews` (or no `required_status_checks`) and a requirement needs it
- **THEN** the change set MUST NOT use `PATCH .../required_pull_request_reviews` (or `PATCH .../required_status_checks`)
- **AND** it MUST add the setting through the translated full `PUT`, which preserves every other existing value

#### Scenario: Requirement already satisfied
- **WHEN** the current settings, or an active ruleset, satisfy every requirement on the target
- **THEN** the change set MUST have no operations and `satisfied_by` MUST be `already` or `ruleset`
- **AND** nothing MUST be written

#### Scenario: Current settings cannot be read
- **WHEN** any read of the target fails
- **THEN** no change set MUST be planned and nothing MUST be written
- **AND** the step MUST be ERROR with the cause

#### Scenario: Unknown protection field
- **WHEN** the protection response contains a field the translator does not know and the plan needs a full `PUT`
- **THEN** the step MUST be ERROR "cannot preserve unknown protection setting <field>" and nothing MUST be written

#### Scenario: Partial write
- **WHEN** one operation of a change set succeeds and a later one is rejected
- **THEN** the outcome MUST be `error` and MUST list exactly the fields the read-back shows changed
- **AND** the control MUST NOT be reported `fixed`

### 4.6 project_update and yaml_inject

**`project_update`** sets project data fields:

| Field | Type | Description |
|-------|------|-------------|
| `updates` | `dict[str, Any]` | Dotted path -> value pairs |

Its plan output is one `FileChange` per project file it changes, with the resulting content. In apply mode the executor writes it through the round-trip writer, only to the dotted paths it targets (section 7.9).

**`yaml_inject`** adds a top-level key to YAML files that lack it:

| Field | Type | Description |
|-------|------|-------------|
| `files` | `str` | Glob of YAML files (relative to the repository) |
| `key` | `str` | Top-level key to add (for example `permissions`) |
| `value` | `str` | YAML value to add (for example `{}`) |
| `insert_after` | `str` | Insert after this key (default `on`); otherwise after any leading comments |

Its plan output is one `FileChange` (`modify`, with the resulting content) per matched file that lacks the key. It never writes; the executor does, in apply mode.

### 4.7 manual (remediation)

A `manual` remediation step (`steps`, `docs_url`, as in section 3.6) has no side effects. It registers `supports_plan=True`, so it is previewable and batch-eligible. A control whose remediation reaches only manual steps, whose platform change is not available through the platform's API (for example organization two-factor enforcement, which can be set only in the web UI), or whose platform change runs under the `manual` policy, has outcome `manual` with the steps; the steps state the change's impact.

### 4.8 Templates

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

The global registry is process-wide and keyed by control id, so it holds every control any earlier audit in the process registered. An audit therefore takes its controls from its own framework definition (including controls composed from other frameworks) plus operator custom controls, never from the registry. The registry is used only when no framework definition can be resolved.

#### Scenario: Two frameworks audited in one process (#442)
- **WHEN** a long-lived process (such as the MCP server) audits framework A and then framework B
- **THEN** the audit of B SHALL evaluate exactly the controls it evaluates in a fresh process
- **AND** no control defined only by A SHALL appear in B's results

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

A detection step's `value_if_fail` applies only when the step ran to completion and answered negatively (a `FAIL`, or a successful command whose CEL `expr` evaluated false) and no earlier step failed to run. A step that errored (missing tool, timeout, unknown handler) or could not decide (an exit code the step does not declare) produces no value, and later steps still run. The same rule applies to every caller: the context resolver, pending-data questions, and the evidence that contradicts a not-applicable claim (14.3). Release status is never `false` unless a successful platform answer showed no releases; a failing `gh release list` leaves `has_releases` unknown.

#### Scenario: Failing release lookup
- **WHEN** no local release evidence exists and `gh release list` exits non-zero (authorization, rate limit, network, no such repository)
- **THEN** `has_releases` is `unknown`, it is listed as pending data, and release-gated controls are evaluated exactly as if it had never been looked up

### 7.8 Canonical Key Names and Vocabularies

Each context key has one canonical name and one vocabulary, taken from the framework TOML. Stored legacy names and spellings are read as the canonical form (`ci.provider` and bare `provider` read as `ci_provider`; `github_actions` -> `github`, `gitlab_ci` -> `gitlab`, `azure_pipelines` -> `azure`, `bitbucket_pipelines` -> `other`, `unknown` -> no value). The framework writes only canonical names and values. Every read of the CI provider goes through this normalization (`darnit.config.context_keys`), including `ProjectConfig.get_ci_provider()`, and the framework has one CI detector (`detect_ci_provider`), which returns canonical values.

### 7.9 Reads Never Write; One Writer

- Auditing (every driver), listing pending data, report generation, a remediation preview (plan mode, section 4.2), the remediation context guard in every mode, and the harness collect phase SHALL NOT create, modify, or delete any file in the audited repository.
- `darnit.config.context_writes` is the only code that writes context values and in-repository confirmation records. It writes only `.project/darnit.yaml` (never `.project/project.yaml`), preserves sections and comments it does not change (including feature 040 `controls:` claims), and refuses every write, returning the errors, when `.project/project.yaml` or `.project/darnit.yaml` is present but unparseable or invalid. The loader distinguishes absent, valid, and invalid files (`load_project_config_checked`).
- `init_project_config` (MCP) creates only an empty `.project/darnit.yaml` when `.project/` is absent, and reports instead of overwriting when it is present.
- An applied remediation's `project_update` (written by the remediation executor, section 4.2) and the file-reference sync after a remediation creates a file (`update_config_after_file_create`, `UnifiedLocator.sync_to_project`) write only the dotted paths they target, through the loader's round-trip helper (`update_project_config`): CNCF fields to `.project/project.yaml`, other fields to `.project/darnit.yaml`, preserving comments, ordering, indentation, and fields darnit does not own. An absent `.project/project.yaml` is created with `name` and the targeted fields only. No darnit code replaces a whole project file. The file-reference sync after remediation records only a `project_reference` declared on the `file_create` step, only for a file created in this run, and only when the field is empty or already equal (section 4.3). When either file is present but invalid they write nothing: planning the update (`plan_project_update`, used by the `project_update` handler and the remediation's `project_update`) raises with the validation errors (an applied remediation reports `project_update: failed: <errors>`), and the sync functions return false.
- An audit reads nothing from a present-but-invalid `.project/` file and reports each validation error in the report's `warnings` (JSON) and as a warning line (Markdown).

### 7.10 Confirmation Tool Contract

The observable payloads of `get_pending_data` and `confirm_project_data` are defined in `specs/042-candidate-integrity/contracts/context-confirmation-tools.md`:

- `get_pending_data` is read-only. Each question carries its candidate as data (`candidate: {value, origin, digest, label}`, where `digest` is the value digest (7.5) and `label` marks it unconfirmed); the candidate's value appears nowhere else in the response. `command_template` holds placeholders only (`<the person's answer>`, `<candidate digest if the person accepts it>`, `owner=..., repo=...`), never a candidate value or a configuration example. `answer_mapping.value_map["Yes"]` for a candidate is `{"accept_candidates": {"<key>": "<candidate.digest>"}}`, a placeholder the agent fills from the question's `candidate.digest` only after the person answered yes. Enum questions list every allowed value in `allowed_values`; when there are more than 4, the selector (`ask_user`) is omitted and the prompt lists them all. `examples` appear only as `format_hint`. Every question in the batch is returned under `questions`, with or without a selector. The response lists `stored_unconfirmed` values with their locations.
- `confirm_project_data` takes a parameter for every context key that the server's bound framework defines, and no other framework's keys (generated from the definitions; an enum parameter accepts only its `values`), plus `accept_candidates` (`{key: candidate digest}`: detection runs again and the current candidate, or a value concluded in this run, is confirmed only if its digest still matches, recording its value and origin as the basis; a mismatch, a key with no candidate, or a key given both an answer and a digest is refused and nothing is written for it), `confirm_stored` and `reject_stored` (review of stored values: a rejected `.project/darnit.yaml` value is deleted; a rejected `.project/project.yaml` value is reported with its file and field and the file is left unchanged), `expires_at` (`{key: date}`), and `owner`, `repo`, `host`, which are required and decide the record location (7.5). `confirm_stored` records a confirmation of the value currently stored for each key (basis: that value, origin `stored_unconfirmed` or `expired_confirmation`). Like a confirmation, a rejection writes to `.project/darnit.yaml` only when the operator trusts the named repository; otherwise it is refused and names the file and field for the person to edit. The result names, per key, `confirmed (in-repository)` with the file written or `confirmed (operator-side)`, `rejected`, `edit required: <file>:<field>`, or `refused: <reason>`.
- **Which server exposes it**: each server's `confirm_project_data` covers only the keys of the framework the server is bound to. The OpenSSF Baseline server defines its own (which also carries `confirm_not_applicable` and `confirm_pass_candidate`). Every other framework server that defines context keys and whose TOML does not define a tool named `confirm_project_data` gets a framework-neutral builtin `confirm_project_data` (a framework with no context keys gets none), registered by the factory the same way as `submit_judgment` and `confirm_pass_candidate` (5.4) and bound to that framework's context definitions. It records context values only: the per-key parameters, `accept_candidates`, `confirm_stored`, `reject_stored`, `expires_at`, `owner`, `repo`, `host`, and `local_path`. Claim confirmations and PASS candidates stay on their existing tools.
- Remediation prompts (the preflight and `format_context_prompt`) show a candidate as labelled, unconfirmed data with its origin and digest, name the key's hint source files that exist without parsing values out of them, and hold placeholders only in their commands.

### 7.11 Consumers of Context Values

Every consumer reads context values from the resolver's usable mapping (7.4) and nothing else:

- **Audit applicability** (`when` clauses): this run's filesystem detections of keys that are not judgment keys, then `.project/project.yaml` mapper values, then usable values. The audit resolves without running the framework's detection pipelines; its only detections are those filesystem detections. Only usable values confirmed in the repository count as repository data for not-applicable claims (14.3). Values the detection pipelines would conclude (for example `has_releases`) are therefore used by the audit only once confirmed: a missing key leaves its control applicable, so a concluded positive changes nothing, and the only effect a concluded negative could have is to make controls not applicable from a network answer (an empty `gh release list` does not show that a project makes no official releases, which it may publish elsewhere). Pending-data questions do run the pipelines, and a person can confirm the proposed value.
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

[[controls."OSPS-AC-03.01".remediation.handlers]]
handler = "platform_setting"
target = "branch_protection"
require = { require_pull_request = true }
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
- **WHEN** `run_sieve_audit()` completes successfully and was not called with `write_cache=False`
- **THEN** it SHALL call `write_audit_cache()` with the `results`, `summary`, `level`, and `framework` name
- **AND** subsequent calls to `read_audit_cache()` from the same repository SHALL return the cached results (assuming no commit change)
- **AND** audit failure (exception before completing) SHALL NOT write to the cache
- **AND** a post-remediation re-check (`run_sieve_audit(controls=..., write_cache=False)`, section 15.5) SHALL NOT write to the cache

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
- **WHEN** `remediate_audit_findings()` completes with `dry_run=False` and at least one outcome changed something (section 15.4)
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
- **AND** the name SHALL come from an explicit parameter (the `--framework` option or a tool's framework argument), or `discover_implementations()` to list available options
- **AND** nothing in the audited repository selects the framework (Section 14.4)

---

## 11. Locator and Context Integration

### 11.1 use_locator for File Existence Checks

A deterministic handler invocation MAY use `use_locator = true` instead of specifying `files` directly. When `use_locator = true` is set, the framework SHALL use the control's `locator.discover` list as the handler's `files` parameter.

- If the control has no `locator` configuration, the framework SHALL log a warning and return INCONCLUSIVE
- If both `use_locator = true` and explicit `files` are specified, `files` takes precedence

### 11.2 Auto-derived on_pass from Locator

When a control has a `locator` with `project_path` AND a deterministic `file_exists` handler (or `use_locator = true`), AND the control does NOT have an explicit `on_pass` configuration, the framework SHALL auto-derive an `on_pass.project_update` that sets the `locator.project_path` to the path of the found file.

Explicit `on_pass` configurations always take precedence over auto-derivation.

An audit never applies an `on_pass` update (feature 042, FR-001): when the control passes, the resolved update is reported in the result's evidence as `proposed_project_update` and nothing is written. Writing it is an explicit action (an applied remediation or a person's confirmation).

### 11.3 Template Variable Context References

Template variable substitution SHALL support:
- `${context.<key>}` -- resolves to usable context values (7.4); reading a defined context key without a usable value stops the remediation with "confirmation required" (7.11)
- `${project.<dotted.path>}` — resolves to project configuration values

Unresolved references SHALL be replaced with an empty string and logged at debug level.

### 11.4 Context Informs But Never Overrides Verification

Project context from `.project/` SHALL be used to inform WHERE the sieve looks for evidence (via `locator.project_path`), but SHALL NOT determine WHETHER a control passes. Even when context indicates a file exists, the sieve SHALL still verify through its normal handler pipeline.

## 12. Handler Registry

The framework SHALL provide a handler registry where handlers are registered by name with a phase affinity. Core SHALL register built-in handlers: `file_exists`, `exec`, `gh_api`, `regex`, `pattern`, `llm_eval`, `llm_extract`, `manual`, `manual_steps`, `mcp`, `file_create`, `platform_setting`, `project_update`, `yaml_inject`. Each registration declares its ceiling (section 3.0.1), its `settings` and `expression_names` (section 3.0.3), and, for remediation handlers, plan support (`supports_plan`, section 4.2). Core registers before any plugin, and the registry refuses a plugin registration that would replace a core step type or another plugin's step type (section 3.0.3). Implementations SHALL register domain-specific handlers via the existing `ComplianceImplementation.register_handlers()` method.

Implementation-registered sieve handlers (non-exhaustive):

| Step type | Registered by | Ceiling |
|-----------|---------------|---------|
| `github_branch_protection` | `darnit-baseline`: the classic-branch-protection + repository-rulesets two-surface check for `OSPS-AC-03.01`, `OSPS-AC-03.02`, `OSPS-QA-03.01`, `OSPS-QA-07.01`; see `specs/032-ruleset-branch-protection/contracts/github-branch-protection-handler.md` | `{pass, fail}` (reads platform settings) |
| `generate_threat_model` | `darnit-baseline` (remediation) | `{pass, fail}` |
| `gittuf_verify_policy`, `gittuf_commits_signed` | `darnit-gittuf` | `{pass, fail}` (cryptographic verification) |
| `repro_deps_pinned`, `repro_build_env_declared`, `repro_hermetic_build`, `repro_provenance_exists`, `repro_bit_for_bit` | `darnit-reproducibility` | `{fail}`: they decide from text and file-presence signals, so PASS needs a corpus-backed promotion (section 3.0.1) |
| `csl_llm_if_present` | `darnit-csl` | `{fail}` |

The reproducibility ceilings are part of that framework's own registration, not its package name, so they hold under a rename of the package.

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
- The `[remediation]` section sets the remediation policy for platform changes (section 15.1).

### 14.2 Trusted repositories and CI

- The operator lists trusted repositories by canonical identity (`host/namespace/name`). The identity used for a trust decision comes from the operator's audit target or CI metadata, never solely from the checkout's own version-control configuration.
- CI trust is opt-in per rule; the initial rule trusts pushes to the default branch of a listed repository. Pull requests from forks and unrecognized events are never trusted.

### 14.3 Project assertions

- Project assertions (for example "this control is not applicable, reason X") live in `.project/` (darnit's extension file for anything upstream `.project/` cannot express). Project data that changes a control's applicability is treated as an assertion. For a context value that is only a value confirmed in the repository (7.5): an unconfirmed stored value is a candidate and has no effect (7.4), and a value the operator confirmed operator-side is the operator's decision, not a repository assertion.
- An assertion-backed not-applicable result is **honored** only for a trusted repository with a reason and no contradicting evidence; otherwise it is **pending** (non-compliant until the operator confirms it) or **contradicted** (ignored, with the evidence reported). Controls MAY declare `contradicted_by` evidence in framework TOML.
- Confirmations are stored on the operator side, keyed by repository identity, claim, and evidence digest, and lapse on expiry or when the evidence changes. Confirmations of project context values follow Section 7.5 instead.
- Reports and attestations label every assertion-backed N/A as asserted, with the asserter and any confirmer.

### 14.4 Repository-level .baseline.toml

darnit does not read a repository's `.baseline.toml` for anything: no per-control status or reason, no `extends`, no settings, no custom controls, and no other key. Not-applicable claims come only from `.project/` (14.3), the framework is selected only by the `--framework` option or a tool's framework argument, and tool settings come only from operator configuration (14.1).

- When the file exists in an audited repository, the audit SHALL record exactly one notice, logged at WARNING and listed in the report's `warnings`: the file is ignored, and `darnit config migrate` moves its claims to `.project/darnit.yaml` and prints an operator configuration fragment for its tool settings. Its keys are not listed in `ignored_repository_settings`.
- `darnit config migrate [REPO]` reads the file itself. It writes the per-control status and reason to `.project/darnit.yaml` (keeping an existing claim for the same control unless `--force` is given), prints a proposed operator configuration fragment for the other settings, never writes operator configuration, and never deletes the file.

#### Scenario: Claim in .baseline.toml for a trusted repository
- **WHEN** a repository the operator trusts has a `.baseline.toml` marking a control `status = "n/a"` with a reason
- **THEN** the control MUST be evaluated as if the file were absent, with no assertion
- **AND** the report MUST carry the single notice

#### Scenario: extends in .baseline.toml
- **WHEN** `.baseline.toml` sets `extends` to a registered framework and the run names no framework
- **THEN** the audit MUST NOT use the framework the file names

## 15. Remediation Safety

Remediation is the part of darnit that changes things: files in the repository, `.project/` data, commits and pull requests, and settings on the hosting platform. Constitution Principle II applied to remediation: a damaging change is worse than no change, and a change reported but not made is worse than an honest "not fixed". This section governs what remediation may change, how it shows the change beforehand, and what it may claim afterwards. Features 040 (operator configuration, trust), 041 (result contract, ERROR), and 042 (only usable context values reach remediation, section 7.11) are unchanged by it. See `specs/043-remediation-safety/` for the full contracts.

### 15.1 Remediation Policy

The operator configuration (section 14.1) sets how platform changes are approved, separately for high-impact changes and for other platform changes:

```toml
# operator configuration (e.g. ~/.config/darnit/config.toml)
[remediation]
platform = "prompt"     # prompt | manual | auto
high_impact = "prompt"  # prompt | manual | auto
```

| Field | Values | Default | Governs |
|-------|--------|---------|---------|
| `platform` | `prompt`, `manual`, `auto` | `prompt` | Platform change sets whose target impact is `platform` (section 4.5) |
| `high_impact` | `prompt`, `manual`, `auto` | `prompt` | Change sets whose target impact is `high_impact`: organization-wide settings and repository visibility |

| Value | Behavior |
|-------|----------|
| `prompt` | darnit previews, and writes a change set only when that change set's digest is approved (15.2) |
| `manual` | darnit makes no platform change; the outcome is `manual` with the exact steps for a person |
| `auto` | darnit writes without asking, and records the change and its impact in the outcome |

- The policy comes only from operator configuration. A `[remediation]` setting in the audited repository (`.project/` or any other file) is ignored.
- An absent section means both values are `prompt`. Unknown keys or values stop the run (section 14.1).
- Every `RemediationRun` records the policy in effect and the operator configuration digest; `darnit config show` prints the resolved section.
- Every value still follows the `platform_setting` rules (section 4.5: read first, never weaken, no write when already satisfied, default branch, read back). `auto` removes only the approval step for platform change sets. It never approves an item that requires individual approval because of `safe = false` or because it cannot be previewed (15.3); those need a person's approval under every policy.
- The policy governs only changes the platform lets darnit make. A change with no platform API (organization two-factor enforcement) is `manual` under every policy.

#### Scenario: Policy in the audited repository
- **WHEN** the audited repository's files contain a `[remediation]` setting
- **THEN** it MUST be ignored, and only the operator configuration MUST set the policy

#### Scenario: Manual policy
- **WHEN** the policy for a change set's impact class is `manual`
- **THEN** no platform write MUST occur
- **AND** the outcome MUST be `manual` with the steps

#### Scenario: Auto policy
- **WHEN** the policy for a change set's impact class is `auto` and the remediation is applied
- **THEN** darnit MUST write the change set without an approval digest
- **AND** MUST still read first, plan the minimal non-weakening change, and read back
- **AND** the report MUST state the policy, the change, and its impact notes

#### Scenario: Prompt policy with no person to ask
- **WHEN** the policy is `prompt`, the apply carries no approval for a change set, and no person can be asked (non-interactive, no agent)
- **THEN** nothing MUST be written for that change set
- **AND** the outcome MUST be `needs_approval` with the previewed change set

### 15.2 Digest-Bound Approval

A **digest** is `"sha256:" + hex(sha256(canonical_json(x)))`, with `canonical_json` = `json.dumps(x, sort_keys=True, separators=(",", ":"))`.

- `ChangeSet.digest` covers `{target, observed_digest, operations}`, so it binds the approval to the exact change and to the observed state the change was computed from.
- `PlanItem.digest` covers the plan item and is used to approve a repository step individually (15.3).

A person approves by digest: an apply call carries the approved digests (`approve` on `remediate_audit_findings` and `enable_branch_protection`), or `darnit run` shows each change set and asks on `/dev/tty`. At apply, darnit re-reads the target and re-plans; it writes only when the recomputed digest equals an approved one. Otherwise it writes nothing for that item. The outcome is `unchanged` with reason `stale_preview`, and a new preview is needed, only when some approval matches no change-set or plan-item digest of the run. A change set applied before a later control is planned may first be classified `stale_preview`; once every control has run, if every approval matches a plan-item or change-set digest the run planned or applied, it is reclassified `needs_approval` (nothing was written for it either way). No extra preview pass runs: each exec preview and platform read runs as often as in an apply without approvals. When every approval matches another item of the run, the unapproved change set is `needs_approval`.

- A high-impact change set is applied under `prompt` only when its own digest is approved. An approval of a batch, or of other change sets, never covers it. Its preview lists its `impact_notes` (for example: all code, history, and Actions logs become publicly readable, and existing private forks are detached).
- An apply flag alone (`dry_run = False`) never approves anything. An agent passes only the digests the person approved.
- Approvals are single-use and are recorded only in the run record: `Approval` = `digest`, `approved_by` (the operator identity, feature 040), `approved_at`. Approvals are not confirmations and are never stored in the confirmation store (sections 5.4, 7.5).

#### Scenario: Stale preview
- **WHEN** a person approved a change set's digest and the target's settings changed before the apply
- **THEN** darnit MUST write nothing for that change set
- **AND** the outcome MUST be `unchanged` with reason `stale_preview`

#### Scenario: Approval of another control's item
- **WHEN** an apply under `prompt` carries only the `PlanItem.digest` of one control's item, and an earlier-applied control's change set is not approved
- **THEN** that change set MUST be `needs_approval`, not `unchanged` with `stale_preview`

#### Scenario: Apply without approval under prompt
- **WHEN** the policy is `prompt` and an apply carries no digest for a change set
- **THEN** nothing MUST be written for it and its outcome MUST be `needs_approval`

#### Scenario: High-impact change in a batch
- **WHEN** a batch apply under `prompt` carries approvals for other change sets but not the digest of a high-impact change set
- **THEN** the high-impact change set MUST NOT be applied

### 15.3 Individual Approval

A plan item has `requires_individual_approval = True`, and runs in a batch apply only when its own digest is approved, when:

1. its remediation declares `safe = false` (every step of that remediation), under every policy;
2. it cannot be previewed exactly (`previewable = False`: a handler without plan support, or an exec step without `effects = "working_tree"` and `offline = true`), under every policy;
3. it holds a high-impact change set and the `high_impact` policy is `prompt`.

An item that can change nothing (it is previewable and has no file change, no platform operation, and no command; for example a `manual` step or a `file_create` of a file that already exists) never requires individual approval.

An item that needs individual approval and has none has outcome `needs_approval`, and nothing is written for it. Approval is per control: while any item of a control's remediation needs approval and lacks it, no step of that remediation runs. An item that needs approval only because of rule 3 is also approved by the digests of its change sets, or by a person at the terminal (15.2).

#### Scenario: Unsafe remediation in a batch
- **WHEN** a batch apply includes a remediation with `safe = false` and its `PlanItem.digest` was not approved
- **THEN** it MUST NOT be applied, under every policy including `auto`

### 15.4 Remediation Outcomes

Each control in an apply has exactly one `RemediationOutcome`:

| `kind` | Meaning |
|--------|---------|
| `fixed` | Something changed and the re-check (15.5) passes |
| `changed_not_passing` | Something changed and the re-check does not pass |
| `changed_not_verified` | Something changed and the re-check could not run or ended ERROR |
| `unchanged` | Nothing changed, with the reason (`already_exists`, `satisfied_by` already or ruleset, `user_changes_present`, `when_not_met`, `stale_preview`) |
| `needs_approval` | An approval is required (15.2, 15.3); carries the previewed change |
| `needs_confirmation` | A context value is not usable: `confirmation required: <key>` (section 7.11) |
| `manual` | darnit made no change and reports the steps (manual-only remediation, `manual` policy, unsupported platform) |
| `error` | A step failed; carries the feature 041 `error.class` and `cause`, and lists any partial changes |

Transitions (apply mode):

```text
plan -> [confirmation missing]            -> needs_confirmation
     -> [manual only / policy manual]     -> manual
     -> [needs approval, none given]      -> needs_approval
     -> [stale digest]                    -> unchanged (reason: stale_preview)
     -> [no operations, no file changes]  -> unchanged (reason from FileChange/ChangeSet)
     -> apply -> [any step error]         -> error (partial changes listed)
              -> recheck -> PASS          -> fixed
                         -> not PASS      -> changed_not_passing
                         -> could not run -> changed_not_verified
```

- Only a definite success with a non-empty change counts as changed. INCONCLUSIVE, ERROR, a step that did not run, and `action = "none"` never count as success.
- The run summary (counts per `kind`) is derived from the outcomes. The Markdown and JSON reports, and every downstream decision (whether to commit or open a pull request), are derived from the outcomes, never from matching symbols or words in output text.
- If the check for unconfirmed project context cannot complete, remediation does not run and the call returns the error.

**`RemediationRun`** (one per preview or apply):

| Field | Description |
|-------|-------------|
| `run_id` | ULID |
| `repository` | Canonical repository identity (feature 040) |
| `mode` | `preview` or `apply` |
| `policy` | The resolved `[remediation]` policy |
| `operator_config_digest` | Digest of the operator configuration |
| `approvals` | `Approval`s used by this run |
| `plan` | `PlanItem`s |
| `outcomes` | `RemediationOutcome`s (apply only) |
| `summary` | Counts per outcome kind, derived from `outcomes` |

**Reports** (Markdown and JSON) show, per control: the outcome `kind`, the files changed, platform fields `before -> after`, the re-check status, and the reason and error; per run: the policy, the operator configuration digest, the approvals (digest, by, at), the run id, and the summary counts. A preview of a high-impact change lists its impact notes. `remediate_audit_findings` returns the Markdown report followed by a fenced JSON block holding the `RemediationRun` (a preview carries `plan` with every digest, `previewable`, and `requires_individual_approval`; an apply carries `outcomes` and `summary`).

#### Scenario: File already exists
- **WHEN** the only step of a control's remediation is a `file_create` whose file already exists
- **THEN** the outcome MUST be `unchanged` with reason `already_exists`, never `fixed`

#### Scenario: Handler result is not a definite success
- **WHEN** a remediation step returns INCONCLUSIVE or ERROR, or does not run
- **THEN** the step MUST NOT count as a change or as a success

#### Scenario: Context guard cannot complete
- **WHEN** the check for unconfirmed project context raises or cannot complete
- **THEN** remediation MUST NOT run and the error MUST be returned

### 15.5 Re-check

After an apply that changed something, darnit re-checks the affected controls with `run_sieve_audit(controls=<affected>, write_cache=False)`: a subset audit through the canonical pipeline (section 10.1) that does not write the audit cache (section 10.4). The sieve is unchanged. A re-check PASS gives `fixed`; FAIL, WARN, or PENDING (including a PASS candidate) gives `changed_not_passing`; ERROR, or a re-check that could not run, gives `changed_not_verified` with the error. A control whose remediation changed nothing is not re-checked and is never `fixed`.

#### Scenario: Changed but still failing
- **WHEN** a remediation changed a file and the re-check of its control is FAIL
- **THEN** the outcome MUST be `changed_not_passing` with the re-check result

#### Scenario: Re-check lookup fails
- **WHEN** the re-check needs a platform lookup that fails
- **THEN** the outcome MUST be `changed_not_verified` with the error, not `fixed`

#### Scenario: Re-check leaves the audit cache unchanged
- **WHEN** a re-check runs
- **THEN** the full-audit cache file MUST be byte-identical before and after

### 15.6 Run Manifest

Every apply records a run manifest operator-side at `user_data_root()/remediation/<repository-identity>/<run_id>.json`, mode 0600. A manifest path inside the checkout is refused. A preview writes no manifest.

| Field | Description |
|-------|-------------|
| `run_id`, `repository`, `created_at` | |
| `files` | `[{path, after_digest}]` for every file the executor wrote, less any a failed exec step changed afterwards (4.4) |
| `change_sets` | Digests of the change sets applied |
| `branch` | Remediation branch, if one was created |
| `base`, `base_commit` | The ref a pull request from `branch` targets, and the commit it pointed to, recorded when the branch is created or switched to; a run that moves to another branch replaces both (empty when the base cannot be resolved) |
| `commit` | Set by the commit tool |

The manifest is the only record of which files remediation wrote; the git tools read it (15.7).

### 15.7 Version-Control Rules

The git tools `create_remediation_branch`, `commit_remediation_changes`, and `create_remediation_pr` take `run_id` (default `None`: the latest run for the repository).

- **Refused states.** When any git step is requested, darnit checks the repository before applying any remediation and stops with nothing changed on a detached HEAD, a merge in progress (`MERGE_HEAD`), a rebase in progress (`rebase-merge`, `rebase-apply`), an existing remediation branch with a commit beyond its base that lacks the `Darnit-Remediation-Run` trailer, or a dirty working tree when switching to an existing branch. When a pull request is requested, it also stops when the pull request's head would be `main`, `master`, or the pull request base branch itself (for example `develop` checked out with no branch name, when the remote's default branch is `develop`), when the pull request base cannot be determined, or when the history the remediation branch starts from (HEAD for a new branch, the branch itself for an existing one) holds a commit without the trailer that is not on the pull request base (for example a local branch, or a `main` with unpushed commits): the pull request would carry work remediation did not make, so the pull request tool would refuse after the commit.
- **No stash.** Remediation never stashes, drops a stash, discards, or overwrites the user's uncommitted changes. A new branch is created with `git checkout -b` from HEAD; the user's uncommitted changes stay in the working tree untouched. Switching to an existing branch requires a clean tree.
- **Manifest-only commits.** `commit_remediation_changes` stages only the run manifest's files, with explicit pathspecs, and only those whose current content digest equals the manifest's `after_digest`; a file edited after remediation wrote it is a conflict and is not committed. Ignored files are never staged. `add_all` does not exist.
- **Trailer.** Every remediation commit message carries `Darnit-Remediation-Run: <run_id>`. The response lists every committed file, and the commit is recorded in the manifest. Everything the commit tool reads that can fail is read before `git commit`, and the commit is recorded in the manifest right after it, before any other step; a failure after `git commit` is reported with the commit's id, never as "Nothing was committed".
- **Push.** `create_remediation_pr` pushes only the remediation branch, and refuses before pushing when that branch is the pull request base branch itself. Unless a base branch is passed, it targets the branch named by the `base` recorded in the run manifest; without a recorded base it resolves the base as at branch creation (the remote's default branch, then `main`, `master`). It checks and lists the branch's commits against the merge base of the branch and the base ref as it is now, so a branch rebased onto a newer base carries only its own commits; only when the recorded base ref cannot be resolved does it use the recorded `base_commit`. The branch must contain the run's commit, or a rebased copy of it with the same patch (`git cherry`); otherwise nothing is pushed.
- **Gates.** Commit and pull request steps run only when at least one outcome changed files (15.4).

#### Scenario: Unrelated work in progress
- **WHEN** the working tree has a modified tracked file, an untracked `.env`, and a stash, and remediation creates a branch, commits, and opens a pull request
- **THEN** the commit MUST contain exactly the manifest's files
- **AND** the modified file and `.env` MUST remain uncommitted and byte-identical, and the stash list MUST be unchanged

#### Scenario: Pull request after a rebase onto a newer base
- **WHEN** the remediation branch was created at C0, the base advanced by C1..C3 without the trailer, and the user rebased the branch onto it
- **THEN** `create_remediation_pr` MUST open the pull request against the recorded base's branch
- **AND** it MUST list only the remediation commits, not C1..C3

#### Scenario: Pull request from history that is not on the base
- **WHEN** remediation is asked to create a branch, commit, and open a pull request, and HEAD holds a commit without the trailer that is not on the pull request base
- **THEN** darnit MUST stop before applying any remediation or creating the branch, and explain why

#### Scenario: Unsafe repository state
- **WHEN** a git step is requested on a detached HEAD, during a merge or rebase, or with an existing branch holding a commit without the trailer
- **THEN** darnit MUST stop before changing anything and explain why

### 15.8 Entry Points

Every writer goes through the executor, the platform engine, and the run manifest; there is no second write path.

| Entry point | Behavior |
|-------------|----------|
| `remediate_audit_findings` | `dry_run = True` by default (preview); `approve: list[str] \| None` carries approved digests; returns the run id and the `RemediationRun` (15.4) |
| `enable_branch_protection` | Thin wrapper over the platform engine (section 4.5); `dry_run = True`, `branch = None`, `approve` |
| `create_remediation_branch`, `commit_remediation_changes`, `create_remediation_pr` | `run_id`; rules of 15.7 |
| `remediate_community_spec` (darnit-csl) | `dry_run = True` by default; its README edit is a `FileChange` in the preview and the manifest; `approve` carries the digests of individually approved items (CSL-02.01 and CSL-03.01 are `safe = false` because they replace an existing document) |
| `create_security_policy` | Writes through the executor and the manifest; keeps its explicit-create semantics |
| `darnit run` | Previews by default; creates or changes files, or platform settings, only with `--apply` (FR-027). In an apply, platform changes follow the policy; under `prompt` with a terminal it asks on `/dev/tty`, otherwise the outcome is `needs_approval`. A plan item that requires individual approval (15.3) is shown on `/dev/tty` with its files (the full content of a created file; for a modified file, a unified diff of the current file against the resulting content, or the full resulting content when the current file cannot be read; never truncated, and escaped to printable ASCII, with lines split only at `\n`, every other line ending or separator (`\r`, form feed, `\x1c`, U+2028) shown escaped, and a missing final newline marked `\ No newline at end of file`, so a change only in whitespace or line endings is never an empty diff), commands, change sets, the reason it needs approval, and its `PlanItem.digest`, and runs only on the person's yes; with no terminal it ends as `needs_approval` |
| Skills (`darnit-remediate`, `darnit-comply`) | Show the preview with before/after fields, impact notes, and digests; pass back only the digests the person approved; never pass `dry_run = false` as a substitute for approval |

The `confirm_*` tools are unchanged; approvals are not confirmations. Audit results and the attestation predicate are unchanged.

#### Scenario: darnit run without --apply
- **WHEN** `darnit run` remediates failing controls and `--apply` is not given
- **THEN** no repository file, platform setting, or run manifest MUST change
- **AND** the output MUST list the planned changes and say that `--apply` writes them

#### Scenario: darnit run asks for an individually approved item
- **WHEN** `darnit run --apply` reaches a plan item that requires individual approval and a terminal is available
- **THEN** it MUST show the item and its digest on `/dev/tty` and run the control's remediation only if the person says yes
- **AND** an approved item MUST be recorded as an `Approval` (digest, by, at); a refusal, or no terminal, MUST leave the control `needs_approval` with nothing written

#### Scenario: A change only in line endings is shown
- **WHEN** a plan item that requires individual approval changes only line endings (CRLF to LF), the final newline, or a line separator character such as U+2028
- **THEN** the text shown on `/dev/tty` MUST show that change, escaped

#### Scenario: A change deep in a modified file is shown
- **WHEN** a plan item that requires individual approval modifies a long file (for example one line deep in an 80-line workflow)
- **THEN** the text shown on `/dev/tty` MUST include that changed line

## Appendix C: Removed Requirements

The following requirements have been superseded: by the handler dispatch architecture, by the feature 043 remediation design (the `api_call` and `requires_confirmation` entries), and by the operator configuration and trust boundary (the last entry, Section 14).

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

### Removed: api_call remediation handler
**Reason**: Feature 043. The handler read a field (`url`) the framework configuration never set, so every declared use errored; its payloads were full-object replacements that would have removed existing platform settings. A payload cannot express "change only what is needed without weakening anything".
**Migration**: Declare a requirement with `handler = "platform_setting"` (section 4.5). A platform change with no API (organization two-factor enforcement) becomes a `manual` remediation step.

#### Scenario: api_call declared
- **WHEN** a framework TOML declares a remediation handler `api_call`
- **THEN** loading MUST fail with an error naming `platform_setting`

### Removed: requires_confirmation, dry_run_supported, and dry_run_command
**Reason**: Feature 043. They were declared but never enforced (FR-025: a safety, confirmation, or preview property is enforced or absent).
**Migration**: Use `safe = false` instead of `requires_confirmation` (section 15.3). Previews come from plan mode (section 4.2); an exec remediation declares `effects = "working_tree"` and `offline = true` instead of a `dry_run_command` (section 4.4).

### Removed: Repository-level .baseline.toml
**Reason**: The audited repository is untrusted input (Section 14). Feature 040 deprecated the file and, for one release, read only its per-control status and reason as claims and its `extends` by registered name; it is now ignored entirely (Section 14.4).
**Migration**: Run `darnit config migrate [REPO]`: claims move to `.project/darnit.yaml`, and the printed fragment goes into operator configuration after review. Select the framework with `--framework`.

#### Scenario: Repository still has .baseline.toml
- **WHEN** an audited repository contains `.baseline.toml`
- **THEN** no key in it MUST affect the audit
- **AND** the audit MUST report one notice pointing at `darnit config migrate`

---

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0-alpha.12 | 2026-10-04 | Repository-level `.baseline.toml` is no longer read: one notice points at `darnit config migrate`, framework selection only by `--framework` or a tool argument (Sections 2.3, 10.5, 14.4, 15.1; Appendix C) |
| 1.0.0-alpha.11 | 2026-10-04 | Close remaining false-PASS paths (feature 044): an expression that cannot be evaluated or is not boolean makes the step ERROR, expression names per step type with usable `project` values and a repository-aware `file_exists`, load-time expression reference check (Section 3.7); step registration declares `settings` and `expression_names`, plugins cannot replace a registered step type, and unknown control keys, unknown step keys, and unregistered step types fail loading (Sections 2.3, 3.0.3); reproducibility step types conclude only FAIL (Sections 3.0.1, 12); `expr_decides`, an expression that decides on a handler PASS (Sections 3.0.3, 3.7); `gh_api` `evidence_fields`, required for personal records (Section 3.8); `file_must_exist` replaced by the registered `file_exists` (Section 3.2); field tables corrected to what each handler reads (Sections 3.3-3.5) |
| 1.0.0-alpha.10 | 2026-10-02 | Remediation safety (feature 043): plan/apply protocol and single writer (Section 4.2), `platform_setting` (4.5), exec `effects`/`offline` and no platform state from exec (4.4), `file_create.project_reference` (4.3), remediation policy, digest-bound approval, outcomes, re-check, run manifest, and version-control rules (Section 15); removed `api_call`, `requires_confirmation`, `dry_run_supported`, `dry_run_command` (Appendix C) |
| 1.0.0-alpha.9 | 2026-09-29 | Context value standing, confirmation records, lapse, detection fallbacks, canonical keys, reads never write, targeted project-file writes, confirmation tool contract (Sections 7.4-7.11, feature 042) |
| 1.0.0-alpha.8 | 2026-02-16 | Added audit result cache (Section 10.4): audit writes cache, remediate reads cache, post-remediation invalidation |
| 1.0.0-alpha.7 | 2026-02-13 | Migrated to handler dispatch architecture: pass classes replaced by named handlers, passes use TOML array-of-tables syntax, register_controls() becomes no-op, removed legacy pass classes (Appendix C) |
| 1.0.0-alpha.5 | 2026-02-08 | Added locator integration (Section 11), handler registry (Section 12) |
| 1.0.0-alpha.4 | 2026-02-07 | Added framework purity requirements (Section 10.5), report parameterization |
| 1.0.0-alpha.3 | 2026-02-06 | Added audit pipeline requirements (Section 10) |
| 1.0.0-alpha.2 | 2026-02-05 | Added CEL expressions, handler registration, Sigstore verification |
| 1.0.0-alpha | 2026-02-04 | Initial authoritative specification |
