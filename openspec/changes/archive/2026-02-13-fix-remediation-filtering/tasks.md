## 1. Fix executor INCONCLUSIVE handling

- [x] 1.1 In `executor.py:_execute_handler_invocations()`, change the success check from `status != PASS` to `status in (FAIL, ERROR)` so that INCONCLUSIVE from manual handlers does not set `all_success = False`
- [x] 1.2 Add unit tests for executor: remediation with `file_create` (PASS) + `manual` (INCONCLUSIVE) returns `success=True`
- [x] 1.3 Add unit test for executor: remediation with a handler returning FAIL returns `success=False`
- [x] 1.4 Add unit test for executor: remediation with only `manual` handlers (INCONCLUSIVE) returns `success=True`

## 2. Always run audit in remediate_audit_findings

- [x] 2.1 Refactor `remediate_audit_findings()` to always run `_run_baseline_checks()`, even when the user passes explicit categories (move audit call before the `if not categories` branch)
- [x] 2.2 Extract `non_passing_ids: set[str]` from audit results (set of control IDs with status != PASS)
- [x] 2.3 Pass `non_passing_ids` to each `_apply_remediation()` call in the category loop

## 3. Filter controls by audit results in _apply_remediation

- [x] 3.1 Add `non_passing_ids: set[str]` parameter to `_apply_remediation()` signature
- [x] 3.2 After filtering by `is_control_applicable()`, further filter `applicable_controls` to only include controls in `non_passing_ids`
- [x] 3.3 If all controls in the category are passing (filtered list empty after audit filtering), return a result with status indicating no remediation needed

## 4. Tests for orchestrator filtering

- [x] 4.1 Add unit test: category with mixed passing/failing controls only remediates the failing one
- [x] 4.2 Add unit test: category where all controls pass is skipped
- [x] 4.3 Add unit test: explicit categories still filter by audit results

## 5. Validation

- [x] 5.1 Run `uv run ruff check .` — all clean
- [x] 5.2 Run `uv run pytest tests/ --ignore=tests/integration/ -q` — all pass
- [x] 5.3 Run `uv run python scripts/validate_sync.py --verbose` — sync passes
