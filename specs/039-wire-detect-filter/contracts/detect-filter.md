# Contract: detect_filter Evaluation

**Feature**: 039 (#165, #150) | **Package**: `darnit` core | **Status**: proposed

## Problem

`detect_filter` is declared on a context key and evaluated nowhere. It is retained in `model_extra` because `ContextDefinitionConfig` sets `extra="allow"`, so nothing errors and nothing runs. The one shipped filter exists to keep `security@example.com` out of `security_contact`, which feeds three OSPS-VM controls and can be auto-accepted without a prompt at confidence 0.8.

## Contract

### C-1: Binding

The candidate is bound as `value`. No other binding is provided. Filters cannot inspect confidence, detection method or repository state; a filter is a statement about a value.

### C-2: Decision

True keeps the candidate. False discards it. Anything else -- compile failure, runtime error, missing binding -- discards it and is reported as unevaluable.

A candidate is never kept because the filter could not judge it.

### C-3: Lists are filtered element-wise

For a list-valued candidate, evaluate once per element and keep the passing elements. A list is never bound whole: CEL's `contains` is membership on a list, so a whole-list binding returns true and keeps a list containing the rejected value.

### C-4: Both detection routes

A candidate produced by the TOML `detect` pipeline and a candidate produced by the sieve fallback are both filtered. Coverage of one route only is a guard with a hole in the path that produced the original report.

### C-5: Ordering

Filtering happens before the auto-accept confidence threshold is consulted. After it, a rejected candidate is already written.

### C-6: Stored values

A value read from stored context is re-evaluated against its key's filter. A failing value is treated as unset and reported. Stored context is never modified -- it may carry a human confirmation the framework is not entitled to revoke silently.

### C-7: Reporting

Rejections and unevaluable filters are reported at a level visible in default output, naming the key. A discarded value is distinguishable from "detection found nothing", and a rejected element count is reported alongside surviving elements.

A guard that silently does not run is the defect being fixed; a guard that silently rejects is the same defect wearing different clothes.

### C-8: No filter, no change

A key declaring no `detect_filter` is evaluated not at all and behaves exactly as before.

## Test obligations

| ID | Assertion |
|---|---|
| DF-1 | `security@example.com` against the shipped expression yields REJECT. |
| DF-2 | A real address yields KEEP. |
| DF-3 | A list keeps passing elements and drops failing ones; the discarded count is reported. |
| DF-4 | A list containing a rejected element is not kept whole -- pins the R2 failure-open mode. |
| DF-5 | A malformed expression yields UNEVALUABLE, is reported naming the key, and does not propagate out of context collection. |
| DF-6 | A wrong-typed value yields UNEVALUABLE and is reported. |
| DF-7 | A rejected candidate from the `detect` pipeline is not stored and not auto-accepted, at any confidence including 1.0. |
| DF-8 | A rejected candidate from the sieve fallback is likewise not stored. |
| DF-9 | A stored value that now fails its filter reads as unset, and `.project/` is byte-identical afterwards. |
| DF-10 | A key with no filter produces byte-identical stored context before and after this change. |
| DF-11 | Validation fails on a `[context.*]` block containing an undeclared key, naming key and file; passes on the current shipped TOMLs. |
