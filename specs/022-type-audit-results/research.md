# Phase 0 Research: Type AuditState.audit_results

**Feature**: 022-type-audit-results
**Date**: 2026-08-04

## R1: Type-checking mechanism -- `TypedDict` vs `dataclass` vs `pydantic.BaseModel`

**Decision:** `typing.TypedDict` with `typing.NotRequired` for optional keys.

**Rationale:**

- Runtime-invariant. TypedDict is a *hint* to static checkers; at runtime the values are plain `dict` objects. Every existing dict flowing through the audit pipeline (produced by `SieveResult.to_legacy_dict()` and the sparse `excluded` case at `tools/audit.py:492`) satisfies the type without conversion.
- Byte-identical serialization. No `.model_dump()`, no `dataclasses.asdict()`, no field-name mapping. JSON output, MCP responses, SARIF: unchanged.
- Zero perf cost. No object allocations, no validation calls.
- Matches the acceptance bar (SC-003: "reports the same pass/fail counts as `main`"). Both alternatives risk failing that bar by introducing implicit conversions somewhere in the code path.
- Stdlib. Python 3.11 has `typing.NotRequired`, so no version-conditional imports and no new dependencies.

**Alternatives considered:**

- `dataclass`: would force every producer and consumer to convert `dict` <-> dataclass at every boundary (audit runners, JSON serializers, MCP tool returns, `to_legacy_dict()` itself). Cascading diff far outside the target three files. Rejected.
- `pydantic.BaseModel`: same conversion cost as dataclass, plus runtime validation overhead on the hot audit path and a version-coupling risk if pydantic changes major versions again. Attractive if we needed runtime validation (we do not; the sieve orchestrator is the only producer and its shape is stable). Rejected for this feature; could be revisited later if runtime validation becomes valuable.
- Leave as `list[dict[str, Any]]` and rely on convention: the status quo. Rejected -- this is exactly the pre-Stage-1 BLOCKING item the architecture review flagged.

## R2: Where `CheckResult` lives

**Decision:** `packages/darnit/src/darnit/sieve/models.py`, alongside `SieveResult` and the other sieve dataclasses.

**Rationale:**

- The producer (`SieveResult.to_legacy_dict()`) already lives in this file. Co-locating the return type with its producer makes the type checker's inference immediate and prevents circular-import trouble.
- `agent/state.py` importing `CheckResult` from `sieve/models.py` is a framework-internal edge that already exists in spirit -- `AuditState` already consumes what the sieve produces.
- Alternative location: a new `packages/darnit/src/darnit/agent/types.py`. Would add a file for one type, and the type belongs conceptually to the sieve's output contract, not to the agent. Rejected.
- Alternative location: `packages/darnit/src/darnit/tools/audit.py`. Would add a cross-package import from `sieve/` into `tools/` for no reason. Rejected.

## R3: Handling the `pass_history` nested structure

**Decision:** Define a nested `PassHistoryEntry` TypedDict (also in `sieve/models.py`) capturing the shape emitted by `to_legacy_dict()` at lines 133-145: `phase` (str), `checks_performed`, `result` (nested dict of `outcome`, `message`, `confidence`), `duration_ms`. `CheckResult["pass_history"]` is `NotRequired[list[PassHistoryEntry]]`.

**Rationale:**

- Prevents `pass_history` from silently degrading back to `list[dict[str, Any]]`. Consumers that iterate `pass_history` get typed access all the way down.
- Zero runtime change; TypedDict-in-TypedDict is standard.

**Alternatives considered:**

- Leave `pass_history: NotRequired[list[dict[str, Any]]]`. Simpler, but leaves a hole for the same class of typo bug we are trying to eliminate. Rejected.

## R4: `status` field -- `Literal[...]` vs `str`

**Decision:** `status: Literal["PASS", "FAIL", "WARN", "N/A", "ERROR", "PENDING_LLM"]`.

**Rationale:**

