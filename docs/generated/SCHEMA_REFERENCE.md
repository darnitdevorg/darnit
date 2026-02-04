# Darnit TOML Schema Reference

> Generated from framework specification
> Spec Version: Unknown

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

# See Section 3: Built-in Pass Types



# Remediation configuration

[controls."OSPS-AC-03.01".remediation]

# See Section 4: Built-in Remediation Actions

```

### 2.3 Schema Requirements



## 3. Built-in Pass Types

The sieve orchestrator executes passes in order, stopping at the first conclusive result.

### 3.1 Pass Execution Order

```
DETERMINISTIC → EXEC → PATTERN → LLM → MANUAL
     ↓            ↓        ↓       ↓       ↓
  Exact checks  External  Regex  AI eval  Human
  (high conf)   commands  match           review
```

### 3.2 DeterministicPass

**Phase**: DETERMINISTIC
**Purpose**: High-confidence checks with binary outcomes

*[This section provides an explanation of the feature described above.
The explanation is limited to approximately 150 words and covers
common use cases and best practices.]*

The deterministic pass handles checks that can be resolved with certainty: file existence, API boolean values, and configuration lookups. These require no interpretation.


**TOML Schema**:
```toml
[controls."EXAMPLE".passes.deterministic]
file_must_exist = ["SECURITY.md", ".github/SECURITY.md"]
file_must_not_exist = [".env", "credentials.json"]
api_check = "darnit_baseline.checks:check_branch_protection"
config_check = "darnit_baseline.checks:check_project_config"
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `file_must_exist` | `list[str]` | Paths/globs where ANY match passes |
| `file_must_not_exist` | `list[str]` | Paths/globs where ANY match fails |
| `api_check` | `str` | Python function reference `module:function` |
| `config_check` | `str` | Python function reference `module:function` |

**Behavior**:
1. If `api_check` is defined and returns PASS/FAIL → return result
2. If `config_check` is defined and returns PASS/FAIL → return result
3. If `file_must_exist` matches → PASS
4. If `file_must_exist` defined but no match → FAIL
5. If `file_must_not_exist` matches → FAIL
6. Otherwise → INCONCLUSIVE (continue to next pass)

<!-- llm:example control_type=security -->

### 3.3 ExecPass

**Phase**: DETERMINISTIC
**Purpose**: Execute external commands for verification

*[This section provides an explanation of the feature described above.
The explanation is limited to approximately 150 words and covers
common use cases and best practices.]*

The exec pass runs external tools like trivy, scorecard, or kusari, evaluating results based on exit codes or output patterns. This enables integration with the security tooling ecosystem.


**TOML Schema**:
```toml
[controls."EXAMPLE".passes.exec]
command = ["kusari", "repo", "scan", "$PATH", "HEAD"]
pass_exit_codes = [0]
fail_exit_codes = [1]
output_format = "json"
pass_if_output_matches = "No issues found"
fail_if_output_matches = "Flagged Issues Detected"
pass_if_json_path = "$.status"
pass_if_json_value = "pass"
timeout = 300
env = { "TOOL_VERBOSE" = "true" }
```

**Fields**:

| Field | Type | Description |
|-------|------|-------------|
| `command` | `list[str]` | Command and arguments (supports `$PATH`, `$OWNER`, `$REPO`, `$BRANCH`) |
| `pass_exit_codes` | `list[int]` | Exit codes that indicate PASS (default: `[0]`) |
| `fail_exit_codes` | `list[int]` | Exit codes that indicate FAIL |
| `output_format` | `str` | Output format: `text`, `json`, `sarif` |
| `pass_if_output_matches` | `str` | Regex pattern - if matches stdout → PASS |
| `fail_if_output_matches` | `str` | Regex pattern - if matches stdout → FAIL |
| `pass_if_json_path` | `str` | JSONPath to extract value |
| `pass_if_json_value` | `str` | Expected value at JSON path for PASS |
| `timeout` | `int` | Timeout in seconds (default: 300) |
| `env` | `dict` | Additional environment variables |

**Security**:
- Commands are executed as a list (no shell interpolation)
- Variable substitution only replaces whole tokens or substrings safely
- Only whitelisted module prefixes can be imported

### 3.4 PatternPass

**Phase**: PATTERN
**Purpose**: Regex-based content analysis

*[This section provides an explanation of the feature described above.
The explanation is limited to approximately 150 words and covers
common use cases and best practices.]*

The pattern pass searches file contents for regex patterns, useful for detecting policy presence, configuration values, or code patterns without full semantic understanding.


**TOML Schema**:
```toml
[controls."EXAMPLE".passes.pattern]
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
| `files` | `list[str]` | File patterns to search |
| `patterns` | `dict[str, str]` | Named patterns (name → regex) |
| `pass_if_any` | `bool` | PASS if any pattern matches (default: true) |
| `fail_if_no_match` | `bool` | FAIL instead of INCONCLUSIVE on no match |

### 3.5 LLMPass

**Phase**: LLM
**Purpose**: AI-assisted verification for ambiguous cases

*[This section provides an explanation of the feature described above.
The explanation is limited to approximately 150 words and covers
common use cases and best practices.]*

The LLM pass delegates to an AI model for semantic understanding: evaluating policy quality, assessing documentation completeness, or interpreting context-dependent requirements.


**TOML Schema**:
```toml
[controls."EXAMPLE".passes.llm]
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
| `prompt` | `str` | Inline prompt template |
| `prompt_file` | `str` | Path to prompt file (alternative to inline) |
| `files_to_include` | `list[str]` | Files to include in LLM context |
| `analysis_hints` | `list[str]` | Hints to guide analysis |
| `confidence_threshold` | `float` | Minimum confidence for conclusive result (default: 0.8) |

### 3.6 ManualPass

**Phase**: MANUAL
**Purpose**: Fallback for human verification

*[This section provides an explanation of the feature described above.
The explanation is limited to approximately 100 words and covers
common use cases and best practices.]*

The manual pass always returns INCONCLUSIVE (resulting in WARN status), providing verification steps for human reviewers. This is the safety net when automated verification cannot determine compliance.


**TOML Schema**:
```toml
[controls."EXAMPLE".passes.manual]
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
| `steps` | `list[str]` | Verification steps for human reviewer |
| `docs_url` | `str` | Link to verification documentation |

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

Templates support variable substitution:

```toml
[templates.security_policy_standard]
description = "Standard SECURITY.md template"
content = """

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

