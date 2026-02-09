## Context

The `toml-schema-improvements` change built the handler-based dispatch infrastructure: `SieveHandlerRegistry` with built-in handlers (`file_exists`, `exec`, `regex`, `llm_eval`, `manual_steps`, `file_create`, `api_call`, `project_update`), `HandlerInvocation` schema with `extra="allow"` pass-through, phased lists in `PassesConfig` and `RemediationConfig`, shared handler resolution, `use_locator`, and a dual-path orchestrator that tries handler dispatch first then falls back to legacy typed passes.

However, all 73 controls with pass definitions in `openssf-baseline.toml` still use legacy typed format. The orchestrator's handler dispatch path (`_dispatch_handler_invocations()`) is never reached in production because no controls populate `metadata["handler_invocations"]`. The migration surface is:

- **16** `passes.exec` blocks
- **68** `passes.pattern` blocks
- **59** `passes.manual` blocks
- **15** `passes.deterministic` blocks (file_must_exist)
- **13** `remediation.file_create` blocks
- **1** `remediation.api_call` block
- **34** `remediation.manual` blocks
- **3** `remediation.project_update` blocks

Additionally, the current `PassesConfig` and `RemediationConfig` schemas use hardcoded phase fields (`deterministic`, `pattern`, `llm`, `manual`) as structural buckets for handler invocation lists. These phases impose structure that the handlers themselves don't need — a handler's confidence and ordering is inherent to what it does, not which schema field it's placed in.

## Goals / Non-Goals

**Goals:**
- Flatten `passes` and `remediation.handlers` from phase-bucketed fields to flat ordered lists of handler invocations
- Migrate all 73 controls' pass definitions to the flat handler invocation list format
- Replace ~15 `file_must_exist` + `locator.discover` DRY violations with `use_locator = true`
- Migrate remediation sections to handler invocation format
- Remove legacy typed-pass dispatch from the orchestrator and executor
- Remove backward compatibility validators and legacy config models from the schema
- Remove phase-bucketed fields from `PassesConfig` and `RemediationConfig`

**Non-Goals:**
- Adding new controls or changing control behavior — this is a format migration + simplification
- Changing handler implementations — built-in handlers already work correctly
- Migrating `config_check` Python references (2 controls) — these should be registered as Python plugin handlers

## Decisions

### 1. Flatten phase buckets to a flat ordered list

**Decision**: Replace the phase-bucketed fields on `PassesConfig` (`deterministic`, `pattern`, `llm`, `manual`) with a single flat `passes: list[HandlerInvocation]` on the control. Similarly, replace the phase-bucketed fields on `RemediationConfig` with a single `handlers: list[HandlerInvocation]`. The orchestrator iterates the list in order and stops at the first conclusive result.

**Rationale**: The phase buckets (`deterministic`, `pattern`, `llm`, `manual`) are hardcoded in the schema but don't add value beyond ordering — which the list position already provides. Handlers inherently know their own confidence level (`file_exists` is always high-confidence, `regex` is always heuristic, `manual_steps` always requires human review). Making this structural imposes unnecessary coupling: adding a new handler type that doesn't fit neatly into a phase would require a schema change. A flat list is simpler, more flexible, and lets the TOML author control execution order explicitly. Complex orchestration logic (conditional branching, context-dependent checks) belongs in Python plugin handlers, not in TOML structure.

**Alternative considered**: Keep the phase buckets as-is and just migrate legacy typed passes into them. Rejected because the phases are a leaky abstraction — `exec` handlers are "deterministic" but so is `file_exists`, and regex matching is computationally deterministic even though it's in the "pattern" phase. The distinction is about confidence, which is a handler property, not a schema property.

### 2. Remove legacy dispatch entirely

**Decision**: Remove the legacy typed-pass execution path from the orchestrator's `verify()` method and the executor's `execute()` method. Remove the backward compatibility validators (`normalize_to_legacy_passes()`) from `PassesConfig` and `RemediationConfig`. Remove legacy typed-pass config models (`DeterministicPassConfig`, `ExecPassConfig`, `PatternPassConfig`, `ManualPassConfig`, `LLMPassConfig`) and legacy remediation config models (`FileCreateRemediationConfig`, `ExecRemediationConfig`, `ApiCallRemediationConfig`, `ManualRemediationConfig`) from the schema.

**Rationale**: No external consumers exist — this is a single-implementer project. Keeping dead code paths creates confusion for contributors and LLMs working on the codebase. The handler format is strictly more capable. A clean break is simpler than maintaining two parallel systems.

**Alternative considered**: Keep legacy dispatch as a fallback with deprecation logging. Rejected because it preserves code complexity for zero users.

### 3. Migrate passes by type, not by control

**Decision**: Convert all passes of one legacy type at a time (e.g., all 16 `passes.exec` blocks, then all 68 `passes.pattern` blocks) rather than migrating one control completely.

**Rationale**: Each legacy pass type has a consistent before/after pattern. Batch migration by type is more mechanical, less error-prone, and easier to review. Each batch is one commit.

