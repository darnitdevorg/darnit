# Contract: TOML Schema for Composite Implementations

**Feature**: 013-plugin-composition · **Status**: Authoritative for v1 · **Date**: 2026-05-13

This is the user-visible contract a composite-implementation author types by hand. It extends the existing `FrameworkConfig` TOML schema with three new constructs: `[[compose]]` blocks, `[overrides."ID"]` blocks, and a root-level `allow_conflicts` flag.

A framework is treated as a composite **if and only if** it has at least one `[[compose]]` block in its TOML.

---

## 1. Anatomy of a composite TOML

```toml
[metadata]
name = "acme-baseline"
display_name = "Acme Baseline"
version = "1.0.0"
spec_version = "Acme v1"

# Optional. Default: false. When true, conflicting control IDs across compose
# blocks fall back to last-wins (by file order) with an INFO log. Default
# behavior (false) raises CompositionConflictError at registration time.
allow_conflicts = false

# ---------------------------------------------------------------------------
# Composition: zero or more [[compose]] blocks, each pulling controls from
# one source implementation.
# ---------------------------------------------------------------------------

[[compose]]
source = "openssf-baseline"
include_levels = [1, 2]
exclude_controls = ["OSPS-AC-02.01"]
version_constraint = ">=1.5,<2.0"   # optional, PEP 440

[[compose]]
source = "darnit-gittuf"
include_all = true

[[compose]]
source = "openssf-baseline"
include_controls = [
    "OSPS-AC-03.01",
    "OSPS-VM-03.01",
    "OSPS-QA-07.01",
]
# version_constraint omitted → default-floating (FR-014)

# ---------------------------------------------------------------------------
# Optional inline controls. These live in the composite's own TOML and are
# merged with composed-in controls (union; subject to conflict rules).
# ---------------------------------------------------------------------------

[controls."ACME-DEPLOY-01.01"]
name = "DeployWindowEnforced"
level = 1
domain = "AC"
description = "Production deploys happen only during the published window."
# ... standard passes/remediation as for any non-composite control ...

# ---------------------------------------------------------------------------
# Optional overrides. Each [overrides."ID"] replaces specific fields of a
# control already present in the resolved set (inline or composed-in).
# ---------------------------------------------------------------------------

[overrides."OSPS-AC-01.01"]
remediation = """
Update SSO config in https://sso.acme.example/admin → "Require MFA".
See the Acme runbook at https://internal.acme.example/runbooks/sso.
"""

[overrides."OSPS-VM-03.01"]
security_severity = 8.5
docs_url = "https://internal.acme.example/runbooks/vuln-management"
```

---

## 2. `[[compose]]` block — field-by-field contract

