## 1. Refactor orchestrator to use handler invocations

- [x] 1.1 Refactor `verify_with_llm_response` in `orchestrator.py` to read `confidence_threshold` from `metadata["handler_invocations"]` (scan for `handler == "llm_eval"`) instead of iterating `control_spec.passes`
- [x] 1.2 Refactor `verify_with_llm_response` to read `verification_steps` from `metadata["handler_invocations"]` (scan for `handler == "manual"`) instead of iterating `control_spec.passes`
- [x] 1.3 Add unit tests for the refactored `verify_with_llm_response` covering: handler invocation with explicit `confidence_threshold`, default `confidence_threshold` of 0.8, manual steps extraction, and missing handler invocations
- [x] 1.4 Remove the `# TODO: migrate to handler invocations` comment and any remaining `.passes` iteration in the orchestrator

## 2. Migrate darnit-example controls to handler architecture

- [x] 2.1 Create `packages/darnit-example/src/darnit_example/handlers.py` with `readme_description_handler(config, context) -> HandlerResult` (deterministic phase logic from `_create_readme_description_check`)
- [x] 2.2 Add `readme_quality_handler(config, context) -> HandlerResult` to handlers.py (pattern phase logic from `_create_readme_quality_analyzer`)
- [x] 2.3 Add `ci_config_handler(config, context) -> HandlerResult` to handlers.py (deterministic phase logic from `_create_ci_config_check`)
- [x] 2.4 Register all three handlers in the example implementation's `register_sieve_handlers()` method via `SieveHandlerRegistry`
- [x] 2.5 Convert PH-DOC-03 and PH-CI-01 from Python pass class definitions to TOML `[[passes]]` entries referencing the new handlers, with manual steps as `handler = "manual"` entries (also migrated all 6 existing controls from legacy phase-bucketed format to flat `[[passes]]` handler format)
- [x] 2.6 Remove legacy pass class imports and factory functions from `controls/level1.py`
- [x] 2.7 Verify darnit-example tests still pass after migration

## 3. Relocate variable substitution tests

- [x] 3.1 Rewrite the 3 `ExecPass._substitute_variables()` tests in `test_control_loader.py` to test the equivalent substitution logic in `builtin_handlers.py:exec_handler` (covering `$OWNER`, `$REPO`, `$PATH`, `$BRANCH`, `$CONTROL`) — already covered by existing tests in `test_builtin_handlers.py` (test_variable_substitution, test_path_substitution)
- [x] 3.2 Remove the old `ExecPass._substitute_variables()` test methods

## 4. Remove ControlSpec.passes field and related code

- [x] 4.1 Remove the `passes` field from the `ControlSpec` dataclass in `sieve/models.py`
- [x] 4.2 Remove `VerificationPassProtocol` from `sieve/models.py`
- [x] 4.3 Remove the `__post_init__` phase-order validation method from `ControlSpec`
- [x] 4.4 Update any test fixtures or factories that construct `ControlSpec(passes=[...])` to remove the `passes` argument

## 5. Delete legacy pass classes

- [x] 5.1 Delete `packages/darnit/src/darnit/sieve/passes.py` (~909 lines)
- [x] 5.2 Remove any remaining imports of pass classes (`DeterministicPass`, `PatternPass`, `LLMPass`, `ManualPass`, `ExecPass`) across the codebase — updated stale comments in builtin_handlers.py, framework_schema.py, and validate_sync.py
- [x] 5.3 Remove the `passes` module from `sieve/__init__.py` exports (if present) — already not exported

## 6. Delete empty stub directories

- [x] 6.1 Delete `packages/darnit-baseline/src/darnit_baseline/checks/` (empty stub with "removed" docstring)
- [x] 6.2 Delete `packages/darnit-baseline/src/darnit_baseline/controls/` (empty stub with "removed" docstring)
- [x] 6.3 Delete `packages/darnit-baseline/src/darnit_baseline/adapters/` (empty stub with "removed" docstring)

## 7. Update documentation

- [x] 7.1 Rewrite `IMPLEMENTATION_GUIDE.md` Section 6 ("Python Controls (Legacy)") to show the custom sieve handler pattern instead of pass class instantiation
- [x] 7.2 Update `IMPLEMENTATION_GUIDE.md` Section 11 quick reference to remove pass class imports and update the pass type cheat sheet to use handler names
- [x] 7.3 Remove `passes.py` from the key source files table in `ARCHITECTURE.md` (currently marked as legacy)
- [x] 7.4 Run `uv run python scripts/generate_docs.py` and commit any generated doc changes — no changes needed

## 8. Validation

- [x] 8.1 Run `uv run ruff check .` — all clean
- [x] 8.2 Run `uv run pytest tests/ --ignore=tests/integration/ -q` — 885 passed, 1 pre-existing upstream hash failure (unrelated)
- [x] 8.3 Run `uv run python scripts/validate_sync.py --verbose` — spec-implementation sync passes
