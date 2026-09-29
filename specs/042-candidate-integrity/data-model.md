# Data Model: Candidate Integrity for Project Values

## ContextKeyDefinition (framework TOML `[context.<key>]`, existing, extended)

| Field | Type | Notes |
|---|---|---|
| `type` | string | existing (`string`, `boolean`, `enum`, `list_or_path`, ...) |
| `values` | list | existing; the only vocabulary for enum keys (R9) |
| `auto_detect` | bool | existing; `false` marks a user-judgment key |
| `allow_sieve_hints`, `hint_sources`, `detect`, `detect_filter` | | existing; produce candidates only |
| `examples` | list | existing; format hints only, never offered as answers (FR-014) |
| `validity_days` | int, optional | NEW: confirmation validity measured from `last_validated` (FR-022) |

Validation: `validity_days > 0` when present. A key cannot be both `auto_detect = false` and concluded (enforced by the resolver, not configuration).

## ResolvedValue (in memory, one per key per run)

| Field | Type | Notes |
|---|---|---|
| `key` | string | canonical name (R9) |
| `standing` | `confirmed` \| `candidate` \| `concluded` \| `unknown` | |
| `value` | any \| None | normalized value; None when `unknown` |
| `origin` | Origin \| None | for `candidate` and `concluded` |
| `confirmation` | ConfirmationRecord \| None | for `confirmed` |
| `lapsed` | ConfirmationRecord \| None | set when a record exists but lapsed or no longer matches |
| `location` | string \| None | file and field where a stored value lives (for review and rejection) |

## Origin

| Field | Type | Notes |
|---|---|---|
| `kind` | `detector` \| `sieve_hint` \| `stored_unconfirmed` \| `expired_confirmation` \| `answer` | |
| `method` | string | detector or handler name, hint file, or storage location |
| `confidence` | float \| None | informational only; never a decision input for judgment keys |

## ResolvedContext

- `values: dict[str, ResolvedValue]`
- `usable() -> dict[str, Any]`: confirmed values, plus concluded values of keys with `auto_detect = true`. The only mapping consumers may read values from.
- `pending() -> list[ResolvedValue]`: keys that are `candidate` or `unknown` and affect a loaded control.
- `stored_unconfirmed() -> list[ResolvedValue]`: candidates with origin `stored_unconfirmed` (the review list, FR-010).

## ConfirmationRecord

In-repository form (`.project/darnit.yaml`, `confirmations.<key>`):

```yaml
confirmations:
  maintainers:
    value_digest: "sha256:..."
    confirmed_by: "alice"
    confirmed_at: "2026-09-29T15:00:00Z"
    last_validated: "2026-09-29T15:00:00Z"
    expires_at: "2027-09-29T00:00:00Z"   # optional
    basis:                                 # optional; absent when the person typed the value
      value: ["@alice", "@bob"]
      origin: { kind: sieve_hint, method: MAINTAINERS.md }
```

Operator-side form: the feature 040 `Confirmation` with `claim = "context_value"`, `control_id = <key>`, `evidence_digest = value_digest`, `confirmed_by`, `confirmed_at`, `expires_at`; `last_validated` equals `confirmed_at` (re-confirmation replaces the entry). The candidate basis is stored in a sibling `context_bases` list keyed the same way (value and origin), so the operator-side store remains readable by feature 040 code.

Rules:
- Matches only when `value_digest` equals the digest of the current normalized value (FR-012).
- Lapses at the earliest of `expires_at` and `last_validated + validity_days` (FR-022). Unparseable timestamps count as lapsed.
- Location: in-repository when the target is trusted by the operator at confirmation time; otherwise operator-side (R3). Reading consults both; the in-repository record wins when both match.

## Value digest

`"sha256:" + sha256(canonical_json(normalize(key, value)))`, where `normalize` applies the canonical vocabulary (R9) and sorts list values whose order is not meaningful (maintainers).

## State transitions (per key)

```
unknown --detect (judgment key)--> candidate(detector|sieve_hint)
unknown --detect concludes (non-judgment key)--> concluded           [per run, never stored by reads]
stored value, no matching record --> candidate(stored_unconfirmed)
candidate --accept_candidates(key, digest) / confirm_stored / answer--> confirmed   [writes value + record]
confirmed --value edited--> candidate(stored_unconfirmed) with lapsed=record
confirmed --expires_at or validity passes--> candidate(expired_confirmation)
candidate(stored_unconfirmed) --reject_stored--> unknown (darnit.yaml value deleted) | unchanged + edit instruction (project.yaml)
```

## ProjectFileState (loader, R10)

`absent` | `valid(config)` | `invalid(errors)`; writers refuse on `invalid` and return the errors. Applies to `project.yaml` and `darnit.yaml` independently.
