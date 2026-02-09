## 1. Update Specs to Reflect Handler-Based Architecture

The specs were written before the design evolved to the handler-based architecture.
They reference `exec = { shared = "..." }` and typed pass fields. Update them to use
`HandlerInvocation` and the phased list format from the design.

- [x] 1.1 Update `specs/shared-execution/spec.md` — rename to `shared-handlers`, replace `ExecPassConfig` references with `HandlerInvocation`, update TOML examples to `[shared_handlers]` and `{ shared = "name", expr = "..." }` format
- [x] 1.2 Update `specs/framework-design/spec.md` — replace `file_must_exist` / `exec` typed field references with handler-based `deterministic = [{ handler = "file_exists", ... }]` format; add requirement for handler registry
- [x] 1.3 Add new spec `specs/handler-pipeline/spec.md` — define the confidence gradient (deterministic → pattern → llm → manual), `HandlerInvocation` schema, handler registration protocol, phase affinity, and how the same gradient applies to context gathering and remediation
- [x] 1.4 Update `specs/conditional-controls/spec.md` and `specs/control-dependencies/spec.md` — minor updates to reference handler pipeline instead of "verification passes"

## 2. Handler Registry and Interface

Core infrastructure that everything else builds on. Must be in `packages/darnit/` (framework layer).

- [x] 2.1 Define `HandlerResult` dataclass — status (pass/fail/error/inconclusive), confidence (0.0-1.0), evidence dict, message string
- [x] 2.2 Define handler callable protocol — `(config: dict, context: HandlerContext) -> HandlerResult` where `HandlerContext` carries local_path, project config, evidence so far, shared cache
- [x] 2.3 Create `SieveHandlerRegistry` class in `packages/darnit/src/darnit/sieve/handler_registry.py` — register by name + phase affinity, lookup by name, phase affinity validation (warn if used in wrong phase)
- [x] 2.4 Register built-in verification handlers: `file_exists`, `exec`, `regex`, `llm_eval`, `manual_steps`
- [x] 2.5 Register built-in remediation handlers: `file_create`, `exec` (reuse), `api_call`, `project_update`, `manual_steps` (reuse)
- [x] 2.6 Wire handler registration into sieve __init__.py exports; implementations use existing register_handlers() to register domain-specific sieve handlers

## 3. Schema Changes

Update `framework_schema.py` Pydantic models to support the new architecture.

- [x] 3.1 Add `HandlerInvocation` model with `handler: str`, `shared: str | None`, and `extra="allow"`
- [x] 3.2 Refactor `PassesConfig` — four optional `list[HandlerInvocation]` fields (deterministic, pattern, llm, manual) replacing the current typed pass fields
- [x] 3.3 Add backward compatibility: `PassesConfig` validator that detects old-style typed configs (bare `DeterministicPassConfig`, `ExecPassConfig`) and converts them to `list[HandlerInvocation]` internally
- [x] 3.4 Refactor `RemediationConfig` — four optional `list[HandlerInvocation]` fields replacing `file_create`, `exec`, `api_call`, `manual`, `project_update`
- [x] 3.5 Add backward compatibility for `RemediationConfig` — same pattern as 3.3
- [x] 3.6 Add `SharedHandlerConfig` model and `shared_handlers: dict[str, SharedHandlerConfig]` to `FrameworkConfig`
- [x] 3.7 Add `when: dict[str, Any] | None` to `ControlConfig`
- [x] 3.8 Add `depends_on: list[str] | None` and `inferred_from: str | None` to `ControlConfig`
- [x] 3.9 Add `use_locator: bool = False` to `HandlerInvocation` (for `file_exists` handler convenience)
- [x] 3.10 Extend context definition schema — add `detect: list[dict] | None` for handler-based context auto-detection pipeline

## 4. Control Loader Updates

Update `control_loader.py` to resolve new schema features at load time.

