---
name: darnit-remediate
description: Apply automated fixes for failing compliance controls. Shows a plan first, then creates a branch with fixes and optionally a PR. Use when the user wants to fix compliance failures, apply remediations, or create a compliance PR.
compatibility: Requires darnit MCP server running (darnit serve)
metadata:
  author: kusari-oss
  version: "2.0"
---

# Compliance Remediation

Show a dry-run plan of fixes for failing controls, get confirmation, then apply changes on a new branch. After applying, enhance generated template files with project-specific content.

## Workflow

### 1. Show dry-run plan

Call `remediate_audit_findings` with `dry_run: true` and any profile mentioned.
The tool internally runs an audit (or uses cached results) — do NOT run a separate audit call.

Present the plan:
- **Safe auto-fixes**: what will be created or modified
- **Unsafe / manual**: why these can't be auto-fixed, what to do instead
- **No fix available**: controls without remediation handlers

Ask: "Apply the safe auto-fixes? This will create a new branch."

### 2. Apply fixes (if confirmed)

Call `remediate_audit_findings` with:
- `dry_run: false`
- `branch_name: "fix/compliance"` (or `"fix/compliance-{profile}"` if a profile was specified)
- `auto_commit: true`

This single call creates the branch, applies all remediations, and commits. Do NOT make separate calls to `create_remediation_branch` or `commit_remediation_changes`.

### 3. Enhance generated files (value-add)

This is where the skill adds unique value beyond what the tool provides. Read the generated template files and improve them with project-specific content:

- Read each generated file (e.g., SECURITY.md, CONTRIBUTING.md, docs/*.md)
- Enhance with real project details: actual maintainer names, real security contact, specific CI/CD details
- Improve language, formatting, and completeness
- Make templates feel like real documentation rather than boilerplate

If any files were enhanced, make a new commit with the improvements.

### 4. Offer PR creation

Ask if the user wants a PR. If yes, call `create_remediation_pr` and display the URL.

### 5. Summary

Show: branch name, controls fixed, files changed, PR URL (if created), and remaining manual items.

## Gotchas

- Always show the dry-run plan first. Never apply changes without confirmation.
- Do NOT call `audit_openssf_baseline` separately — `remediate_audit_findings` handles audit internally.
- Do NOT call `create_remediation_branch` or `commit_remediation_changes` separately — use the `branch_name` and `auto_commit` params instead.
- If `remediate_audit_findings` fails mid-way, report which files were already changed so the user can review.
- The tool respects the `safe` flag on remediations — only safe remediations are auto-applied. Unsafe ones are listed but excluded.
- If there are unresolved context questions, the remediation tool will block and tell you. Suggest running `/darnit-context` first.

## Error handling

If the tool returns a context warning, suggest running `/darnit-context` first.
If branch creation fails, report the error — the tool aborts before applying any changes.
