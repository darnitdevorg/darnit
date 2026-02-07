## Why

When `audit_openssf_baseline` runs, it appends a passive "Help Improve This Audit" section listing pending context items (maintainers, CI provider, etc.) as optional follow-up questions. The LLM agent then asks the user a three-way question — "Would you like me to remediate the failures, provide more context to improve the audit, or dig into any specific controls?" — forcing the user to choose between getting accurate results and fixing problems. This is a false choice: the audit should collect pending context as part of its flow so the first audit result is as accurate as possible.

## What Changes

- **Replace passive context display with active collection**: Instead of the "Help Improve This Audit" appendix, the audit output will contain explicit `confirm_project_context()` calls with auto-detected values pre-filled, formatted as imperative instructions to the LLM agent
- **Add structured agent directives to audit output**: The audit output will include a "Next Steps" section that tells the LLM agent exactly what to do — first collect any pending context, then offer remediation — removing the need for a multi-choice question
- **Rewrite `_get_pending_context_section()`**: Current implementation shows informational bullets; new implementation generates ready-to-execute tool calls grouped by confidence level (auto-detected values to confirm vs. values the user must provide)

## Capabilities

### New Capabilities

- `audit-context-collection`: Defines how audit output directs the LLM agent to collect pending context automatically, including the format of agent directives, confidence-based grouping, and the expected flow (collect → re-audit or proceed to remediation)

### Modified Capabilities

- `framework-design`: The `format_results_markdown` output contract changes — the "Help Improve This Audit" section is replaced with structured agent directives. This affects the MCP tool response format that LLM agents consume.

## Impact

- **`packages/darnit/src/darnit/tools/audit.py`**: `_get_pending_context_section()` rewritten; `format_results_markdown()` gains a "Next Steps" section
- **MCP tool contract**: `audit_openssf_baseline` and `builtin_audit` responses change format — LLM agents consuming these will get directive-style output instead of informational output
- **No API changes**: Function signatures unchanged; this is a pure output format change
- **No breaking changes for programmatic consumers**: The output is markdown consumed by LLM agents, not parsed by code
