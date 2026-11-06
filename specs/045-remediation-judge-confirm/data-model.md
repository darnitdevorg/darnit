# Data Model: Judge and Confirm After Remediation

## RemediationOutcome (changed)

`packages/darnit/src/darnit/remediation/plan.py`

| Field | Type | Change |
|---|---|---|
| `pending_kind` | `"llm_judgment" \| "confirmation" \| None` | New. What a PENDING re-check awaits. |

Validation (added to `_kind_matches_evidence`):

- `pending_kind` is not None if and only if `kind == "changed_not_passing"` and `recheck.status == "PENDING"`.
- When set, it equals `recheck["pending"]["kind"]`. A PENDING re-check without a `pending.kind` in `{llm_judgment, confirmation}` is invalid (the sieve always sets one, framework-design 3.0, 5.4).
- `kind` values, `OUTCOME_KINDS`, and `summarize` are unchanged.

## RemediationRun (changed)

| Field | Type | Change |
|---|---|---|
| `awaiting` | `dict[str, list[str]]` | New, derived from `outcomes`: `{"llm_judgment": [...], "confirmation": [...]}`, control ids sorted, keys present only when non-empty. Like `summary`, a supplied value must equal the derived one. A preview has none. |

## PassCandidateEntry (new, response shape only)

One entry of `get_pass_candidates` (contracts/get-pass-candidates.md). Built from the audit result (status `PENDING`, `pending.kind = "confirmation"`), the stored candidate (`StoredCandidate.candidate`), the control's TOML metadata, and optionally the run manifest.

| Field | Source |
|---|---|
| `control_id` | audit result |
| `title`, `description` | control metadata (TOML) |
| `files` | judged file paths (`judged_content` keys) |
| `reasoning`, `cited_evidence`, `model`, `model_version`, `source` | stored candidate |
| `evidence_digest` | stored candidate |
| `remediation` | only with `run_id` and a judged file in that run's manifest: `{run_id, path, written: true, edited_after_write: bool}` |

Not stored. Never contains a candidate for a digest other than the current evidence.

## Recorded judgment and confirmation (new, test-only)

In `scripts/comply_replay.toml` (#666), beside the recorded answers. Read only by `scripts/comply_replay.py`.

```toml
[judgments."OSPS-GV-03.01"]
verdict = "pass"            # or "fail"
reasoning = "..."
cited_evidence = ["...verbatim passage..."]

[confirmations]
controls = ["OSPS-GV-03.01"]
```

- Submitted as `model = "recorded"`, `model_version = "comply_replay.toml"`.
- A control in `confirmations.controls` with no `pass` judgment is a fixture error.

## State transitions (unchanged, now reachable in comply)

```text
remediation writes doc -> re-check PENDING(llm_judgment)   outcome changed_not_passing, pending_kind=llm_judgment
agent improves doc     -> (digest changes; still llm_judgment)
judge (pass, cited)    -> PENDING(confirmation)            PASS candidate stored
judge (fail)           -> PENDING(llm_judgment)            suggestive finding, nothing stored
person confirms        -> PASS (asserted, confirmation)    operator-side, this machine
doc edited later       -> PENDING(llm_judgment)            confirmation no longer matches the digest
```
