## 1. Schema Changes

- [x] 1.1 Add `when: dict[str, Any] | None = None` field to `HandlerInvocation` in `framework_schema.py`
- [x] 1.2 Add `strategy: Literal["all", "first_match"] = "all"` field to `RemediationConfig` in `framework_schema.py`
- [x] 1.3 Add `languages: list[str] | None = None` field to the context schema in `schema.py`

## 2. When Evaluator

- [x] 2.1 Create `packages/darnit/src/darnit/config/when_evaluator.py` with `evaluate_when(when_clause, context) -> bool`
- [x] 2.2 Implement match rules: str==str, str-in-list, bool==bool, scalar-in-list-context, subset check, missing key returns False
- [x] 2.3 Implement AND semantics for multiple keys in a single `when` clause
- [x] 2.4 Add debug logging for missing context keys and evaluation results

## 3. Language Detection

- [x] 3.1 Add `detect_languages(local_path) -> list[str]` to `auto_detect.py` that collects all manifest matches without early break
- [x] 3.2 Apply TypeScript refinement (package.json + tsconfig.json → typescript instead of javascript) in `detect_languages()`
- [x] 3.3 Call `detect_languages()` from `collect_auto_context()` and include result as `languages` key
- [x] 3.4 Add `languages` to context storage flattening in `context_storage.py` (preserve list value, don't convert to string)

## 4. Sieve Orchestrator Integration

- [x] 4.1 Import `evaluate_when` in `orchestrator.py`
- [x] 4.2 Add `when` evaluation before handler dispatch in `_dispatch_handler_invocations()` — skip handler if `invocation.when` is set and evaluates to false
- [x] 4.3 Assemble flat context dict from `HandlerContext.project_context` for `when` evaluation

## 5. Remediation Executor Integration

- [x] 5.1 Import `evaluate_when` in `executor.py`
- [x] 5.2 Add `when` evaluation before handler dispatch in `_execute_handler_invocations()` — skip handler if `invocation.when` is set and evaluates to false
- [x] 5.3 Implement `first_match` strategy: break after first dispatched handler when `config.strategy == "first_match"`
- [x] 5.4 Handle `first_match` with no matching handlers: return result with "no applicable remediation" message listing unmatched conditions
- [x] 5.5 Assemble flat context dict from `self._project_values` and `self._context_values` for `when` evaluation

## 6. Tests

- [x] 6.1 Unit tests for `evaluate_when()`: str equality, bool equality, str-in-list, scalar-in-list-context, subset check, missing key, empty list, AND semantics
- [x] 6.2 Unit tests for `detect_languages()`: single language, multi-language, TypeScript refinement, no manifests, deduplication (multiple python manifests)
- [x] 6.3 Integration test: sieve orchestrator skips handler when `when` condition is false, runs when true, runs unconditionally when no `when`
- [x] 6.4 Integration test: remediation executor with `strategy = "all"` runs all matching handlers
- [x] 6.5 Integration test: remediation executor with `strategy = "first_match"` stops after first match, falls through to manual, handles no-match case
- [x] 6.6 Test that `when` field does NOT appear in handler config dict (Pydantic explicit field vs model_extra)

## 7. Spec Sync and Docs

- [x] 7.1 Run `validate_sync.py` and fix any spec-implementation drift
- [x] 7.2 Run `generate_docs.py` and commit any changes to `docs/generated/`