**Alternative considered**: Migrate by control level (level 1 first, then level 2, then level 3). Rejected because it mixes pass types within each batch, increasing review complexity.

### 4. TOML format: `passes` as an ordered list of handler invocations

**Decision**: Each control's `passes` field becomes an ordered list of handler invocations. Controls with multiple check types list them in natural confidence order (high-confidence first, manual last). The TOML uses array-of-tables syntax for handlers with many fields, or inline tables for simple ones.

**Before (legacy):**
```toml
[controls."OSPS-XX-01".passes]
exec = { command = ["gh", "api", "..."], expr = "..." }
manual = { steps = ["Review settings page"] }
```

**After (flat list):**
```toml
[[controls."OSPS-XX-01".passes]]
handler = "exec"
command = ["gh", "api", "..."]
expr = "..."

[[controls."OSPS-XX-01".passes]]
handler = "manual_steps"
steps = ["Review settings page"]
```

**Rationale**: Array-of-tables (`[[...]]`) syntax works cleanly with TOML v1.0, handles handlers with many fields, and preserves ordering. The `handler` field identifies which built-in or plugin handler to invoke. All other fields pass through via `extra="allow"` on `HandlerInvocation`.

### 5. `file_must_exist` with `locator.discover` uses `use_locator = true`

**Decision**: For the ~15 controls where `file_must_exist` duplicates the `locator.discover` list, replace with `{ handler = "file_exists", use_locator = true }`. For controls without a locator, use `{ handler = "file_exists", files = [...] }`.

**Rationale**: `use_locator = true` copies `locator.discover` into the handler's `files` parameter at load time, eliminating the DRY violation. Controls without a locator need explicit `files`.

### 6. Remediation uses the same flat list pattern

**Decision**: `RemediationConfig` keeps its metadata fields (`requires_context`, `project_update`) but replaces its phase-bucketed handler lists with a single `handlers: list[HandlerInvocation]`. In TOML:

```toml
[controls."OSPS-XX-01".remediation]
requires_context = ["governance.maintainers"]

[[controls."OSPS-XX-01".remediation.handlers]]
handler = "file_create"
path = "GOVERNANCE.md"
template = "governance"
```

`project_update` stays as a separate field on `RemediationConfig` — it's a post-pass operation applied via `on_pass`, not a remediation handler.

**Rationale**: Remediation phases were especially artificial — `file_create` isn't "deterministic" in the same sense as `file_exists`. A flat list of remediation handlers with the metadata fields alongside is cleaner.

### 7. `manual_steps` and `llm_eval` are just handlers in the list

**Decision**: `manual_steps` is a handler that returns structured guidance for the user (or hints for an LLM agent). `llm_eval` is a handler that sends prompts back to the LLM for investigation. Neither gets special treatment — they're entries in the flat list like any other handler, ordered by the TOML author.

**Rationale**: There's no architectural reason to treat these differently from `exec` or `file_exists`. The orchestrator iterates the list and stops at the first conclusive result. A `manual_steps` entry at the end of the list only runs if all preceding handlers were inconclusive.

### 8. Complex orchestration logic belongs in Python plugin handlers

**Decision**: When a control needs conditional branching, context-dependent check selection, multi-step refinement, or any logic beyond "try these in order," the control should use a Python plugin handler registered via `register_handlers()`. The TOML references it by name:

```toml
[[controls."OSPS-XX-01".passes]]
handler = "check_branch_protection"
```

**Rationale**: TOML is declarative — encoding orchestration logic in it leads to a mini programming language. Python is already available via the plugin system and can express arbitrary logic. This keeps TOML simple and Python powerful, with a clean boundary between them.

### 9. Add an integration test that asserts handler-only dispatch

**Decision**: Add a test that loads handler-format TOML controls and asserts that the orchestrator dispatches every control through the handler invocation path with no legacy fallback.

**Rationale**: This is the acceptance criterion — after migration, the handler dispatch path must be the exclusive path for all openssf-baseline controls.

## Risks / Trade-offs

**[Bulk TOML changes]** — 145+ pass blocks and 51+ remediation blocks changing format in one file.
> Mitigation: Migrate by pass type in separate commits. Each commit is reviewable. Run full test suite after each batch.

**[Schema structure change]** — `PassesConfig` phase fields become a flat list, which changes how controls are parsed.
> Mitigation: The `HandlerInvocation` model is unchanged. Only the container structure changes. Tests validate both old-format rejection and new-format parsing.

**[Subtle behavior differences]** — Handler dispatch may have slightly different behavior than legacy dispatch (e.g., evidence accumulation, error handling).
> Mitigation: The handler implementations wrap the same underlying logic. Run a before/after comparison audit on a real repository to verify identical results.

**[`config_check` controls]** — 2 controls use `config_check = "module:function"` which has no handler equivalent yet.
> Mitigation: Register the Python functions as named handlers via `register_handlers()` in the implementation, then reference by name in TOML.

## Open Questions

1. Should `project_update` remediation be migrated to handler format, or is it better left as the `on_pass` mechanism it currently uses? The `project_update` built-in handler exists but `on_pass` is the canonical path for post-verification context updates.
