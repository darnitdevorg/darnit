---
name: darnit-data
description: Collect missing project data to improve audit accuracy. Use when the user wants to set up project data, answer compliance questions, configure their project for auditing, or when an audit shows many WARN results due to missing data.
compatibility: Requires darnit MCP server running (darnit serve)
metadata:
  author: kusari-oss
  version: "2.1"
---

# Project Data Collection

Guide the user through providing missing project data that darnit needs for accurate audits. A value darnit detected is only a candidate: it is shown to the user as unconfirmed data with where it came from, and it counts only after the user confirms it.

## The repository

Name the audited repository on every darnit call, the audit included: `owner` and `repo`, plus `host` when it is not github.com. darnit applies the person's confirmed answers, stored PASS candidates, and trust only to a named repository, and never takes the name from the checkout's remotes. Before the first call, ask the person to confirm which repository this is, offering the checkout's `origin` remote as the suggestion, and use their answer for every call.

## Workflow

1. Call `get_pending_data` with `local_path` set to the repository root and `owner` and `repo` naming the repository. If the user mentioned a profile, pass it as `profile`. This call writes nothing.

2. Follow the `procedure` in its result, step by step. It says how to show candidates, how to ask the questions, how to call `confirm_project_data`, when to call `get_pending_data` again, how to review values stored without a confirmation, and what to summarize at the end. Each `confirm_project_data` result names the next call.

3. When `status` is `"complete"` and the procedure's review and summary are done, suggest re-running the audit to see the updated results.

## Gotchas

- Never fill in values on the user's behalf. A candidate is not a value until the user confirms it, however confident its origin.
- Do not edit `.project/` files by hand to record answers; `confirm_project_data` is the only way to record them. `.project/project.yaml` is never written by this workflow.
- Confirmed values are recorded in `.project/darnit.yaml` when the operator trusts the repository; otherwise they are recorded operator-side and nothing is written to the repository.
- Answers submitted to an ActionPlan `collect_context` step (`submit_action_result`) are used for that run only and are never saved. To record a value, use `confirm_project_data`.
- `expires_at={"<key>": "<date the user gave>"}` records an expiry with a confirmation, only when the user asks for one.
- Each framework's server has its own `confirm_project_data`, covering only that framework's keys. Use the tool of the server whose framework asked the question.
- Register darnit's MCP server at user scope (`darnit install` does this by default), not in a configuration file committed to the repository; a repository-scoped `uv run darnit serve` runs the repository's own copy of darnit.
- Project data that makes a control not applicable (for example "no releases") is a not-applicable claim. It counts only when the operator trusts the repository and no evidence contradicts it. Confirm a pending claim (`confirm_not_applicable`) only when the operator explicitly names that claim; a user's answer to a data question is not a confirmation of a claim.

## Error handling

If `get_pending_data` is not available, the implementation module may not support data collection; say so and stop.
If all data is already collected, report that and suggest re-running the audit.
If `confirm_project_data` refuses a key, report the reason to the user; nothing was written for that key.
