# Declarative Configuration System

The darnit declarative configuration system enables compliance frameworks to be defined via TOML configuration files rather than Python code. This allows:

- **Framework authors** to define compliance frameworks declaratively
- **Framework users** to customize controls for their specific needs
- **Extensibility** through pluggable adapters for check execution

## Architecture Overview

```
┌─────────────────────────────────────────────────────────────────┐
│  Framework Package (e.g., darnit-baseline, darnit-testchecks)   │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  {framework}.toml                                         │  │
│  │  - metadata (name, version, spec)                         │  │
│  │  - controls (id, level, domain, passes, remediation)      │  │
│  │  - adapters (builtin handlers)                            │  │
│  └───────────────────────────────────────────────────────────┘  │
│  + Python adapters for check execution                          │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  User Repository                                                 │
│  ┌───────────────────────────────────────────────────────────┐  │
│  │  .baseline.toml                                           │  │
│  │  - extends = "framework-name"                             │  │
│  │  - control overrides (status, adapter, config)            │  │
│  │  - custom adapters                                        │  │
│  └───────────────────────────────────────────────────────────┘  │
└─────────────────────────────────────────────────────────────────┘
                              ↓
┌─────────────────────────────────────────────────────────────────┐
│  Effective Configuration (Runtime)                               │
│  - All controls from framework                                   │
│  - User overrides applied                                        │
│  - Adapters resolved and ready                                   │
└─────────────────────────────────────────────────────────────────┘
```

## Framework Definition Format

Framework definitions are TOML files that declare controls, verification passes, and remediation actions.

### Basic Structure

```toml
# {framework-name}.toml

[metadata]
name = "my-framework"
display_name = "My Compliance Framework"
version = "1.0.0"
schema_version = "0.1.0-alpha"  # TOML config format version
spec_version = "v2025.1"
description = "Description of this framework"
url = "https://example.com/framework"

[defaults]
check_adapter = "builtin"
remediation_adapter = "builtin"

[adapters.builtin]
type = "python"
module = "my_framework.adapters.builtin"
class = "MyCheckAdapter"

[controls."CTRL-001"]
name = "ControlName"
description = "What this control checks"
tags = { level = 1, domain = "DOMAIN", security_severity = 7.5, tag1 = true, tag2 = true }
docs_url = "https://example.com/docs/CTRL-001"

[controls."CTRL-001".passes]
deterministic = { file_must_exist = ["README.md"] }

[controls."CTRL-001".remediation]
handler = "create_readme"
safe = true
```

> **Note**: The `tags` field is a flexible dictionary that can contain any key-value pairs.
> Standard keys like `level`, `domain`, and `security_severity` are extracted automatically
> for filtering and reporting. Boolean tags (e.g., `tag1 = true`) enable tag-based filtering.

### Metadata Section

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `name` | string | Yes | Unique identifier for the framework |
| `display_name` | string | Yes | Human-readable name |
| `version` | string | Yes | Semantic version of the framework |
| `schema_version` | string | No | TOML config format version (default: `"0.1.0-alpha"`) |
| `spec_version` | string | No | Version of the spec this implements |
| `description` | string | No | Brief description |
| `url` | string | No | Link to framework documentation |

> ⚠️ **Schema Version Notice**: The current schema version is `0.1.0-alpha`, indicating
> the TOML configuration format is in early development. Breaking changes may occur
> between minor versions. Framework authors should expect to update their TOML files
> as the schema evolves toward 1.0 stability.

### Defaults Section

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `check_adapter` | string | `"builtin"` | Default adapter for running checks |
| `remediation_adapter` | string | `"builtin"` | Default adapter for remediations |

### Templates Section

Templates define reusable content for remediation file creation. They support variable
substitution for dynamic content generation.

