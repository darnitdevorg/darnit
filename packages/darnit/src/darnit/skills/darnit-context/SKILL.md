---
name: darnit-context
description: Collect missing project context to improve audit accuracy. Use when the user wants to set up project context, answer compliance questions, configure their project for auditing, or when an audit shows many WARN results due to missing context.
compatibility: Requires darnit MCP server running (darnit serve)
metadata:
  author: kusari-oss
  version: "1.1"
---

# Project Context Collection

Guide the user through providing missing project context that darnit needs for accurate audits. Auto-detected values are presented for confirmation; remaining values are asked as questions.

## Workflow

1. Call `get_pending_context` MCP tool with `local_path` set to the repository root and `level` set to `3`.
   - If the user mentioned a profile, pass it as the `profile` parameter to scope questions to that profile's controls.

2. The tool returns a batch of questions. For each one:
   - If auto-detected with high confidence: present it as "We detected X — is this correct?" and wait for confirmation.
   - If not auto-detected: ask the question clearly, including any hints and examples from the response.
   - If the user says "skip" or "I don't know": move on. Don't block.

3. For each answer, call `confirm_project_context` MCP tool with the appropriate key and value.

4. Call `get_pending_context` again. If `status` is `"complete"`, move to step 5. Otherwise repeat from step 2.

5. Summarize what was collected:
   - Values confirmed (auto-detected and user-provided)
   - Skipped questions
   - Which controls are now unblocked
   - Suggest running `/darnit-audit` to see improved results

## Gotchas

- Never fill in values on the user's behalf. Auto-detected values must be confirmed, not silently applied.
- The `get_pending_context` response includes an `answer_mapping` field showing how to map each answer to `confirm_project_context` parameters.
- Questions are sorted by priority (number of affected controls). Present them in order.
- Context is persisted to `.project/project.yaml` — this file should be committed to the repository.
- If `get_pending_context` is not available, the implementation module may not support context collection. Suggest manually editing `.project/project.yaml`.

## Error handling

If all context is already collected, report that and suggest running `/darnit-audit`.
