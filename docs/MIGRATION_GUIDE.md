# Migration Guide

This guide helps you migrate existing configurations to the new TOML schema.

## Handler References

### Before (Full Module Paths)
```toml
[mcp.tools.audit_openssf_baseline]
handler = "darnit_baseline.tools:audit_openssf_baseline"
```

### After (Short Names)
```toml
[mcp.tools.audit_openssf_baseline]
handler = "audit_openssf_baseline"
```

Handler short names are registered by the implementation's `register_handlers()` method.

## CEL Expressions

### Before (Multiple Fields)
```toml removed
[[controls."OSPS-XX-01.01".passes]]
handler = "exec"
command = ["kusari", "scan"]
output_format = "json"
pass_if_json_path = "$.status"
pass_if_json_value = "pass"
```

### After (CEL Expression)
```toml
[[controls."OSPS-XX-01.01".passes]]
handler = "exec"
command = ["kusari", "scan"]
output_format = "json"
expr = 'output.json.status == "pass"'
```

**Note**: The legacy `pass_if_*` fields are removed. A step that still declares one fails loading, naming the key (feature 044); replace it with `expr`.

### CEL Context Variables

| Pass Type | Available Variables |
|-----------|---------------------|
| exec | `output.stdout`, `output.stderr`, `output.exit_code`, `output.json` |
| api_check | `response.status_code`, `response.body`, `response.headers` |
| pattern | `files`, `matches` |
| all | `project.*` (from `.project/` context) |

## Plugin Security Configuration

### New Configuration
Add to your `.baseline.toml`:

```toml
[plugins]
# Require signed plugins in production
allow_unsigned = false

# Trust additional publishers beyond defaults (kusari-oss, kusaridev)
trusted_publishers = [
    "https://github.com/my-org",
]

# Per-plugin configuration
[plugins."my-plugin"]
version = ">=1.0.0"
```

## Context System

### Project Context
Create `.project/project.yaml` for project-level context:

```yaml
name: my-project

security:
  policy:
    type: SECURITY.md

governance:
  maintainers:
    - "@alice"
    - "@bob"
```

This context is automatically injected into the sieve orchestrator and available in CEL expressions via `project.*`.

### Confirming Context
Use the `confirm_project_data` MCP tool, on the person's explicit instruction, to record context values. `owner` and `repo` are required: they decide whether the confirmation record goes in `.project/darnit.yaml` (a repository the operator trusts) or operator-side:

```python
confirm_project_data(
    owner="my-org",
    repo="my-repo",
    maintainers="CODEOWNERS",
    security_contact="security@realcorp.io",
    ci_provider="github"
)
```

Values stored by an earlier darnit version have no confirmation record and are treated as unconfirmed candidates. `get_pending_data` lists them under `stored_unconfirmed`; review them in one call with `confirm_project_data(confirm_stored=[...], reject_stored=[...], owner=..., repo=...)`.

## Version Compatibility

| Feature | Minimum Version |
|---------|-----------------|
| CEL expressions | 0.2.0 |
| Handler short names | 0.2.0 |
| Plugin verification | 0.2.0 |
| Context system | 0.2.0 |

## Deprecation Notices

### rules/catalog.py (Deprecated)
SARIF metadata should be defined in TOML:

```toml
[controls."OSPS-XX-01.01"]
name = "ControlName"
description = "Control description"
security_severity = 8.0
help_md = "..."
docs_url = "https://..."
```

### pass_if_* Fields (Deprecated)
Prefer CEL expressions for new controls. Legacy fields remain for backwards compatibility.
