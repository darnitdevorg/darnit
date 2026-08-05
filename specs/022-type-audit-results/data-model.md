# Phase 1 Data Model: Type AuditState.audit_results

**Feature**: 022-type-audit-results
**Date**: 2026-08-04

## `CheckResult` (NEW)

The typed schema for one entry in `AuditState.audit_results`. Introduced in `packages/darnit/src/darnit/sieve/models.py`.

```python
from typing import Any, Literal, NotRequired, TypedDict


CheckStatus = Literal["PASS", "FAIL", "WARN", "N/A", "ERROR", "PENDING_LLM"]


class PassHistoryEntry(TypedDict):
    """One phase attempt inside a CheckResult's pass_history.

    Emitted by SieveResult.to_legacy_dict() at models.py:132-145.
    """
    phase: str
    checks_performed: int
    result: PassHistoryResult
    duration_ms: float


class PassHistoryResult(TypedDict):
    """The nested `result` field inside a PassHistoryEntry."""
    outcome: str
    message: str
    confidence: float | None


class CheckResult(TypedDict):
    """The wire shape of one entry in AuditState.audit_results.

    Produced by SieveResult.to_legacy_dict() for the normal audit path and by
    the excluded-control path in tools/audit.py:492. The `when` key is
    attached ad-hoc after to_legacy_dict() returns (tools/audit.py:530).
    """
    # Required (present in every producer path)
    id: str
    status: CheckStatus
    details: str
    level: int

    # Optional (present when the corresponding SieveResult field was set)
    sieve_phase: NotRequired[str]
    confidence: NotRequired[float]
    verification_steps: NotRequired[list[str]]
    evidence: NotRequired[dict[str, Any]]
    resolving_pass_index: NotRequired[int]
    resolving_pass_handler: NotRequired[str]
    pass_history: NotRequired[list[PassHistoryEntry]]

    # Attached post-hoc at tools/audit.py:530
    when: NotRequired[str]
```

## Field derivation and invariants

| Key | Source | Required? | Notes |
|-----|--------|-----------|-------|
| `id` | `SieveResult.control_id` / literal `control_id` at `audit.py:494` | required | Control identifier, e.g. `"OSPS-AC-01.01"`. |
| `status` | `SieveResult.status` / literal `"N/A"` at `audit.py:495` | required | One of six literals; see `CheckStatus`. |
| `details` | `SieveResult.message` / literal explanation at `audit.py:496` | required | Human-readable summary. |
| `level` | `SieveResult.level` / `spec.level or 1` at `audit.py:497` | required | Maturity level (1, 2, 3). |
| `sieve_phase` | `SieveResult.conclusive_phase.value` when present | optional | e.g. `"deterministic"`, `"pattern"`, `"llm"`, `"manual"`. |
| `confidence` | `SieveResult.confidence` when present | optional | Float 0.0-1.0. |
| `verification_steps` | `SieveResult.verification_steps` when present | optional | Manual-phase instructions. |
| `evidence` | `SieveResult.evidence` when present | optional | Arbitrary handler-specific evidence dict. |
| `resolving_pass_index` | `SieveResult.resolving_pass_index` when present | optional | Which pass in the control's pass list produced the verdict. |
| `resolving_pass_handler` | `SieveResult.resolving_pass_handler` when present | optional | Handler name that produced the verdict. |
| `pass_history` | serialized `SieveResult.pass_history` list | optional | Trace of every phase attempt; each entry typed by `PassHistoryEntry`. |
| `when` | `spec.metadata.get("when")` at `audit.py:530` | optional | The control's `[[controls.X.when]]` clause; attached post-hoc. |

## Consumers whose typing improves

| Consumer | Location | What changes |
|---|---|---|
| `AuditState.audit_results` | `agent/state.py:61` | Annotation: `list[dict[str, Any]]` -> `list[CheckResult]`. No runtime change. |
| `AuditState.failing_control_ids()` | `agent/state.py:84` | `r["id"]` and `r.get("status")` become typed lookups. Return type unchanged. |
| `AuditState.warn_control_ids()` | `agent/state.py:88` | Same as above. |
| `SieveResult.to_legacy_dict()` | `sieve/models.py:111` | Return annotation: `dict[str, Any]` -> `CheckResult`. |
| `run_sieve_audit()` | `tools/audit.py:319` | Return type widens from `tuple[list[dict[str, Any]], dict[str, int]]` to `tuple[list[CheckResult], dict[str, int]]`. |
| `run_checks()` | `tools/audit.py:269` | Same widening as `run_sieve_audit()`. |

## No new entities beyond `CheckResult`, `PassHistoryEntry`, `PassHistoryResult`

The `AuditState`, `FeedbackQuestion`, `SieveResult`, and `PassAttempt` dataclasses are unchanged. `AuditState.remediation_results: list[dict[str, Any]]` is deliberately unchanged (out of scope; noted as a follow-up in `spec.md` Assumptions).

## Non-goals

- Do NOT change any dict keys, dict values, or serialization formats.
- Do NOT touch `remediation_results` typing.
- Do NOT refactor the `when` post-hoc attach at `tools/audit.py:530` into `SieveResult` proper. That is a separate cleanup called out in the spec as a smell.
