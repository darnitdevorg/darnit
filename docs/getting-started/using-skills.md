# Using Darnit Skills in Claude Code

Darnit ships with four skills that provide structured compliance workflows directly in Claude Code. Skills orchestrate darnit's MCP tools behind the scenes — you type a simple command and get guided through the full workflow.

## Installation

```bash
# Install MCP server config + skills globally
darnit install

# Install skills per-project (checked into git, shared with team)
darnit install --project

# MCP config only, no skills
darnit install --mcp-only
```

After installation, restart Claude Code. The skills appear as slash commands.

## Available Skills

| Skill | What it does |
|-------|-------------|
| `/darnit-audit` | Run a compliance audit and get a formatted report |
| `/darnit-context` | Collect missing project context to improve audit accuracy |
| `/darnit-remediate` | Apply automated fixes for failing controls |
| `/darnit-comply` | Full pipeline: audit, context, remediate, and PR creation |

## Usage Examples

### Basic audit

```
/darnit-audit
```

If only one implementation module is loaded (e.g., openssf-baseline), runs it automatically. If multiple modules are available, Claude asks which one to use.

### Audit a specific module

When multiple modules are loaded (e.g., openssf-baseline, gittuf, reproducibility):

```
/darnit-audit openssf baseline
/darnit-audit gittuf
/darnit-audit reproducibility
```

Claude matches your intent to the right MCP tool (`audit_openssf_baseline`, `audit_gittuf`, etc.).

### Audit with a profile

Profiles are named subsets of controls defined by each implementation module.

```
/darnit-audit level 1 only
/darnit-audit access control checks
/darnit-audit gittuf onboard profile
/darnit-audit just the security critical controls
```

### Collect project context

```
/darnit-context
```

Guides you through answering questions about your project (maintainers, CI provider, governance model). Auto-detected values are presented for confirmation. You can skip any question.

### Scoped context collection

```
/darnit-context for gittuf
/darnit-context just what's needed for access control
```

### Apply fixes

```
/darnit-remediate
```

Shows a dry-run plan first, asks for confirmation, then creates a branch with fixes and offers to open a PR.

### Full pipeline

```
/darnit-comply
```

Runs the complete workflow: audit, collect missing context, re-audit, show remediation plan, apply fixes, create PR.

```
/darnit-comply openssf baseline
/darnit-comply gittuf onboard profile
```

## How Skills Work

Skills are prompt templates that instruct Claude how to orchestrate darnit's MCP tools. They follow the [Agent Skills specification](https://agentskills.io/specification).

When you type `/darnit-audit`, Claude Code:

1. Loads the skill's `SKILL.md` instructions
2. Discovers available darnit MCP tools (e.g., `audit_openssf_baseline`)
3. Calls the appropriate tools based on your request
4. Resolves any controls that need LLM judgment (PENDING_LLM)
5. Formats and presents the results

Skills are an orchestration layer over the MCP tools — not a replacement. You can always call MCP tools directly if you need more control.

## Where Skills Live

| Scope | Location | Installed by |
|-------|----------|-------------|
| Global | `~/.claude/skills/` | `darnit install` (default) |
| Project | `.claude/skills/` | `darnit install --project` |
| Package | `darnit_baseline/skills/` | Bundled in the Python package |

## Multiple Modules

When multiple darnit implementation modules are installed, each registers its own MCP tools:

| Module | Audit tool | Remediate tool |
|--------|-----------|---------------|
| openssf-baseline | `audit_openssf_baseline` | `remediate_audit_findings` |
| gittuf | `audit_gittuf` | `remediate_gittuf_findings` |
| reproducibility | `audit_reproducibility` | `remediate_reproducibility_findings` |

Skills automatically discover available tools. Just mention the module name and Claude picks the right one.

## Audit Profiles

Implementation modules can define named profiles — subsets of controls for different audit scenarios.

```bash
# List available profiles from the CLI
darnit profiles

# List profiles for a specific module
darnit profiles --impl openssf-baseline
```

Example profiles in openssf-baseline:

| Profile | Description |
|---------|-------------|
| `level1_quick` | Level 1 controls only — quick compliance check |
| `security_critical` | High-severity controls across all levels |
| `access_control` | Access control domain (branch protection, MFA, permissions) |

Use profiles with any skill:

```
/darnit-audit level1_quick profile
/darnit-comply security critical controls only
/darnit-remediate just access control
```

### Defining profiles (for module authors)

Add an `[audit_profiles]` section to your framework TOML:

```toml
[audit_profiles.onboard]
description = "Verify initial setup is complete"
controls = ["SETUP-01", "SETUP-02", "SETUP-03"]

[audit_profiles.verify]
description = "Ongoing compliance verification"
tags = { domain = "POLICY" }
```

No Python code needed — profiles are TOML-only.

## Troubleshooting

**Skills not appearing as slash commands:**
- Run `darnit install` and restart Claude Code
- Check that `~/.claude/skills/darnit-audit/SKILL.md` exists

**"No audit tools available" error:**
- Check that `darnit serve` is running
- Check that an implementation package is installed: `pip install darnit-baseline`

**Wrong module selected:**
- Be specific: `/darnit-audit openssf baseline` instead of just `/darnit-audit`
- Or use the MCP tool directly: call `audit_openssf_baseline` tool
