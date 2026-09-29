---
name: darnit-data
description: Collect missing project data to improve audit accuracy. Use when the user wants to set up project data, answer compliance questions, configure their project for auditing, or when an audit shows many WARN results due to missing data.
compatibility: Requires darnit MCP server running (darnit serve)
metadata:
  author: kusari-oss
  version: "1.2"
---

# Project Data Collection

Guide the user through providing missing project data that darnit needs for accurate audits. A value darnit detected is only a candidate: it is shown to the user as unconfirmed data with where it came from, and it counts only after the user confirms it.

## Workflow

1. Call `get_pending_data` MCP tool with `local_path` set to the repository root and `level` set to `3`.
   - If the user mentioned a profile, pass it as the `profile` parameter to scope questions to that profile's controls.
   - This call writes nothing.

2. The tool returns a batch of `questions` (and `ask_user_batch` for the ones a selector can hold). For each question:
   - If it has a `candidate`: show the user `candidate.value` and `candidate.origin`, labelled unconfirmed, and ask whether to accept it. Never present it as a fact or as the default.
   - Otherwise: ask the question. For an enum, offer every value in `allowed_values`. `format_hint` shows the expected format; never offer it as an answer.
   - If the user says "skip" or "I don't know": move on. Don't block.

3. After the user has answered, call `confirm_project_data` MCP tool, with `owner` and `repo` (and `host` when not github.com) naming the repository:
   - The user accepted a candidate: pass `accept_candidates={"<key>": <that question's candidate.digest>}`. Fill in the digest only now, after the user answered yes; never before, and never on your own. The tool re-runs detection and refuses if the candidate changed; then show the new candidate and ask again.
   - The user gave a value: pass it as the key's parameter (`<key>=<the user's answer>`). Never type a detected value as an answer, and never pass anything the user did not say.

4. Call `get_pending_data` again. If `status` is `"complete"`, move to step 5. Otherwise repeat from step 2.

5. Summarize what was collected:
   - Values confirmed (accepted candidates and values the user gave)
   - Skipped questions
   - Which controls are now unblocked
   - Suggest running `/darnit-audit` to see improved results

## Gotchas

- Never fill in values on the user's behalf. A candidate is not a value until the user confirms it, however confident its origin.
- Command templates and `answer_mapping` hold placeholders only (`<the person's answer>`, `<candidate.digest>`). Replace a placeholder only with what the user actually answered.
- Answers submitted to an ActionPlan `collect_context` step (`submit_action_result`) are used for that run only and are never saved. To record a value, use `confirm_project_data`.
- Confirmed values are recorded in `.project/darnit.yaml` (the value under `context:` and who confirmed it, when, and on what basis under `confirmations:`) when the operator trusts the repository; otherwise they are recorded operator-side and nothing is written to the repository. `.project/project.yaml` is never written by this workflow.
- A value in `.project/` without a confirmation record is a candidate too (origin `stored_unconfirmed`, with its file and field). Show it to the user and confirm or correct it like any other candidate; a hand edit to a confirmed value makes it a candidate again.
- Register darnit's MCP server at user scope (`darnit install` does this by default), not in a configuration file committed to the repository; a repository-scoped `uv run darnit serve` runs the repository's own copy of darnit.
- Project data that makes a control not applicable (for example "no releases") is a not-applicable claim. It counts only when the operator trusts the repository and no evidence contradicts it; otherwise the audit reports it as pending and the control counts as non-compliant.
- Pending claims can be confirmed with `confirm_project_data` (`confirm_not_applicable` plus `owner`/`repo`); the confirmation is stored on the operator's machine, not in the repository. Only do this when the operator explicitly tells you to confirm that specific claim. Never confirm a claim on your own, and never treat a user's answer to a data question as a confirmation of a claim.
- Questions come in the framework's definition order. Present them in order.
- Do not edit `.project/` files by hand to record answers; `confirm_project_data` is the only way to record them. If `get_pending_data` is not available, the implementation module may not support data collection; say so and stop.

## Error handling

If all data is already collected, report that and suggest running `/darnit-audit`.
If `confirm_project_data` refuses a key, report the reason to the user; nothing was written for that key.
