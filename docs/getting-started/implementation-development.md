# Implementation Development

This guide covers how to create and modify compliance implementations (plugins) for the darnit framework. Read this if you want to add controls to the existing OpenSSF Baseline implementation or create a new compliance framework plugin.

## TOML-First Architecture

All controls MUST be defined in the implementation's TOML configuration file. Python code is NOT the source of truth for control metadata.

- New controls are defined entirely in TOML with passes, metadata, severity, and help URLs
- CEL expressions in TOML follow documented escaping rules (see [CEL Reference](cel-reference.md))
- TOML controls overwrite any Python-registered controls

## Control Definition Format

Each control is defined under `[controls."CONTROL-ID"]` in the TOML file:

```toml
[controls."MS-DOC-01"]
name = "ReadmeExists"
description = "Project must have a README file"
tags = { level = 1, domain = "DOC", documentation = true }
docs_url = "https://example.com/mystandard#MS-DOC-01"
help_md = """Create a README.md file in the repository root.

**Remediation:**
1. Create README.md with project description
2. Include usage instructions
"""
```

### Control metadata fields

| Field | Required | Purpose |
|-------|----------|---------|
| `name` | Yes | Short identifier |
| `description` | Yes | Human-readable description |
| `tags` | Yes | Must include `level` (integer) and `domain` (string) |
| `docs_url` | No | Link to the standard's documentation |
| `help_md` | No | Markdown help text shown on failure |
| `when` | No | Preconditions for when this control applies |

### `when` clauses

Controls can declare preconditions. If not met, the control is **skipped** (not failed):

```toml
[controls."MS-CI-01"]
name = "SecureWorkflowInputs"
description = "Workflows handle untrusted inputs safely"
when = { ci_provider = "github" }
```

The `when` keys are matched against project context from `.project/project.yaml`.

## Pass Types

Controls define one or more `[[passes]]` entries. The sieve pipeline executes them in order, stopping at the first conclusive result.

### file_exists

Check if any listed file exists:

```toml
[[controls."MS-SEC-01".passes]]
handler = "file_exists"
files = ["SECURITY.md", ".github/SECURITY.md", "docs/SECURITY.md"]
```

### exec (external command)

Run a CLI command and evaluate the result:

```toml
[[controls."MS-AC-01".passes]]
handler = "exec"
command = ["gh", "api", "/orgs/$OWNER"]
pass_exit_codes = [0]
fail_exit_codes = [1]
output_format = "json"
expr = 'output.json.two_factor_requirement_enabled == true'
timeout = 30
```

Variable substitution: `$PATH` (local repo), `$OWNER`, `$REPO`, `$BRANCH`, `$CONTROL`.

### pattern (regex matching)

Search file contents with regex:

```toml
[[controls."MS-DOC-02".passes]]
handler = "pattern"
file_patterns = ["SECURITY.md", ".github/SECURITY.md"]
content_patterns = { security_contact = '([\w.-]+@[\w.-]+\.\w+|security\s*contact)' }
expr = 'output.any_match'
```

### manual (human verification)

Always returns INCONCLUSIVE with steps for human review:

```toml
[[controls."MS-DOC-02".passes]]
handler = "manual"
steps = [
    "Open SECURITY.md",
    "Verify it contains a clear contact method",
    "Confirm the contact method is monitored",
]
```

## Remediation in TOML

Controls can define declarative remediation actions:

### file_create

```toml
[controls."MS-SEC-01".remediation]
safe = true
dry_run_supported = true

[controls."MS-SEC-01".remediation.file_create]
path = "SECURITY.md"
template = "security_policy"
overwrite = false
```

### exec

```toml
[controls."MS-BR-01".remediation.exec]
command = ["git", "tag", "-s", "v1.0.0"]
success_exit_codes = [0]
timeout = 30
```

### api_call

```toml
[controls."MS-AC-01".remediation.api_call]
method = "PUT"
endpoint = "/repos/$OWNER/$REPO/branches/$BRANCH/protection"
payload_template = "branch_protection_payload"
```