```toml
[templates.security_policy_standard]
description = "Standard SECURITY.md template"
content = """# Security Policy

## Reporting a Vulnerability

Please report security vulnerabilities by:
- Using GitHub's "Report a vulnerability" feature in the Security tab
- Or emailing security@$OWNER.github.io

We will respond within 48 hours.
"""

[templates.contributing_standard]
description = "Standard CONTRIBUTING.md template"
content = """# Contributing to $REPO

Thank you for your interest in contributing!

## Getting Started

1. Fork the repository
2. Clone your fork: `git clone https://github.com/YOUR-USERNAME/$REPO.git`
3. Create a branch: `git checkout -b feature/your-feature`
4. Make your changes and commit
5. Push and open a Pull Request
"""
```

**Template Parameters:**

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `content` | string | Yes* | Inline template content |
| `file` | string | Yes* | Path to external template file (alternative to content) |
| `description` | string | No | Description of the template's purpose |

*Either `content` or `file` is required.

**Variable Substitution:**

Templates support these variables (automatically replaced at runtime):

| Variable | Description | Example |
|----------|-------------|---------|
| `$OWNER` | Repository owner/organization | `myorg` |
| `$REPO` | Repository name | `myproject` |
| `$BRANCH` | Default branch name | `main` |
| `$PATH` | Local repository path | `/home/user/myproject` |
| `$YEAR` | Current year | `2025` |
| `$DATE` | Current date (ISO format) | `2025-01-23` |
| `$CONTROL` | Control ID being remediated | `OSPS-VM-02.01` |

**Using Templates in Remediation:**

```toml
[controls."OSPS-VM-02.01".remediation.file_create]
path = "SECURITY.md"
template = "security_policy_standard"    # References [templates.security_policy_standard]
overwrite = false
```

### Adapter Section

Adapters define how checks and remediations are executed.

```toml
[adapters.builtin]
type = "python"
module = "my_framework.adapters.builtin"
class = "MyCheckAdapter"

[adapters.kusari]
type = "command"
command = "kusari"
output_format = "json"

[adapters.custom_script]
type = "script"
command = "./scripts/check.sh"
output_format = "json"
```

| Adapter Type | Description |
|--------------|-------------|
| `python` | Python module with CheckAdapter class |
| `command` | External CLI tool |
| `script` | Shell script |

> **Security Note**: Python adapter modules are validated against a whitelist before loading.
> Only modules with these prefixes can be loaded: `darnit.*`, `darnit_baseline.*`, `darnit_plugins.*`, `darnit_testchecks.*`.
> To use custom adapters, name your package with the `darnit_` prefix (e.g., `darnit_mycompany`).
> See [SECURITY_GUIDE.md](SECURITY_GUIDE.md) for details.

### Control Section

Each control is defined under `[controls."CONTROL-ID"]`:

```toml
[controls."CTRL-001"]
name = "ControlName"           # Required: Human-readable name
description = "..."            # Required: What this control checks
tags = { level = 1, domain = "SEC", security_severity = 7.5, security = true }
docs_url = "https://..."       # Optional: Link to documentation
```

#### Tags Schema

The `tags` field is a flexible dictionary (`Dict[str, Any]`) that supports:

| Key | Type | Description |
|-----|------|-------------|
| `level` | int | Maturity level (1, 2, or 3) - used for filtering |
| `domain` | string | Domain code (e.g., "AC", "VM", "SEC") - used for filtering |
| `security_severity` | float | CVSS-like severity score (0.0-10.0) |
| `<custom>` | bool/any | Custom tags for categorization (e.g., `security = true`) |

**Tag-based filtering examples:**
- `level=1` - Filter by maturity level
- `domain=AC` - Filter by domain
- `severity>=7.0` - Filter by security severity
- `security` - Filter controls with `security = true` tag

> **Backward Compatibility**: For compatibility, `level`, `domain`, and `security_severity`
> can also be specified as top-level fields. When present in both locations, top-level
> values take precedence.

### Locator Section

Locators define where to find evidence that satisfies a control. This enables the
system to check user-provided configuration (`.project.yaml`) before falling back
to discovery patterns.

```toml
[controls."OSPS-VM-02.01".locator]
project_path = "security.policy"          # Path in .project.yaml
kind = "file"                             # Evidence type: file, url, api, config
check_files = ["SECURITY.md", "docs/SECURITY.md", ".github/SECURITY.md"]
look_for_urls = true                      # Also check for URL references

[controls."OSPS-VM-02.01".locator.discover]
# Discovery patterns if not in .project.yaml
patterns = ["SECURITY*", "**/SECURITY*"]

[controls."OSPS-VM-02.01".locator.llm_hints]
# Hints for LLM-assisted evidence finding
search_terms = ["security policy", "vulnerability reporting"]
file_patterns = ["*.md", "docs/**"]
```

**Locator Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `project_path` | string | `null` | Dot-notation path in `.project.yaml` (e.g., `security.policy`) |
| `kind` | string | `"file"` | Evidence type: `"file"`, `"url"`, `"api"`, `"config"` |
| `check_files` | list | `[]` | Files to check for evidence |
| `look_for_urls` | bool | `false` | Whether to look for URL references in content |
| `discover` | list | `[]` | Glob patterns for discovery if not in project config |

**Evidence Kinds:**

| Kind | Description | Example |
|------|-------------|---------|
| `file` | Local file in repository | `SECURITY.md` |
| `url` | External URL reference | `https://example.com/security` |
| `api` | API endpoint or configuration | GitHub branch protection settings |
| `config` | Configuration file setting | `.github/dependabot.yml` |

**LLM Hints (for ambiguous cases):**

When automatic discovery fails, LLM hints guide AI-assisted evidence finding:

```toml
[controls."OSPS-GV-01.01".locator.llm_hints]
search_terms = ["maintainer", "governance", "project lead"]
file_patterns = ["*.md", "GOVERNANCE*", "MAINTAINERS*"]
context = "Look for documentation that identifies project maintainers"
```

### Verification Passes

Controls define verification passes that determine compliance:

#### Deterministic Pass

Fast, definitive checks for file existence or absence. These run first and provide
immediate PASS/FAIL results without ambiguity.

```toml
[controls."CTRL-001".passes]
# Check if any of these files exist (PASS if any found)
deterministic = { file_must_exist = [
    "README.md",
    "README.rst",
    "README.txt",
]}

# Check that certain files do NOT exist (PASS if none found)
[controls."CTRL-002".passes]
deterministic = { file_must_not_exist = [
    ".env",
    "secrets.json",
    "credentials.json",
]}

# Combine both checks
[controls."CTRL-003".passes]
deterministic = {
    file_must_exist = ["LICENSE"],
    file_must_not_exist = ["LICENSE.proprietary"]
}
```

**Deterministic Pass Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `file_must_exist` | list | `null` | Glob patterns - PASS if ANY file matches |
| `file_must_not_exist` | list | `null` | Glob patterns - PASS if NO files match |
| `api_check` | string | `null` | Function reference for API-based checks |
| `config_check` | string | `null` | Function reference for config-based checks |

**Glob Pattern Support:**

File patterns support standard glob syntax:
- `README.md` - Exact filename
- `*.md` - Any markdown file in root
- `**/*.yml` - Any YAML file in any directory
- `docs/SECURITY*` - Files starting with SECURITY in docs/

**Evaluation Logic:**

1. If `file_must_exist` is set: PASS if **any** pattern matches a file
2. If `file_must_not_exist` is set: PASS if **no** patterns match any file
3. Both can be combined (both conditions must be satisfied)

#### Pattern Pass

Search for regex patterns within file contents. Useful for detecting required content
or forbidden patterns (like hardcoded secrets).

```toml
# Detect forbidden patterns (secrets) - PASS if NOT found
[controls."CTRL-002".passes.pattern]
files = ["**/*.py", "**/*.js", "**/*.ts"]
pass_if_any = false                        # PASS if patterns are NOT found
fail_if_no_match = false

[controls."CTRL-002".passes.pattern.patterns]
aws_key = "AKIA[0-9A-Z]{16}"
private_key = "-----BEGIN (RSA |EC )?PRIVATE KEY-----"
api_token = "(api[_-]?key|api[_-]?token)\\s*[=:]\\s*['\"][a-zA-Z0-9]{20,}"

# Detect required patterns - PASS if found
[controls."CTRL-003".passes.pattern]
files = [".github/workflows/*.yml"]
pass_if_any = true                         # PASS if ANY pattern is found

[controls."CTRL-003".passes.pattern.patterns]
ci_test_step = "run:.*test"
ci_lint_step = "run:.*lint"
```

**Pattern Pass Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `files` | list | `null` | Glob patterns for files to search |
| `patterns` | dict | `null` | Named regex patterns (`name = "regex"`) |
| `pass_if_any` | bool | `true` | If true, PASS when pattern found; if false, PASS when NOT found |
| `fail_if_no_match` | bool | `false` | FAIL if no files match the file patterns |
| `custom_analyzer` | string | `null` | Function reference for custom analysis |

**Pattern Pass Modes:**

| Mode | `pass_if_any` | Use Case | Example |
|------|---------------|----------|---------|
| Detect required content | `true` | Verify CI/CD has test steps | PASS if test step found |
| Detect forbidden content | `false` | Find hardcoded secrets | PASS if NO secrets found |

**Regex Syntax:**

Patterns use Python regex syntax. Remember to escape backslashes in TOML:
- `\\s` for whitespace
- `\\d` for digits
- `\\w` for word characters

#### Exec Pass

Execute external commands and evaluate results. This enables integration with external
tools like `gh` CLI, `trivy`, `scorecard`, `kusari`, etc.

```toml
[controls."CTRL-004".passes.exec]
command = ["gh", "api", "/repos/$OWNER/$REPO/branches/$BRANCH/protection"]
pass_exit_codes = [0]
fail_exit_codes = [1]
output_format = "json"
timeout = 30
```

**Exec Pass Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `command` | list | required | Command as list of arguments (secure, no shell interpolation) |
| `pass_exit_codes` | list | `[0]` | Exit codes that indicate PASS |
| `fail_exit_codes` | list | `null` | Exit codes that indicate FAIL (others = inconclusive) |
| `output_format` | string | `"text"` | Output format: `"json"`, `"text"`, or `"sarif"` |
| `timeout` | int | `300` | Timeout in seconds |
| `cwd` | string | repo path | Working directory |
| `env` | dict | `{}` | Environment variables to set |
| `pass_if_output_matches` | string | `null` | Regex pattern - PASS if stdout matches |
| `fail_if_output_matches` | string | `null` | Regex pattern - FAIL if stdout matches |
| `pass_if_json_path` | string | `null` | JSON path to extract value from output |
| `pass_if_json_value` | string | `null` | Expected value at JSON path (string comparison) |

**Variable Substitution in Commands:**

Commands support these variables (substituted as whole list elements):
- `$OWNER` - Repository owner/organization
- `$REPO` - Repository name
- `$BRANCH` - Default branch name
- `$PATH` - Local repository path

**JSON Output Evaluation:**

When `output_format = "json"`, you can extract and check values from the JSON response:

```toml
[controls."OSPS-AC-01.01".passes.exec]
command = ["gh", "api", "/orgs/$OWNER"]
pass_exit_codes = [0]
fail_exit_codes = [1]
output_format = "json"
pass_if_json_path = "two_factor_requirement_enabled"
pass_if_json_value = "true"
timeout = 30
```

**JSON Path Syntax (Current):**

The current implementation supports **simple dot-notation paths only**:

```toml
# Supported paths:
pass_if_json_path = "status"                      # Top-level key
pass_if_json_path = "checks.BranchProtection"     # Nested keys
pass_if_json_path = "results.0.score"             # Array index
pass_if_json_path = "$.data.enabled"              # With optional $. prefix
```

**Current Limitations:**

> ⚠️ **Note**: The current JSON evaluation is intentionally simple. More powerful
> policy expressions are planned for a future release.

Current limitations:
- **Single value only**: `pass_if_json_value` checks one value (no OR logic)
- **String comparison**: Values are compared as strings (`"true"` not `true`)
- **No operators**: No support for `>`, `<`, `>=`, `contains`, etc.
- **No wildcards**: No `[*]` array wildcards or `..` recursive descent
- **No filters**: No JSONPath filter expressions like `[?(@.score>80)]`

**Examples:**

```toml
# Check branch protection exists
[controls."OSPS-AC-03.01".passes.exec]
command = ["gh", "api", "/repos/$OWNER/$REPO/branches/$BRANCH/protection"]
pass_exit_codes = [0]
fail_exit_codes = [1]
output_format = "json"
pass_if_json_path = "required_pull_request_reviews"
timeout = 30

# Check for specific boolean value
[controls."OSPS-AC-01.01".passes.exec]
command = ["gh", "api", "/orgs/$OWNER"]
output_format = "json"
pass_if_json_path = "two_factor_requirement_enabled"
pass_if_json_value = "true"

# Check text output with regex
[controls."OSPS-QA-01.01".passes.exec]
command = ["gh", "workflow", "list", "--repo", "$OWNER/$REPO"]
output_format = "text"
pass_if_output_matches = "^.+\\s+active\\s+"
```

**Evaluation Order:**

1. `fail_if_output_matches` (if set, checked first)
2. `pass_if_output_matches` (if set)
3. `pass_if_json_path` + `pass_if_json_value` (if JSON format)
4. Exit code evaluation (`pass_exit_codes` / `fail_exit_codes`)

**Future Enhancements (Roadmap):**

Future versions will add more powerful policy evaluation:

```toml
# PLANNED - Not yet implemented
[controls."EXAMPLE".passes.exec]
command = ["scorecard", "--format", "json", "--repo", "$OWNER/$REPO"]
output_format = "json"

# Future: Multiple acceptable values (OR logic)
pass_if_json_values = ["true", "enabled", "active"]

# Future: Numeric comparisons
pass_if_json_path = "score"
pass_if_json_gte = 7.0              # Greater than or equal

# Future: Full JSONPath with filters
pass_if_json_path = "$.checks[?(@.name=='BranchProtection')].score"
pass_if_json_gte = 8

# Future: Policy expressions (CEL or similar)
policy = "data.score >= 7.0 && data.checks.BranchProtection.pass == true"
```

#### LLM Pass

For controls requiring semantic analysis or judgment that can't be expressed as simple patterns.
LLM passes use AI to analyze file contents and make compliance determinations.

```toml
[controls."OSPS-GV-01.01".passes.llm]
prompt = """
Analyze the following files to determine if the project clearly identifies
its maintainers or governance structure.

