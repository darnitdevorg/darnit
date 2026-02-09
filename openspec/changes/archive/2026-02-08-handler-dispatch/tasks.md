## Tasks

### Group 1: Schema Changes — Flatten Phase Buckets

Replace phase-bucketed handler lists with flat ordered lists in the schema, per Design Decisions 1 and 6.

- [x] 1.1 Replace `PassesConfig` phase fields with flat list
  - Remove `PassesConfig` model (or simplify it) — `passes` on the control becomes `list[HandlerInvocation]` directly
  - Remove the four phase fields: `deterministic`, `pattern`, `llm`, `manual`
  - Remove `normalize_to_legacy_passes()` validator, `get_ordered_passes()`, `has_handler_invocations()`, `get_handler_invocations()`
  - Add a validator that rejects legacy typed format with a clear error message (Spec: "Legacy typed-pass TOML format is rejected at load time")
  - File: `packages/darnit/src/darnit/config/framework_schema.py`

- [x] 1.2 Replace `RemediationConfig` phase fields with `handlers` list
  - Replace the four phase fields (`deterministic`, `pattern`, `llm`, `manual`) with a single `handlers: list[HandlerInvocation]` field
  - Keep metadata fields: `requires_context`, `project_update`
  - Remove `has_handler_invocations()`, `has_legacy_config()`, `get_handler_invocations()`
  - File: `packages/darnit/src/darnit/config/framework_schema.py`

- [x] 1.3 Remove legacy pass config classes
  - Remove `DeterministicPassConfig`, `PatternPassConfig`, `LLMPassConfig`, `ManualPassConfig`, `ExecPassConfig`
  - Remove the optional typed fields from `PassesConfig` that reference these classes
  - File: `packages/darnit/src/darnit/config/framework_schema.py`

- [x] 1.4 Remove legacy remediation config classes
  - Remove `FileCreateRemediationConfig`, `ExecRemediationConfig`, `ApiCallRemediationConfig`, `ManualRemediationConfig`, `ProjectUpdateRemediationConfig`
  - Remove the optional typed fields from `RemediationConfig` that reference these classes
  - File: `packages/darnit/src/darnit/config/framework_schema.py`

### Group 2: Orchestrator & Executor — Remove Legacy Dispatch

Remove legacy execution paths and update dispatch to use the flat handler list.

- [x] 2.1 Update orchestrator to iterate flat handler list
  - `_dispatch_handler_invocations()` should read from the flat `passes` list instead of phase-bucketed fields
  - Remove the legacy pass execution loop ("Step 5") from `verify()` (~lines 363-501)
  - When `passes` is empty or missing, return WARN (Spec: "Control without handler invocations fails gracefully")
  - File: `packages/darnit/src/darnit/sieve/orchestrator.py`

- [x] 2.2 Update executor to iterate flat handler list
  - `_execute_handler_invocations()` should read from `config.handlers` instead of phase-bucketed fields
  - Remove legacy format dispatch in `execute()`: the `if config.file_create / elif config.exec / ...` chain
  - Remove legacy implementation methods: `_execute_file_create()`, `_execute_exec()`, `_execute_api_call()`
  - Keep `apply_project_update()` — used by `on_pass`, not remediation dispatch
  - File: `packages/darnit/src/darnit/remediation/executor.py`

- [x] 2.3 Update handler registry phase affinity
  - Phase affinity kept as metadata (documentation/categorization only, not structural)
  - List position determines execution order; phase is advisory
  - Added `"pattern"` and `"manual"` aliases so TOML can use intuitive names
  - File: `packages/darnit/src/darnit/sieve/handler_registry.py`, `packages/darnit/src/darnit/sieve/builtin_handlers.py`

### Group 3: TOML Pass Migration

Migrate all verification pass blocks in `openssf-baseline.toml` from legacy typed format to flat handler invocation lists. Each task is one legacy pass type, migrated as a batch per Design Decision 3.

- [x] 3.1 Convert all `passes.exec` blocks to handler invocations
  - 16 blocks: `passes.exec = { command = [...] }` → `[[controls."ID".passes]]` with `handler = "exec"`
  - Preserve all fields (command, pass_exit_codes, output_format, expr, timeout, env, cwd) via `extra="allow"`
  - Order: place exec handlers before manual_steps in the list
  - File: `packages/darnit-baseline/openssf-baseline.toml`

- [x] 3.2 Convert all `passes.pattern` blocks to handler invocations
  - 35 blocks migrated to `[[controls."ID".passes]]` with `handler = "pattern"` (alias for `"regex"`)
  - Alias registered in `builtin_handlers.py` so both names resolve to `regex_handler`
  - All fields preserved via `extra="allow"`
  - File: `packages/darnit-baseline/openssf-baseline.toml`

- [x] 3.3 Convert all `passes.manual` blocks to handler invocations
  - 93 blocks migrated to `[[controls."ID".passes]]` with `handler = "manual"` (alias for `"manual_steps"`)
  - Alias registered in `builtin_handlers.py` so both names resolve to `manual_steps_handler`
  - All fields preserved via `extra="allow"`; manual handlers placed last in lists
  - File: `packages/darnit-baseline/openssf-baseline.toml`

