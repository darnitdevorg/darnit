# Darnit TOML Schema Reference

> Generated from framework specification
> Spec Version: 1.0.0-alpha.8

This document provides a complete reference for the TOML configuration schema
used to define controls, passes, and remediations.

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

### 2.2 Control Definition

Each control is defined under `[controls."CONTROL-ID"]`:

```toml
[controls."OSPS-AC-03.01"]

# Remediation configuration

[controls."OSPS-AC-03.01".remediation]

# See Section 4: Built-in Remediation Actions

```

#### Scenario: Passes defined as ordered array

- **WHEN** a control defines verification passes
- **THEN** they MUST be declared as a TOML array of tables using `[[controls."ID".passes]]`
- **AND** each entry MUST have a `handler` field naming the handler to dispatch to
- **AND** the orchestrator MUST execute passes in declaration order

### 2.3 Schema Requirements



## 3. Built-in Pass Types

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
| `confidence_threshold` | `float` | Minimum confidence for conclusive result (default: 0.8) |

**`files_to_include` resolution**: The handler MUST resolve `$FOUND_FILE` entries by looking up `found_file` in `context.gathered_evidence`. Each resolved file path MUST be read (up to 10KB per file, max 5 files) and included as `file_contents` in the `consultation_request`. File paths that are not absolute MUST be resolved relative to `context.local_path`. Files that cannot be read MUST be silently skipped.

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

---

### 9.1 Schema Validation

All TOML configs MUST validate against the framework schema:
- Required fields present
- Field types correct
- Pass configurations valid

#### Requirement: Remediation consumes cached audit results

- **WHEN** `remediate_audit_findings()` is called and `read_audit_cache()` returns valid cached results
- **THEN** it SHALL extract failed control IDs from the cached results (entries with `status == "FAIL"`)
- **AND** it SHALL NOT run a redundant audit
- **WHEN** `read_audit_cache()` returns `None` (cache miss)
- **THEN** it SHALL run the sieve audit as normal (existing behavior)
- **AND** it SHALL iterate all remediation categories, letting per-control filtering exclude categories where no controls failed

### Removed: VerificationPassProtocol

**Reason**: Replaced by handler dispatch architecture. Pass classes that implemented this protocol (`DeterministicPass`, `PatternPass`, `LLMPass`, `ManualPass`, `ExecPass`) are superseded by handler functions registered in `SieveHandlerRegistry`.
**Migration**: Define verification logic as handler functions matching `Callable[[dict, HandlerContext], HandlerResult]` and register via `SieveHandlerRegistry.register()`. Reference handlers by name in TOML `[[passes]]` entries.

### Removed: DeterministicPass api_check and config_check callable fields

**Reason**: The `api_check` and `config_check` fields referenced Python callables (`"module:function"` strings) for deterministic verification. This pattern is replaced by custom sieve handlers registered in `SieveHandlerRegistry`.
**Migration**: Convert `api_check`/`config_check` callables to handler functions and register them via `SieveHandlerRegistry.register()`. Reference by handler name in TOML.

#### Scenario: Python callable references removed from TOML schema

- **WHEN** a control needs Python-based verification logic
- **THEN** it MUST use a custom handler referenced by name (e.g., `handler = "my_custom_check"`)
- **AND** it MUST NOT use `api_check` or `config_check` fields with `"module:function"` references

#### Scenario: Pass classes unavailable for import

- **WHEN** plugin code attempts to import pass classes from `darnit.sieve.passes`
- **THEN** the import MUST raise `ImportError`
- **AND** the migration path MUST be documented in `IMPLEMENTATION_GUIDE.md`

