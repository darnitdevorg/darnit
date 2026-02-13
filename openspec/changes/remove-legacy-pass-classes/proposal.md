## Why

The framework migrated from class-based pass objects (`DeterministicPass`, `PatternPass`, etc.) to a handler-dispatch architecture (`builtin_handlers.py` + `SieveHandlerRegistry`), but ~1,200 lines of legacy pass class code remain. The orchestrator uses handler invocations for all TOML-loaded controls, yet `passes.py` (909 lines), `VerificationPassProtocol`, and the `ControlSpec.passes` field are still present. One orchestrator method (`verify_with_llm_response`) still iterates the legacy `.passes` field with a TODO to migrate. The `darnit-example` package still uses legacy pass classes for 2 of its 8 controls. Three empty stub directories in `darnit-baseline` linger from a previous cleanup. Removing all of this completes the handler-first migration and eliminates a confusing dual-path architecture.

## What Changes

- **BREAKING**: Remove `DeterministicPass`, `PatternPass`, `LLMPass`, `ManualPass`, `ExecPass` classes from `sieve/passes.py` (~909 lines)
- **BREAKING**: Remove `VerificationPassProtocol` from `sieve/models.py`
- **BREAKING**: Remove `ControlSpec.passes` field (and its `__post_init__` phase-order validation)
- Refactor `orchestrator.py:verify_with_llm_response()` to read LLM/manual config from `metadata["handler_invocations"]` instead of iterating `.passes`
- Migrate `darnit-example` controls (`PH-DOC-03`, `PH-CI-01`) from Python pass classes to TOML handler invocations + custom sieve handlers
- Move `ExecPass._substitute_variables()` tests to test the equivalent logic in `builtin_handlers.py`
- Remove empty stub directories: `darnit-baseline/checks/`, `darnit-baseline/controls/`, `darnit-baseline/adapters/`
- Update `IMPLEMENTATION_GUIDE.md` Section 6 ("Python Controls (Legacy)") and any other doc references to pass classes

## Capabilities

### New Capabilities

_(none — this is a removal/cleanup change)_

### Modified Capabilities

- `framework-design`: The spec references pass classes and the `passes` field on `ControlSpec`. These references need updating to reflect the handler-only architecture.

## Impact

- **Breaking for external plugins** that instantiate pass classes directly (e.g., `DeterministicPass(config_check=...)`). Migration path: use TOML handler invocations or register custom sieve handlers via `SieveHandlerRegistry`.
- **darnit-example** must be migrated before removal (it's the reference implementation for plugin authors).
- **Orchestrator** `verify_with_llm_response()` must be refactored to use `handler_invocations` metadata before the `.passes` field can be removed.
- **Tests**: 3 tests in `test_control_loader.py` test `ExecPass._substitute_variables()` — the variable substitution logic lives in `builtin_handlers.py` now but these tests need to be redirected or rewritten.
- **Docs**: `IMPLEMENTATION_GUIDE.md` Section 6, Section 11 quick reference, and `ARCHITECTURE.md` key source files table reference pass classes.
- **Net deletion**: ~1,200 lines of code + 3 empty stub directories.
