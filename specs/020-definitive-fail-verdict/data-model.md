# Data Model: preserve handler-conclusive FAIL through the CEL post-step

No new entities. Same underlying framework types as feature 019 US2. This document exists to satisfy the plan artifact list and to record which existing types are touched.

## Existing framework types used

### `PassOutcome` (framework, `packages/darnit/src/darnit/sieve/models.py`)

Four-valued enum: `PASS` / `FAIL` / `INCONCLUSIVE` / `ERROR`. Unchanged schema. This spec changes only the *transitions* the CEL post-step performs between these values. Transition table lives in `contracts/cel-post-step.md`.

### `HandlerResult` (framework, `packages/darnit/src/darnit/sieve/models.py`)

Handler return value carrying `status: PassOutcome`, `message: str`, `confidence: float`, and `evidence: dict[str, Any]`. `evidence` is the input to CEL evaluation. Unchanged schema.

For exec handlers with `output_format = "json"`, the evidence shape is:

```python
evidence = {
    "stdout": str,
    "stderr": str,
    "exit_code": int,
    "json": dict | list,   # parsed body, absent if JSON decode fails
}
```

For the 404 "Branch not protected" case specifically:

```python
evidence = {
    "stdout": '{"message": "Branch not protected", "documentation_url": "...", "status": "404"}',
    "stderr": "",  # or a gh warning
    "exit_code": 1,
    "json": {"message": "Branch not protected", "documentation_url": "...", "status": "404"},
}
```

### `_apply_cel_expr` (framework, `packages/darnit/src/darnit/sieve/orchestrator.py:60-75`)

The transformation this spec modifies. Signature unchanged; internal logic is the sole change. New behavior documented in `contracts/cel-post-step.md`.

## Relationships (unchanged)

```
exec handler (proc.returncode) -> HandlerResult{status: PASS|FAIL|INCONCLUSIVE, evidence: {...}}
        |
        v (only if handler status is PASS or FAIL)
CEL post-step evaluates pass_config["expr"] against evidence
        |
        v
Final HandlerResult -> orchestrator picks next pass or stops at conclusive verdict
```

## State transitions

The only behavioral change. See `contracts/cel-post-step.md` for the before/after transition tables.

## No storage, no schema, no migrations

Pure in-memory transformation change. Nothing persisted; nothing to migrate.
