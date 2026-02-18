## Context

CEL expression evaluation currently lives inside `exec_handler` (builtin_handlers.py:170-207). It builds a handler-specific context (`output.stdout`, `output.exit_code`, etc.), evaluates the expression, and returns PASS/INCONCLUSIVE/fallthrough based on the result. No other handler supports `expr`.

Meanwhile, the pattern/regex handler has two ad-hoc negation mechanisms:
- `must_not_match = true` — inverts match result (1 consumer: BR-01.01)
- `mode = "exclude_must_not_exist"` — PASS if file globs match nothing (2 consumers: QA-05.01, QA-05.02)

Both are special cases of "evaluate the handler's evidence with an expression." The `cel-expressions` spec already defines context variables for the pattern handler (`files`, `matches`) but they were never implemented.

The handler invocation point is `orchestrator.py:214`:
```python
handler_result = handler_info.fn(handler_config, handler_ctx)
```

## Goals / Non-Goals

**Goals:**
- `expr` works on any handler, not just exec
- Remove `must_not_match` and `mode = "exclude_must_not_exist"` from the pattern handler
- Each handler defines its own CEL context shape via its evidence dict
- The exec handler's existing CEL behavior is preserved (same context shape, same INCONCLUSIVE-on-false semantics)

**Non-Goals:**
- Changing how CEL expressions are parsed or sandboxed (cel_evaluator.py is unchanged)
- Adding new CEL functions
- Making `pass_if_any` expressible via CEL (it's still a handler-level config field)
- Supporting `expr` on remediation handlers (audit passes only)

## Decisions

### Decision 1: CEL evaluation lives in the orchestrator, not in handlers

**Choice:** Add a post-handler CEL evaluation step in `orchestrator.py` between handler invocation (line 214) and result recording (line 232).

**Alternative considered:** A decorator/wrapper function that each handler calls. Rejected because it requires every handler author to remember to call it, and plugin handlers would need to import it.

**Alternative considered:** Keep CEL in each handler individually (current exec approach). Rejected because it duplicates logic and requires every handler to independently build CEL contexts.

**Rationale:** The orchestrator already has the handler result and the config. It's the natural place for cross-cutting post-processing. Handler authors never need to know about CEL.

### Decision 2: The CEL context is built from handler evidence

**Choice:** The CEL context is `{"output": handler_result.evidence}`. Each handler already populates `evidence` with its relevant data — the pattern handler puts `any_match`, `files_checked`, `results` there; the exec handler puts `stdout`, `exit_code`, `json` there.

**Alternative considered:** Each handler defines a `get_cel_context()` method. Rejected because handlers are plain functions, not classes, and adding a protocol would be a larger refactor.

**Alternative considered:** A registry mapping handler names to context builders. Rejected as over-engineering for the current need.

**Rationale:** Evidence is already the handler's structured output. Making it the CEL context means zero handler changes — every handler automatically supports `expr` with whatever evidence it already provides.

### Decision 3: CEL false → INCONCLUSIVE (pipeline continues), not FAIL

**Choice:** When `expr` evaluates to `false`, return INCONCLUSIVE so the next pass in the pipeline can try. This matches the exec handler's current behavior (builtin_handlers.py:196-201).

**Alternative considered:** CEL false → FAIL. Rejected because it would break pipeline fallthrough semantics. For example, if zizmor's `expr` fails because zizmor isn't installed, the pattern fallback pass should still run.

**Exception:** When the handler itself already returned PASS and `expr` overrides it to false, INCONCLUSIVE is correct — it means "this handler didn't confirm compliance, try the next one."

### Decision 4: Exec handler keeps its domain-specific context shape

**Choice:** The exec handler continues to build its own evidence dict with `stdout`, `stderr`, `exit_code`, `json`. The universal CEL step wraps this as `{"output": evidence}`. Existing TOML expressions like `expr = 'output.exit_code == 0'` continue to work because `evidence["exit_code"]` maps to `output.exit_code`.

No migration needed for existing exec-handler `expr` usage.

### Decision 5: Pattern handler evidence gets `files_found` for exclude mode replacement

**Choice:** The exclude mode (`mode = "exclude_must_not_exist"`) is replaced by the pattern handler always including `files_found` (count of files matching the globs) in evidence. The TOML becomes:

```toml
[[controls."OSPS-QA-05.01".passes]]
handler = "pattern"
exclude_files = ["**/*.exe", "**/*.dll", "**/*.so"]
expr = 'output.files_found == 0'
```

The `exclude_files` field remains — it's the glob list. But `mode` is removed; the handler resolves the globs and puts the count in evidence. CEL does the pass/fail decision.

**Alternative considered:** Remove `exclude_files` entirely and use `files` + `expr`. Rejected because `exclude_files` semantically communicates "these are things we don't want to find" and the handler needs to know to glob without reading content.

## Risks / Trade-offs

**[CEL dependency becomes load-bearing for more controls]** → The CEL evaluator is already a dependency for exec passes. Making it universal means a CEL bug affects all handler types. Mitigation: CEL evaluation failures fall through to the handler's own verdict (same as current exec behavior).

**[Evidence shape becomes a contract]** → Handler evidence keys are now part of the TOML-facing API (TOML authors write `output.any_match`). Changing evidence keys becomes a breaking change. Mitigation: Document the evidence contract per handler in the spec. This is actually an improvement — currently evidence shapes are undocumented.

**[Three TOML controls need migration]** → BR-01.01 (`must_not_match → expr`), QA-05.01 and QA-05.02 (`mode → expr`). This is a small, auditable change. No user-facing TOML controls exist outside the framework yet (alpha schema).
