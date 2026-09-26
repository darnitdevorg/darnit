# Data Model: Operator Configuration and Trust Model

## OperatorConfig

Loaded from the operator configuration file (see [contracts/operator-config.md](contracts/operator-config.md)). Immutable for the duration of a run.

| Field | Type | Notes |
|---|---|---|
| `schema_version` | int | Required; `1` for this feature. Unknown or missing is an error. |
| `plugins.allowed` | list[str] | Plugin (framework) names that may load. Empty means all installed. |
| `plugins.trusted_publishers` | list[str] | Signing identities trusted for plugins. |
| `plugins.allow_unsigned` | bool | Default `false`. |
| `mcp_servers.<name>` | object | Launch command, env (`$VAR` references substituted at launch), trusted publisher. |
| `controls.<id>.passes` | list | Operator-supplied pass overrides (replaces the repository-level mechanism). |
| `custom_controls.<id>` | object | Operator-defined controls. |
| `stores.<kind>` | object | Storage backend selection per kind. |
| `llm` | object | Provider, model, and budget limits. |
| `trust.repos` | list[str] | Canonical repository identities the operator trusts. |
| `trust.case_insensitive_hosts` | list[str] | Extra hosts whose paths are case-insensitive. |
| `trust.ci` | list[CiTrustRule] | Empty by default. |
| `policy.confirmation_expiry_days` | int | Default 180. |
| `policy.strict_permissions` | bool | Default `false`. May only turn strict mode on; strict mode is primarily set by the `--strict-operator-config` launch option and is on by default in recognized CI. |
| `operator.identity` | str | Identity recorded as `confirmed_by`; defaults to the OS user name. |

Validation: every model forbids unknown keys; errors name the file and dotted key.

Derived at load: `source` (absolute path or `builtin-defaults`) and `digest` (SHA-256 of file bytes), both recorded in every report (FR-009).

## RepositoryIdentity

| Field | Type | Notes |
|---|---|---|
| `canonical` | str | `host/namespace/name`, normalized per research R3. |
| `source` | enum | `operator_target`, `ci_metadata`, or `checkout_hint`. |
| `trusted_eligible` | bool | `true` only when `source` is `operator_target` or `ci_metadata` (FR-016a). |

## CiTrustRule

| Field | Type | Notes |
|---|---|---|
| `event` | enum | v1: `push-default-branch` only. |
| `repos` | list[str] | Optional narrowing to specific trusted repositories. |

## TrustDecision (per run)

| Field | Type | Notes |
|---|---|---|
| `repository` | RepositoryIdentity | |
| `trusted` | bool | |
| `reason` | str | For example `listed; local run`, `not listed`, `ci: fork pull request`, `ci: unknown event`, `identity from checkout only`. |
| `ci_facts` | map | Platform, event, ref, default branch, head/base identity when in CI. |
| `warnings` | list[str] | For example a mismatch between the operator target and the checkout's `origin` remote. |

Recorded in the report and attestation.

## ProjectAssertion

Read from `.project/darnit.yaml` `controls.<id>` (or, during deprecation, `.baseline.toml`), or derived from applicability-changing context values (FR-013a).

| Field | Type | Notes |
|---|---|---|
| `control_id` | str | Must exist in the selected framework, otherwise reported as unknown and ignored. |
| `claim` | enum | `not_applicable`. |
| `reason` | str or null | Missing reason forces `pending` for explicit claims (FR-018); context-value claims are exempt. |
| `asserted_by` | str | From the file when given; otherwise `repository content`. |
| `location` | str | Repository-relative file and key path. |
| `origin` | enum | `explicit_claim` or `context_value:<key>`. |

## AssertionOutcome (per control)

State machine:

```
            +-------------+
            |  asserted   |
            +------+------+
                   |
   repo trusted?   | no -----------------------------> pending
                   | yes
   reason present? | no (explicit claim) -------------> pending
                   |   (context values need no reason)
                   | yes
   evidence declared & obtainable?
                   | declared, unobtainable ----------> pending
                   | declared, contradicts ----------> contradicted
                   | not declared / does not contradict
                   v
               honored (N/A, labelled asserted)

   pending --(valid confirmation for same claim and evidence digest)--> honored (N/A, labelled asserted + confirmed)
   honored-by-confirmation --(expiry or evidence digest change)--> pending
```

| Outcome | Compliance effect |
|---|---|
| `honored` | Control counts as N/A; result labelled `asserted` (and `confirmed` when applicable). |
| `pending` | Control counts as non-compliant until confirmed (Principle II). |
| `contradicted` | Claim ignored; control evaluated normally; contradiction and evidence reported. |

## Confirmation

Stored under the darnit data root (operator side), never in the audited repository.

| Field | Type | Notes |
|---|---|---|
| `repository` | str | Canonical identity. |
| `control_id` | str | |
| `claim` | enum | `not_applicable`. |
| `evidence_digest` | str | Digest of the assertion text plus any declared evidence observed at confirmation time. |
| `confirmed_by` | str | `operator.identity` from operator configuration, else the OS user name. |
| `confirmed_at` | timestamp | |
| `expires_at` | timestamp | `confirmed_at + policy.confirmation_expiry_days`. |

A confirmation applies only when repository, control, claim, and evidence digest all match and it has not expired.

## ContradictingEvidence (framework TOML)

| Field | Type | Notes |
|---|---|---|
| `contradicted_by` | reference | On a control: names an existing detection or check whose positive result refutes a not-applicable claim. |
