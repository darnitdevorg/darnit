## 1. Extract `run_sieve_audit()` from existing code

- [x] 1.1 Rename `_run_sieve_checks()` to `run_sieve_audit()` in `packages/darnit/src/darnit/tools/audit.py`, broaden signature to accept optional `controls: list[ControlSpec] | None`, `tags: list[str] | None`, `apply_user_config: bool = True`, `stop_on_llm: bool = True`
- [x] 1.2 When `controls` parameter is provided, skip the TOML/registry loading and use provided controls directly; when `None`, preserve existing loading behavior
- [x] 1.3 Add `summarize_results()` call at the end of `run_sieve_audit()` so it returns `(results, summary)` tuple
- [x] 1.4 Add `run_sieve_audit` to the public exports in `darnit/tools/__init__.py`

## 2. Update `run_checks()` as thin wrapper

- [x] 2.1 Rewrite `run_checks()` to call `run_sieve_audit()` internally, converting its return from `(results, summary)` to the existing `(results, skipped_controls)` return type
- [x] 2.2 Verify CLI path (`cmd_audit`) and remediation orchestrator (`_run_baseline_checks`) still work through `run_checks()` — run existing tests

## 3. Refactor `builtin_audit()` to delegate

- [x] 3.1 Rewrite `builtin_audit()` in `packages/darnit/src/darnit/server/tools/builtin_audit.py` to call `run_sieve_audit(controls=loaded_controls, ...)` instead of inline sieve loop
- [x] 3.2 Replace `_format_audit_report()` call with `format_results_markdown()` from `darnit.tools.audit`
- [x] 3.3 Delete `_format_audit_report()` function (~90 lines)

## 4. Refactor `audit_openssf_baseline()` to delegate

- [x] 4.1 Rewrite the sieve loop section in `audit_openssf_baseline()` in `packages/darnit-baseline/src/darnit_baseline/tools.py` to call `run_sieve_audit(controls=filtered_controls, ...)` instead of inline loop + summary calculation
- [x] 4.2 Keep existing config/control loading and tag filtering before the call
- [x] 4.3 Keep existing `format_results_markdown()` usage after the call

## 5. Delete duplicate `detect_workflow_checks`

- [x] 5.1 Grep for all imports of `detect_workflow_checks` from `darnit.remediation.helpers` and redirect them to `darnit.remediation.github`
- [x] 5.2 Delete `detect_workflow_checks()` from `packages/darnit/src/darnit/remediation/helpers.py` (~80 lines)
- [x] 5.3 Verify no remaining references to the deleted function

## 6. Update framework-design spec

- [x] 6.1 Add "Audit Pipeline" section to `openspec/specs/framework-design/spec.md` codifying: all audit entry points MUST delegate to `run_sieve_audit()`, no module SHALL reimplement the sieve loop, utility functions MUST NOT be duplicated within the framework package

## 7. Tests and verification

- [x] 7.1 Run `uv run ruff check .` — all linting passes
- [x] 7.2 Run `uv run pytest tests/ --ignore=tests/integration/ -q` — all tests pass
- [x] 7.3 Grep for any remaining inline `orchestrator.verify()` loops outside `run_sieve_audit()` — should be zero
- [x] 7.4 Grep for `_format_audit_report` — should be zero hits
- [x] 7.5 Grep for `detect_workflow_checks` in `helpers.py` — should be zero hits
