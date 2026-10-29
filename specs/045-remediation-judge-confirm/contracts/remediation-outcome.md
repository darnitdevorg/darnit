# Contract: remediation outcome and run (framework-design 15.4, 15.5)

## RemediationOutcome.pending_kind

| `kind` | re-check status | `pending_kind` |
|---|---|---|
| `fixed` | PASS | absent |
| `changed_not_passing` | FAIL, WARN | absent |
| `changed_not_passing` | PENDING, `pending.kind = llm_judgment` | `"llm_judgment"` |
| `changed_not_passing` | PENDING, `pending.kind = confirmation` | `"confirmation"` |
| `changed_not_verified` | ERROR, or no re-check | absent |
| every other kind | none | absent |

Serialized in the fenced JSON block of `remediate_audit_findings` when present. The Markdown outcome adds one line for it: `- **Awaiting:** a model judgment` or `- **Awaiting:** the operator's confirmation of a PASS candidate`.

## RemediationRun.awaiting

```json
"awaiting": {"llm_judgment": ["OSPS-DO-03.01", "OSPS-GV-01.01"], "confirmation": []}
```

Derived from `outcomes`; keys with no ids are omitted; `{}` when nothing awaits. The Markdown report adds, after the outcomes, a "Next steps" section from `remediation_next_steps(...)` (contracts/procedures.md) naming those ids and the tools to call.

## Unchanged

- `OUTCOME_KINDS`, `summary` (counts per kind), the commit and pull request gates (a `changed_not_passing` outcome with `pending_kind` changed files and counts as changed), compliance calculation, attestations.
- `fixed` only from a re-check PASS.
