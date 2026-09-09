# Compliance Audit Report

**Framework:** OpenSSF Baseline v0.1.0
**Spec Version:** OSPS v2026.02.19
**Generated At:** <SCRUBBED-TIMESTAMP>
**Repository:** baseline-owner/baseline-repo
**Level Assessed:** 1

## Summary

| Status | Count | Meaning |
|--------|-------|---------|
| ✅ Pass | 1 | Control satisfied |
| ❌ Fail | 1 | **Control NOT satisfied - action required** |
| ⚠️ Needs Verification | 0 | **Could not verify automatically - manual review required** |
| 🤖 Pending LLM | 0 | Awaiting LLM analysis |
| ➖ N/A | 0 | Not applicable to this project |
| 🔴 Error | 0 | Check could not run |
| **Total** | 2 | |

> **Important:** Items marked ⚠️ Needs Verification are NOT informational warnings.
> They represent controls that could not be automatically verified and **require manual review**
> to determine compliance. Treat these as potential failures until verified.

> **🔧 Remediation:** To fix failures, use the MCP tools provided by this server:
> - `remediate_audit_findings()` - Auto-fix multiple issues
> - `enable_branch_protection()` - Configure branch protection
> - `create_security_policy()` - Generate SECURITY.md
> 
> **🔀 Git Workflow:** Use MCP tools for version control:
> - `create_remediation_branch()` → `commit_remediation_changes()` → `create_remediation_pr()`
> 
> **Do NOT run `gh` or `git` commands directly.** Always use the MCP tools for remediation.

## Level Compliance

- **Level 1:** ❌ Not Compliant (1 failed)

## Detailed Results

### ❌ FAIL - Action Required (1)

*These controls are NOT satisfied and must be addressed:*

- **OSPS-LE-03.01** (L1): None of the required files found: ['LICENSE', 'LICENSE.md', 'LICENSE.txt', 'LICENCE', 'LICENCE.md', 'LICENCE.txt', 'COPYING', 'COPYING.md', 'COPYING.txt']
  - *Resolved by:* `file_exists` (pass #0)

  > **ℹ️ Note for OSPS-LE-03.01:**
  > Add license file to repository.
  > 
  > **Remediation:**
  > 1. Create LICENSE or COPYING file in repository root
  > 2. Use full license text, not abbreviation
  > 3. GitHub will auto-detect standard licenses


### ✅ PASS (1)

*These controls are satisfied:*

- **OSPS-DO-01.01** (L1): Required file found: README.md
  - *Resolved by:* `file_exists` (pass #0)

---

## 🔧 Recommended Remediation

**IMPORTANT: Use the MCP tools below to fix issues. Do NOT run shell commands directly.**

### 🔀 Git Workflow for Remediations

Use these MCP tools to manage remediation changes through Git:

| Step | Tool | Description |
|------|------|-------------|
| 1 | `create_remediation_branch()` | Create a dedicated branch for fixes |
| 2 | *remediation tools above* | Apply the fixes |
| 3 | `commit_remediation_changes()` | Commit with auto-generated message |
| 4 | `create_remediation_pr()` | Open PR with compliance summary |

**Recommended workflow:**
```python
# 1. Create a branch for remediation work
create_remediation_branch(branch_name="fix/compliance", local_path="/path/to/repo")

# 2. Apply remediations (files will be created/modified)
remediate_audit_findings(local_path="/path/to/repo")

# 3. Commit the changes
commit_remediation_changes(message="Add Compliance compliance files", local_path="/path/to/repo")

# 4. Open a pull request
create_remediation_pr(title="Compliance Compliance", local_path="/path/to/repo")
```

Use `get_remediation_status()` at any time to check current git state and next steps.

> ⚠️ **Never run `gh api`, `git`, or other shell commands directly for remediation.**
> Always use the MCP tools provided by this server to ensure proper error handling
> and consistent implementation.

---

## Next Steps

**Step 1: Confirm project context** (8 items needed)

Call `get_pending_data(local_path="<FIXTURE>")` to start. It will walk you through each question one at a time.

**Step 2: Remediate failures** (1 controls failed)

```python
remediate_audit_findings(local_path="<FIXTURE>", dry_run=True)
```

---
