## 1. Config Schema Updates

- [x] 1.1 Add `presentation_hint: str | None = None` field to `ContextDefinition` in `packages/darnit/src/darnit/config/context_schema.py`
- [x] 1.2 Add `allowed_values: list[str] | None = None` field to `ContextDefinition` in `packages/darnit/src/darnit/config/context_schema.py`
- [x] 1.3 Add a `computed_presentation_hint` property (or post-init logic) to `ContextDefinition` that returns: the explicit `presentation_hint` if set; `[y/N]` for boolean type; auto-generated `[val1/val2/...]` for enum type with `allowed_values` or `values`; `None` otherwise

## 2. Tool Modifications

- [x] 2.1 Add `limit: int = 1` parameter to `get_pending_context()` in `packages/darnit-baseline/src/darnit_baseline/tools.py`
- [x] 2.2 Implement pagination: compute full pending list, record `total = len(pending)`, then slice to `pending[:limit]` (or all if `limit == 0`), before building the questions JSON
- [x] 2.3 Add `"progress": {"current": N, "total": M}` to the JSON response, where `current` is `total - len(pending) + 1` (position in the overall sequence) and `total` is the count before slicing
- [x] 2.4 Include `presentation_hint` in the question dict returned by `_build_context_question()` — use `req.definition.computed_presentation_hint` (or equivalent)
- [x] 2.5 Define the LLM directive footer as a module-level constant string (e.g., `_LLM_DIRECTIVE`) that forbids batching, checkboxes, paraphrasing, and instructs the caller to use exact `prompt` text, call `confirm_project_context`, then call `get_pending_context` again
- [x] 2.6 Append the LLM directive footer after the JSON string in the return value (only when status is `"pending"`, not when `"complete"`)
- [x] 2.7 Rewrite the `get_pending_context` docstring to define the sequential-form-processor behavioral contract (returns one question at a time, caller MUST present exact prompt, MUST NOT batch/paraphrase, describes the loop)

## 3. TOML Presentation Hints

- [x] 3.1 Add `presentation_hint` to boolean context definitions in `packages/darnit-baseline/openssf-baseline.toml` (e.g., `has_subprojects`, `has_releases`, `is_library`, `has_compiled_assets`) with value `[y/N]`
- [x] 3.2 Add `presentation_hint` and/or `allowed_values` to enum context definitions in `openssf-baseline.toml` (e.g., `ci_provider`, `governance_model`, `sbom_tool`, `sast_tool`)

## 4. Spec & Doc Updates

- [x] 4.1 Update `openspec/specs/context-collection/spec.md` — sync delta spec additions (presentation hints, pagination, progress) into the main spec
- [x] 4.2 Update `openspec/specs/implementation-provided-tools/spec.md` — sync delta spec additions (LLM directive footer, hardened docstring, presentation hint in payload) into the main spec

## 5. Tests

- [x] 5.1 Unit test: `ContextDefinition` with `presentation_hint` field parses correctly from TOML-like dict
- [x] 5.2 Unit test: `ContextDefinition` computed hint defaults to `[y/N]` for boolean type when no explicit hint
- [x] 5.3 Unit test: `ContextDefinition` computed hint auto-generates from `values` for enum type when no explicit hint
- [x] 5.4 Unit test: `get_pending_context` with default `limit` returns exactly 1 question when multiple are pending
- [x] 5.5 Unit test: `get_pending_context` with `limit=0` returns all pending questions
- [x] 5.6 Unit test: `get_pending_context` response includes `progress` object with correct `current` and `total`
- [x] 5.7 Unit test: `get_pending_context` response string ends with the LLM directive footer when questions are pending
- [x] 5.8 Unit test: `get_pending_context` response does NOT include directive footer when no questions are pending (status: complete)
- [x] 5.9 Unit test: `_build_context_question` includes `presentation_hint` in the question dict when available