Look for:
- Named maintainers with contact information
- Governance documentation
- CODEOWNERS file with actual GitHub usernames
- README sections about project leadership

Return PASS if maintainers are clearly identified, FAIL otherwise.
"""
files_to_include = ["README.md", "GOVERNANCE.md", "CODEOWNERS", "MAINTAINERS*"]
hints = ["maintainer", "governance", "owner", "lead"]
confidence_threshold = 0.8
```

**LLM Pass Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `prompt` | string | `null` | Inline prompt template for LLM analysis |
| `prompt_file` | string | `null` | Path to external prompt file (alternative to `prompt`) |
| `files_to_include` | list | `null` | Glob patterns for files to include in context |
| `hints` | list | `[]` | Keywords to guide LLM analysis (alias: `analysis_hints`) |
| `confidence_threshold` | float | `0.8` | Minimum confidence (0.0-1.0) for PASS determination |

**When to Use LLM Pass:**

- Semantic analysis requiring understanding of content meaning
- Subjective quality assessments (e.g., "documentation is sufficient")
- Complex pattern matching that can't be expressed in regex
- Controls requiring judgment across multiple files

**When NOT to Use LLM Pass:**

- Simple file existence checks → Use Deterministic Pass
- Pattern matching → Use Pattern Pass
- External tool integration → Use Exec Pass

> ⚠️ **Note**: LLM passes incur AI inference costs and are non-deterministic.
> Use deterministic checks when possible. LLM passes should be reserved for
> controls that truly require semantic understanding.

#### Manual Pass

For controls requiring human verification that cannot be automated:

```toml
[controls."CTRL-003".passes.manual]
steps = [
    "Navigate to Repository Settings → Security",
    "Verify MFA is enabled for all organization members",
    "Check that SSO is configured with your identity provider",
    "Confirm security alerts are enabled",
]
docs_url = "https://docs.github.com/en/organizations/keeping-your-organization-secure"
```

**Manual Pass Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `steps` | list | `[]` | Ordered verification steps for human reviewer (alias: `verification_steps`) |
| `docs_url` | string | `null` | Link to documentation for verification guidance (alias: `verification_docs_url`) |

**When to Use Manual Pass:**

- Controls requiring visual inspection of UI settings
- Verification of external systems not accessible via API
- Compliance checks requiring human judgment
- Audit procedures that must be performed by a person

**Best Practices:**

1. Write clear, actionable steps
2. Include specific UI paths (e.g., "Settings → Security → Authentication")
3. Provide documentation links when available
4. Keep step count reasonable (3-7 steps typically)

### Remediation Section

Define automated fixes for controls. Remediation supports multiple strategies:
- **handler**: Python function reference (for complex logic)
- **file_create**: Create files from templates
- **exec**: Execute external commands
- **api_call**: Make GitHub API calls

#### Basic Remediation Structure

```toml
[controls."CTRL-001".remediation]
handler = "create_readme"         # Python function name in adapter
safe = true                       # Safe to run without user confirmation
requires_api = false              # Requires API access (not just local files)
requires_confirmation = false     # Require explicit user confirmation
dry_run_supported = true          # Supports preview mode
```

**Common Remediation Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `adapter` | string | `"builtin"` | Adapter providing the handler function |
| `handler` | string | `null` | Python function name for remediation |
| `safe` | bool | `true` | Safe to auto-apply without confirmation |
| `requires_api` | bool | `false` | Requires external API access |
| `requires_confirmation` | bool | `false` | Require explicit user confirmation |
| `dry_run_supported` | bool | `true` | Supports preview/dry-run mode |
| `template` | string | `null` | Template name for content generation |
| `config` | dict | `{}` | Additional configuration for the handler |

#### File Create Remediation

Create files from templates with variable substitution. This is the most common
remediation type for creating documentation files.

```toml
[controls."OSPS-VM-02.01".remediation]
safe = true
dry_run_supported = true

[controls."OSPS-VM-02.01".remediation.file_create]
path = "SECURITY.md"
template = "security_policy_standard"    # References [templates.security_policy_standard]
overwrite = false                         # Don't overwrite existing files
create_dirs = true                        # Create parent directories if needed
```

**With inline content (instead of template):**

```toml
[controls."OSPS-DO-01.01".remediation.file_create]
path = "README.md"
content = """# $REPO

