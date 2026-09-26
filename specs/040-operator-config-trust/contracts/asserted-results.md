# Contract: Asserted Not-Applicable Results

## Sources of assertions

1. `.project/darnit.yaml`:

```yaml
controls:
  OSPS-BR-02.01:
    status: n/a
    reason: "Pre-1.0 project with no releases yet; tracked in #123"
    asserted_by: "@maintainer"      # optional
```

2. Applicability-changing context values in `.project/` (for example a value that a control's applicability condition reads), treated as an assertion for each control they would make not applicable.
3. During the deprecation release only: per-control `status`/`reason` in `.baseline.toml`.

## Per-control result fields

| Field | Values |
|---|---|
| `status` | `N/A` only when the assertion outcome is `honored`; otherwise the control's normally evaluated status, with pending claims counted as non-compliant. |
| `assertion.outcome` | `honored`, `pending`, `contradicted` |
| `assertion.origin` | `explicit_claim` or `context_value:<key>` |
| `assertion.reason` | string or null |
| `assertion.asserted_by` | string (`repository content` when not given) |
| `assertion.location` | repository-relative path and key |
| `assertion.confirmation` | `{ confirmed_by, confirmed_at, expires_at }` or null |
| `assertion.contradiction` | `{ evidence_source, observed_at, summary }` or null |

## Compliance math

- `honored`: excluded from the level's denominator, as N/A today.
- `pending`: counts as non-compliant (Principle II).
- `contradicted`: the claim has no effect.

## Attestation

Every result whose `N/A` comes from an assertion carries `authority: asserted`, `asserted_by`, and, when present, `confirmed_by` and `confirmed_at`. A downstream policy can therefore reject assertion-backed N/A results without re-deriving anything.

## Framework TOML: declaring contradicting evidence

```toml
[controls."OSPS-BR-02.01"]
contradicted_by = { context = "has_releases", when_value = true }
```

`contradicted_by` references existing detection (a context key's detection pipeline or a named check). If the referenced evidence cannot be obtained, the claim is `pending`.