### project_update

Update `.project/project.yaml` after remediation:

```toml
[controls."MS-SEC-01".remediation.project_update]
set = { "security.policy.path" = "SECURITY.md" }
```

## Templates

Templates are content blocks used by remediation actions:

```toml
[templates.security_policy]
description = "Standard SECURITY.md template"
content = """# Security Policy

## Reporting a Vulnerability

Report vulnerabilities by emailing security@$OWNER.example.com.
We will respond within 48 hours.
"""
```

Templates support `$OWNER` and `$REPO` variable substitution.

## Custom Python Handlers

When built-in pass types aren't enough, write custom sieve handlers.

### Handler signature

```python
from typing import Any
from darnit.sieve.handler_registry import HandlerContext, HandlerResult, HandlerResultStatus

def my_handler(config: dict[str, Any], context: HandlerContext) -> HandlerResult:
    """Check something and return a result."""
    return HandlerResult(
        status=HandlerResultStatus.PASS,
        message="Check passed",
        confidence=1.0,
        evidence={"key": "value"},
    )
```

- `config`: All fields from the TOML `[[passes]]` entry (minus `handler`, `shared`, `phase`)
- `context`: Framework-provided context (repo path, control ID, evidence, project context)

### Registering handlers

Register from your implementation class:

```python
from darnit.sieve.handler_registry import get_sieve_handler_registry

def register_sieve_handlers(self):
    registry = get_sieve_handler_registry()
    registry.set_plugin_context(self.name)

    registry.register("my_check", "deterministic", my_handler,
                       description="My custom check")

    registry.set_plugin_context(None)  # Always clear when done
```

Then reference in TOML:

```toml
[[controls."MS-LIC-01".passes]]
phase = "deterministic"
handler = "my_check"
file_extensions = [".py", ".js"]   # → config["file_extensions"]
```

### Handler result statuses

| Status | Meaning | When to use |
|--------|---------|-------------|
| `PASS` | Control satisfied | Positively verified compliance |
| `FAIL` | Control NOT satisfied | Positively verified non-compliance |
| `INCONCLUSIVE` | Cannot determine | Let the next handler try |
| `ERROR` | Handler malfunction | Your handler broke (not the control) |

## Entry Point Configuration

Register your implementation via Python entry points in `pyproject.toml`:

```toml
[project.entry-points."darnit.implementations"]
my-framework = "my_package:register"
```

The `register()` function returns an instance of your implementation class:

```python
# my_package/__init__.py
def register():
    from .implementation import MyImplementation
    return MyImplementation()
```

## MCP Tool Handlers

To expose custom tools to AI assistants, implement `register_handlers()` on your implementation class:

```python
def register_handlers(self) -> None:
    from darnit.core.handlers import get_handler_registry
    from . import tools

    registry = get_handler_registry()
    registry.set_plugin_context(self.name)
    registry.register_handler("my_tool", tools.my_tool)
    registry.set_plugin_context(None)
```

Then reference in TOML:

```toml
[mcp.tools.my_tool]
handler = "my_tool"
description = "Run my custom tool"
```

## Reference Implementation

The OpenSSF Baseline implementation (`packages/darnit-baseline/`) is the canonical example:

| File | What to learn |
|------|---------------|
| `openssf-baseline.toml` | TOML config with 62 controls, templates, context definitions |
| `src/darnit_baseline/implementation.py` | ComplianceImplementation class |
| `src/darnit_baseline/__init__.py` | register() function |
| `pyproject.toml` | Entry point configuration |

## Next Steps

- [CEL Reference](cel-reference.md) — CEL expression syntax and pitfalls
- [Tutorial: Add a New Control](../tutorials/add-new-control.md) — Step-by-step walkthrough
- [Tutorial: Create a New Implementation](../tutorials/create-new-implementation.md) — Build a plugin from scratch
- [Testing Guide](testing.md) — Testing your implementation
- Back to [Getting Started](README.md)
