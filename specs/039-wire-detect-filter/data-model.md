# Phase 1 Data Model: Wire detect_filter Into Context Detection

**Feature**: 039 | **Date**: 2026-09-23

No persisted state changes. One schema field, one decision type, one evaluation contract.

---

## Schema: `ContextDefinitionConfig` gains `detect_filter`

| Field | Type | Default | Meaning |
|---|---|---|---|
| `detect_filter` | `str \| None` | `None` | CEL expression over a single candidate, bound as `value`. True keeps, false discards. |

Declared rather than left to `extra="allow"`, so the field is visible in the model and the FR-010 check has something to validate against.

The model keeps `extra="allow"`. Undeclared keys continue to load (spec FR-010); only shipped TOMLs are checked in CI.

---

## `FilterDecision`

The result of evaluating one candidate.

| Value | Meaning | Effect |
|---|---|---|
| `KEEP` | expression returned true | candidate survives |
| `REJECT` | expression returned false | candidate discarded, reported |
| `UNEVALUABLE` | expression could not compile, or errored against this value | candidate discarded, reported (FR-006) |

`REJECT` and `UNEVALUABLE` have the same effect on the value and different meanings in the report: one says "the filter judged this and said no", the other says "the filter could not judge this". Collapsing them would reproduce the defect being fixed, where a guard that did not run looked like a guard that passed.

---

## Evaluation rules

### Scalars

Bind the candidate as `value`, evaluate, map to `FilterDecision`.

### Lists (FR-012)

Evaluate once per element. Keep passing elements, discard the rest.

| Situation | Result |
|---|---|
| some elements pass | key keeps the passing elements; discarded count reported (FR-013) |
| no elements pass | key is left unset |
| list is empty | treated as no value |

A list is never bound whole. Research R2: CEL `contains` on a list is membership, so a whole-list binding returns true and keeps a list containing the rejected value -- the filter fails open.

### Error handling (FR-006, R3)

Two distinct failure paths, both ending in `UNEVALUABLE`:

| Path | Raised or returned |
|---|---|
| expression does not compile | `CELCompilationError` raised from `evaluate_cel` |
| expression errors on this value (wrong type, missing binding) | `CELResult(success=False, error=...)` |

Compile once per key, before evaluating any element, so a malformed expression is reported once naming the key rather than once per element.

---

## Where the decision is applied

### At detection (FR-004, FR-005)

`context_storage.py:547-557`. Both routes converge on `current_value` before the threshold check:

```text
detect pipeline  ---\
                     >--- current_value --- [FILTER] --- auto-accept threshold --- store
sieve fallback   ---/
```

One choke point covers both routes and lands before the threshold, which is what FR-005 requires: filtering after the threshold would still have written the rejected value.

### At read (FR-014, FR-015)

`get_context_value` re-evaluates the stored value against its key's filter. A failing value is reported and treated as unset for control verification, compliance calculation and remediation input.

**Nothing is written.** `.project/` is a file people edit, and a stored value may carry a human confirmation.

---

## What does not change

- Keys declaring no `detect_filter`: no evaluation, no behaviour change (FR-009, SC-007).
- The auto-accept mechanism and threshold.
- Which keys carry `auto_detect = true`.
- `CELContext` and the control sieve.
