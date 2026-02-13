## Context

The TOML-first architecture enforces that control definitions live in TOML files and are executed via handler dispatch (`handler_invocations`). However, ~8,000 lines of legacy Python code still define full control check logic using the old `passes` field on `ControlSpec`. This code is dead — the orchestrator's `verify()` method only reads `handler_invocations` from metadata, never `passes`. The legacy code caused a critical bug where 61/62 controls silently returned WARN because Python-registered controls blocked TOML registration.

The `overwrite=True` fix in `audit.py` is a bandaid. The dead code must be removed to enforce the architectural principle: **plugins register handlers, not control definitions**.

## Goals

1. Delete all legacy Python control definitions (~8,000 lines of dead code)
2. Remove hardcoded control registrations from the framework's `registry.py`
3. Make `implementation.register_controls()` a no-op while preserving protocol compatibility
4. Clean up all dangling imports, re-exports, and test files for deleted modules
5. Zero runtime behavior change — audit results must be identical before and after

## Non-Goals

- Removing `rules/catalog.py` (still used as SARIF formatter fallback — separate task)
- Removing `passes.py` dataclass definitions (still used by framework internals and `validate_sync.py`)
- Refactoring `verify_with_llm_response()` to use handler metadata (mark with TODO, separate task)
- Touching `darnit-example` or `darnit-testchecks` packages
- Changing the `ControlRegistry` class or `register_control()` function (TOML controls use them)

## Decisions

### D1: Execution order — framework first, then implementation

Remove hardcoded controls from `registry.py` (framework) before gutting `implementation.register_controls()` (implementation). Rationale: the framework hardcoded controls are an import-time side effect that runs before any implementation code. Removing them first eliminates the earliest source of legacy registrations. Both are dead code, but cleaning framework before implementation follows the dependency direction.

### D2: `register_controls()` becomes a no-op, not deleted

The method must remain on the implementation class for `ComplianceImplementation` protocol compatibility. External plugin authors may implement this method. We make it a no-op with a docstring explaining why, rather than removing it from the protocol.

### D3: Delete entire files, not surgical edits

For `controls/level{1,2,3}.py`, `checks/level{1,2,3}.py`, `checks/helpers.py`, `checks/constants.py`, and `adapters/builtin.py` — delete the files entirely rather than gutting their contents. These files serve no purpose and keeping empty shells adds confusion. The `__init__.py` files in each package stay but get their imports cleaned.

### D4: Remove legacy pass re-exports from `sieve/__init__.py`

`DeterministicPass`, `PatternPass`, `LLMPass`, `ManualPass` are re-exported from `sieve/__init__.py`. The only consumers of these re-exports are the hardcoded controls in `registry.py` (being removed) and `controls/level{1,2,3}.py` (being deleted). The pass classes themselves in `passes.py` stay — only the convenience re-exports from `__init__.py` are removed.

### D5: Leave `overwrite=True` in audit.py

After this cleanup, `impl.register_controls()` is a no-op so there's nothing to overwrite. The `overwrite=True` parameter is harmless and provides defense-in-depth if a future plugin accidentally registers controls via Python. Not worth a separate change to remove it.

### D6: `verify_with_llm_response()` gets a TODO, not a refactor

The orchestrator's `verify_with_llm_response()` still iterates `control_spec.passes` (the old field). This is a vestigial code path used only for LLM consultation. Refactoring it to use handler metadata is a separate concern. Adding a TODO comment is sufficient for this change.

## Risks and Trade-offs

### R1: Breaking plugin authors who use `register_controls()` for Python control definitions

**Impact**: Any external plugin that defines controls via Python (using `passes=[]` on ControlSpec) will find those definitions ignored by the orchestrator. This was already true — the orchestrator only uses `handler_invocations` — but making `register_controls()` a no-op makes it explicit.

**Mitigation**: This is already documented as BREAKING in the proposal. The supported extension point is `register_handlers()` for custom sieve/remediation handlers, with control definitions in TOML.

### R2: Tests that import deleted modules will fail

**Impact**: `tests/darnit_baseline/test_checks.py` tests the legacy check functions directly. Any other tests that transitively import from `controls/` or `checks/` will break.

**Mitigation**: Delete `test_checks.py` (tests dead code). Run full test suite to catch any transitive imports. Search for all imports of deleted modules before committing.

### R3: `rules/catalog.py` import chain from `registry.py`

**Impact**: `registry.py` imports `rules/catalog.py` via `_get_rule_metadata()` for the 5 hardcoded controls. Removing the hardcoded controls removes this import chain. If `catalog.py` has other consumers (SARIF formatter), those are unaffected.

**Mitigation**: `catalog.py` stays — it's still used by the SARIF formatter as fallback. Only the `_get_rule_metadata()` helper in `registry.py` is removed.

### R4: Zero runtime regression

**Impact**: The entire point is that deleted code is dead. But if any code path still reaches it, we'd break functionality.

**Mitigation**: Run the full audit against this repo before and after. Compare results — must be identical (26+ PASS, same FAIL/WARN distribution). Run full test suite. Grep for zero remaining imports of deleted modules.
