## Why

The `get_pending_context` MCP tool currently returns all missing context items as a bulk JSON array. Because LLMs are non-deterministic, giving them a full list of pending questions causes them to improvise the UI: batching questions into markdown checkboxes, asking out of order, paraphrasing the carefully crafted `prompt` strings from the TOML configuration, or inventing their own formatting. This makes the context-collection experience unpredictable and error-prone. We need to force the LLM to act as a strict, sequential CLI wizard that asks one question at a time using the exact prompt text we define.

## What Changes

- **Single-item pagination**: `get_pending_context` returns only the single highest-priority missing item by default, preventing the LLM from seeing future questions and batching them. An optional `limit` parameter preserves the ability to request multiple items.
- **LLM directive footer**: The string returned by `get_pending_context` includes a hardcoded directive block at the end that explicitly forbids checkboxes, batching, and paraphrasing. This leverages recency bias to override the LLM's default conversational instincts.
- **Docstring hardening**: The MCP tool docstring for `get_pending_context` is rewritten to define its usage contract as a sequential form processor, not a general-purpose data retrieval tool.
- **TOML presentation hints**: The context schema (`ContextDefinition`) gains `presentation_hint` and `allowed_values` fields so the TOML config can specify exactly how the LLM should format each question (e.g., `[y/N]` for booleans, `[1/2/3]` for enums).

## Capabilities

### New Capabilities

_(none — all changes modify existing capabilities)_

### Modified Capabilities

- `context-collection`: Add `presentation_hint` and `allowed_values` to the context definition schema. Add requirement for single-item-at-a-time pagination default.
- `implementation-provided-tools`: Update `get_pending_context` tool contract to require LLM directive footer, single-item default, and hardened docstring.

## Impact

- **`packages/darnit/src/darnit/config/context_schema.py`**: Add `presentation_hint` and `allowed_values` fields to `ContextDefinition` model.
- **`packages/darnit/src/darnit/config/context_storage.py`**: Update `get_pending_context` to default `limit=1`, inject LLM directive footer into return string.
- **`packages/darnit-baseline/src/darnit_baseline/tools.py`**: Update `get_pending_context` wrapper — hardened docstring, pass-through for new `limit` parameter.
- **`packages/darnit-baseline/openssf-baseline.toml`**: Add `presentation_hint` / `allowed_values` to existing `[context.*]` definitions.
- **`openspec/specs/context-collection/spec.md`**: Delta spec for new schema fields and pagination behavior.
- **`openspec/specs/implementation-provided-tools/spec.md`**: Delta spec for tool contract changes.
