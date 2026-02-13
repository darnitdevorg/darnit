## Context

The framework migrated to a handler-dispatch architecture where TOML `[[passes]]` entries become `HandlerInvocation` objects stored in `ControlSpec.metadata["handler_invocations"]`. The orchestrator iterates this flat list, dispatching to registered handler functions (`file_exists`, `exec`, `regex`, `manual`, or custom plugin handlers).

The old architecture used Python dataclasses (`DeterministicPass`, `PatternPass`, `LLMPass`, `ManualPass`, `ExecPass`) stored in `ControlSpec.passes`. These classes implemented `VerificationPassProtocol` with an `execute(context) -> PassResult` interface. Nothing populates `ControlSpec.passes` with these objects anymore for TOML-loaded controls — only `darnit-example`'s two Python-defined controls still use them.

One orchestrator method (`verify_with_llm_response`) still reads from the legacy `.passes` field to find `confidence_threshold` (from `LLMPass`) and `verification_steps` (from `ManualPass`). This is the only code path preventing removal.

## Goals / Non-Goals

**Goals:**
- Remove all legacy pass class code (~1,200 lines)
- Ensure `verify_with_llm_response` works entirely from `handler_invocations` metadata
- Migrate `darnit-example` Python controls to the handler architecture (TOML + custom sieve handlers)
- Remove empty stub directories from `darnit-baseline`
- Update docs to reflect handler-only architecture

**Non-Goals:**
- Removing `rules/catalog.py` (still actively used by SARIF formatter)
- Removing `core/adapters.py` (unrelated orphaned code, separate concern)
- Changing the handler dispatch architecture itself
- Modifying any TOML control definitions (they already use the new format)

## Decisions

### 1. Refactor `verify_with_llm_response` to read from `handler_invocations`

The method currently iterates `control_spec.passes` looking for objects with `.phase == LLM` or `.phase == MANUAL`. The handler-based equivalent is:

- **confidence_threshold**: The `llm_eval` handler already stores `confidence_threshold` in its config dict (see `builtin_handlers.py:357`). When `verify_with_llm_response` is called, we can scan `metadata["handler_invocations"]` for an invocation with `handler == "llm_eval"` and read `confidence_threshold` from its extra fields. Default remains `0.8`.
- **verification_steps**: The `manual` handler already stores `steps` in `HandlerResult.details["verification_steps"]` (see `builtin_handlers.py:377`). We can scan `handler_invocations` for `handler == "manual"` and read `steps` from its config. Alternatively, read from the last `PassAttempt` in history if a manual handler already ran.

**Alternative considered**: Store these values in `ControlSpec.metadata` directly during TOML loading. Rejected because the values already exist in the handler invocations — no need for a second copy.

### 2. Migrate `darnit-example` controls to custom sieve handlers

The two Python controls (`PH-DOC-03`, `PH-CI-01`) use factory functions that return closures matching `Callable[[CheckContext], PassResult]`. These need to become sieve handler functions matching `Callable[[dict, HandlerContext], HandlerResult]`.

**Approach**: Convert each factory function into a sieve handler function, register them in the example implementation's `register_sieve_handlers()` method, and wire them from TOML.

For `PH-DOC-03` (ReadmeHasDescription):
- `_create_readme_description_check()` → `readme_description_handler(config, context) -> HandlerResult` (deterministic phase)
- `_create_readme_quality_analyzer()` → `readme_quality_handler(config, context) -> HandlerResult` (pattern phase)
- Manual steps move to TOML `[[passes]]` with `handler = "manual"`

For `PH-CI-01` (CIConfigExists):
- `_create_ci_config_check()` → `ci_config_handler(config, context) -> HandlerResult` (deterministic phase)
- Manual steps move to TOML `[[passes]]` with `handler = "manual"`

The handler functions go in a new `handlers.py` file (or the existing `controls/level1.py` renamed). Registration happens in `implementation.py`.

**Alternative considered**: Move these controls entirely to TOML using built-in handlers. Rejected because they demonstrate custom Python logic (README quality analysis, glob pattern matching) which is exactly the use case the example package should showcase.

### 3. Relocate `_substitute_variables` test coverage

The 3 tests in `test_control_loader.py` test `ExecPass._substitute_variables()`. This variable substitution logic (`$OWNER`, `$REPO`, `$PATH`, `$BRANCH`, `$CONTROL`) also exists in `builtin_handlers.py:exec_handler`. The tests should be rewritten to test the builtin handler's substitution directly.

**Alternative considered**: Keep `_substitute_variables` as a standalone utility function extracted from passes.py. Rejected because `builtin_handlers.py` already has its own implementation — we'd be maintaining two copies.

### 4. Remove `ControlSpec.passes` field and `__post_init__` validation

After the orchestrator no longer reads `.passes`, the field can be removed from the dataclass. The `__post_init__` method that validates phase ordering becomes unnecessary — TOML-loaded controls are validated at schema load time, and handler-based dispatch respects declaration order.

The field removal is **BREAKING** for any code that constructs `ControlSpec(passes=[...])`. The `darnit-example` migration (Decision 2) must complete first.

### 5. Delete empty stub directories in one pass

`darnit-baseline/checks/`, `darnit-baseline/controls/`, `darnit-baseline/adapters/` each contain only an `__init__.py` with a "removed" docstring. These exist for "structural compatibility" but nothing imports from them. Safe to delete entirely.

### 6. Update docs to remove pass class references

- `IMPLEMENTATION_GUIDE.md` Section 6 ("Python Controls (Legacy)") — rewrite to show custom sieve handler pattern instead
- `IMPLEMENTATION_GUIDE.md` Section 11 quick reference — remove pass class imports, update pass type cheat sheet
- `ARCHITECTURE.md` key source files table — already updated to note passes.py is legacy

## Risks / Trade-offs

**[Breaking change for external plugins]** → Any plugin using `DeterministicPass(config_check=...)` will break. Mitigation: this is pre-1.0 software, and the IMPLEMENTATION_GUIDE already marks Section 6 as "Superseded". The migration path (custom sieve handlers) is well-documented in Section 5.

**[verify_with_llm_response refactoring correctness]** → Subtle behavioral change if handler invocations don't carry `confidence_threshold` or `steps`. Mitigation: default to 0.8 and generic verification steps (same as current behavior when no LLM/manual pass is found). Add tests for the refactored method.

**[darnit-example migration]** → The example package is used in docs to teach plugin authoring. Changing it means updating cross-references. Mitigation: the migration actually improves the example by demonstrating the recommended (handler) pattern instead of the legacy one.

## Execution Order

The work must proceed in dependency order:

1. Refactor `verify_with_llm_response` to read from `handler_invocations` (unblocks `.passes` removal)
2. Migrate `darnit-example` controls to handlers (unblocks `.passes` removal)
3. Relocate variable substitution tests (unblocks `passes.py` removal)
4. Remove `ControlSpec.passes` field, `VerificationPassProtocol`, and `__post_init__` validation
5. Delete `sieve/passes.py`
6. Delete empty stub directories
7. Update docs