- The set of statuses is closed and documented in `SieveResult.status` (`sieve/models.py:95`: "PASS, FAIL, WARN, NA, ERROR, PENDING_LLM"). `"N/A"` is the wire format used in `tools/audit.py:495`.
- Codifying it as a `Literal` catches typo bugs like `r["status"] == "PSS"` at type-check time, matching the spirit of SC-002.

**Caveat:** the exact set of literal values must match what the codebase actually emits. Reconciled by grepping the codebase before coding: the six above are the only status strings produced by the sieve or by the excluded-control path. If any producer later invents a new status, the checker will flag it (which is the desired behavior).

**Alternatives considered:**

- `str` -- weaker; misses status-value typos. Rejected.
- Reuse `PassOutcome` enum from `sieve/models.py` -- close but not exact: `PassOutcome` covers `PASS/FAIL/INCONCLUSIVE/ERROR` (four outcomes), while `SieveResult.status` and downstream consumers use six string labels including `WARN`, `N/A`, `PENDING_LLM`. These are different sets. Rejected.

## R5: Type checker

**Decision:** `mypy` (already configured in the project).

**Rationale:**

- `pyproject.toml:111-126` already has `[tool.mypy]` with `packages = ["darnit", "darnit_baseline"]` and strict-ish flags. No new tool to install or configure.
- Documented baseline (measured 2026-08-04 against `main` after feature 021): 19 preexisting mypy errors total across the five in-scope files -- 1 in `sieve/models.py` (missing return annotation at line 171); 10 in `tools/audit.py` (missing return annotation at 28; 2x `no-any-return` at 181/199; 1x `no-untyped-call` at 350; 6x `dict-item` at 1124-1141); 4 in `cli.py` (3x `var-annotated` at 83/297/376; 1x `no-any-return` at 1088); 4 in `agent/graph.py` (2x `arg-type` on `str | None` at 74/75; missing return annotation at 318; `attr-defined` for `load_framework_config` at 321). None relate to `audit_results`. SC-001 acceptance: after this feature, the same-or-fewer count, and no new `audit_results`-related errors.

**Alternatives considered:**

- `pyright` / `ty`: not configured; would add a tool and diverge from the project's baseline. Rejected for scope.
- Neither / manual review only: would not satisfy SC-002 (the negative-verification step depends on an automated checker). Rejected.

## R6: Handling the ad-hoc `when` key attached at `tools/audit.py:530`

**Decision:** Include `when: NotRequired[str]` in `CheckResult` (list it as an optional key) and leave the code that attaches it unchanged.

**Rationale:**

- The attach site is small, well-scoped, and mutating the dict after `to_legacy_dict()` returns is the pragmatic pattern the codebase already uses.
- Refactoring `SieveResult` to carry `when` and emit it from `to_legacy_dict()` would be a nicer design but expands scope. That refactor is called out as a smell in the spec (Assumptions section) but explicitly deferred.

**Alternatives considered:**

- Move `when` into `SieveResult` and emit it from `to_legacy_dict()`. Better long-term; out of scope for feature 022. Would appear as a follow-up if the wart bothers us.

## R7: Test coverage

**Decision:** No new pytest tests for feature 022. The acceptance is a static check.

**Rationale:**

- The change is runtime-invariant (SC-003). Adding a runtime test that asserts "the annotation is a TypedDict" is testing the language, not the code.
- The negative-verification step (SC-002: introduce a typo, watch mypy flag it, revert) belongs in `quickstart.md` as a manual acceptance step, not as an automated test that ships. Automating it would require running mypy programmatically inside pytest, which is more machinery than the acceptance bar warrants.

**Alternatives considered:**

- Add a `test_check_result_schema.py` that constructs a `CheckResult` with all required keys and asserts `isinstance(..., dict)`. Trivially passes; provides no ongoing signal. Rejected.
- Wire mypy into CI as part of this feature. Attractive but out of scope; feature 022 sets up the annotation, and CI wiring is a natural follow-up if the project decides to gate PRs on mypy.
