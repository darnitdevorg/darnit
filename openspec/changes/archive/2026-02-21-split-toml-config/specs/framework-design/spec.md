## MODIFIED Requirements

### 4.5 Templates

Templates support variable substitution and can source their content from inline strings or external files:

```toml
# Inline content (existing behavior)
[templates.security_policy_standard]
description = "Standard SECURITY.md template"
content = """
# Security Policy
...
"""

# External file (new)
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

**Variable Resolution**: `$OWNER`, `$REPO`, and `$BRANCH` MUST be resolved using `detect_repo_from_git()` from `darnit.core.utils` — the canonical repo identity resolution path.

#### Scenario: Template with inline content
- **WHEN** a `[templates.foo]` entry has `content = "# Header\n..."`
- **THEN** the executor SHALL use the inline string as the template body

#### Scenario: Template with external file
- **WHEN** a `[templates.foo]` entry has `file = "templates/foo.tmpl"`
- **THEN** the executor SHALL read the file relative to the TOML directory and use its contents as the template body

#### Scenario: Variable substitution on file-sourced template
- **WHEN** a template loaded from file contains `$OWNER` and `${context.maintainers}`
- **THEN** the executor SHALL substitute variables identically to inline templates
