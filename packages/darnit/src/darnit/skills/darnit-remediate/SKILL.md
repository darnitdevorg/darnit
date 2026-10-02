---
name: darnit-remediate
description: Apply automated fixes for failing compliance controls. Shows a plan first, then creates a branch with fixes and optionally a PR. Use when the user wants to fix compliance failures, apply remediations, or create a compliance PR.
compatibility: Requires darnit MCP server running (darnit serve)
metadata:
  author: kusari-oss
  version: "2.1"
---

# Compliance Remediation

Show a dry-run plan of fixes for failing controls, get confirmation, then apply changes on a new branch. After applying, enhance generated template files with project-specific content.

## Workflow

### 1. Show dry-run plan

Call `remediate_audit_findings` with `dry_run: true` and any profile mentioned.
The tool internally runs an audit (or uses cached results) — do NOT run a separate audit call.

The response is a Markdown report followed by a fenced JSON block (the run record). Read the `plan` in the JSON block: each item has `file_changes`, `change_sets` (platform settings), `commands`, `previewable`, `requires_individual_approval`, and a `digest`; each change set has its own `digest`.

Present the plan:
- **File changes**: every file that will be created or modified
- **Platform changes**: for each change set, the target (repository or branch), every field as `before -> after`, and its `impact_notes` word for word. A high-impact change (repository visibility, organization settings) is shown on its own, with its impact, never folded into a list
- **Needs individual approval**: items with `requires_individual_approval: true` (unsafe, cannot be previewed exactly, or high-impact), each with its digest
- **Manual**: why these can't be auto-fixed, what to do instead
- **No fix available**: controls without remediation handlers

Ask the person which changes to apply. Ask about each platform change set and each item that needs individual approval separately; approving the file changes or "everything else" does not approve them.

### 2. Apply fixes (if confirmed)

Call `remediate_audit_findings` with:
- `dry_run: false`
- `approve: [...]`: only the digests (change-set digests and plan-item digests) the person approved, copied from the preview's JSON block
- `branch_name: "fix/compliance"` (or `"fix/compliance-{profile}"` if a profile was specified)
- `auto_commit: true`

`dry_run: false` is not an approval. Never pass it as a substitute for asking, and never pass a digest the person did not approve. Under the default operator policy (`prompt`), a platform change set whose digest is not in `approve` is not written; its outcome is `needs_approval`. If an outcome says `stale_preview`, the settings changed since the preview: show a new preview and ask again.

This single call creates the branch, applies all remediations, and commits. Do NOT make separate calls to `create_remediation_branch` or `commit_remediation_changes`.

### 3. Review generated files (quality check)

Most generated files are template-based and finished as-emitted — trust them and apply only mechanical fixes. A small set is intentionally a DRAFT that asks for human/agent triage; those carry an explicit marker.

#### 3a. Files that contain `<!-- darnit:verification-prompt-block -->`

These are review-required drafts (today: `THREAT_MODEL.md` / `docs/threatmodel/SUMMARY.md` produced by `generate_threat_model`). The marker block embeds the canonical instructions for triaging the file's findings — open the marker block, follow what it says.

**Workflow:**

1. Read the marker block and surface its instructions to the user along with a quick tally (how many findings, of what kinds, in which files).
2. **Ask the user before any extensive triage.** Large outputs (10+ findings) imply a long edit pass; the user should opt in. Offer to: (a) triage everything per the embedded prompt, (b) triage just a specific subset (e.g., one finding class), or (c) leave the draft as-emitted.
3. With consent: read each finding, judge true-positive vs false-positive against the actual source, and either enrich it with project-specific reasoning or remove it. Collapse repetitive same-cause findings into a single explanatory entry where it improves the document.
4. Preserve the marker block itself — its presence signals that the draft has gone through review. (You may remove the CLI-specific paragraph inside the block once you've triaged the CLI section per its own instructions.)

This is the ONE category of generated file where the rules in §3b about not enhancing do NOT apply.

#### 3b. All other generated files (templates)

Read them. The templates are designed to produce correct output — trust them.

**Fix ONLY these issues:**
- Broken syntax (malformed YAML, unclosed brackets, invalid workflow expressions)
- Unsubstituted `${...}` placeholder tokens that should have been filled in
- Factual contradictions within a single file (e.g., a section header says X but the body says the opposite)

**Do NOT change:**
- Tool or product names (e.g., Kusari Inspector references are correct — NEVER replace with CodeQL, Dependabot, etc.)
- Scanning frequencies, severity thresholds, or timeline values
- Policy content, process descriptions, or remediation steps
- Generic phrasing — do NOT "enhance" by injecting specific names, emails, or details from the repo. "Contact the maintainers" is fine as-is; changing it to "Contact Alice and Bob" adds nothing.
- Style preferences (wording, formatting, section order)

**The test for whether a change is justified:** Would a wrong value here cause someone to do the wrong thing or break a CI pipeline? If no, leave it alone.

If any files needed syntax fixes, make a new commit describing the specific fixes. If everything is clean (which is the expected case), say so and move on.

### 4. Offer PR creation

Ask if the user wants a PR. If yes, call `create_remediation_pr` and display the URL.

### 5. Summary

Show: branch name, controls fixed, files changed, PR URL (if created), and remaining manual items.

## Gotchas

- Always show the dry-run plan first. Never apply changes without confirmation.
- Do NOT call `audit_openssf_baseline` separately — `remediate_audit_findings` handles audit internally.
- Do NOT call `create_remediation_branch` or `commit_remediation_changes` separately — use the `branch_name` and `auto_commit` params instead.
- If `remediate_audit_findings` fails mid-way, report which files were already changed so the user can review.
- Unsafe remediations (`safe = false`), steps that cannot be previewed exactly, and high-impact platform changes run only when their own digest is in `approve`. Approving a batch never covers them.
- The operator's `[remediation]` policy decides how platform changes are made: `prompt` (approve by digest), `manual` (darnit only reports the steps; give them to the person), or `auto` (applied without a digest). The report states the policy in effect. Never try to change it from the repository.
- `enable_branch_protection` follows the same rules: it previews by default, never lowers existing settings, and applies only with `dry_run: false` and `approve` set to the change-set digest the person approved.
- Register darnit's MCP server at user scope (`darnit install` does this by default); a repository-scoped `uv run darnit serve` runs the repository's own copy of darnit.
- Only controls whose not-applicable claim is `honored` are skipped. Controls with a `pending` or `contradicted` claim are remediated like any other failing control. Do not confirm a pending claim to avoid a remediation; confirm one only when the operator explicitly tells you to.
- If there are unresolved data questions, the remediation tool will block and tell you. Suggest running `/darnit-data` first.
- The §3a verification-prompt-block files (today: `THREAT_MODEL.md` / `docs/threatmodel/SUMMARY.md`) are the ONE exception to §3b's "trust the template" stance. Always ask the user before doing a large triage pass on these — don't silently rewrite dozens of findings, and don't silently skip them either. The default "skip enhancement" rule from §3b is wrong for these files.

## Error handling

If the tool returns a data warning, suggest running `/darnit-data` first.
If branch creation fails, report the error — the tool aborts before applying any changes.
