## 1. Implement `_get_next_steps_section()`

- [x] 1.1 Create `_get_next_steps_section(local_path, summary)` in `packages/darnit/src/darnit/tools/audit.py` that returns `list[str]` of markdown lines. Include the dynamic step counter logic: increment step number for each applicable block (context, remediation, manual review). Return empty list when no steps apply.
- [x] 1.2 Implement the context collection step: call `get_pending_context(local_path)`, split results into auto-detected (items with `current_value`) and unknown (items without). Format auto-detected items as a single compound `confirm_project_context()` call with all values pre-filled. Format unknown items as individual prompts with placeholders and definition text. Cap at 8 items per group.
- [x] 1.3 Implement the remediation step: emit a `remediate_audit_findings()` directive when `summary["FAIL"] > 0`. Include the `local_path` parameter pre-filled.
- [x] 1.4 Implement the manual review step: emit a brief note about WARN controls when `summary["WARN"] > 0`.
- [x] 1.5 Add the re-audit directive after the context collection step: tell the agent to re-run `audit_openssf_baseline(local_path=...)` after confirming context.

## 2. Wire up in `format_results_markdown()`

- [x] 2.1 Replace the call to `_get_pending_context_section(local_path)` (around line 728) with `_get_next_steps_section(local_path, summary)` in `format_results_markdown()`.
- [x] 2.2 Delete the old `_get_pending_context_section()` function (lines 735-813).

## 3. Tests

- [x] 3.1 Add test: audit output with pending context and failures produces Next Steps with context collection as step 1 and remediation as step 2. Verify `confirm_project_context()` call appears in output. Verify "Help Improve This Audit" does NOT appear.
- [x] 3.2 Add test: audit output with failures but no pending context produces Next Steps starting with remediation (no context step).
- [x] 3.3 Add test: audit output with all passing and no pending context produces no Next Steps section.
- [x] 3.4 Add test: auto-detected values appear as a single compound `confirm_project_context()` call; unknown values appear as individual prompts with definition text.
- [x] 3.5 Add test: re-audit directive (`audit_openssf_baseline`) appears after context collection step.

## 4. Verify

- [x] 4.1 Run `uv run ruff check .` — all checks pass.
- [x] 4.2 Run `uv run pytest tests/ --ignore=tests/integration/ -q` — no new failures.
- [x] 4.3 Grep: zero hits for "Help Improve This Audit" in `packages/darnit/src/darnit/tools/audit.py`.
