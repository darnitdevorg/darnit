# Contract: sieve orchestrator CEL post-step

**Scope:** internal framework contract between `packages/darnit/src/darnit/sieve/orchestrator.py` and its callers (the sieve orchestrator itself). Not a public API. Not a plugin protocol.

**Function:** `_apply_cel_expr(handler_config, handler_result) -> HandlerResult`.

## Current behavior (before this spec)

Given a handler that returned PASS or FAIL (INCONCLUSIVE / ERROR are passed through unchanged) and a pass config carrying a CEL `expr`:

| Handler status | CEL result | Post-step status |
|----------------|------------|------------------|
| PASS           | true       | PASS             |
| PASS           | false      | INCONCLUSIVE     |
| FAIL           | true       | **PASS**         |
| FAIL           | false      | **INCONCLUSIVE** |

The last two rows are the root cause of issue #343: a handler-conclusive FAIL is being overridden by the CEL post-step in both directions.

## New behavior (after this spec)

| Handler status | CEL result | Post-step status |
|----------------|------------|------------------|
| PASS           | true       | PASS             |
| PASS           | false      | INCONCLUSIVE     |
| FAIL           | true       | INCONCLUSIVE     |
| FAIL           | false      | **FAIL**         |

Interpretation:

- Both entities (handler and CEL) agreeing on PASS -> conclusive PASS.
- Both entities agreeing on FAIL -> conclusive FAIL.
- Handler and CEL disagreeing (PASS+false or FAIL+true) -> INCONCLUSIVE, pipeline continues.

Rationale: the two disagreement rows are ambiguous — one signal says compliant, the other says not — and INCONCLUSIVE correctly defers to the next pass. The two agreement rows are conclusive and preserve the handler's original conclusion; the CEL post-step confirms rather than contradicts.

## Invariants preserved

- ERROR and INCONCLUSIVE from the handler are passed through unchanged (no CEL evaluation attempted). Unchanged from today.
- When `expr` is absent from the pass config, the handler's original result is returned unchanged. Unchanged from today.
- When CEL evaluation raises or returns an error (not a boolean), the handler's original result is returned unchanged. Unchanged from today.
- Confidence, message, and evidence handling remain the same: the returned `HandlerResult` may synthesize a new message ("CEL expression passed", "CEL expression evaluated to false") but must include the original evidence.

## Test coverage required

The unit test suite must exercise all eight cells of the transition table (four rows above, times "expr present" and "expr absent" -> but the "absent" case is trivially handled and can be covered once). At minimum:

1. Handler PASS + CEL true + expr -> PASS
2. Handler PASS + CEL false + expr -> INCONCLUSIVE
3. Handler FAIL + CEL true + expr -> INCONCLUSIVE (new)
4. Handler FAIL + CEL false + expr -> FAIL (new; this is issue #343)
5. Handler INCONCLUSIVE + any CEL + expr -> INCONCLUSIVE (pass-through)
6. Handler ERROR + any CEL + expr -> ERROR (pass-through)
7. Any handler status + no expr -> unchanged
8. Any handler status + CEL evaluation error -> unchanged

Tests live at `tests/darnit/sieve/test_orchestrator_cel.py`.

## Downstream effect on TOML controls

Twelve controls in `packages/darnit-baseline/openssf-baseline.toml` combine `fail_exit_codes` + `expr` in the same pass (audit in `research.md` R5). All twelve get the new semantics automatically; no TOML change is required for the branch-protection fix beyond the LE-01.01 level tag.

An integration test at `tests/darnit_baseline/controls/test_branch_protection.py` should exercise at least one of the four named branch-protection controls (`OSPS-AC-03.01`, `OSPS-AC-03.02`, `OSPS-QA-03.01`, `OSPS-QA-07.01`) end-to-end with a stubbed `gh api` command that returns the exact "Branch not protected" 404 response documented in `research.md` R3.