| Field | Type | Required | Default | Behavior |
|---|---|---|---|---|
| `source` | `string` | yes | — | The slug of the source implementation (matches `[metadata].name` of the source's TOML). Resolved via the `darnit.implementations` entry-point group. |
| `include_all` | `bool` | no | `false` | When `true`, pull every control from the source. MUST NOT be combined with the other `include_*` fields. |
| `include_levels` | `array<int>` | no | `[]` | Pull controls whose `level` is in this list. |
| `include_controls` | `array<string>` | no | `[]` | Pull controls by exact control ID. |
| `include_tags` | `table<string, any>` | no | `{}` | Pull controls whose `tags` dict contains every key/value pair in this table (AND across keys). |
| `exclude_controls` | `array<string>` | no | `[]` | Applied AFTER the inclusion expressions. Removes named IDs from the set selected by inclusion. |
| `version_constraint` | `string` | no | `None` | PEP 440 specifier. When present, the source's installed `version` MUST satisfy it; mismatch → registration error. |

**Rules**:

- A `[[compose]]` block MUST define at least one inclusion expression (either `include_all = true` OR at least one of `include_levels`, `include_controls`, `include_tags`). A block with only `exclude_controls` is rejected.
- `include_all = true` is mutually exclusive with the other `include_*` fields.
- Inclusion expressions are evaluated as the **intersection** of all expressions present in the block (R-009). Then `exclude_controls` is subtracted from that intersection.
- An empty result (filters narrow to zero controls) is NOT an error — it contributes nothing and emits a DEBUG log.

---

## 3. `[overrides."CONTROL-ID"]` block — field-by-field contract

The key in the table header is the target control ID, quoted because control IDs contain dots.

| Field | Type | Required | Behavior |
|---|---|---|---|
| `passes` | `array<table>` | no | If present, **wholesale replaces** the underlying control's `passes`. Partial pass-block edits are out of scope for v1. |
| `remediation` | `table` | no | If present, replaces the control's `remediation` block. |
| `security_severity` | `number` | no | If present, replaces the control's `security_severity` (0.0–10.0 CVSS-like). |
| `description` | `string` | no | If present, replaces the control's `description`. |
| `docs_url` | `string` | no | If present, replaces the control's `docs_url`. |
| `tags` | `table<string, any>` | no | Shallow-merged into the control's `tags`. Reserved keys `_composed_from` and `_original_control_id` are silently dropped if redefined (with a WARNING log). |

**Rules**:

- The target control ID MUST exist in the resolved set after `[[compose]]` blocks have run. Orphan overrides → registration error.
- Every field named MUST be a known field on `ControlConfig`. Unknown fields → registration error. **Override field names match the real `ControlConfig` schema** (so `severity` and `help_url` are rejected as unknown — use `security_severity` and `docs_url`). The framework offers no friendly aliases in v1.
- A `[overrides."ID"]` block MUST define at least one field. An empty block is rejected.

---

## 4. Root-level `allow_conflicts` flag

| Field | Type | Required | Default | Behavior |
|---|---|---|---|---|
| `allow_conflicts` | `bool` | no | `false` | Top-level (sibling of `[metadata]`, NOT inside any `[[compose]]` block). Default `false` → conflicts raise. Set to `true` → conflicts last-wins by TOML file order with an INFO log. Does NOT suppress orphan-override, unknown-field, missing-source, cycle, or version-mismatch errors. |

---

## 5. Conflict resolution — precedence summary

When two paths through the composition produce the same control ID:

1. **`[overrides."ID"]` always wins.** Even in strict mode (`allow_conflicts = false`), the presence of an explicit override on the conflicting ID is treated as the composite author's acknowledgement of the conflict, so registration succeeds and the override's fields replace whatever the compose phase produced. The override's fields layer onto the **earliest** compose block's contribution (by TOML file order); later compose blocks contributing the same ID are skipped entirely. **This earliest-base rule is mode-independent — it holds under `allow_conflicts = false` AND `allow_conflicts = true`.** To pick a later compose block as the base, replicate its relevant fields inside the override.
2. **Otherwise, with `allow_conflicts = true`**: the LATER `[[compose]]` block in TOML file order wins; INFO log emitted naming both sources and the winner.
3. **Otherwise (strict, default)**: registration fails with `CompositionConflictError(control_id, sources=[earlier, later])`.

---

## 6. Provenance contract

Every control in the resolved set carries two framework-stamped tags:

| Tag key | Meaning |
|---|---|
| `_composed_from` | The slug of the **ultimate non-composite** source the control originated in. For recursive composition (composite-includes-composite), this is preserved from the source's already-resolved control, not overwritten with the intermediate composite's slug. |
| `_original_control_id` | The control's ID as it appears in the originating non-composite source. Identical to the resolved control's ID in v1; recorded explicitly to future-proof for rename support. |

Inline controls (defined directly in the composite's own TOML) are stamped with `_composed_from = "<composite-slug>"` and `_original_control_id = "<their-own-id>"`.

Audit results, list-controls output, and any consumer that serializes `tags` automatically inherits this provenance — no consumer-side schema change is required.

---

## 7. Error contract (registration time)

A composite registers via the standard `darnit.implementations` entry point. Its TOML is loaded through `darnit.config.merger.load_framework_config(...)`, which delegates to the composition resolver when `[[compose]]` blocks are present. All errors below are raised during this load, BEFORE any audit code runs:

| Error class | Raised when | Message MUST name |
|---|---|---|
| `CompositionMissingSourceError` | A `[[compose]]` block names a `source` slug not installed on the host. | The missing slug. |
| `CompositionConflictError` | Two `[[compose]]` blocks contribute the same control ID, no override resolves it, `allow_conflicts` is false. | Both source slugs, the conflicting control ID, and the two opt-out mechanisms. |
| `CompositionOrphanOverrideError` | An `[overrides."ID"]` block targets a control ID not present in the resolved set. | The orphan ID. |
| `CompositionUnknownFieldError` | An override names a field not on `ControlConfig`. | The unknown field name and the control ID. |
| `CompositionCycleError` | A composition graph contains a cycle (self, A↔B, A→B→C→A, etc.). | The full cycle chain in resolution order. |
| `CompositionVersionMismatchError` | A `[[compose]]` block's `version_constraint` is not satisfied by the installed source's version. | The constraint, the source slug, and the installed version. |

All inherit from a common base `CompositionError(Exception)` so consumers can catch all composition errors uniformly via one `except` clause.

---

## 8. Backward compatibility

- Non-composite frameworks (no `[[compose]]` block, no `[overrides]` block, no `allow_conflicts`) load with **identical** behavior to today. SC-008.
- All existing implementations (`darnit-baseline`, `darnit-gittuf`, `darnit-example`, `darnit-hello`, `darnit-testchecks`) require zero changes.
- Downstream consumers of `FrameworkConfig.controls` (audit pipeline, sieve, list-controls, remediation) see the same shape after resolution as before. The `controls` dict's value type, `ControlConfig`, gains no new required fields.
