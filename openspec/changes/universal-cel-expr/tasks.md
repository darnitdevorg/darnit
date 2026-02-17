## 1. Extract CEL evaluation from exec handler into orchestrator

- [x] 1.1 Add post-handler CEL evaluation function in `orchestrator.py` that takes `handler_config`, `handler_result` and evaluates `expr` from config against `{"output": handler_result.evidence}`
- [x] 1.2 Wire the new function into the handler invocation path (between line 214 handler call and line 232 result recording) — only run when `handler_config` contains `expr` and handler returned PASS or FAIL
- [x] 1.3 Remove CEL evaluation block from `exec_handler` in `builtin_handlers.py` (lines 170-207) — the exec handler should just return its result with evidence; orchestrator handles `expr`
- [x] 1.4 Verify existing exec handler CEL tests still pass (evidence shape unchanged, `output.exit_code` / `output.stdout` / `output.json` still available via `{"output": evidence}`)

## 2. Remove ad-hoc negation from pattern handler

- [x] 2.1 Remove `must_not_match` parameter from `_regex_match_files()` and the `if must_not_match:` branch (lines 452-466)
- [x] 2.2 Remove `must_not_match` config read from `regex_handler()` (line 279) and from the call to `_regex_match_files()` (line 283)
- [x] 2.3 Remove `mode = "exclude_must_not_exist"` check and `_regex_exclude_mode()` function (lines 257-261, 287-310)
- [x] 2.4 Refactor `_regex_exclude_mode` into a simpler evidence-returning path: when `exclude_files` is present, glob the files, return a result with `files_found` and `found_files` in evidence (CEL does the pass/fail via `expr`)

## 3. Update TOML controls

- [x] 3.1 BR-01.01: Replace `must_not_match = true` with `expr = '!(output.any_match)'`
- [x] 3.2 QA-05.01: Replace `mode = "exclude_must_not_exist"` with `expr = 'output.files_found == 0'`
- [x] 3.3 QA-05.02: Replace `mode = "exclude_must_not_exist"` with `expr = 'output.files_found == 0'`

## 4. Update tests

- [x] 4.1 Replace `test_pass_with_must_not_match_absent` and `test_fail_with_must_not_match_present` with CEL expression equivalents (test the orchestrator-level evaluation, not the handler)
- [x] 4.2 Replace `test_exclude_pass_when_no_files` and `test_exclude_fail_when_files_found` with CEL expression equivalents
- [x] 4.3 Add test: `expr` on pattern handler — `expr = 'output.any_match'` returns PASS when pattern matches
- [x] 4.4 Add test: `expr` on pattern handler — `expr = '!(output.any_match)'` returns PASS when pattern absent
- [x] 4.5 Add test: `expr` on exec handler still works after extraction (backwards compat)
- [x] 4.6 Add test: `expr` CEL error falls through to handler verdict
- [x] 4.7 Add test: `expr` skipped when handler returns ERROR or INCONCLUSIVE

## 5. Update docs and handler docstrings

- [x] 5.1 Update `regex_handler` docstring to remove `must_not_match` and `mode` fields, add note that `expr` is available via orchestrator
- [x] 5.2 Update `exec_handler` docstring to note that `expr` is now evaluated by the orchestrator, not the handler itself
- [x] 5.3 Run `uv run python scripts/validate_sync.py --verbose` to verify spec sync
- [x] 5.4 Run `uv run python scripts/generate_docs.py` and commit any doc changes
