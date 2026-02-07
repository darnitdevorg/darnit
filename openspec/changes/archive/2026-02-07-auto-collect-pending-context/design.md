## Context

The audit output from `format_results_markdown()` in `packages/darnit/src/darnit/tools/audit.py` is consumed by LLM agents via MCP tools (`audit_openssf_baseline`, `builtin_audit`). Currently, the function appends a passive "Help Improve This Audit" section (produced by `_get_pending_context_section()`, lines 735-813) that lists pending context as informational bullets. The LLM agent then improvises a multi-choice question, which splits the user's attention between context collection and remediation.

The pending context data is already available via `get_pending_context()` from `context_storage.py`, which returns `ContextPromptRequest` objects containing:
- `key`: context key name
- `definition`: ContextDefinition with prompt, hint, examples, type
- `current_value`: auto-detected ContextValue if sieve found something (or None)
- `control_ids`: which controls this affects
- `priority`: number of controls affected

## Goals / Non-Goals

**Goals:**
- Replace the "Help Improve This Audit" section with a "Next Steps" section containing ordered, imperative agent directives
- Group pending context by confidence: auto-detected values in a single compound tool call, unknown values listed individually with prompts
- Direct the agent to re-audit after context is collected
- Keep the change scoped to `_get_pending_context_section()` and the tail of `format_results_markdown()`

**Non-Goals:**
- Changing how `get_pending_context()` works (data layer unchanged)
- Changing function signatures or return types
- Adding automatic context confirmation without user involvement (the agent still presents values to the user)
- Consolidating the 7 duplicate owner/repo detectors (deferred)
- Changing SARIF or JSON output formats (only markdown affected)

## Decisions

### 1. Rewrite `_get_pending_context_section()` → `_get_next_steps_section()`

**Decision:** Rename and rewrite the function to produce the full Next Steps section, not just the context part.

**Rationale:** The Next Steps section is a single cohesive block with 3 potential steps (context → remediation → manual review). Building it as one function keeps the ordering logic in one place rather than scattering steps across `format_results_markdown()`.

**New signature:**
```python
def _get_next_steps_section(
    local_path: str | None,
    summary: dict[str, int],
) -> list[str]:
```

The `summary` parameter is needed to determine whether remediation and manual review steps should appear (based on FAIL and WARN counts).

**Alternative considered:** Keep `_get_pending_context_section()` and add a separate `_get_remediation_directive()`. Rejected because the numbering/ordering logic would be split across functions, making it fragile.

### 2. Compound tool call for auto-detected values

**Decision:** Emit a single `confirm_project_context()` call with all auto-detected values as keyword arguments, rather than one call per item.

**Example output:**
```markdown
**Step 1: Confirm project context** (auto-detected — verify and correct if needed)

```python
confirm_project_context(
    local_path="/path/to/repo",
    maintainers=["@alice", "@bob"],  # detected from CODEOWNERS
    ci_provider="github",  # detected from .github/workflows/
)
```​

> After confirming, re-run: `audit_openssf_baseline(local_path="/path/to/repo")`
```

**Rationale:** A single compound call reduces user interaction to one confirmation step. The agent can present it, the user says "yes" or corrects a value, and the agent executes it. One call per item would create a tedious confirm-execute loop.

### 3. Unknown values rendered as individual prompts with placeholders

**Decision:** For pending context items without auto-detection, list each individually with its prompt text and a placeholder tool call.

**Example output:**
```markdown
The following context needs your input:

- **governance_model**: What governance model does this project use?
  Options: `bdfl`, `meritocracy`, `democracy`, `corporate`, `foundation`, `committee`, `other`
  ```python
  confirm_project_context(governance_model="<ask user>")
  ```​
```

**Rationale:** Without a detected value, we can't pre-fill the call. Showing the prompt and options gives the agent enough information to ask the user a targeted question rather than a vague one.

**Alternative considered:** Omit unknown values entirely and only show auto-detected ones. Rejected because this would leave context permanently uncollected if sieve detection doesn't cover it.

### 4. Step numbering is dynamic based on what's present

**Decision:** Steps are numbered 1, 2, 3 dynamically — only steps that apply are included. Step order is always: context collection → remediation → manual review.

| Has pending context? | Has failures? | Has WARN? | Steps shown |
|---------------------|--------------|-----------|-------------|
| Yes | Yes | Yes | 1: context, 2: remediate, 3: manual |
| Yes | Yes | No | 1: context, 2: remediate |
| Yes | No | Yes | 1: context, 2: manual |
| No | Yes | Yes | 1: remediate, 2: manual |
| No | Yes | No | 1: remediate |
| No | No | Yes | 1: manual |
| No | No | No | (no section) |

**Rationale:** Static step numbers with "N/A" markers add noise. Dynamic numbering keeps the output clean and actionable.

### 5. Remove the existing "Help Improve This Audit" call site

**Decision:** In `format_results_markdown()`, replace the call to `_get_pending_context_section(local_path)` (lines 728-730) with a call to `_get_next_steps_section(local_path, summary)`. The old function is deleted entirely.

The new call site is positioned at the very end of the markdown output, after the git workflow section (which stays as-is since it's specifically about the remediation git workflow, not about what to do next).

## Risks / Trade-offs

**[Output length increase for complex cases]** → The compound tool call with many auto-detected values could be long. Mitigation: cap at 8 pending items in the auto-detected group; show "...and N more" with a `get_pending_context()` reference for the rest. This matches the existing cap of 5 items.

**[LLM agents may not follow directives perfectly]** → The output is a suggestion to the agent, not a hard contract. Mitigation: Use imperative language ("Execute this tool call", "Re-run the audit") and code blocks with valid Python syntax. LLMs are good at following explicit tool call patterns.

**[Re-audit after context collection doubles API calls]** → If the user confirms context, the agent re-runs the full audit. Mitigation: This is the correct behavior — the point is to get accurate results. The audit is fast (typically <30s). The alternative (partial re-scoring) would require significant new infrastructure for marginal time savings.

## Open Questions

None — this is a focused output format change with clear implementation path.
