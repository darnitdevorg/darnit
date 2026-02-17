## Why

The pattern handler has two ad-hoc negation mechanisms (`must_not_match` boolean flag, `mode = "exclude_must_not_exist"` string) that solve specific one-off needs but don't compose. Meanwhile, the `cel-expressions` spec already defines `expr` as a universal field with context variables for every handler type — but only the exec handler implements it. The schema is `0.1.0-alpha`, so now is the time to close this gap before the TOML contract stabilizes.

## What Changes

- **BREAKING**: Remove `must_not_match` field from the pattern/regex handler. Replace with `expr = '!(output.any_match)'` in TOML controls that used it (currently only BR-01.01).
- **BREAKING**: Remove `mode = "exclude_must_not_exist"` from the pattern handler. Replace with `expr = 'output.files_found == 0'` in TOML controls that used it (QA-05.01, QA-05.02).
- Move CEL expression evaluation out of `exec_handler` into a shared post-handler step in the sieve orchestrator or a common wrapper, so `expr` works on any handler that returns `HandlerResult`.
- Define the CEL context shape for the pattern handler (aligning with the existing `cel-expressions` spec which already specifies `files` and `matches` for pattern passes).
- Update `openssf-baseline.toml` controls to use `expr` instead of the removed fields.

## Capabilities

### New Capabilities

_(none — this extends an existing capability)_

### Modified Capabilities

- `cel-expressions`: The `expr` field moves from exec-handler-only to a universal post-handler evaluation step. The pattern handler context variables (`files`, `matches`) specified in the existing spec get implemented. A new `output.any_match` boolean and `output.files_found` integer are added to the pattern context to support common assertions without requiring TOML authors to write list expressions.
- `handler-pipeline`: The sieve pipeline gains a post-handler CEL evaluation step that runs after any handler returns a result, before the orchestrator records the verdict.

## Impact

- **`packages/darnit/src/darnit/sieve/builtin_handlers.py`**: Remove `must_not_match` parameter, `_regex_exclude_mode` function, and CEL evaluation from `exec_handler`. Pattern handler simplifies.
- **`packages/darnit/src/darnit/sieve/orchestrator.py`** (or new shared module): Add universal post-handler CEL evaluation step.
- **`packages/darnit-baseline/openssf-baseline.toml`**: Update BR-01.01 (`must_not_match → expr`), QA-05.01 and QA-05.02 (`mode → expr`).
- **`tests/darnit/sieve/test_builtin_handlers.py`**: Replace `must_not_match` tests with CEL expression tests on the pattern handler.
- **No new dependencies**: CEL evaluator already exists and is used by exec handler.
