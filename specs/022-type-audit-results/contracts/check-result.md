# Contract: CheckResult (sieve orchestrator -> agent state)

**Feature**: 022-type-audit-results
**Status**: Enforced statically (mypy TypedDict); runtime-invariant.

This contract governs the shape of one entry in `AuditState.audit_results`. It is emitted by the sieve orchestrator via `SieveResult.to_legacy_dict()` (plus one sparse variant for excluded controls) and consumed by every downstream node in the current agent graph and every future RFC-0001 Stage 1 harness step.

## Producer obligations

Every producer of a `CheckResult` MUST:

1. **Emit the four required keys** with the specified types:
   - `id: str` -- control identifier.
   - `status: Literal["PASS", "FAIL", "WARN", "N/A", "ERROR", "PENDING_LLM"]` -- one of the six string labels; no new values without updating `CheckStatus`.
   - `details: str` -- human-readable summary.
   - `level: int` -- maturity level (1, 2, or 3).
2. **Populate optional keys only when the corresponding data exists.** If a producer does not have a value for `confidence`, `evidence`, `pass_history`, etc., it MUST omit the key entirely rather than emit `None`. (`NotRequired` semantics do not include `None`.)
3. **Not invent new keys.** New optional keys require a `CheckResult` schema update in `packages/darnit/src/darnit/sieve/models.py` in the same PR. Untyped keys defeat the purpose of this contract.

Today's producer sites (post-feature-022) are:

- `SieveResult.to_legacy_dict()` at `packages/darnit/src/darnit/sieve/models.py:111` -- primary producer.
- The excluded-control path at `packages/darnit/src/darnit/tools/audit.py:492` -- sparse producer (only the four required keys).
- The post-hoc `when` attach at `packages/darnit/src/darnit/tools/audit.py:530` -- an out-of-band mutation; permitted because `when` is listed as an optional key on `CheckResult`. Producers SHOULD prefer emitting the key inline; this one is grandfathered.

## Consumer obligations

Every consumer of a `CheckResult` MUST:

1. **Access keys via the typed shape.** Consumers reading `r["id"]`, `r["status"]`, etc. get static verification that the key exists and has the expected type. Consumers reading `r["idd"]` MUST fail type-check.
2. **Guard access to optional keys.** `r.get("confidence")` returns `float | None`; consumers wanting to use it must check for `None` (or use `if "confidence" in r`).
3. **Not mutate the shape.** Consumers do not add keys to a `CheckResult` they receive; that role is reserved for producers. (The one exception is the pre-existing `when` attach in `tools/audit.py`, kept in place for feature 022 and flagged as a follow-up cleanup.)

Today's consumer sites are:

- `AuditState.failing_control_ids()` and `AuditState.warn_control_ids()` in `packages/darnit/src/darnit/agent/state.py:84-90`.
- The CLI's `cmd_run` in `packages/darnit/src/darnit/cli.py:700` (assigns `final_state.audit_results` to `check_results` and passes to the remediation orchestrator).
- The remediation orchestrator and any MCP tool that returns audit results in its response.
- Future RFC-0001 Stage 1 harness steps that pass `HarnessState.check_results: list[CheckResult]` between driver stages.

## Runtime invariants

- `CheckResult` is a `TypedDict`. At runtime it IS a plain `dict[str, Any]`; there is no wrapper class, no `__init_subclass__`, no validation.
- JSON serialization of a `CheckResult` produces the same bytes as JSON serialization of the same dict pre-feature-022.
- Consumers written pre-feature-022 (e.g., third-party MCP clients parsing the response) do not need to change.

## Static enforcement

- `mypy` treats `CheckResult` as a strict structural type. `packages/darnit/src/darnit/agent/state.py`, `packages/darnit/src/darnit/agent/graph.py`, and `packages/darnit/src/darnit/cli.py` must produce zero NEW `audit_results`-related mypy errors after this feature lands (baseline: 15 preexisting errors in `sieve/models.py` + `tools/audit.py` + `cli.py`, 4 in `agent/graph.py`; none related to `audit_results`).

- The negative-verification step (introducing a typo, watching mypy flag it) is documented in `quickstart.md` and is the acceptance criterion for "the annotation is actually being enforced" (SC-002).

## Applies to

- The current agent graph (`audit`, `collect_context`, `remediate` nodes).
- The CLI's `cmd_run` pipeline (`packages/darnit/src/darnit/cli.py:630-727`).
- The upcoming RFC-0001 Stage 1 harness driver (`HarnessState` consumers).
- Any future framework code that receives or emits an audit result dict.

## Non-goals

- Runtime validation of `CheckResult` shapes. TypedDict is a static hint only; if a producer emits a malformed dict, the checker will catch it, but no runtime guardrail is added.
- Coverage of `remediation_results` (deliberately out of scope; a parallel `RemediationResult` TypedDict is a natural follow-up but is not required by this contract).
- Wiring mypy into CI as a gating check. This contract enables the check but does not mandate CI enforcement in this feature.
