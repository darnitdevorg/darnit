## Context

The `get_pending_context` MCP tool returns structured JSON with all missing context items. The calling LLM (e.g., Claude Code) receives this bulk payload and decides how to present each question to the user. In practice, LLMs batch questions into markdown checklists, paraphrase prompt strings, reorder questions, and invent UI patterns not defined by the tool. The root cause is that the tool gives the LLM too much information at once and relies on soft "instructions" fields in the JSON payload to control behavior.

The current architecture has two layers:
1. **Core layer** (`darnit/config/context_storage.py`): `get_pending_context()` returns a `list[ContextPromptRequest]` sorted by priority.
2. **Implementation layer** (`darnit_baseline/tools.py`): `get_pending_context()` wraps the core function, formats results as JSON with per-question `instruction` and `input_type` fields.

The implementation layer already attempts to constrain LLM behavior via per-question `instruction` strings, but these are buried in the middle of a large JSON payload and are routinely ignored.

## Goals / Non-Goals

**Goals:**
- Force one-question-at-a-time flow so the LLM cannot batch or reorder questions
- Ensure the LLM uses the exact `prompt` text from the TOML config, not a paraphrase
- Provide explicit formatting hints (e.g., `[y/N]`, `[1/2/3/4]`) so the LLM knows how to render each prompt without guessing
- Maintain backward compatibility — callers that pass `limit=N` can still get multiple items

**Non-Goals:**
- Changing the `confirm_project_context` tool (the write side is not part of this change)
- Implementing a full terminal UI or interactive wizard in the framework itself
- Modifying the core `context_storage.get_pending_context()` return type — it stays `list[ContextPromptRequest]`
- Adding client-side validation of user answers (that's a separate concern)

## Decisions

### D1: Pagination lives in the implementation layer, not the core

The core `context_storage.get_pending_context()` continues to return the full `list[ContextPromptRequest]`. The implementation layer (`darnit_baseline/tools.py`) applies the `limit` parameter (default 1) when formatting the JSON output. This keeps the core reusable and avoids coupling framework code to LLM-specific UX concerns.

**Alternative considered:** Adding `limit` to the core function. Rejected because other consumers (CI pipelines, non-LLM integrations) may need the full list.

### D2: LLM directive as a trailing string block, not a JSON field

The directive is appended as a raw string block after the JSON payload, not as a field within the JSON. This exploits recency bias — LLMs weight the last tokens they see more heavily than tokens in the middle of a structured payload. The directive is a short, imperative paragraph that says exactly what to do and what not to do.

**Alternative considered:** Adding a top-level `"directive"` field in the JSON. Rejected because LLMs treat JSON fields as data to be interpreted, not as instructions to follow. A trailing plaintext block reads more like a system instruction.

### D3: Presentation hints are optional fields on ContextDefinition

Two new optional fields are added to `ContextDefinition` in `context_schema.py`:
- `presentation_hint: str | None` — Short format string appended to the prompt (e.g., `[y/N]`, `[1-3]`)
- `allowed_values: list[str] | None` — Explicit allowed values for display (distinct from `values` which is for enum validation)

These are surfaced in the question JSON so the LLM knows exactly how to format the prompt. For booleans, `presentation_hint` defaults to `[y/N]`. For enums, it is auto-generated from `allowed_values` or `values` if not explicitly set.

**Alternative considered:** Reusing the existing `values` field for presentation. Rejected because `values` serves a validation purpose (enum constraint) while `presentation_hint` is purely cosmetic. A question might have valid values `["github", "gitlab", "jenkins", "circleci", "azure", "travis", "none", "other"]` but a presentation hint of `[github/gitlab/jenkins/...]`.

### D4: Docstring serves as the MCP tool description

The MCP tool docstring is the primary mechanism LLMs use to understand a tool's purpose. The `get_pending_context` docstring is rewritten to explicitly state:
1. It returns ONE question at a time by default
2. The caller MUST present the question using the exact `prompt` text
3. The caller MUST NOT batch, paraphrase, or use markdown formatting
4. After the user answers, the caller should call `confirm_project_context` and then call `get_pending_context` again for the next question

This turns the docstring from a developer reference into an LLM behavioral contract.

### D5: Progress indicator in the response

Each response includes `"progress": {"current": N, "total": M}` so the LLM can tell the user "Question 2 of 8" without needing to know the full list. This is computed from the full pending list before slicing to `limit`.

## Risks / Trade-offs

**[Increased round-trips]** → Single-item pagination means N tool calls instead of 1 for N context items. Acceptable because context collection is infrequent (once per project setup) and correctness matters more than speed.

**[LLM may still ignore directives]** → No amount of prompting guarantees LLM compliance. Mitigation: the directive uses strong, unambiguous language and is positioned at the end of the response (recency bias). The single-item pagination is the primary guardrail — the directive is defense-in-depth.

**[Breaking change for callers expecting full list]** → Callers that relied on getting all questions in one call will now get only one. Mitigation: the `limit` parameter allows `limit=0` to restore the old behavior. The docstring documents this.

**[TOML schema expansion]** → Adding `presentation_hint` and `allowed_values` to every `[context.*]` block adds verbosity. Mitigation: both fields are optional with sensible defaults. Existing TOML configs work without modification.
