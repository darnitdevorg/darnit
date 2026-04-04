# Data Model: Skills-Based Orchestration Layer with Audit Profiles

**Feature**: 008-skills-orchestration | **Date**: 2026-04-04

## Entities

### AuditProfile

A named subset of controls within an implementation module, representing a distinct audit scenario.

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| name | string | Yes | Profile identifier (TOML key, e.g., "onboard") |
| description | string | Yes | Human-readable purpose of this profile |
| controls | list[string] | No* | Explicit control IDs to include |
| tags | dict[string, any] | No* | Tag-based filter to select controls |

*At least one of `controls` or `tags` must be non-empty.

**Validation rules**:
- `name` must be a valid TOML key (alphanumeric + hyphens + underscores)
- `controls` entries must reference valid control IDs in the same TOML file
- `tags` filter keys must match tag keys defined on controls (e.g., `level`, `domain`, `security_severity_gte`)
- When both `controls` and `tags` are specified, the result is the union (controls explicitly listed + controls matching tags)

**Relationships**:
- Belongs to one `FrameworkConfig` (implementation)
- References zero or more `ControlConfig` entries by ID
- Referenced by skill `--profile` parameter, CLI `--profile` flag, MCP tool `profile` parameter

### Skill

A Claude Code skill definition file (`.md`) that orchestrates compliance workflows.

| Field | Type | Description |
|-------|------|-------------|
| filename | string | Skill file (e.g., `audit.md`) |
| slash_command | string | User-facing command (e.g., `/audit`) |
| parameters | list[string] | Accepted parameters (e.g., `--profile`, `--level`) |
| mcp_tools_used | list[string] | MCP tools this skill orchestrates |

**Not a database entity** — skills are static `.md` files, not runtime objects. This documents their structure for reference.

### ProfileResolution (runtime, not persisted)

The result of resolving a `--profile` argument to a concrete control list.

| Field | Type | Description |
|-------|------|-------------|
| implementation_name | string | Which implementation the profile belongs to |
| profile_name | string | The resolved profile name |
| control_ids | list[string] | Final list of control IDs after resolution |
| source | string | "explicit" (from controls list) or "tags" (from tag filter) or "both" |

## State Transitions

### Audit Profile Lifecycle

```
TOML Definition → Load Time Resolution → Runtime Filtering
```

1. **TOML Definition**: Author writes `[audit_profiles.onboard]` in framework TOML
2. **Load Time Resolution**: `FrameworkConfig` parses and validates profiles during config load
3. **Runtime Filtering**: When `--profile` is specified, profile is resolved to control IDs and passed to `run_sieve_audit(controls=...)` or equivalent

No state persistence — profiles are stateless configuration.

### Skill Execution Lifecycle

```
User invokes /audit → Skill loaded → MCP tools called → Results formatted → User sees report
```

Skills are stateless prompt templates. Any state between steps (e.g., audit results for remediation) is managed by Claude's conversation context or by darnit's existing caching (audit result cache in `.darnit/`).

## TOML Schema Extension

### New section in framework TOML:

```toml
# Added to FrameworkConfig
[audit_profiles.level1_quick]
description = "Level 1 controls only — quick compliance check"
tags = { level = 1 }

[audit_profiles.security_critical]
description = "High-severity security controls"
tags = { security_severity_gte = 8.0 }

[audit_profiles.access_control]
description = "Access control domain controls"
controls = ["OSPS-AC-01.01", "OSPS-AC-02.01", "OSPS-AC-03.01"]
```

### Pydantic model addition to `framework_schema.py`:

```
AuditProfileConfig:
  description: str (required)
  controls: list[str] (default: [])
  tags: dict[str, Any] (default: {})
  
  Validator: at least one of controls or tags must be non-empty
```

### FrameworkConfig extension:

```
FrameworkConfig:
  ...existing fields...
  audit_profiles: dict[str, AuditProfileConfig] (default: {})
```
