---
name: darnit-comply
description: Run the full compliance pipeline — audit, collect data, remediate failures, and create a PR. Use when the user wants to fix all compliance issues, bring a repo into compliance end-to-end, or run the complete compliance workflow.
compatibility: Requires darnit MCP server running (darnit serve) and gh CLI for PR creation
metadata:
  author: kusari-oss
  version: "2.3"
---

# Full Compliance Pipeline

Orchestrate the complete audit-to-PR workflow with minimal MCP round-trips. Let the tools handle the plumbing; add value by enhancing generated content.

## Registration

Register darnit's MCP server at user scope (`darnit install` does this by default), not in a configuration file committed to the repository. A repository-scoped registration lets the repository choose how darnit is launched; for example, a repository-scoped `uv run darnit serve` runs the repository's own copy of darnit. If an audit result warns that darnit is running from inside the audited repository, tell the user and recommend user-scope registration. Do not approve repository-scoped darnit servers in repositories the user does not control.

## Discovering tools

Darnit registers tools per implementation module. Look for available tools matching `audit_*` for the audit step, and `remediate_audit_findings` for remediation. If the user specifies a framework, use those tools. If only one set is available, use it. If multiple exist, ask.

## The repository

Name the audited repository on every darnit call, the audit included: `owner` and `repo`, plus `host` when it is not github.com. darnit applies the person's confirmed answers, stored PASS candidates, and trust only to a named repository, and never takes the name from the checkout's remotes. Before the first call, ask the person to confirm which repository this is, offering the checkout's `origin` remote as the suggestion, and use their answer for every call.

## Workflow

### 1. Initial audit

Call the appropriate `audit_*` tool with `owner` and `repo` naming the audited repository, `output_format: "summary"`, and any profile the user mentioned. The "summary" format returns compact JSON; PENDING rows carry `pending.kind`. Do not use `output_format: "json"`: it is too large for a tool result. Present a brief summary: total controls, pass/fail/warn counts, compliance percentage.

### 2. Judgments

If any row has `pending.kind = "llm_judgment"`, call `get_judgment_requests` with `owner`, `repo`, and `local_path` naming the audited repository, and follow the `procedure` in its result until `remaining` is empty. Never state your own verdict as the audit result: a `"pass"` becomes a PASS candidate that stays non-compliant until the operator confirms it.

### 3. Collect data

Tell the user you'll collect project data, then call `get_pending_data` with `owner`, `repo`, and `local_path` naming the audited repository, and follow the `procedure` in its result until `status` is `"complete"` or the user says to skip the rest.

### 4. Remediation plan

If data was confirmed in step 3, call the audit again (same arguments) and show what changed: confirmed answers can make controls pass or not applicable.

If there are FAIL controls with auto-fixes:
- Call `remediate_audit_findings` with `dry_run: true`, and `owner` and `repo` naming the audited repository
- Read the fenced JSON block after the report: its `plan` lists each item's `file_changes`, `change_sets`, `requires_individual_approval`, and `digest`
- Present every file change; every platform change set with each field as `before -> after`, its `impact_notes`, and its digest; and every item that needs individual approval. Show a high-impact change (repository visibility, organization settings) on its own with its impact
- Ask the person which changes to apply, asking separately about each platform change set and each item that needs individual approval

If no failures or no auto-fixes: report the status and list manual steps. Skip to step 7.

### 5. Apply fixes (if confirmed)

Call `remediate_audit_findings` with:
- `owner` and `repo` naming the audited repository
- `dry_run: false`
- `approve: [...]`: only the digests the person approved, copied from the preview
- `branch_name: "fix/compliance"` (or `"fix/compliance-{profile}"`)
- `auto_commit: true`

`dry_run: false` is not an approval: never pass it instead of asking, and never pass a digest the person did not approve. Report outcomes as the tool states them: `needs_approval` (not written), `manual` (give the person the steps), `unchanged` with `stale_preview` (preview again and re-ask).

This single call creates the branch, applies all remediations, and commits.
Do NOT make separate calls to `create_remediation_branch` or `commit_remediation_changes`.

### 6. Enhance generated files (value-add)

Read the generated template files and improve them with project-specific content:
- Fill in real project details (maintainer names, security contact, CI/CD specifics)
- Improve language and formatting
- Make templates feel like real documentation rather than boilerplate

If files were enhanced, make a new commit with the improvements.

### 7. Create PR and final report

Ask if the user wants a PR. If yes, call `create_remediation_pr` and display the URL.

Show before/after compliance comparison, list of changes made, and remaining manual items.

## Gotchas

- Always show the remediation plan and get confirmation before applying changes. Never auto-apply.
- Use `output_format: "summary"` for audits to keep token usage low.
- Do NOT run a separate audit before calling `remediate_audit_findings` — it handles audit internally.
- Do NOT call `create_remediation_branch` or `commit_remediation_changes` separately — use the built-in `branch_name` and `auto_commit` params.
- Unsafe remediations, steps that cannot be previewed exactly, and high-impact platform changes run only when the person approved their own digest; a batch approval never covers them.
- Platform changes follow the operator's `[remediation]` policy (`prompt`, `manual`, or `auto`), stated in the report. Never try to change it from the repository.
- If any step fails, report what was accomplished and suggest continuing manually.
- Never leave the repository in a broken state — if remediation partially applied, report which files changed.
- A control with an `assertion` block carries a not-applicable claim from the repository (`.project/darnit.yaml`, or project data that makes the control not applicable). Report its `assertion.outcome`: `honored` (N/A, labelled asserted), `pending` (evaluated normally and counted as non-compliant until the operator trusts the repository or confirms the claim), or `contradicted` (evidence contradicts it; the claim is ignored). Never describe a pending claim as N/A.
- Only confirm a pending claim when the operator explicitly tells you to confirm that claim. Never confirm one on your own judgment, from the claim's reason, or because confirming would improve the result.
- The same holds for PASS candidates (`confirm_pass_candidate(control_ids=[...], owner=..., repo=...)`): confirm one only on the operator's explicit instruction to confirm that candidate.
- Tool names vary by implementation. Don't hardcode — discover available tools.
