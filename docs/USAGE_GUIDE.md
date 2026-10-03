# OpenSSF Baseline MCP Server
## Usage Guide & Presentation

---

## What is This?

**OpenSSF Baseline MCP Server** is an AI-powered compliance audit tool that checks repositories against the [OpenSSF Baseline](https://baseline.openssf.org) security standard (OSPS v2026.02.19).

### Key Features
- 🔍 **65 security controls** across 3 maturity levels
- 🤖 **MCP integration** - works with Claude, Cursor, and other AI tools
- 🔧 **Auto-remediation** - fix common issues automatically
- 📊 **Multiple output formats** - Markdown, JSON, SARIF
- 🔏 **Attestation support** - cryptographic proof via Sigstore

---

## Architecture

```
┌─────────────────────────────────────────────────────────┐
│                    MCP Server (main.py)                  │
├─────────────────────────────────────────────────────────┤
│  darnit (Framework)        │  darnit-baseline (OSPS)    │
│  ├── core/                 │  ├── checks/               │
│  ├── sieve/                │  ├── controls/             │
│  ├── attestation/          │  ├── rules/                │
│  ├── threat_model/         │  ├── formatters/           │
│  └── remediation/          │  └── remediation/          │
└─────────────────────────────────────────────────────────┘
```

---

## Installation

### Prerequisites
- Python 3.11+
- [uv](https://docs.astral.sh/uv/) package manager
- GitHub CLI (`gh`) for GitHub API access

### Setup
```bash
# Clone the repository
git clone https://github.com/yourorg/baseline-mcp
cd baseline-mcp

# Install dependencies
uv sync

# Authenticate with GitHub (required for some checks)
gh auth login
```

---

## Running the MCP Server

### Option 1: Direct Python
```bash
uv run python main.py
```

### Option 2: With Claude Desktop
Add to `~/Library/Application Support/Claude/claude_desktop_config.json`:

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

### Option 3: With Cursor/VS Code
Add to your MCP settings with the same configuration.

---

## Available MCP Tools

| Tool | Purpose |
|------|---------|
| `audit_openssf_baseline` | Run compliance audit |
| `list_available_checks` | Show all 65 controls |
| `get_project_config` | View project.toml config |
| `init_project_config` | Create project.toml |
| `generate_threat_model` | STRIDE threat analysis |
| `generate_attestation` | Create signed attestation |
| `create_security_policy` | Generate SECURITY.md |
| `enable_branch_protection` | Preview or apply branch protection (only tightens) |
| `remediate_audit_findings` | Preview or apply fixes for failing controls |

---

## Running an Audit

### Basic Audit
```
Use the audit_openssf_baseline tool to check this repository
```

### With Parameters
```
audit_openssf_baseline(
  owner="myorg",
  repo="myrepo",
  local_path="/path/to/repo",
  level=3,                    # Check all levels (1, 2, 3)
  output_format="markdown"    # or "json", "sarif"
)
```

### Output Formats
- **markdown** - Human-readable report
- **json** - Machine-readable structured data
- **sarif** - GitHub Code Scanning compatible

---

## Understanding Audit Results

### Status Icons
| Icon | Status | Meaning |
|------|--------|---------|
| ✅ | PASS | Control satisfied |
| ❌ | FAIL | **Action required** |
| ⚠️ | NEEDS_VERIFICATION | **Manual review required** |
| ➖ | N/A | Not applicable |
| 🔴 | ERROR | Check couldn't run |

### Maturity Levels
- **Level 1** (25 controls) - Basic security hygiene (includes 1 upstream-retired control retained for backward compatibility)
- **Level 2** (19 controls) - Enhanced security practices
- **Level 3** (21 controls) - Advanced security maturity

Upstream OSPS Baseline v2026.02.19 defines 64 controls (24 / 19 / 21). Darnit ships one additional Level 1 control (`OSPS-BR-01.02`) that upstream retired in [ossf/security-baseline#443](https://github.com/ossf/security-baseline/pull/443); it is retained because the underlying "sanitize `github.head_ref`" concern is still valid, and it is included in Level 1 audits.

---

## Example Audit Output

```markdown
# OpenSSF Baseline Audit Report

**Repository:** myorg/myrepo
**Level Assessed:** 3

## Summary
| Status | Count |
|--------|-------|
| ✅ Pass | 45 |
| ❌ Fail | 8 |
| ⚠️ Needs Verification | 5 |
| ➖ N/A | 4 |

## Level Compliance
- Level 1: ✅ Compliant
- Level 2: ❌ Not Compliant
- Level 3: ❌ Not Compliant

## Failures
- OSPS-AC-03.02: No branch protection on 'main'
- OSPS-VM-02.01: Missing SECURITY.md
...
```

---

## Fixing Issues (Remediation)

Remediation previews by default. A preview runs the same logic as the apply against the current state and changes nothing; it lists every file to be created or changed, every platform setting with its value before and after, every command, and the digests to approve.

### Preview, then apply
```
# 1. Preview (dry_run defaults to true)
remediate_audit_findings(
  local_path="/path/to/repo",
  categories=["access_control", "governance"]
)

# 2. Apply, passing only the digests the person approved
remediate_audit_findings(
  local_path="/path/to/repo",
  categories=["access_control", "governance"],
  dry_run=false,
  approve=["sha256:..."]
)
```

- `dry_run=false` alone approves nothing. Under the default policy a platform change (branch protection, repository visibility, private vulnerability reporting) is written only when its change-set digest is in `approve`, and a high-impact change (repository visibility, organization-wide settings) only by its own digest, never as part of a batch.
- Remediations marked `safe = false` and steps that cannot be previewed exactly (for example a fixing tool that needs the network) run only when their plan item digest is approved.
- If the settings changed since the preview, nothing is written for that change and you need a new preview.
- Platform changes read the current settings first, change only what the control requires, never weaken an existing setting, and are read back afterwards. Branch protection targets the repository's default branch.
- The operator configuration sets the policy (`[remediation]` `platform` and `high_impact`: `prompt` (default), `manual`, or `auto`); see the [Security Guide](SECURITY_GUIDE.md#remediation-safety).

### Outcomes

The apply reports one outcome per control, derived from what changed and from a re-check of the control:

| Outcome | Meaning |
|---------|---------|
| `fixed` | Something changed and the re-check passes |
| `changed_not_passing` | Something changed; the control still does not pass |
| `changed_not_verified` | Something changed; the re-check could not run |
| `unchanged` | Nothing changed, with the reason (for example `already_exists`, `user_changes_present`) |
| `needs_approval` | An approval is required; nothing was written for it |
| `needs_confirmation` | A project value must be confirmed first (`confirm_project_data`) |
| `manual` | darnit made no change and lists the steps |
| `error` | A step failed; the error names its cause |

`remediate_audit_findings` returns the Markdown report followed by a fenced JSON block holding the run (`run_id`, `plan` with digests, `outcomes`, `summary`).

### Remediation Categories

Categories are control domains: `access_control`, `build_release`, `documentation`, `governance`, `legal`, `quality`, `security_architecture`, `vulnerability_management`, or `["all"]` (the default).

---

## Remediation Workflow

### Recommended Git Workflow
```
1. remediate_audit_findings()                          # Preview
2. remediate_audit_findings(dry_run=false, approve=[...],
       branch_name="fix/openssf-baseline", auto_commit=true, create_pr=true)
```

Or step by step after an apply:
```
create_remediation_branch(branch_name="fix/security-baseline")
commit_remediation_changes()      # Commits only the files this run wrote
create_remediation_pr()           # Pushes only the remediation branch
```

The git tools take `run_id` (default: the repository's latest run). They follow these rules:

- The commit stages only the files the remediation run wrote, and only while they are unchanged since; your other changes, untracked files, and ignored files are never committed. The commit message carries `Darnit-Remediation-Run: <run_id>`.
- darnit never stashes. A new branch keeps your uncommitted changes in the working tree; switching to an existing branch needs a clean tree.
- darnit stops before changing anything on a detached HEAD, during a merge or rebase, or when the remediation branch holds commits darnit did not make.
- A file with your uncommitted changes is not written; the outcome says `user_changes_present`.

---

## Project Configuration (project.toml)

### Initialize Config
```
init_project_config(
  local_path="/path/to/repo",
  project_name="my-project",
  project_type="software"
)
```

### Example project.toml
```toml
schema_version = "0.1"

[project]
name = "my-project"
type = "software"

[security]
policy = { path = "SECURITY.md" }

[governance]
contributing = { path = "CONTRIBUTING.md" }
codeowners = { path = ".github/CODEOWNERS" }

[legal]
license = { path = "LICENSE" }
```

---

## Threat Modeling

### Generate STRIDE Threat Model
```
generate_threat_model(
  local_path="/path/to/repo",
  output_format="markdown"
)
```

### What It Analyzes
- 🔍 Entry points (API routes, server actions)
- 🔐 Authentication mechanisms
- 💾 Data stores and sensitive data
- 💉 Potential injection vulnerabilities
- 🔑 Hardcoded secrets

---

## Attestations

### Generate Signed Attestation
```
generate_attestation(
  local_path="/path/to/repo",
  level=3,
  sign=true
)
```

### What You Get
- In-toto attestation format
- Sigstore signing (OIDC-based)
- Cryptographic proof of compliance status
- Output to stdout or returned via MCP tool response

---

## Common Workflows

### 1. Initial Assessment
```
1. audit_openssf_baseline(level=1)    # Start with Level 1
2. Review failures and warnings
3. remediate_audit_findings()          # Preview fixes, then apply approved ones
4. Re-audit to verify fixes
```

### 2. Continuous Compliance
```
1. Add to CI/CD pipeline
2. Run audit on PRs
3. Use SARIF output for GitHub Code Scanning
4. Block merges on Level 1 failures
```

### 3. Security Review
```
1. generate_threat_model()             # Understand attack surface
2. audit_openssf_baseline(level=3)     # Full assessment
3. generate_attestation()              # Document compliance
```

---

## Tips & Best Practices

### Do ✅
- Start with Level 1 compliance
- Preview remediation (the default) and approve only the changes you reviewed
- Review auto-generated files before committing
- Keep project.toml updated

### Don't ❌
- Run `gh` or `git` commands directly (use MCP tools)
- Skip manual verification items
- Ignore "Needs Verification" warnings
- Write audit results to project.toml

---

## Troubleshooting

### "Could not auto-detect owner/repo"
```
# Provide explicit parameters:
audit_openssf_baseline(
  owner="myorg",
  repo="myrepo",
  local_path="/path/to/repo"
)
```

### GitHub API Errors
```bash
# Re-authenticate with GitHub CLI
gh auth login
gh auth status
```

### Branch Protection Failures
```
# Reading or changing protection needs admin access to the repository.
# If darnit cannot read the current protection, it writes nothing and
# reports the cause. Check: Settings -> Branches -> Branch protection rules
```

---

## Resources

- **OpenSSF Baseline Spec**: https://baseline.openssf.org
- **OSPS Controls Reference**: https://baseline.openssf.org/versions/2025-10-10
- **MCP Protocol**: https://modelcontextprotocol.io
- **Sigstore**: https://sigstore.dev

---

## Quick Reference Card

```
┌────────────────────────────────────────────────────────┐
│                    QUICK COMMANDS                       │
├────────────────────────────────────────────────────────┤
│ Audit:        audit_openssf_baseline(level=3)          │
│ List checks:  list_available_checks()                  │
│ Fix issues:   remediate_audit_findings()  (preview)    │
│ Threat model: generate_threat_model()                  │
│ Attestation:  generate_attestation(sign=true)          │
│ Init config:  init_project_config()                    │
│ View config:  get_project_config()                     │
└────────────────────────────────────────────────────────┘
```

---

## Questions?

For issues or feedback:
- GitHub Issues: https://github.com/yourorg/baseline-mcp/issues
- OpenSSF Community: https://openssf.org/community/

---

*Generated for OpenSSF Baseline MCP Server v0.1.0*
*OSPS Specification: v2025.10.10*
