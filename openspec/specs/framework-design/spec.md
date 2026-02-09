# Darnit Framework Design Specification

> **Version**: 1.0.0-alpha
> **Status**: Authoritative
> **Last Updated**: 2026-02-04

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

# Verification passes
[controls."OSPS-AC-03.01".passes]
# See Section 3: Built-in Pass Types

# Remediation configuration
[controls."OSPS-AC-03.01".remediation]
# See Section 4: Built-in Remediation Actions
```

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

<!-- llm:explain max_words=150 -->
The deterministic pass handles checks that can be resolved with certainty: file existence, API boolean values, and configuration lookups. These require no interpretation.
<!-- /llm:explain -->

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

<!-- llm:explain max_words=150 -->
The exec pass runs external tools like trivy, scorecard, or kusari, evaluating results based on exit codes or output patterns. This enables integration with the security tooling ecosystem.
<!-- /llm:explain -->

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
| `expr` | `str` | CEL expression for pass logic (see Section 3.7) |
| `timeout` | `int` | Timeout in seconds (default: 300) |
| `env` | `dict` | Additional environment variables |

**Security**:
- Commands are executed as a list (no shell interpolation)
- Variable substitution only replaces whole tokens or substrings safely
- Only whitelisted module prefixes can be imported

### 3.4 PatternPass

**Phase**: PATTERN
**Purpose**: Regex-based content analysis

<!-- llm:explain max_words=150 -->
The pattern pass searches file contents for regex patterns, useful for detecting policy presence, configuration values, or code patterns without full semantic understanding.
<!-- /llm:explain -->

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

<!-- llm:explain max_words=150 -->
The LLM pass delegates to an AI model for semantic understanding: evaluating policy quality, assessing documentation completeness, or interpreting context-dependent requirements.
<!-- /llm:explain -->

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

<!-- llm:explain max_words=100 -->
The manual pass always returns INCONCLUSIVE (resulting in WARN status), providing verification steps for human reviewers. This is the safety net when automated verification cannot determine compliance.
<!-- /llm:explain -->

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

### 3.7 CEL Expressions

Pass types support Common Expression Language (CEL) for flexible result evaluation.

**Purpose**: Replace multiple `pass_if_*` fields with a single declarative expression.

**TOML Schema**:
```toml
[controls."EXAMPLE".passes.deterministic]
exec = { command = "gh api /orgs/{org}/settings" }
expr = 'response.two_factor_requirement_enabled == true'

[controls."EXAMPLE2".passes.exec]
command = ["kusari", "scan"]
output_format = "json"
expr = 'output.json.status == "pass" && size(output.json.issues) == 0'
```

**Context Variables**:

| Variable | Pass Type | Description |
|----------|-----------|-------------|
| `output.stdout` | exec | Command stdout |
| `output.stderr` | exec | Command stderr |
| `output.exit_code` | exec | Command exit code |
| `output.json` | exec | Parsed JSON from stdout (if `output_format = "json"`) |
| `response.status_code` | api_check | HTTP status code |
| `response.body` | api_check | Response body |
| `response.headers` | api_check | Response headers |
| `files` | pattern | List of matched file paths |
| `matches` | pattern | Dict of pattern name → match results |
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
# Security Policy

## Reporting a Vulnerability

Please report security vulnerabilities to security@$OWNER.github.io
or use GitHub's "Report a vulnerability" feature.

### Response Timeline
- **Initial Response**: Within 48 hours
- **Status Update**: Within 7 days
- **Resolution Target**: Within 90 days
"""
```

**Variables**:

| Variable | Description |
|----------|-------------|
| `$OWNER` | Repository owner |
| `$REPO` | Repository name |
| `$BRANCH` | Default branch |
| `$YEAR` | Current year |
| `$DATE` | Current date (ISO format) |
| `$MAINTAINERS` | Detected maintainers (if available) |

**Variable Resolution**: `$OWNER`, `$REPO`, and `$BRANCH` MUST be resolved
using `detect_repo_from_git()` from `darnit.core.utils` — the canonical repo
identity detector. This function prefers the `upstream` git remote over
`origin` so that audits on forks evaluate the upstream project. No other
module SHALL implement repo identity detection logic (parsing git remotes,
calling `gh repo view`, etc.).

---

## 5. Sieve Orchestrator

### 5.1 Execution Model

The orchestrator runs passes sequentially, stopping at first conclusive result:

