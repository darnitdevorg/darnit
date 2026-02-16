# OpenSSF Baseline MCP Server
## Usage Guide & Presentation

---

## What is This?

**OpenSSF Baseline MCP Server** is an AI-powered compliance audit tool that checks repositories against the [OpenSSF Baseline](https://baseline.openssf.org) security standard (OSPS v2025.10.10).

### Key Features
- 🔍 **62 security controls** across 3 maturity levels
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
| `list_available_checks` | Show all 62 controls |
| `get_project_config` | View project.toml config |
| `init_project_config` | Create project.toml |
| `generate_threat_model` | STRIDE threat analysis |
| `generate_attestation` | Create signed attestation |
| `create_security_policy` | Generate SECURITY.md |
| `enable_branch_protection` | Configure branch rules |
| `remediate_audit_findings` | Auto-fix multiple issues |

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
- **Level 1** (24 controls) - Basic security hygiene
- **Level 2** (18 controls) - Enhanced security practices
- **Level 3** (20 controls) - Advanced security maturity

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

### Auto-Fix Multiple Issues
```
remediate_audit_findings(
  local_path="/path/to/repo",
  categories=["security_policy", "branch_protection"],
  dry_run=false
)
```

### Available Remediation Categories
| Category | Controls Fixed |
|----------|----------------|
| `security_policy` | OSPS-VM-01, VM-02, VM-03 |
| `branch_protection` | OSPS-AC-03.01, AC-03.02, QA-07.01 |
| `codeowners` | OSPS-GV-01.01, GV-01.02, GV-04.01 |
| `governance` | OSPS-GV-01.01, GV-01.02 |
| `contributing` | OSPS-GV-03.01, GV-03.02 |
| `dependabot` | OSPS-VM-05.* |
| `bug_report_template` | OSPS-DO-02.01 |

---

## Remediation Workflow

### Recommended Git Workflow
```
1. create_remediation_branch()     # Create fix/openssf-baseline-compliance
2. remediate_audit_findings()      # Apply fixes
3. commit_remediation_changes()    # Commit with message
4. create_remediation_pr()         # Open PR for review
```

### Example
```
# Step 1: Create branch
create_remediation_branch(branch_name="fix/security-baseline")

# Step 2: Apply fixes (dry run first)
remediate_audit_findings(categories=["all"], dry_run=true)

# Step 3: Apply fixes for real
remediate_audit_findings(categories=["all"], dry_run=false)

# Step 4: Commit and PR
commit_remediation_changes()
create_remediation_pr()
```

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
3. remediate_audit_findings()          # Fix easy issues
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
- Use `dry_run=true` before remediation
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
# Ensure you have admin access to the repository
# Check: Settings → Branches → Branch protection rules
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
│ Fix issues:   remediate_audit_findings(dry_run=false)  │
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
