---
name: darnit-remediate
description: Apply automated fixes for failing compliance controls. Shows a plan first, then creates a branch with fixes and optionally a PR. Use when the user wants to fix compliance failures, apply remediations, or create a compliance PR.
compatibility: Requires darnit MCP server running (darnit serve) and gh CLI for PR creation
metadata:
  author: kusari-oss
  version: "1.2"
---

# Compliance Remediation

Apply automated fixes for failing compliance controls on a new branch.

## Quick vs reviewed mode

If the user signals they want speed (e.g., "quick", "just fix it", "skip the review", "apply everything"), use **quick mode**: skip the dry-run, create the branch, apply fixes, commit, and report what changed. Do not ask for confirmation.

Otherwise, use **reviewed mode** (default): show a dry-run plan first, get confirmation, then apply.

## Quick mode

1. Call `create_remediation_branch`
2. Call `remediate_audit_findings` with `dry_run: false`
3. Call `commit_remediation_changes`
4. Report: branch name, controls fixed, files changed
5. Ask if the user wants a PR

## Reviewed mode

### 1. Get audit results

Check conversation context for recent audit results. If none exist, call the appropriate `audit_*` MCP tool with `output_format: "json"`.

### 2. Show dry-run plan

Call `remediate_audit_findings` with `dry_run: true`.

Present the plan:
- **Safe auto-fixes**: what will be created or modified
- **Unsafe / manual**: why these can't be auto-fixed, what to do instead

Ask: "Apply the safe auto-fixes? This will create a new branch."

### 3. Apply fixes (if confirmed)

1. `create_remediation_branch`
2. `remediate_audit_findings` with `dry_run: false`
3. `commit_remediation_changes`

### 4. Offer PR creation

Ask if the user wants a PR. If yes, call `create_remediation_pr` and display the URL.

## Gotchas

- In reviewed mode, always show the plan before applying. In quick mode, skip straight to applying.
- The tool only applies `safe: true` remediations. Unsafe ones are always skipped regardless of mode.
- If there are unresolved context questions, the remediation tool will block. Suggest running `/darnit-context` first.
- If `remediate_audit_findings` fails mid-way, report which files were already changed.
- Tool names vary by implementation. Discover available tools from the darnit MCP server.
