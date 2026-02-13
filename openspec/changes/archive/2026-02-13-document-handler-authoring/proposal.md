## Why

The framework supports custom sieve handlers for checking and remediation (Layer 1 and Layer 2), but there is no documentation explaining how to author one. The existing `IMPLEMENTATION_GUIDE.md` covers MCP tool handler registration (Layer 3) in detail, and the `handler-pipeline` spec defines the framework mechanics (phases, confidence gradient, invocation schema), but neither explains the practical steps: how to write a handler function, what the `HandlerContext` provides, how to return results, how to register it, and how to wire it into TOML control definitions. Without this, implementation authors must reverse-engineer `builtin_handlers.py` to understand the pattern.

## What Changes

- Add a **Sieve Handler Authoring Guide** section to `docs/IMPLEMENTATION_GUIDE.md` covering:
  - Handler function signature (`(config: dict, context: HandlerContext) -> HandlerResult`)
  - `HandlerContext` fields and what they provide (local_path, owner, repo, gathered_evidence, shared_cache, etc.)
  - `HandlerResult` construction (status, message, confidence, evidence, details)
  - Registration via `SieveHandlerRegistry` with phase affinity
  - Wiring into TOML `[[passes]]` blocks with pass-through config fields
  - Evidence propagation between handlers in the same pipeline
  - End-to-end example: a custom handler from function to TOML usage
- Add a **Remediation Handler Authoring** subsection covering:
  - How remediation handlers differ from checking handlers (all handlers in a phase execute, not stop-on-first-conclusive)
  - `project_update` integration via `on_pass` auto-derivation
  - Dry-run support pattern

## Capabilities

### New Capabilities
- `sieve-handler-authoring`: Documentation for writing, registering, and wiring custom sieve handlers for checking and remediation

### Modified Capabilities
(none — no spec-level requirement changes, this is documentation of existing behavior)

## Impact

- **Docs**: `docs/IMPLEMENTATION_GUIDE.md` gains a new section between the existing "Layer 1" and "Layer 3" content
- **Code**: No code changes — this documents existing APIs
- **Users**: Implementation authors (anyone building a new compliance standard plugin) can follow a guide instead of reading source code
