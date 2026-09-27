---
name: darnit-data
description: Collect missing project data to improve audit accuracy. Use when the user wants to set up project data, answer compliance questions, configure their project for auditing, or when an audit shows many WARN results due to missing data.
compatibility: Requires darnit MCP server running (darnit serve)
metadata:
  author: kusari-oss
  version: "1.1"
---

# Project Data Collection

Guide the user through providing missing project data that darnit needs for accurate audits. Auto-detected values are presented for confirmation; remaining values are asked as questions.

## Workflow

1. Call `get_pending_data` MCP tool with `local_path` set to the repository root and `level` set to `3`.
   - If the user mentioned a profile, pass it as the `profile` parameter to scope questions to that profile's controls.

2. The tool returns a batch of questions. For each one:
   - If auto-detected with high confidence: present it as "We detected X — is this correct?" and wait for confirmation.
   - If not auto-detected: ask the question clearly, including any hints and examples from the response.
   - If the user says "skip" or "I don't know": move on. Don't block.

3. For each answer, call `confirm_project_data` MCP tool with the appropriate key and value.

4. Call `get_pending_data` again. If `status` is `"complete"`, move to step 5. Otherwise repeat from step 2.

5. Summarize what was collected:
   - Values confirmed (auto-detected and user-provided)
   - Skipped questions
   - Which controls are now unblocked
   - Suggest running `/darnit-audit` to see improved results

## Gotchas

- Never fill in values on the user's behalf. Auto-detected values must be confirmed, not silently applied.
- Register darnit's MCP server at user scope (`darnit install` does this by default), not in a configuration file committed to the repository; a repository-scoped `uv run darnit serve` runs the repository's own copy of darnit.
- Project data that makes a control not applicable (for example "no releases") is a not-applicable claim. It counts only when the operator trusts the repository and no evidence contradicts it; otherwise the audit reports it as pending and the control counts as non-compliant.
- Pending claims can be confirmed with `confirm_project_data` (`confirm_not_applicable` plus `owner`/`repo`); the confirmation is stored on the operator's machine, not in the repository. Only do this when the operator explicitly tells you to confirm that specific claim. Never confirm a claim on your own, and never treat a user's answer to a data question as a confirmation of a claim.
- The `get_pending_data` response includes an `answer_mapping` field showing how to map each answer to `confirm_project_data` parameters.
- Questions are sorted by priority (number of affected controls). Present them in order.
- Data is persisted to `.project/project.yaml` — this file should be committed to the repository.
- If `get_pending_data` is not available, the implementation module may not support data collection. Suggest manually editing `.project/project.yaml`.

## Error handling

If all data is already collected, report that and suggest running `/darnit-audit`.
