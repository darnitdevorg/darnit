## Why

Remediation handlers and sieve pass handlers are unconditional today — every handler in a pipeline runs regardless of project characteristics like language, platform, or CI provider. This means we cannot express "create `go.mod` for Go projects" vs "create `pyproject.toml` for Python projects" as alternative handlers for the same control. The building blocks exist (language auto-detection in `auto_detect.py`, `when` clauses on `ControlConfig`, `languages` in the context model) but they aren't wired to the handler invocation level where remediation dispatch actually happens.

## What Changes

- **`when` clause on `HandlerInvocation`**: Add an optional `when: dict[str, Any]` field to the `HandlerInvocation` model. Before dispatching a handler, the executor evaluates the `when` clause against auto-detected + user-confirmed context. If the condition is not met, the handler is skipped.
- **`when` evaluation supports list-valued context**: Extend `when` evaluation to handle list-valued context keys. When the context value is a list and the `when` value is a scalar, match if the scalar is contained in the list (e.g., `when = { languages = "go" }` matches `languages = ["go", "typescript"]`). This is forward-compatible with monorepo scenarios where multiple languages coexist.
- **Remediation strategy field**: Add `strategy` to `RemediationConfig` with values `"all"` (default, run all matching handlers — existing behavior) and `"first_match"` (stop after the first handler whose `when` matches). This prevents running multiple conflicting remediations for the same control (e.g., creating both `go.mod` and `pyproject.toml`).
- **`languages` context key**: Add a `languages: list[str]` field to the auto-detection context alongside the existing `primary_language: str`. Detection scans for all manifest files rather than stopping at the first match.

## Capabilities

### New Capabilities

_(none — this change extends existing capabilities rather than introducing new top-level ones)_

### Modified Capabilities

- `handler-pipeline`: `HandlerInvocation` gains an optional `when` field; the orchestrator/executor must evaluate it before dispatching. Remediation pipeline gains a `strategy` field controlling handler selection semantics.
- `conditional-controls`: The `when` evaluation logic is extended to support list-valued context (`value in list` semantics). This applies both to control-level `when` and handler-level `when`.
- `context-collection`: The auto-detection subsystem gains a `languages: list[str]` context key that collects all detected languages, not just the primary one. The context flattening and storage layers must support this new key.

## Impact

- **`packages/darnit/src/darnit/config/framework_schema.py`**: Add `when` to `HandlerInvocation`, add `strategy` to `RemediationConfig`
- **`packages/darnit/src/darnit/remediation/executor.py`**: Evaluate `when` on each handler before dispatching; respect `strategy` for early-exit
- **`packages/darnit/src/darnit/sieve/orchestrator.py`**: Evaluate `when` on sieve pass handlers (same logic as remediation)
- **`packages/darnit/src/darnit/context/auto_detect.py`**: `detect_primary_language()` → also populate `languages` list; add `detect_languages()` function
- **`packages/darnit/src/darnit/config/schema.py`**: Add `languages: list[str]` field to context schema
- **`packages/darnit/src/darnit/config/context_storage.py`**: Support `languages` key in flattening and storage
- **TOML configs**: No breaking changes — `when` on handlers and `strategy` on remediation are both optional with backward-compatible defaults
- **Tests**: New tests for handler-level `when` evaluation, list membership matching, `first_match` strategy, and multi-language detection
