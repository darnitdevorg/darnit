## Why

The TOML-first architecture is the source of truth for control definitions, but ~8,000 lines of legacy Python code still define full control check logic that duplicates or bypasses the TOML pipeline. This code caused a critical bug where 61/62 controls silently returned WARN because Python-registered controls blocked TOML registration. The `overwrite=True` fix is a bandaid — the dead code must be removed to enforce the architectural principle that plugins only register **handlers** (checking, context, remediation), never full control definitions.

## What Changes

- **BREAKING**: Remove `implementation.register_controls()` side-effect imports of `controls/level{1,2,3}.py`. The method becomes a no-op.
- Remove 5 hardcoded `register_control()` calls from `sieve/registry.py` (framework package) that define full ControlSpecs with Python check logic at module import time
- **DELETE** `controls/level{1,2,3}.py` — 61 Python-defined controls (~3,000 lines) that duplicate TOML definitions
- **DELETE** `checks/level{1,2,3}.py`, `checks/helpers.py`, `checks/constants.py` — legacy domain check functions (~4,000 lines) not called by any active code path
- **DELETE** `adapters/builtin.py` — adapter bridging old check functions (~580 lines), not wired into audit
- **DELETE** `tests/darnit_baseline/test_checks.py` — tests for dead code
- Clean up `__init__.py` re-exports for deleted modules
- Remove legacy pass class re-exports (`DeterministicPass`, `PatternPass`, `LLMPass`, `ManualPass`) from `sieve/__init__.py`

## Capabilities

### New Capabilities

None — this is a removal, not an addition.

### Modified Capabilities

- `framework-design`: The plugin extension model is tightened. `register_controls()` no longer imports Python control definitions. The `ControlSpec.passes` field is no longer populated by implementations. The only path for control definitions is TOML → handler dispatch.

## Impact

- **packages/darnit/** (framework): Remove hardcoded controls from `sieve/registry.py`, clean up `sieve/__init__.py` re-exports
- **packages/darnit-baseline/** (implementation): Delete `controls/`, `checks/`, `adapters/builtin.py` directories/files; gut `implementation.register_controls()`
- **tests/**: Delete `test_checks.py`
- **No runtime behavior change**: All deleted code is already dead (overwritten by TOML or never called)
- **Plugin authors**: Must define controls in TOML, not Python. Custom sieve handlers via `register_handlers()` are the supported extension point.
