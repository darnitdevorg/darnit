# Contract: Conclusive WARN Handler Outcome

**Feature**: 037 (FR-016, FR-017) | **Package**: `darnit` core | **Status**: proposed

This is a framework contract. It governs every sieve handler, not just the one that motivated it. Per Development Workflow item 3, the normative version of this contract must land in `docs/architecture/framework-design.md` before the code.

## Problem

A handler can report PASS, FAIL, INCONCLUSIVE, or ERROR. There is no way to report "I read the evidence, I understood it, and it is insufficient." Handlers in that position must return INCONCLUSIVE, which sends the pipeline to the next pass and, once passes are exhausted, produces a WARN whose message is the fixed string `"Could not automatically verify - manual verification required"` (`orchestrator.py:585`).

The operator then reads, about a file the tool successfully parsed, that the tool could not verify it. That is the same confusion issue #427 was about, arriving by a different route.

## Contract

### C-1: Vocabulary

`HandlerResultStatus` includes `WARN`. Its meaning is: *the handler reached a conclusion, and the conclusion is that the evidence is insufficient to pass.*

WARN is distinct from INCONCLUSIVE in kind, not in degree:

- INCONCLUSIVE -- the handler determined nothing. Another pass may still determine something.
- WARN -- the handler determined something, and what it determined is not a pass.

A handler MUST NOT return WARN to mean "I am unsure." That is INCONCLUSIVE.

### C-2: Authority gating

A WARN concludes the control only when the effective authority is terminal (`dispositive` or `asserted`), resolved by the existing precedence: TOML step override, then `HandlerResult.authority`, then the handler's registered `default_authority`.

A WARN from a non-terminal authority attaches evidence and continues, exactly as a non-terminal PASS or FAIL does, and terminates INCONCLUSIVE if it was the last step.

This is not an optional safety nicety. Without it, a suggestive LLM step could halt verification before a dispositive step ran. The feature 025 invariant is that only dispositive and asserted results conclude; WARN is a result, so the invariant covers it.

### C-3: Compliance semantics

A WARN control counts as FAIL for compliance calculations (Constitution Principle II). This contract adds no exception. A control concluding WARN is not compliant.

### C-4: Pipeline semantics

A conclusive WARN stops the pass chain, consistent with Principle V's "the orchestrator stops at the first conclusive result." It never short-circuits to PASS. It does not change the behavior of INCONCLUSIVE, which continues to the next phase as before.

### C-5: Result construction

A `CONCLUDE_WARN` disposition produces a `SieveResult` with `status="WARN"` carrying, from the resolving pass: `message`, `confidence`, `evidence`, `resolving_pass_index`, `resolving_pass_handler`, `authority`, and `error_class`.

The handler's own message reaches the operator. That is the entire purpose of this contract; a WARN that substitutes a generic string satisfies nothing here.

### C-6: CEL post-step

`_apply_cel_expr` does not modify a WARN result. The CEL transition table is defined for PASS and FAIL only; there is no "CEL disagrees with WARN" cell, because WARN already asserts that the evidence is incomplete.

### C-7: Backward compatibility

No existing handler returns WARN. Therefore:

- No existing control's status changes (FR-017, SC-008).
- The all-inconclusive fallthrough at `orchestrator.py:585` is unchanged and continues to produce its WARN for controls that exhaust their passes.
- `SieveResult.status` gains no new value: `CheckStatus` already includes `"WARN"`, and formatters, compliance arithmetic, and harness exit codes already handle it.

A consumer that switches exhaustively on `HandlerResultStatus` and does not handle `WARN` is a defect introduced by this change and must be found and fixed, not defaulted. `_handler_status_to_outcome` is the one such site in core and gains an explicit mapping.

## Test obligations

| ID | Assertion |
|---|---|
| T-1 | A dispositive handler returning WARN yields `SieveResult.status == "WARN"` with the handler's own message. |
| T-2 | A suggestive handler returning WARN does not conclude; the pipeline continues to the next pass. |
| T-3 | A suggestive WARN on the last step terminates INCONCLUSIVE, not WARN. |
| T-4 | A WARN carries `confidence`, `evidence`, `resolving_pass_handler`, and `authority` from the resolving pass. |
| T-5 | A WARN carrying an `error_class` preserves it on the `SieveResult`. |
| T-6 | `_apply_cel_expr` returns a WARN result unchanged, with and without an `expr` configured. |
| T-7 | `pass_history` records the pass outcome as WARN, not INCONCLUSIVE. |
| T-8 | Every existing control fixture produces an unchanged status (SC-008). |
