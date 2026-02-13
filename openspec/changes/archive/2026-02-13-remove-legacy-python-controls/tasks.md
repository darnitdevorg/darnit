## 1. Remove Hardcoded Controls from Framework

- [x] 1.1 Delete `_get_rule_metadata()` helper and all 5 `register_control()` calls from `packages/darnit/src/darnit/sieve/registry.py` (lines 230-409)
- [x] 1.2 Remove unused imports from `registry.py` (`json`, `subprocess`, `DeterministicPass`, `LLMPass`, `ManualPass`, `PatternPass`, `PassOutcome`, `PassResult`, `VerificationPhase`)
- [x] 1.3 Remove legacy pass re-exports (`DeterministicPass`, `PatternPass`, `LLMPass`, `ManualPass`) from `packages/darnit/src/darnit/sieve/__init__.py`

## 2. Gut Implementation register_controls()

- [x] 2.1 Replace `register_controls()` body in `packages/darnit-baseline/src/darnit_baseline/implementation.py` with `pass` and a docstring explaining it is a no-op

## 3. Delete Dead Implementation Files

- [x] 3.1 Delete `packages/darnit-baseline/src/darnit_baseline/controls/level1.py`
- [x] 3.2 Delete `packages/darnit-baseline/src/darnit_baseline/controls/level2.py`
- [x] 3.3 Delete `packages/darnit-baseline/src/darnit_baseline/controls/level3.py`
- [x] 3.4 Clean up `packages/darnit-baseline/src/darnit_baseline/controls/__init__.py` — remove imports of deleted modules
- [x] 3.5 Delete `packages/darnit-baseline/src/darnit_baseline/checks/level1.py`
- [x] 3.6 Delete `packages/darnit-baseline/src/darnit_baseline/checks/level2.py`
- [x] 3.7 Delete `packages/darnit-baseline/src/darnit_baseline/checks/level3.py`
- [x] 3.8 Delete `packages/darnit-baseline/src/darnit_baseline/checks/helpers.py`
- [x] 3.9 Delete `packages/darnit-baseline/src/darnit_baseline/checks/constants.py`
- [x] 3.10 Clean up `packages/darnit-baseline/src/darnit_baseline/checks/__init__.py` — remove imports of deleted modules
- [x] 3.11 Delete `packages/darnit-baseline/src/darnit_baseline/adapters/builtin.py`
- [x] 3.12 Clean up `packages/darnit-baseline/src/darnit_baseline/adapters/__init__.py` — remove imports of deleted module

## 4. Delete Dead Tests

- [x] 4.1 Delete `tests/darnit_baseline/test_checks.py`

## 5. Clean Up Remaining References

- [x] 5.1 Add TODO comment to `verify_with_llm_response()` in `packages/darnit/src/darnit/sieve/orchestrator.py` noting it still iterates `control_spec.passes` and should be refactored to use handler metadata
- [x] 5.2 Grep entire codebase for imports of deleted modules and fix (updated TOML function ref, docstring examples, and test string literals) (`controls.level1`, `controls.level2`, `controls.level3`, `checks.level1`, `checks.level2`, `checks.level3`, `checks.helpers`, `checks.constants`, `adapters.builtin`) and fix any remaining references

## 6. Verification

- [x] 6.1 Run `uv run ruff check .` — zero lint errors
- [x] 6.2 Run `uv run pytest tests/ --ignore=tests/integration/ -q` — all tests pass (838 passed)
- [x] 6.3 Run `uv run python scripts/validate_sync.py --verbose` — spec sync passes
- [x] 6.4 Run audit against this repo and verify results match pre-change baseline (26 PASS, 4 FAIL, 32 WARN — no regressions)
- [x] 6.5 Confirm zero remaining imports of deleted modules via grep