```python
for pass in control.passes:
    result = pass.execute(context)

    if result.outcome == PASS:
        return SieveResult(status="PASS", ...)
    elif result.outcome == FAIL:
        return SieveResult(status="FAIL", ...)
    elif result.outcome == ERROR:
        return SieveResult(status="ERROR", ...)
    # INCONCLUSIVE → continue to next pass

# All passes inconclusive
return SieveResult(status="WARN", verification_steps=manual_steps)
```

### 5.2 Result Statuses

| Status | Description | Conclusive |
|--------|-------------|------------|
| `PASS` | Control verified compliant | Yes |
| `FAIL` | Control verified non-compliant | Yes |
| `ERROR` | Check execution failed | Yes |
| `WARN` | Manual verification required | No |
| `PENDING_LLM` | Awaiting LLM consultation | No |

### 5.3 Evidence Accumulation

Evidence from each pass accumulates and is available to subsequent passes:

```python
context.gathered_evidence["api_check_result"] = {...}
context.gathered_evidence["file_found"] = "/path/to/SECURITY.md"
```

### 5.4 LLM Consultation Protocol

When an LLM pass is reached and `stop_on_llm=True`:

1. Orchestrator returns `PENDING_LLM` with consultation request
2. Calling LLM analyzes and returns `LLMConsultationResponse`
3. Orchestrator continues with `verify_with_llm_response()`

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
        # Register Python-defined controls with sieve
        ...

    def register_handlers(self) -> None:
        # Register MCP tool handlers with registry
        ...
```

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

Plugins can be verified using Sigstore-based attestations:

```toml
# .baseline.toml
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
```

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

[controls."OSPS-AC-03.01".passes]
deterministic = { api_check = "darnit_baseline.checks:check_branch_protection" }
manual = { steps = ["Verify branch protection in repository settings"] }

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

### 10.4 Framework Contains No Implementation-Specific Code

The darnit framework package SHALL NOT contain code, modules, or string literals specific to any particular compliance implementation.

#### Requirement: No OSPS control IDs in framework
- **WHEN** the `packages/darnit/src/darnit/` source tree is searched
- **THEN** no hardcoded OSPS control ID patterns (e.g., `OSPS-AC-03.01`) SHALL exist in executable code

#### Requirement: No attestation or threat model modules in framework
- **WHEN** the `packages/darnit/src/darnit/` directory listing is checked
- **THEN** `attestation/` and `threat_model/` directories SHALL NOT exist
- **AND** these modules SHALL reside in the implementation package

#### Requirement: No hardcoded implementation preference in discovery
- **WHEN** `get_default_implementation()` is called
- **THEN** it SHALL return the first discovered implementation
- **AND** SHALL NOT hardcode a preference for any specific implementation name

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
- `${context.<key>}` — resolves to confirmed context values from `.project/project.yaml`
- `${project.<dotted.path>}` — resolves to project configuration values

Unresolved references SHALL be replaced with an empty string and logged at debug level.

### 11.4 Context Informs But Never Overrides Verification

Project context from `.project/` SHALL be used to inform WHERE the sieve looks for evidence (via `locator.project_path`), but SHALL NOT determine WHETHER a control passes. Even when context indicates a file exists, the sieve SHALL still verify through its normal handler pipeline.

## 12. Handler Registry

The framework SHALL provide a handler registry where handlers are registered by name with a phase affinity. Core SHALL register built-in handlers: `file_exists`, `exec`, `regex`, `llm_eval`, `manual_steps`, `file_create`, `api_call`, `project_update`. Implementations SHALL register domain-specific handlers via the existing `ComplianceImplementation.register_handlers()` method.

A handler used in a phase different from its registered affinity SHALL trigger a warning but still execute.

## Version History

| Version | Date | Changes |
|---------|------|---------|
| 1.0.0-alpha.5 | 2026-02-08 | Added locator integration (Section 11), handler registry (Section 12) |
| 1.0.0-alpha.4 | 2026-02-07 | Added framework purity requirements (Section 10.4), report parameterization |
| 1.0.0-alpha.3 | 2026-02-06 | Added audit pipeline requirements (Section 10) |
| 1.0.0-alpha.2 | 2026-02-05 | Added CEL expressions, handler registration, Sigstore verification |
| 1.0.0-alpha | 2026-02-04 | Initial authoritative specification |
