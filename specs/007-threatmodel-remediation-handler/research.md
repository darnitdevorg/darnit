# Research: Threat Model Remediation Handler

**Branch**: `007-threatmodel-remediation-handler` | **Date**: 2026-03-25

## R1: Handler Registry Choice — Sieve vs MCP Tool

**Decision**: Use the sieve handler registry (`darnit.sieve.handler_registry`), not the MCP tool handler registry (`darnit.core.handlers`).

**Rationale**: The remediation executor dispatches handlers via the sieve handler registry. Existing remediation handlers (`file_create`, `api_call`, `project_update`) are all registered there with the `(config: dict, context: HandlerContext) -> HandlerResult` signature. The MCP tool registry is for AI-assistant-facing tools with different signatures.

**Alternatives considered**:
- MCP tool registry — rejected (wrong dispatch path; executor doesn't query it)
- Dual registration — rejected (unnecessary complexity; remediation executor only needs sieve registry)

## R2: Handler Registration Point

**Decision**: Register the new handler in `implementation.py`'s existing `register_handlers()` method by also registering with the sieve handler registry, following the same pattern used for built-in handlers in `builtin_handlers.py`.

**Rationale**: The `register_handlers()` method in `implementation.py` already runs during plugin initialization. Adding sieve handler registration here keeps all plugin registration in one place. The sieve registry's `set_plugin_context()` ensures the handler is associated with the baseline plugin.

**Alternatives considered**:
- Register in `builtin_handlers.py` — rejected (this is a plugin handler, not a core built-in)
- Auto-registration via entry points — rejected (over-engineering for a single handler)

## R3: Fallback Mechanism

**Decision**: The handler catches exceptions from the dynamic analysis pipeline internally and falls back to reading the static template content, writing that instead. The fallback is entirely within the handler — no executor-level chaining.

**Rationale**: Per the clarification, the new handler replaces `file_create` entirely. It must handle its own failure modes. The static template (`threat_model_basic`) is resolved via the same template lookup mechanism the executor uses for `file_create`, accessed through the context or config.

**Alternatives considered**:
- Handler chaining (new handler + file_create) — rejected per clarification (adds executor complexity)
- Return INCONCLUSIVE to let executor try next handler — rejected (no next handler to try)

## R4: Dry-Run Support

**Decision**: When the executor signals dry-run mode (detected via config or context), the handler returns a descriptive `HandlerResult` with status PASS and a message explaining what it would do, without writing any files.

**Rationale**: Dry-run is a standard remediation feature. The handler checks for dry-run early and short-circuits with a descriptive message. This matches how `file_create_handler` handles dry-run in the executor.

**Alternatives considered**:
- Let the executor handle dry-run — the executor already skips handler invocation in dry-run mode and generates a summary, so the handler may not even be called during dry-run. The handler should still support it defensively.

## R5: Template Content Access for Fallback

**Decision**: The handler receives template content via the `config` dict's `content` field, which the executor pre-resolves from template names before calling the handler. This is the same mechanism `file_create_handler` uses.

**Rationale**: The executor's `_execute_handler_invocations()` method already resolves `template` references to `content` before calling any handler. So if the TOML config still includes `template = "threat_model_basic"`, the executor will resolve it and pass the content. The handler can use this pre-resolved content as its fallback.

**Alternatives considered**:
- Handler resolves template itself — rejected (duplicates executor logic; fragile if template paths change)
