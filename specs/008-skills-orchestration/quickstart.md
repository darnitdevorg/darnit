# Quickstart: Skills-Based Orchestration Layer with Audit Profiles

**Feature**: 008-skills-orchestration | **Date**: 2026-04-04

## For Users: Using Skills

### Run an Audit

In Claude Code, type:
```
/audit
```

The skill runs the full compliance audit and shows results with actionable next steps.

To audit a specific profile:
```
/audit --profile level1_quick
```

### Collect Project Context

```
/context
```

Guides you through answering questions about your project (maintainers, CI provider, governance model, etc.) to improve audit accuracy.

### Full Compliance Pipeline

```
/comply
```

Runs audit → context collection → remediation → PR creation in one flow.

### Apply Remediations

```
/remediate
```

Shows a dry-run plan of fixes, asks for confirmation, then creates a branch with all changes.

## For Implementation Authors: Defining Audit Profiles

Add an `[audit_profiles]` section to your framework TOML:

```toml
[audit_profiles.onboard]
description = "Verify initial setup is complete"
controls = ["SETUP-01", "SETUP-02", "SETUP-03"]

[audit_profiles.verify]
description = "Ongoing compliance verification"
tags = { domain = "POLICY" }

[audit_profiles.security_critical]
description = "High-severity controls only"
tags = { security_severity_gte = 8.0 }
```

Then implement the optional protocol method:

```python
def get_audit_profiles(self) -> dict[str, AuditProfile] | None:
    """Return named audit profiles from TOML config."""
    config = load_framework_config(self.get_framework_config_path())
    return config.audit_profiles or None
```

Users can then run:
```bash
darnit audit --profile onboard /path/to/repo
darnit profiles --impl my-framework
```

## Development: Adding a New Skill

1. Create a `.md` file in `packages/darnit-baseline/skills/`
2. Write structured instructions referencing MCP tools by name
3. Register the skill in the project's skill configuration
4. Test by invoking the slash command in Claude Code

Skills are prompt templates — no Python code needed for orchestration logic.