A project by $OWNER.

## Installation

See the documentation for installation instructions.
"""
overwrite = false
```

**File Create Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `path` | string | required | Target file path relative to repo root |
| `template` | string | `null` | Template name from `[templates.*]` section |
| `content` | string | `null` | Inline content (alternative to template) |
| `overwrite` | bool | `false` | Whether to overwrite existing files |
| `create_dirs` | bool | `true` | Create parent directories if they don't exist |

**Variable Substitution:**

Both templates and inline content support these variables:
- `$OWNER` - Repository owner/organization
- `$REPO` - Repository name
- `$BRANCH` - Default branch name
- `$PATH` - Local repository path
- `$YEAR` - Current year
- `$DATE` - Current date (ISO format)
- `$CONTROL` - Control ID being remediated

#### Exec Remediation

Execute external commands for remediation. Supports variable substitution and
stdin input from templates.

```toml
[controls."OSPS-QA-01.01".remediation.exec]
command = ["gh", "workflow", "enable", "--repo", "$OWNER/$REPO", "ci.yml"]
success_exit_codes = [0]
timeout = 60
```

**With stdin input:**

```toml
[controls."OSPS-AC-03.01".remediation.exec]
command = ["gh", "api", "-X", "PUT", "/repos/$OWNER/$REPO/branches/$BRANCH/protection", "--input", "-"]
stdin_template = "branch_protection_payload"    # References a template
success_exit_codes = [0]
timeout = 60
```

**Exec Remediation Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `command` | list | required | Command as list of arguments (no shell interpolation) |
| `stdin_template` | string | `null` | Template name for stdin input |
| `stdin` | string | `null` | Inline stdin content (alternative to template) |
| `success_exit_codes` | list | `[0]` | Exit codes indicating success |
| `timeout` | int | `300` | Timeout in seconds |
| `env` | dict | `{}` | Environment variables to set |

**Security Note:** Commands are passed as lists, never interpolated into
shell strings. Variables like `$OWNER` are substituted as whole list elements.

#### API Call Remediation

Convenience wrapper for GitHub API calls using the `gh` CLI. Simplifies common
API operations with automatic JSON payload handling.

```toml
[controls."OSPS-AC-03.01".remediation.api_call]
method = "PUT"
endpoint = "/repos/$OWNER/$REPO/branches/$BRANCH/protection"
payload = {
    enforce_admins = true,
    required_pull_request_reviews = { required_approving_review_count = 1 },
    required_status_checks = null,
    restrictions = null,
    allow_force_pushes = false,
    allow_deletions = false
}
```

**With payload template:**

```toml
[controls."OSPS-AC-03.02".remediation.api_call]
method = "PUT"
endpoint = "/repos/$OWNER/$REPO/branches/$BRANCH/protection"
payload_template = "branch_protection_strict"    # References a template
```

**API Call Parameters:**

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `method` | string | `"PUT"` | HTTP method (GET, POST, PUT, PATCH, DELETE) |
| `endpoint` | string | required | GitHub API endpoint (supports variable substitution) |
| `payload` | dict | `null` | Inline JSON payload |
| `payload_template` | string | `null` | Template name for JSON payload |
| `jq_filter` | string | `null` | JQ filter to apply to response |

**Supported Endpoints:**

The API call remediation works with any GitHub API endpoint:
- `/repos/$OWNER/$REPO/branches/$BRANCH/protection` - Branch protection
- `/repos/$OWNER/$REPO/vulnerability-alerts` - Security alerts
- `/repos/$OWNER/$REPO/automated-security-fixes` - Dependabot
- `/orgs/$OWNER/settings` - Organization settings

#### Combining Remediation Strategies

Controls can define multiple remediation approaches. The system tries them
in order: declarative types first, then falls back to Python handlers.

```toml
[controls."OSPS-VM-02.01".remediation]
handler = "create_security_policy"    # Python fallback
safe = true

# Declarative file creation (tried first)
[controls."OSPS-VM-02.01".remediation.file_create]
path = "SECURITY.md"
template = "security_policy_standard"
```

**Resolution Order:**

1. `file_create` - If defined, create file from template
2. `exec` - If defined, execute command
3. `api_call` - If defined, make API call
4. `handler` - Fall back to Python function

## User Configuration Format

Users customize framework behavior via `.baseline.toml` in their repository root.

### Basic Structure

```toml
# .baseline.toml
version = "1.0"
extends = "openssf-baseline"

[settings]
cache_results = true
cache_ttl = 300
timeout = 300

[controls."OSPS-AC-01.01"]
status = "n/a"
reason = "MFA handled at organization level"

[controls."OSPS-VM-05.02"]
check = { adapter = "kusari" }
```

### Settings Section

| Field | Type | Default | Description |
|-------|------|---------|-------------|
| `cache_results` | bool | `true` | Cache check results |
| `cache_ttl` | int | `300` | Cache time-to-live in seconds |
| `timeout` | int | `300` | Default operation timeout |
| `fail_on_error` | bool | `false` | Fail audit if any check errors |
| `parallel_checks` | bool | `true` | Run independent checks in parallel |
| `max_parallel` | int | `5` | Maximum parallel operations |

### Control Overrides

#### Marking Controls as Not Applicable

```toml
[controls."CTRL-001"]
status = "n/a"
reason = "This control doesn't apply because..."

[controls."CTRL-002"]
status = "disabled"
reason = "Temporarily disabled for migration"
```

**Status Values:**
- `n/a` - Control is not applicable to this project
- `disabled` - Control is explicitly disabled
- `enabled` - Control is explicitly enabled (default)

#### Using Different Adapters

```toml
# Use a different check adapter
[controls."OSPS-VM-05.02"]
check = { adapter = "kusari" }

# With additional configuration
[controls."OSPS-VM-05.02"]
check = { adapter = "kusari", config = { severity = "high" } }
```

#### Custom Adapter Definitions

```toml
[adapters.kusari]
type = "command"
command = "kusari"
output_format = "json"

[adapters.my_scanner]
type = "python"
module = "my_company.security.scanner"

[adapters.custom_script]
type = "script"
command = "./scripts/check-compliance.sh"
output_format = "json"
```

### Control Groups

Apply configuration to multiple controls at once:

```toml
[control_groups.vulnerability-scanning]
controls = ["OSPS-VM-05.02", "OSPS-VM-05.03"]
check = { adapter = "kusari" }
config = { severity_threshold = "medium" }
```

### Custom Controls

Define project-specific controls:

```toml
[controls."CUSTOM-SEC-01"]
name = "InternalSecurityReview"
description = "Require internal security review sign-off"
tags = { level = 1, domain = "SA", security = true, internal = true }
check = { adapter = "custom_script" }
```

## Configuration Merge Semantics

When framework and user configurations are merged:

1. **Scalar values**: User overrides framework
2. **Objects/dicts**: Deep merge (user keys override, framework keys preserved)
3. **Arrays/lists**: User replaces framework entirely
4. **Special keys**:
   - `status = "n/a"` → Marks control as not applicable
   - `check = {...}` → Replaces entire check configuration
   - `extends = "..."` → Specifies base framework

### Example Merge

```toml
# Framework: openssf-baseline.toml
[controls."OSPS-VM-05.02"]
name = "PreReleaseSCA"
tags = { level = 3, domain = "VM", security_severity = 6.0, dependency-scanning = true }
check = { adapter = "builtin", handler = "check_sca_workflow" }
remediation = { handler = "add_dependency_review" }

# User: .baseline.toml
[controls."OSPS-VM-05.02"]
check = { adapter = "kusari" }

# Effective (merged):
[controls."OSPS-VM-05.02"]
name = "PreReleaseSCA"                              # from framework
tags = { level = 3, domain = "VM", ... }            # from framework
check = { adapter = "kusari" }                       # user override
remediation = { handler = "add_dependency_review" }  # from framework
```

## Creating a Custom Framework

### 1. Package Structure

```
my-framework/
├── myframework.toml           # Framework definition
├── pyproject.toml             # Python package config
├── README.md
└── src/my_framework/
    ├── __init__.py            # Exports get_framework_path()
    └── adapters/
        ├── __init__.py
        └── builtin.py         # Check implementations
```

### 2. Framework Definition

Create `myframework.toml`:

```toml
[metadata]
name = "myframework"
display_name = "My Compliance Framework"
version = "1.0.0"
schema_version = "0.1.0-alpha"
description = "Custom compliance checks"

[defaults]
check_adapter = "builtin"

[adapters.builtin]
type = "python"
module = "my_framework.adapters.builtin"

[controls."MY-001"]
name = "HasReadme"
description = "Repository must have a README"
tags = { level = 1, domain = "DOC", documentation = true }

[controls."MY-001".passes]
deterministic = { file_must_exist = ["README.md", "README.rst"] }
```

### 3. Package Init

Create `src/my_framework/__init__.py`:

```python
from pathlib import Path

__version__ = "1.0.0"

def get_framework_path() -> Path:
    """Return path to framework TOML file."""
    return Path(__file__).parent.parent.parent / "myframework.toml"
```

### 4. Check Adapter

Create `src/my_framework/adapters/builtin.py`:

```python
from pathlib import Path
from typing import Any, Dict, List

from darnit.core.adapters import CheckAdapter
from darnit.core.models import AdapterCapability, CheckResult, CheckStatus


class MyCheckAdapter(CheckAdapter):
    """Check adapter for My Framework."""

    def name(self) -> str:
        return "myframework"

    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(
            control_ids={"MY-001", "MY-002"},
            supports_batch=True,
        )

    def check(
        self,
        control_id: str,
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any],
    ) -> CheckResult:
        if control_id == "MY-001":
            return self._check_readme(local_path)
        # ... other controls
        return CheckResult(
            control_id=control_id,
            status=CheckStatus.ERROR,
            message=f"Unknown control: {control_id}",
            level=1,
            source="myframework",
        )

    def _check_readme(self, local_path: str) -> CheckResult:
        repo = Path(local_path)
        for name in ["README.md", "README.rst", "README.txt"]:
            if (repo / name).exists():
                return CheckResult(
                    control_id="MY-001",
                    status=CheckStatus.PASS,
                    message=f"Found {name}",
                    level=1,
                    source="myframework",
                )
        return CheckResult(
            control_id="MY-001",
            status=CheckStatus.FAIL,
            message="No README found",
            level=1,
            source="myframework",
        )

    def check_batch(
        self,
        control_ids: List[str],
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any],
    ) -> List[CheckResult]:
        return [
            self.check(cid, owner, repo, local_path, config)
            for cid in control_ids
        ]
```

### 5. Package Configuration

Create `pyproject.toml`:

```toml
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[project]
name = "my-framework"
version = "1.0.0"
dependencies = ["darnit>=0.1.0"]

[project.entry-points."darnit.frameworks"]
myframework = "my_framework:get_framework_path"

[project.entry-points."darnit.adapters"]
myframework = "my_framework.adapters.builtin:MyCheckAdapter"
```

### 6. Usage

```python
from darnit.config.merger import load_framework_config, load_effective_config
from my_framework import get_framework_path
from my_framework.adapters import MyCheckAdapter

# Load framework
framework = load_framework_config(get_framework_path())
print(f"Loaded {len(framework.controls)} controls")

# Run checks
adapter = MyCheckAdapter()
result = adapter.check("MY-001", "", "", "/path/to/repo", {})
print(f"{result.control_id}: {result.status.value}")
```

## API Reference

### Loading Configuration

```python
from darnit.config.merger import (
    load_framework_config,
    load_user_config,
    load_effective_config,
    merge_configs,
)

# Load framework from TOML
framework = load_framework_config(Path("framework.toml"))

# Load user config from repository
user_config = load_user_config(Path("/path/to/repo"))

# Load and merge both
effective = load_effective_config(
    framework_path=Path("framework.toml"),
    repo_path=Path("/path/to/repo"),
)

# Or merge manually
effective = merge_configs(framework, user_config)
```

### Working with Effective Config

```python
# Get controls by level
level1_controls = effective.get_controls_by_level(1)

# Get controls by domain
security_controls = effective.get_controls_by_domain("SEC")

# Get excluded (n/a) controls with reasons
excluded = effective.get_excluded_controls()
for control_id, reason in excluded.items():
    print(f"{control_id}: {reason}")

# Check if control is applicable
ctrl = effective.controls["CTRL-001"]
if ctrl.is_applicable():
    # Run check
    pass
```

### Check Adapter Interface

```python
from darnit.core.adapters import CheckAdapter
from darnit.core.models import AdapterCapability, CheckResult, CheckStatus

class MyAdapter(CheckAdapter):
    def name(self) -> str:
        """Return adapter identifier."""
        return "myadapter"

    def capabilities(self) -> AdapterCapability:
        """Return supported controls and features."""
        return AdapterCapability(
            control_ids={"CTRL-001", "CTRL-002"},
            supports_batch=True,
        )

    def check(
        self,
        control_id: str,
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any],
    ) -> CheckResult:
        """Run check for a single control."""
        # Implementation
        return CheckResult(
            control_id=control_id,
            status=CheckStatus.PASS,
            message="Check passed",
            level=1,
            source=self.name(),
        )

    def check_batch(
        self,
        control_ids: List[str],
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any],
    ) -> List[CheckResult]:
        """Run checks for multiple controls."""
        return [self.check(cid, owner, repo, local_path, config) for cid in control_ids]
```

### Remediation Adapter Interface

```python
from darnit.core.adapters import RemediationAdapter
from darnit.core.models import RemediationResult

class MyRemediationAdapter(RemediationAdapter):
    def name(self) -> str:
        return "myadapter"

    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(
            control_ids={"CTRL-001"},
            supports_batch=False,
        )

    def remediate(
        self,
        control_id: str,
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any],
        dry_run: bool = True,
    ) -> RemediationResult:
        """Apply remediation for a control."""
        if dry_run:
            return RemediationResult(
                control_id=control_id,
                success=True,
                message="Would create README.md",
                changes_made=[],
                source=self.name(),
            )

        # Apply actual changes
        Path(local_path, "README.md").write_text("# Project\n")
        return RemediationResult(
            control_id=control_id,
            success=True,
            message="Created README.md",
            changes_made=["README.md"],
            source=self.name(),
        )
```

## Plugin System

The darnit plugin system enables cross-package adapter sharing. Any installed package can provide adapters that can be used by any framework.

### Entry Point Groups

| Entry Point Group | Purpose | Example |
|-------------------|---------|---------|
| `darnit.frameworks` | Framework TOML providers | `openssf-baseline = "darnit_baseline:get_framework_path"` |
| `darnit.check_adapters` | Check adapter classes | `kusari = "darnit_plugins.adapters.kusari:KusariCheckAdapter"` |
| `darnit.remediation_adapters` | Remediation adapter classes | `github-api = "darnit_plugins.adapters:GitHubRemediationAdapter"` |

### Using Adapters from Other Packages

Once an adapter package is installed, any framework can reference its adapters by name:

```toml
# In your framework.toml or .baseline.toml
[controls."OSPS-VM-05.02"]
check = { adapter = "kusari" }  # Uses kusari from darnit-plugins

[controls."OSPS-SA-03.01"]
check = { adapter = "trivy" }   # Uses trivy from another plugin package
```

### Adapter Resolution Order

When you reference an adapter by name, darnit resolves it in this order:

1. **Explicit module path** - If the config specifies `type = "python"` with a `module`
2. **Local config** - `[adapters.name]` section in the same TOML file
3. **Entry points** - `darnit.check_adapters` entry points from installed packages
4. **Fallback** - Uses framework's default "builtin" adapter

### Creating a Plugin Package

1. **Create adapters:**

```python
# my_plugins/adapters/scanner.py
from darnit.core.adapters import CheckAdapter
from darnit.core.models import AdapterCapability, CheckResult, CheckStatus

class MyScanner(CheckAdapter):
    def name(self) -> str:
        return "my-scanner"

    def capabilities(self) -> AdapterCapability:
        return AdapterCapability(
            control_ids={"MY-CTRL-*"},  # Supports wildcard patterns
            supports_batch=True,
        )

    def check(self, control_id, owner, repo, local_path, config) -> CheckResult:
        # Your check logic here
        return CheckResult(
            control_id=control_id,
            status=CheckStatus.PASS,
            message="Check passed",
            level=1,
            source="my-scanner",
        )
```

2. **Register via entry points:**

```toml
# pyproject.toml
[project.entry-points."darnit.check_adapters"]
my-scanner = "my_plugins.adapters.scanner:MyScanner"
```

3. **Use in any framework:**

```toml
# .baseline.toml
[controls."MY-CTRL-01"]
check = { adapter = "my-scanner" }
```

### Using the Plugin Registry Programmatically

```python
from darnit.core import get_plugin_registry

# Get registry and discover plugins
registry = get_plugin_registry()
registry.discover_all()

# List what's available
print("Frameworks:", registry.list_frameworks())
print("Check adapters:", registry.list_check_adapters())

# Get an adapter by name
adapter = registry.get_check_adapter("kusari")
if adapter:
    result = adapter.check("CTRL-001", "", "", "/path/to/repo", {})

# Get plugin summary
summary = registry.get_plugin_summary()
print(f"Found {summary['counts']['check_adapters']} check adapters")
```

### Example: darnit-plugins Package

The `darnit-plugins` package demonstrates the plugin pattern:

```
darnit-plugins/
├── pyproject.toml              # Entry point registration
├── src/darnit_plugins/
│   └── adapters/
│       ├── kusari.py           # Kusari CLI wrapper
│       └── echo.py             # Simple testing adapter
```

Entry points in `pyproject.toml`:
```toml
[project.entry-points."darnit.check_adapters"]
kusari = "darnit_plugins.adapters.kusari:KusariCheckAdapter"
echo = "darnit_plugins.adapters.echo:EchoCheckAdapter"
```

## Examples

### Example: OpenSSF Baseline Framework

See `packages/darnit-baseline/openssf-baseline.toml` for a production framework with 47 controls.

### Example: Test Checks Framework

See `packages/darnit-testchecks/` for a minimal example framework with:
- 12 controls across 3 levels
- File existence checks
- Pattern matching checks
- Remediation implementations
- Complete test suite

### Example: User Configuration

```toml
# .baseline.toml - Real-world example
version = "1.0"
extends = "openssf-baseline"

[settings]
cache_results = true
timeout = 600

# Use Kusari for dependency scanning
[adapters.kusari]
type = "command"
command = "kusari"
output_format = "json"

# Skip MFA check - handled at org level
[controls."OSPS-AC-01.01"]
status = "n/a"
reason = "MFA enforced via SSO at organization level"

# Skip release-related controls for pre-1.0 project
[controls."OSPS-BR-02.01"]
status = "n/a"
reason = "Pre-1.0 project, no releases yet"

[controls."OSPS-LE-02.02"]
status = "n/a"
reason = "Pre-1.0 project, no releases yet"

# Use Kusari for SCA controls
[control_groups.sca]
controls = ["OSPS-VM-05.02", "OSPS-VM-05.03"]
check = { adapter = "kusari" }
```

## MCP Server Integration

Darnit frameworks can be exposed via MCP (Model Context Protocol) servers for integration with AI assistants like Claude Code, Cursor, and others.

### Claude Code Configuration

Add a darnit-based MCP server to Claude Code by editing your settings:

**Global configuration** (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "darnit": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/baseline-mcp", "python", "main.py"]
    }
  }
}
```

**Project-specific configuration** (`.claude/settings.json` in your repo):

```json
{
  "mcpServers": {
    "openssf-baseline": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/baseline-mcp", "python", "main.py"]
    }
  }
}
```

### Creating a Custom MCP Server

To expose your own framework via MCP:

#### 1. Create the Server Entry Point

```python
# my_framework_mcp/main.py
"""MCP server for My Compliance Framework."""

from mcp.server.fastmcp import FastMCP
from pathlib import Path
from typing import Optional
import json

from darnit.core import get_plugin_registry
from darnit.core.models import CheckStatus
from darnit.config.merger import (
    load_effective_config_by_name,
    load_effective_config,
)

# Create MCP server
mcp = FastMCP("My Compliance Framework")


@mcp.tool()
def audit_my_framework(
    local_path: str = ".",
    level: int = 3,
    output_format: str = "markdown",
) -> str:
    """
    Run compliance audit against My Framework.

    Args:
        local_path: Path to the repository to audit
        level: Maximum maturity level to check (1, 2, or 3)
        output_format: Output format (markdown, json, sarif)

    Returns:
        Formatted audit report
    """
    # Discover plugins
    registry = get_plugin_registry()
    registry.discover_all()

    # Load framework + user overrides
    config = load_effective_config_by_name(
        framework_name="my-framework",
        repo_path=Path(local_path),
    )

    # Get adapter and run checks
    results = []
    for control_id, control in config.controls.items():
        if control.level > level:
            continue

        adapter_name = config.get_check_adapter(control_id)
        adapter = registry.get_check_adapter(adapter_name)

        if adapter:
            result = adapter.check(
                control_id=control_id,
                owner="",
                repo="",
                local_path=local_path,
                config=control.check.config if control.check else {},
            )
            results.append(result)

    # Format output
    if output_format == "json":
        return json.dumps([r.to_dict() for r in results], indent=2)

    # Default: markdown
    passed = sum(1 for r in results if r.status == CheckStatus.PASS)
    total = len(results)

    lines = [
        f"# My Framework Audit Results",
        f"",
        f"**Compliance**: {passed}/{total} controls passed",
        f"",
        "## Results",
        "",
    ]

    for result in results:
        status_emoji = "✅" if result.status == CheckStatus.PASS else "❌"
        lines.append(f"- {status_emoji} **{result.control_id}**: {result.message}")

    return "\n".join(lines)


@mcp.tool()
def list_my_framework_controls() -> str:
    """List all controls in My Framework."""
    registry = get_plugin_registry()
    registry.discover_all()

    config = load_effective_config_by_name("my-framework", None)

    controls = []
    for control_id, control in sorted(config.controls.items()):
        controls.append({
            "id": control_id,
            "name": control.name,
            "level": control.level,
            "domain": control.domain,
        })

    return json.dumps(controls, indent=2)


if __name__ == "__main__":
    mcp.run()
```

#### 2. Package Configuration

```toml
# pyproject.toml
[project]
name = "my-framework-mcp"
version = "0.1.0"
dependencies = [
    "darnit",
    "my-framework",  # Your framework package
    "mcp",
]

[project.scripts]
my-framework-mcp = "my_framework_mcp.main:mcp.run"
```

#### 3. Register with Claude Code

```json
{
  "mcpServers": {
    "my-framework": {
      "command": "uvx",
      "args": ["my-framework-mcp"]
    }
  }
}
```

Or for local development:

```json
{
  "mcpServers": {
    "my-framework": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/my-framework-mcp", "python", "main.py"]
    }
  }
}
```

### MCP Tools Best Practices

When creating MCP tools for your framework:

1. **Use descriptive docstrings** - These become the tool descriptions visible to AI assistants

2. **Provide sensible defaults** - Most parameters should have reasonable defaults

3. **Return structured output** - Use markdown for human-readable output, JSON for structured data

4. **Handle errors gracefully** - Return error messages rather than raising exceptions

5. **Support dry-run modes** - For remediation tools, always support previewing changes

6. **Auto-detect context** - Detect owner/repo from git when not provided

### Example: Multi-Framework Server

You can expose multiple frameworks from a single MCP server:

```python
from mcp.server.fastmcp import FastMCP
from darnit.core import get_plugin_registry

mcp = FastMCP("Multi-Framework Compliance Server")

@mcp.tool()
def audit(
    framework: str = "openssf-baseline",
    local_path: str = ".",
) -> str:
    """
    Run compliance audit.

    Args:
        framework: Framework to audit against (openssf-baseline, my-framework, etc.)
        local_path: Path to repository
    """
    registry = get_plugin_registry()
    registry.discover_all()

    available = registry.list_frameworks()
    if framework not in available:
        return f"Unknown framework: {framework}. Available: {', '.join(available)}"

    # ... run audit ...

@mcp.tool()
def list_frameworks() -> str:
    """List available compliance frameworks."""
    registry = get_plugin_registry()
    registry.discover_all()
    return json.dumps(registry.list_frameworks(), indent=2)
```

## Future: Shared Execution Context

> **Status**: Planned enhancement. See TODOs in source code.

Currently, each control check runs independently. A future enhancement will enable tools like OpenSSF Scorecard to run once and provide results for multiple controls.

### Proposed Design

```toml
# Adapter declares it supports caching
[adapters.scorecard]
type = "command"
command = "scorecard"
cache_key = "scorecard"      # Results cached under this key
batch_controls = true        # Single run serves multiple controls

# Multiple controls extract from the same cached result
[controls."OSPS-AC-03.01"]
check = { adapter = "scorecard", extract = "checks.BranchProtection" }

[controls."OSPS-QA-02.01"]
check = { adapter = "scorecard", extract = "checks.CITests" }

[controls."OSPS-QA-03.01"]
check = { adapter = "scorecard", extract = "checks.CI-Tests" }
```

### Implementation Locations

TODOs have been added to track this enhancement:

| File | Component | Description |
|------|-----------|-------------|
| `darnit/core/adapters.py` | `CheckAdapter` class | Add `ExecutionContext` parameter |
| `darnit/core/adapters.py` | `check_batch()` method | Shared result caching pattern |
| `darnit/core/models.py` | `ExecutionContext` class | New class definition (commented) |
| `darnit/config/framework_schema.py` | `CheckConfig` | Add `extract` field |
| `darnit/config/framework_schema.py` | `CommandAdapterConfig` | Add `cache_key`, `batch_controls` |

### Workaround for Now

Adapters can implement internal caching:

```python
class ScorecardAdapter(CheckAdapter):
    _cached_result = None
    _cached_path = None

    def check(self, control_id, owner, repo, local_path, config):
        # Cache scorecard run per repo path
        if self._cached_path != local_path:
            self._cached_result = self._run_scorecard(local_path)
            self._cached_path = local_path

        return self._extract_control(control_id, self._cached_result)
```

## Troubleshooting

### Common Issues

**TOML Syntax Errors**

Multi-line inline tables are not valid TOML:
```toml
# WRONG
pattern = {
    files = ["*.py"],
    patterns = { todo = "TODO" },
}

# CORRECT
[controls."CTRL-001".passes.pattern]
files = ["*.py"]

[controls."CTRL-001".passes.pattern.patterns]
todo = "TODO"
```

**Framework Not Found**

Ensure `get_framework_path()` returns the correct path:
```python
def get_framework_path() -> Path:
    # Path relative to package location
    return Path(__file__).parent.parent.parent / "framework.toml"
```

**Adapter Not Recognized**

Check entry points in `pyproject.toml`:
```toml
[project.entry-points."darnit.frameworks"]
myframework = "my_framework:get_framework_path"

[project.entry-points."darnit.adapters"]
myframework = "my_framework.adapters:MyAdapter"
```

### Debug Mode

Enable debug logging to troubleshoot configuration loading:

```python
import logging
logging.basicConfig(level=logging.DEBUG)

from darnit.config.merger import load_framework_config
framework = load_framework_config(path)
```

## Roadmap

> **Schema Version**: The current schema version is `0.1.0-alpha`. This roadmap outlines
> planned enhancements. Breaking changes may occur before 1.0 release.

### High Priority

#### Policy Language Support

The current JSON evaluation in Exec Pass is intentionally simple. Future versions will
support expressive policy languages for complex conditions.

**Candidates under evaluation:**

| Language | Pros | Cons |
|----------|------|------|
| **CEL** (Google) | Type-safe, portable, good tooling | Limited Python support |
| **Rego** (OPA) | Industry standard for policy-as-code | Steeper learning curve |
| **CUE** | Strong typing, validation built-in | Limited ecosystem |
| **JSONPath++** | Familiar syntax | Less expressive |

**Proposed syntax:**

```toml
[controls."EXAMPLE".passes.exec]
command = ["scorecard", "--format", "json"]
output_format = "json"

# Future: CEL policy expression
policy = "data.score >= 7.0 && data.checks.BranchProtection.pass == true"

# Future: Multiple acceptable values
pass_if_json_values = ["true", "enabled", "active"]

# Future: Numeric comparisons
pass_if_json_gte = 7.0
```

#### External Template Files

Load templates from external files instead of inline content.

**Primary approach: Relative paths from framework TOML location**

Templates resolved relative to where the framework TOML file lives, allowing
frameworks to bundle templates alongside their configuration:

```
darnit-baseline/
├── openssf-baseline.toml
└── templates/
    ├── security_policy.md
    ├── contributing.md
    └── codeowners.md
```

```toml
# Current: inline content only (works today)
[templates.security_policy]
content = """..."""

# Future: File relative to TOML location (primary enhancement)
[templates.security_policy]
file = "templates/security_policy.md"

# Future: Template inheritance
[templates.security_policy_custom]
extends = "security_policy_standard"
content = """
## Additional Section
Custom content appended to base template.
"""
```

**Future exploration: Remote template sources**

For shared templates across organizations (to explore after local file support is solid):

```toml
# Remote URL with integrity verification
[templates.security_policy]
file = "https://example.com/templates/security.md"
file_sha256 = "abc123..."  # Required for remote files

# Git repository reference (concept)
[templates.security_policy]
file = "git://github.com/org/templates#security.md"

# Template registry (concept)
[templates.security_policy]
file = "registry://openssf/security-policy@1.0"
```

> **Note**: Remote templates require careful security consideration (trust,
> integrity, availability) and will be explored after local file support is complete.

#### Schema Migration Tooling

Tools to help upgrade configuration files between schema versions:

```bash
# Validate config against schema
darnit config validate framework.toml

# Check for deprecated fields
darnit config lint framework.toml

# Migrate to new schema version
darnit config migrate framework.toml --to 0.2.0

# Show migration diff without applying
darnit config migrate framework.toml --dry-run
```

### Medium Priority

#### Control Dependencies

Run controls conditionally based on other control results:

```toml
[controls."OSPS-QA-02.01"]
name = "CIRunsTests"
description = "CI pipeline must run tests"
depends_on = ["OSPS-QA-01.01"]  # Requires "CI exists" to pass first
```

#### Conditional Controls

Enable controls based on project context:

```toml
[controls."OSPS-BR-02.01"]
name = "SignedReleases"
description = "Releases must be signed"
when = { has_releases = true }  # Only check if project makes releases

[controls."OSPS-SA-01.01"]
name = "SASTEnabled"
when = { language = ["python", "javascript", "go"] }  # Language-specific
```

#### Parallel Check Execution

Run independent checks concurrently:

```toml
[defaults]
parallel_checks = true
max_concurrency = 5
timeout = 300
```

#### Shared Execution Context

Run expensive tools once and extract multiple control results:

```toml
[adapters.scorecard]
type = "command"
command = "scorecard"
cache_key = "scorecard"        # Cache results under this key
batch_controls = true          # Single run serves multiple controls

[controls."OSPS-AC-03.01"]
check = { adapter = "scorecard", extract = "checks.BranchProtection" }

[controls."OSPS-QA-02.01"]
check = { adapter = "scorecard", extract = "checks.CITests" }
```

### Lower Priority

#### Rich Output Formats

Additional report formats beyond markdown/JSON/SARIF:

- HTML reports with charts and drill-down
- PDF export for compliance documentation
- GitHub Actions annotations
- GitLab CI report format
- OSCAL (Open Security Controls Assessment Language)

#### Framework Inheritance

Extend base frameworks with custom controls:

```toml
[metadata]
name = "my-company-baseline"
extends = "openssf-baseline"  # Inherit all controls

# Override specific controls
[controls."OSPS-AC-01.01"]
status = "n/a"
reason = "Handled at organization level"

# Add custom controls
[controls."MYCO-SEC-01"]
name = "InternalSecurityReview"
description = "Custom internal security check"
```

#### Control Versioning

Track control evolution with deprecation notices:

```toml
[controls."OSPS-OLD-01"]
deprecated = true
deprecated_by = "OSPS-NEW-01"
sunset_date = "2025-06-01"
migration_guide = "https://example.com/migration"
```

### Contributing

We welcome contributions to help implement these roadmap items. See the TODOs in:

- `packages/darnit/src/darnit/config/framework_schema.py` - Schema enhancements
- `packages/darnit/src/darnit/sieve/passes.py` - Policy language support
- `packages/darnit/src/darnit/remediation/executor.py` - Template loading
