---
name: darnit-comply
description: Run the full compliance pipeline — audit, collect context, remediate failures, and create a PR. Use when the user wants to fix all compliance issues, bring a repo into compliance end-to-end, or run the complete compliance workflow.
compatibility: Requires darnit MCP server running (darnit serve) and gh CLI for PR creation
metadata:
  author: kusari-oss
  version: "1.1"
---

# Full Compliance Pipeline

Orchestrate the complete audit-to-PR workflow. Run audit, collect missing context, re-audit, show remediation plan, apply fixes, and create a PR.

## Discovering tools

Darnit registers tools per implementation module. Look for available tools matching `audit_*` for the audit step, and `remediate_audit_findings` for remediation. If the user specifies a framework, use those tools. If only one set is available, use it. If multiple exist, ask.

## Workflow

### 1. Initial audit

Call the appropriate `audit_*` tool with `output_format: "json"` and any profile the user mentioned. Present a brief summary: total controls, pass/fail/warn counts, compliance percentage. Resolve any PENDING_LLM controls using your own reasoning.

### 2. Collect context (if needed)

If WARN controls exist due to missing context:
- Tell the user you'll collect context to improve accuracy
- Follow the `/darnit-context` skill workflow: call `get_pending_context`, present questions, call `confirm_project_context` for answers
- Continue until `status: "complete"` or the user says "skip remaining"

### 3. Re-audit (if context was collected)

Call the audit tool again. Show the improvement: "X controls improved from WARN to PASS."

### 4. Remediation plan

If there are FAIL controls with auto-fixes:
- Call `remediate_audit_findings` with `dry_run: true`
- Present the plan, distinguishing safe auto-fixes from unsafe/manual ones
- Ask: "Apply the safe auto-fixes?"

If no failures or no auto-fixes: report the status and list manual steps.

### 5. Apply fixes (if confirmed)

1. `create_remediation_branch` — branch name like "fix/compliance"
2. `remediate_audit_findings` with `dry_run: false`
3. `commit_remediation_changes`
4. Ask if the user wants a PR → `create_remediation_pr`

### 6. Final report

Show before/after compliance comparison, list of changes made, and remaining manual items.

## Gotchas

- Always show the remediation plan and get confirmation before applying changes. Never auto-apply.
- Unsafe remediations (requiring API access or manual review) must be clearly excluded from automatic application.
- If any step fails, report what was accomplished and suggest continuing manually.
- Never leave the repository in a broken state — if remediation partially applied, report which files changed.
- Tool names vary by implementation. Don't hardcode — discover available tools.