- [x] 4.1 Resolve `shared` references in `HandlerInvocation` — merge shared handler config with per-control overrides (control's `expr` etc. take precedence)
- [x] 4.2 Resolve `use_locator = true` — copy `locator.discover` into handler's `files` parameter at load time; log warning if `locator.discover` missing
- [x] 4.3 Auto-derive `on_pass` — when control has `locator.project_path` + deterministic `file_exists` handler + no explicit `on_pass`, generate `on_pass.project_update`
- [x] 4.4 Validate `depends_on` and `inferred_from` references — warn on references to unknown control IDs

## 5. Sieve Orchestrator Updates

Update `orchestrator.py` for the new execution model.

- [x] 5.1 Add `SieveStatus.NOT_APPLICABLE` result status
- [x] 5.2 Implement `when` clause evaluation — evaluate before entering phase loop, return N/A if condition is false, run normally if context key is missing (debug log)
- [x] 5.3 Implement `_resolve_execution_order()` — topological sort from `depends_on` + implicit deps from `inferred_from`, cycle detection with warning and back-edge removal
- [x] 5.4 Implement `inferred_from` logic — if referenced control PASSES, auto-PASS with inference message; otherwise run own handlers normally
- [x] 5.5 Inject dependency results into evidence — `dependency.<CTRL_ID>.status` available to dependent controls
- [x] 5.6 Add `SharedHandlerCache` — dict keyed by shared handler name, populated on first execution, reused for subsequent references within the same audit run
- [x] 5.7 Refactor `verify()` to dispatch handler invocations from phase lists instead of typed pass objects — iterate phases in order, for each phase iterate handler invocations, stop at first conclusive result

## 6. Remediation Executor Updates

- [x] 6.1 Refactor executor to dispatch handler invocations from phased lists instead of typed remediation fields
- [x] 6.2 Extend `_get_substitutions()` to resolve `${context.<key>}` from confirmed context values
- [x] 6.3 Extend `_get_substitutions()` to resolve `${project.<dotted.path>}` from `.project/project.yaml`
- [x] 6.4 Update `_substitute()` to handle `${...}` patterns alongside existing `$VAR` replacement

## 7. Context Gathering Pipeline

- [x] 7.1 Implement context detection pipeline runner — process `detect` list from context definitions through the phase gradient (deterministic → pattern → llm → manual/confirm)
- [x] 7.2 Wire detection pipeline into `get_pending_context` — replace ad-hoc `_auto_detect_context()` with handler-based detection
- [x] 7.3 Implement `confirm = "manual"` — prompt user for confirmation of detected values before writing to `.project/`

## 8. Audit Report Updates

- [x] 8.1 Add "Not Applicable" section to markdown report — list N/A controls with their unmet `when` conditions, separate from PASS/FAIL/WARN
- [x] 8.2 Add inference annotations — mark inferred PASSes with their source control in the report

## 9. Migrate openssf-baseline.toml

Migrate the existing 2600+ line TOML to use new features. Can be done incrementally
since backward compatibility (tasks 3.3, 3.5) ensures old format still works.

- [x] 9.1 Add `[shared_handlers]` section — extract `branch_protection`, `repo_info`, and other repeated API calls into shared definitions
- [x] 9.2 Add `when` clauses to release/library/CI-specific controls (e.g., `when = { has_releases = true }` on OSPS-BR-02.*)
- [x] 9.3 Add `depends_on` and `inferred_from` where applicable (e.g., OSPS-LE-03.02 `inferred_from = "OSPS-LE-03.01"`)
- [x] 9.4 Replace `file_must_exist` + `locator.discover` DRY violations with `use_locator = true` — 12 controls converted, `_resolve_use_locator()` copies `locator.discover` into `files` at load time
- [x] 9.5 Convert controls to handler-based format — completed in handler-dispatch change; all controls use `[[controls."ID".passes]]` with handler invocations
- [x] 9.6 Add `detect` pipelines to context definitions — replace hardcoded detection logic with declarative handler pipelines

## 10. Tests

- [x] 10.1 Unit tests for `HandlerRegistry` — registration, lookup, phase affinity validation, duplicate name handling
- [x] 10.2 Unit tests for `HandlerInvocation` schema — `extra="allow"` passes through handler-specific config, `shared` reference resolution
- [x] 10.3 Unit tests for backward compatibility — old-style `PassesConfig` and `RemediationConfig` auto-converted to handler lists
- [x] 10.4 Unit tests for `when` clause evaluation — boolean, string equality, list membership, missing key, multiple AND conditions
- [x] 10.5 Unit tests for dependency resolution — topological sort, cycle detection, out-of-scope references ignored
- [x] 10.6 Unit tests for `inferred_from` — auto-PASS on source pass, normal execution on source fail, implicit depends_on
- [x] 10.7 Unit tests for shared handler cache — execute once, reuse cached result, cache scoped to audit run, error propagation
- [x] 10.8 Unit tests for `use_locator` and auto-derived `on_pass` — load-time resolution, precedence rules
- [x] 10.9 Unit tests for `${context.*}` and `${project.*}` template variables — resolution, unresolved → empty string, dotted path traversal
- [x] 10.10 Unit tests for N/A report section — separate from PASS/FAIL/WARN, shows unmet conditions
- [x] 10.11 Integration test — end-to-end audit with shared handlers, when clauses, dependencies, inferred_from, template variables, and N/A reporting
