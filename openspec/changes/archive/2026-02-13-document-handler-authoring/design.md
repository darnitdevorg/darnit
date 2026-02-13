## Context

The `docs/IMPLEMENTATION_GUIDE.md` is the canonical guide for building a darnit implementation plugin. It currently has 10 numbered sections covering package setup, implementation class, TOML configuration, the sieve pipeline, Python controls, remediation, MCP tools, testing, common pitfalls, and quick reference.

Section 5 ("Python Controls") documents the **legacy** pattern: factory functions returning closures, `DeterministicPass`/`ManualPass` classes, and `register_control()`. This pattern was superseded by the TOML-first handler dispatch architecture, where controls are defined in TOML and handlers are registered via `SieveHandlerRegistry`.

Section 7 ("MCP Tools") documents `HandlerRegistry` (Layer 3 — tool handlers exposed to the LLM), which is a **different** registry from `SieveHandlerRegistry` (Layer 1/2 — sieve pipeline handlers).

There is no existing section that explains how to write a custom sieve handler.

## Goals / Non-Goals

**Goals:**
- Add a new section to `IMPLEMENTATION_GUIDE.md` that teaches implementation authors how to write, register, and wire custom sieve handlers
- Cover both checking (verification) and remediation handler authoring
- Include a complete end-to-end example with realistic domain logic
- Update section 5 to reflect that the legacy Python control pattern is superseded by TOML + handlers

**Non-Goals:**
- Rewriting the entire Implementation Guide
- Documenting framework internals (orchestrator logic, evidence merging implementation)
- Creating a separate standalone document (all content goes into the existing guide)
- Changing any code — this is documentation only

## Decisions

### Decision 1: Add as new section 5, renumber existing sections

**Choice**: Insert the handler authoring guide as the new **Section 5** ("Custom Sieve Handlers"), and renumber the current section 5 ("Python Controls") to section 6 with a deprecation notice pointing to the new section 5.

**Rationale**: Section 4 covers the sieve pipeline mechanics — handler authoring is the natural next step. The current section 5 (legacy Python controls) becomes a "Legacy" appendix-style section. Placing handler authoring before MCP tools (currently section 7) maintains the Layer 1 → Layer 2 → Layer 3 progression that matches the "three layers" diagram at the top.

**Alternative considered**: Replacing section 5 entirely. Rejected because the legacy pattern still works (backward compatibility) and some implementations may still use it.

### Decision 2: Structure as progressive tutorial, not API reference

**Choice**: Structure the section as a tutorial that builds incrementally: signature → context → result → registration → TOML wiring → evidence chaining → remediation → complete example.

**Rationale**: The existing guide follows a tutorial pattern (package setup → implementation class → TOML → pipeline → controls). An API reference style would break the flow. Authors can read `handler_registry.py` docstrings for API-level detail; the guide should teach the *pattern*.

**Alternative considered**: API reference with code snippets. Rejected because the existing guide is tutorial-style.

### Decision 3: Use a realistic example handler, not a stub

**Choice**: The end-to-end example will be a `license_header` handler that checks source files for license headers — realistic enough to demonstrate config parsing, file I/O, evidence production, and error handling, but simple enough to fit in ~30 lines.

**Rationale**: Trivial stubs (return PASS) don't teach error handling or evidence patterns. The `license_header` example uses common operations (file reading, pattern matching) that any implementation author would recognize, and demonstrates how a custom handler complements the built-in `regex` handler with domain-specific logic.

**Alternative considered**: `scorecard` handler (calls OpenSSF Scorecard API). Rejected because it requires network access and API-specific knowledge that distracts from the handler pattern itself.

### Decision 4: Cover the two-registry distinction explicitly

**Choice**: Add a callout box/note explicitly distinguishing `SieveHandlerRegistry` (Layer 1/2, for sieve pipeline handlers) from `HandlerRegistry` (Layer 3, for MCP tool handlers), since both are accessed via `register_handlers()` in the implementation class.

**Rationale**: This is a common confusion point. The implementation's `register_handlers()` method currently only registers MCP tool handlers. Sieve handlers are registered via `get_sieve_handler_registry()` — which could be called from the same method or from a separate initialization path. The guide must be clear about which registry to use.

## Risks / Trade-offs

**[Docs diverge from code]** → Keep examples minimal and reference canonical source files. Add a note at the top: "For the authoritative API, see `packages/darnit/src/darnit/sieve/handler_registry.py`."

**[Legacy section 5 confusion]** → Add a clear deprecation banner at the top of the legacy section: "The pattern in this section is superseded by TOML + custom handlers (Section 5). Use this only if you need backward compatibility with pre-TOML implementations."

**[Section renumbering breaks external links]** → The guide is not published externally yet, so renumbering is safe. Internal cross-references within the guide need updating.

## Open Questions

- Should the implementation class grow a `register_sieve_handlers()` method (separate from `register_handlers()` for MCP tools), or should sieve handler registration remain a side-effect of module import / explicit call in `register_handlers()`? This is a code design question that may warrant a separate change — for now, document the current pattern (explicit `get_sieve_handler_registry()` call).