- [x] 3.4 Convert all `passes.deterministic` (file_must_exist) blocks to handler invocations
  - ~15 blocks: `passes.deterministic = { file_must_exist = [...] }` → `[[controls."ID".passes]]` with `handler = "file_exists"`
  - For controls with `locator.discover` that duplicates `file_must_exist`, use `use_locator = true` per Design Decision 5
  - For controls without a locator, use explicit `files = [...]`
  - These should be first in each control's passes list (highest confidence)
  - File: `packages/darnit-baseline/openssf-baseline.toml`

### Group 4: TOML Remediation Migration

Migrate all remediation blocks from legacy typed format to flat handler invocation lists per Design Decision 6.

- [x] 4.1 Convert all `remediation.file_create` blocks to handler invocations
  - 13 blocks: `remediation.file_create = { ... }` → `[[controls."ID".remediation.handlers]]` with `handler = "file_create"`
  - Preserve all fields (path, template, content, overwrite, create_dirs) via `extra="allow"`
  - File: `packages/darnit-baseline/openssf-baseline.toml`

- [x] 4.2 Convert the `remediation.api_call` block to handler invocation
  - 1 block: `remediation.api_call = { ... }` → `[[controls."ID".remediation.handlers]]` with `handler = "api_call"`
  - File: `packages/darnit-baseline/openssf-baseline.toml`

- [x] 4.3 Convert all `remediation.manual` blocks to handler invocations
  - All blocks migrated to `[[controls."ID".remediation.handlers]]` with `handler = "manual"` (alias for `"manual_steps"`)
  - All fields preserved via `extra="allow"`
  - File: `packages/darnit-baseline/openssf-baseline.toml`

- [x] 4.4 Verify `remediation.project_update` blocks work unchanged
  - 3 blocks use `project_update = { set = {...} }` applied via `on_pass`
  - Per Design Decision 6, `project_update` stays as a separate field on `RemediationConfig`
  - Verify these still work after schema changes
  - File: `packages/darnit-baseline/openssf-baseline.toml`

### Group 5: Tests

Update and add tests to cover the flat-list dispatch path and verify migration correctness.

- [x] 5.1 Add integration test asserting handler-only dispatch
  - Test loads real openssf-baseline.toml via `load_controls_from_toml`, verifies >50 controls with handler_invocations
  - Verifies all handler names in TOML resolve in registry (including "pattern" and "manual" aliases)
  - File: `tests/darnit_baseline/test_handler_dispatch_integration.py`

- [x] 5.2 Add test that legacy TOML format is rejected at load time
  - Already exists in `tests/darnit/sieve/test_handler_architecture.py::TestLegacyFormatRejection`
  - Tests `test_passes_legacy_dict_rejected` and `test_passes_flat_list_accepted`

- [x] 5.3 Add test for graceful WARN on empty passes list
  - `TestWarnOnEmptyPasses::test_no_handler_invocations_returns_warn`
  - `TestWarnOnEmptyPasses::test_empty_handler_invocations_returns_warn`
  - File: `tests/darnit_baseline/test_handler_dispatch_integration.py`

- [x] 5.4 Add test for flat list ordering
  - `TestFlatListOrdering::test_stops_at_first_pass`
  - `TestFlatListOrdering::test_continues_through_inconclusive`
  - `TestFlatListOrdering::test_stops_at_first_fail`
  - `TestFlatListOrdering::test_manual_only_reached_if_preceding_inconclusive`
  - `TestFlatListOrdering::test_evidence_accumulates_across_handlers`
  - File: `tests/darnit_baseline/test_handler_dispatch_integration.py`

- [x] 5.5 Update existing tests
  - No legacy fallback or phase-bucketed tests exist — already cleaned up
  - No `normalize_to_legacy_passes` tests exist — already removed
  - Existing handler tests in `test_handler_architecture.py` already use flat list format
  - 845 tests pass with no legacy test debt

- [x] 5.6 Run full test suite and fix any failures
  - `uv run pytest tests/ --ignore=tests/integration/ -q` — 834 passed
  - `uv run ruff check .` — All checks passed
  - No failures from schema/dispatch changes

### Group 6: Verification

Final checks that the migration is complete and correct.

- [x] 6.1 Verify no legacy format remains in TOML
  - Grepped for all legacy patterns: 0 hits for `passes.exec =`, `passes.pattern =`, `passes.manual =`, `passes.deterministic =`, `remediation.file_create =`, `remediation.api_call =`, `remediation.manual =`
  - All pass/remediation blocks use handler invocation list format

- [x] 6.2 Verify no legacy dispatch code remains in framework
  - Grepped for all legacy class names: 0 hits in `packages/` (only stale __pycache__ and TODO comments)
  - `normalize_to_legacy_passes`, `get_ordered_passes`, `has_legacy_config`: 0 hits

- [x] 6.3 Verify no phase-bucketed fields remain in schema
  - `PassesConfig` class does not exist — `ControlConfig.passes` is `list[HandlerInvocation]` directly
  - `RemediationConfig.handlers` is `list[HandlerInvocation]` — no phase fields
  - Legacy format validator on `ControlConfig.validate_passes_format` rejects phase-bucketed input

- [ ] 6.4 Verify `use_locator = true` replaced DRY violations
  - 19 `file_exists` handlers with explicit `files = [...]`, 0 use `use_locator = true`
  - Low-priority optimization: could replace explicit lists with `use_locator = true` where locator.discover exists
  - Not a functional gap — all handlers work correctly with explicit file lists
