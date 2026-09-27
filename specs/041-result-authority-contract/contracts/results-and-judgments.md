# Contract: Results and Judgments

## Per-control result (all drivers, JSON)

```json
{
  "id": "OSPS-DO-01.01",
  "status": "PENDING",
  "authority": "suggestive",
  "concluded_by": "none",
  "pending": {"kind": "confirmation"},
  "candidate": {
    "verdict": "pass",
    "reasoning": "...",
    "cited_evidence": ["## Installation\n..."],
    "model": "claude-sonnet-5",
    "model_version": "2026-08-01",
    "evidence_digest": "sha256:...",
    "source": "harness"
  },
  "error": null,
  "confirmation": null,
  "evidence": []
}
```

- `status` is one of PASS, FAIL, WARN, N/A, ERROR, PENDING. `PENDING_LLM` is removed; `PENDING` with `pending.kind = "llm_judgment"` replaces it.
- `ERROR` always carries `error: {class, cause}`; classes include `auth`, `rate_limit`, `unavailable`, `missing_tool`, `evaluation`.
- A confirmed candidate appears as `status: PASS`, `authority: asserted`, `concluded_by: confirmation`, with `confirmation: {confirmed_by, confirmed_at, expires_at}`.
- A negative judgment appears as `status: FAIL`, `authority: suggestive`, `concluded_by: llm_judgment`.

## Compliance

One function computes level compliance for every driver, report format, and attestation: compliant only if every applicable control is PASS or N/A. Deterministic-only test runs (issue #505) leave judgment-requiring controls PENDING and therefore never report a level compliant.

## MCP: submit_judgment

```
submit_judgment(
  control_id: str, verdict: "pass" | "fail", reasoning: str,
  cited_evidence: list[str], model: str, model_version: str,
  owner: str, repo: str, host: str = "github.com", local_path: str = "."
) -> {status, candidate | finding | rejection}
```

- Re-gathers the control's evidence for `local_path`, verifies each `cited_evidence` excerpt appears verbatim (whitespace-normalized) in it, and computes the evidence digest.
- `verdict = "pass"` with verified citations: records a PASS candidate operator-side (feature 040 store, claim `pass_candidate`) and returns it. The control reports PENDING (confirmation) on the next audit.
- `verdict = "fail"`: returns a suggestive FAIL finding; nothing is stored.
- Unverifiable citations: returns a rejection naming the excerpts not found; nothing is stored.
- The existing confirmation tool confirms a candidate (by `control_id`, repository, and current digest); confirmation is only on the operator's explicit instruction.

## ActionPlan

`submit_action_result` for the audit step no longer accepts client-supplied per-control statuses; the engine records only results it produced. Judgments go through `submit_judgment`.

## Skills

Audit and comply skills: call `submit_judgment` for PENDING (llm_judgment) controls with verbatim excerpts; never state a verdict as the audit result; never confirm a candidate without the operator's explicit instruction.
