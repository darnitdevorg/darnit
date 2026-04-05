---
name: darnit-comply
description: Run the full compliance pipeline — audit, collect context, remediate failures, and create a PR. Use when the user wants to fix all compliance issues, bring a repo into compliance end-to-end, or run the complete compliance workflow.
compatibility: Requires darnit MCP server running (darnit serve) and gh CLI for PR creation
metadata:
  author: kusari-oss
  version: "2.0"
---

# Full Compliance Pipeline

Orchestrate the complete audit-to-PR workflow with minimal MCP round-trips. Let the tools handle the plumbing; add value by enhancing generated content.

## Discovering tools

Darnit registers tools per implementation module. Look for available tools matching `audit_*` for the audit step, and `remediate_audit_findings` for remediation. If the user specifies a framework, use those tools. If only one set is available, use it. If multiple exist, ask.

## Workflow

### 1. Initial audit

Call the appropriate `audit_*` tool with `output_format: "summary"` and any profile the user mentioned. The "summary" format returns compact JSON (~5-8K vs ~164K for full JSON). Present a brief summary: total controls, pass/fail/warn counts, compliance percentage. Resolve any PENDING_LLM controls using your own reasoning.

### 2. Collect context (if needed)

If WARN controls exist due to missing context:
- Tell the user you'll collect context to improve accuracy
- Follow the `/darnit-context` skill workflow: call `get_pending_context`, present questions, call `confirm_project_context` for answers
- Continue until `status: "complete"` or the user says "skip remaining"

### 3. Remediation plan

If there are FAIL controls with auto-fixes:
- Call `remediate_audit_findings` with `dry_run: true`
- Present the plan, distinguishing safe auto-fixes from unsafe/manual ones
- Ask: "Apply the safe auto-fixes?"

If no failures or no auto-fixes: report the status and list manual steps. Skip to step 6.

### 4. Apply fixes (if confirmed)

Call `remediate_audit_findings` with:
- `dry_run: false`
- `branch_name: "fix/compliance"` (or `"fix/compliance-{profile}"`)
- `auto_commit: true`

This single call creates the branch, applies all remediations, and commits.
Do NOT make separate calls to `create_remediation_branch` or `commit_remediation_changes`.

### 5. Enhance generated files (value-add)

Read the generated template files and improve them with project-specific content:
- Fill in real project details (maintainer names, security contact, CI/CD specifics)
- Improve language and formatting
- Make templates feel like real documentation rather than boilerplate

If files were enhanced, make a new commit with the improvements.

### 6. Create PR and final report

Ask if the user wants a PR. If yes, call `create_remediation_pr` and display the URL.

Show before/after compliance comparison, list of changes made, and remaining manual items.

## Gotchas

- Always show the remediation plan and get confirmation before applying changes. Never auto-apply.
- Use `output_format: "summary"` for audits to keep token usage low.
- Do NOT run a separate audit before calling `remediate_audit_findings` — it handles audit internally.
- Do NOT call `create_remediation_branch` or `commit_remediation_changes` separately — use the built-in `branch_name` and `auto_commit` params.
- Unsafe remediations (requiring API access or manual review) must be clearly excluded from automatic application.
- If any step fails, report what was accomplished and suggest continuing manually.
- Never leave the repository in a broken state — if remediation partially applied, report which files changed.
- Tool names vary by implementation. Don't hardcode — discover available tools.
