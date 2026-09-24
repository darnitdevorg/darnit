# Phase 0 Research: Wire detect_filter Into Context Detection

**Feature**: 039 | **Date**: 2026-09-23

Every behaviour below was executed against the evaluator in this repository, not inferred.

---

## R1: How the expression gets a `value` binding

**Decision**: pass a plain dict, `evaluate_cel(expression, {"value": candidate})`. Do not add a field to `CELContext`.

**Verified**: `CELContext` declares `output`, `response`, `files`, `matches`, `project`, `context`, `repo` -- there is no `value`. But `evaluate_cel` accepts `dict[str, Any] | CELContext`, and the dict path works with the shipped expression:

```
security@example.com   -> success=True  value=False   (reject)
security@real.org      -> success=True  value=True    (keep)
SECURITY.md            -> success=True  value=True    (keep)
```

**Rationale**: `CELContext` is shared with the control sieve, where `value` would be a meaningless binding. Adding a field there to serve one context-detection feature widens a shared type for a local need. The dict path already exists and is already public.

**Alternatives considered**: adding `value: Any` to `CELContext`. Rejected as above. Introducing a second expression language: never seriously considered, the spec rules it out.

---

## R2: Binding a list fails open, which corrects the spec

**Decision**: element-wise evaluation is not merely tidier than binding the whole list -- binding the whole list is actively unsafe.

**Verified**: the spec's Edge Cases said a list-valued key "would fail the expression at evaluation time." That is wrong. It does not fail:

```
evaluate_cel("!value.contains('example.com')", {"value": ["a@example.com"]})
  -> success=True, value=True     # the filter PASSES
```

CEL's `contains` on a list is **membership, not substring**. `["a@example.com"].contains("example.com")` is `False`, because no element equals that string. Negated, the filter returns true and the list is kept -- including the element the filter was written to reject.

**Rationale**: this is the same failure shape as the bug being fixed, arriving through the fix itself. A guard that returns "passed" for input it cannot meaningfully judge is worse than one that errors, because nothing surfaces. FR-012's element-wise rule avoids it by only ever binding scalars.

**Consequence for the spec**: the Edge Cases entry asserting evaluation-time failure is factually wrong and is corrected as part of this feature.

---

## R3: Compile errors raise; runtime errors return

**Decision**: handle both paths. `success=False` is not sufficient on its own.

**Verified**:

| input | behaviour |
|---|---|
| malformed expression (`!value.contains(`) | **raises `CELCompilationError`** from `evaluate_cel` |
| wrong type (`value` is an int) | returns `CELResult(success=False, error="no such overload...")` |
| binding absent entirely | returns `CELResult(success=False, error="undeclared reference to 'value'")` |

**Rationale**: an implementation that only inspects `result.success` will propagate `CELCompilationError` out of context collection and crash the audit, instead of discarding the value and reporting as FR-006 and FR-007 require. An implementation that only catches the exception will treat a runtime type error as... nothing at all, because no exception arrives.

**Note**: compiling once per key rather than once per element is both faster and the point at which a malformed expression is detected -- before any element is evaluated, so the report names the key once rather than once per element.

---

## R4: Where filtering has to happen

**Decision**: filter inside the detection step in `context_storage.py`, between the two detection routes and the auto-accept check.

**Verified** at `context_storage.py:547-557`:

```python
current_value = None
if detect_pipeline:
    current_value = _run_detect_pipeline(key, detect_pipeline, local_path, owner, repo)
if current_value is None and definition.auto_detect:
    current_value = _try_sieve_detection(key, local_path, owner, repo)

if current_value is not None and current_value.confidence >= auto_accept_threshold:
    ...save_context_value(...)
```

Both routes converge on `current_value` before the threshold is consulted. A single filter applied to `current_value` after the second `if` and before the threshold check satisfies FR-004 and FR-005 together, with no duplicated logic.

**Rationale**: filtering inside each route separately would be two call sites to keep in step, and the sieve fallback is the older path most likely to be forgotten. One choke point is harder to leave a hole in.

---

## R5: The auto-accept threshold makes this reachable without a prompt

**Verified**: `auto_accept_threshold` defaults to 0.8 (`context_storage.py:516`) and `openssf-baseline.toml:274` sets `auto_accept_confidence = 0.8`. A detect-pipeline result carrying no explicit confidence is normalized to 0.8 (PR #417), landing exactly on the threshold.

**Consequence**: a detected `security@example.com` is written to `.project/` as `AUTO_DETECTED` with no prompt. This is why #165's "Impact: Low -- the context collection step still asks the user to confirm" understates it, and why FR-005's ordering constraint carries the severity rather than being a tidiness point.

---

## R6: The read path does nothing

**Verified**: `get_context_value` (`context_storage.py:177`) calls `load_context` and returns whatever is stored. No validation, no filtering.

**Decision**: re-evaluate the filter there (FR-014), and do not write (FR-015).

**Rationale**: without this the feature only protects repositories that have never been audited. With it, the population most affected by the bug is covered on their next audit. Not writing keeps the framework from revoking a value a person may have confirmed -- `.project/` is a file humans edit.

---

## R7: Catching the next unwired key

**Decision**: extend `scripts/validate_sync.py` with a check that every key in a `[context.*]` block of a shipped TOML is a declared field on `ContextDefinitionConfig`.

**Rationale**: `ContextDefinitionConfig` sets `extra="allow"`, so an undeclared key is retained and never reported. `detect_filter` and `value_if_fail` are two instances of the same defect found by two unrelated bug reports. The check is a dozen lines and turns the class into a CI failure.

**Scope boundary**: the check reads TOMLs shipped in this repository. It does not change the schema, so third-party plugin configs continue to load as they do today (spec FR-010).

---

## R8: How the read path resolves the filter (T018, decided during implementation)

**Decision**: resolve it inside the read path via `get_context_definitions(local_path)`. Do not add a parameter to `get_context_value`.

**Rationale**: the alternative -- an optional parameter defaulting to no filtering -- means any future caller silently skips the guard. That is this feature's own defect class, reintroduced by its fix. Resolving internally means no caller can opt out by omission.

**Cost, measured**: framework config loading is cached by path and mtime (`merger.py:536`, `_framework_config_cache`), so the lookup is not a per-read config parse.

**A gap this surfaced**: `context_schema.ContextDefinition` also lacked `detect_filter`, and `get_context_definitions` did not map it across. Issue #165 named both models; T001 as written covered only `framework_schema.ContextDefinitionConfig`. The read path reads the other one, so wiring it required both.
