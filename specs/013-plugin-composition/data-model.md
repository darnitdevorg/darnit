# Phase 1 Data Model: Composition of compliance implementations

**Feature**: 013-plugin-composition · **Date**: 2026-05-13

Composition introduces **three new entities** in the TOML schema and **one resolution algorithm**. Everything below targets `packages/darnit/src/darnit/config/framework_schema.py` (new pydantic models) and `packages/darnit/src/darnit/core/composition.py` (the resolver).

---

## Entity 1 — `ComposeBlock`

One entry in a composite's `[[compose]]` table-array. Names a source implementation plus the inclusion/exclusion filters that select controls from it.

### Fields

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `source` | `str` | yes | — | The source implementation's slug (e.g., `"openssf-baseline"`). Resolved via `darnit.implementations` entry points. |
| `include_all` | `bool` | no | `false` | Pull every control from the source. Mutually exclusive with the other `include_*` fields (FR-003). |
| `include_levels` | `list[int]` | no | `[]` | Pull controls whose `level` is in this list. |
| `include_controls` | `list[str]` | no | `[]` | Pull controls by exact ID. |
| `include_tags` | `dict[str, Any]` | no | `{}` | Pull controls matching every tag/value pair (AND semantics across keys). |
| `exclude_controls` | `list[str]` | no | `[]` | After inclusion filters are applied, drop these IDs from the result. |
| `version_constraint` | `str \| None` | no | `None` | PEP 440 specifier (`">=1.5,<2.0"`). When present, source's `metadata.version` must satisfy it (FR-013). |

### Validation rules

- **V1.1** — Exactly one of `include_all` or one-or-more of (`include_levels`, `include_controls`, `include_tags`) MUST be set. A `[[compose]]` block with no inclusion expressions is a registration error: "No controls selected from source `<slug>`."
- **V1.2** — If `include_all = true`, the other `include_*` fields MUST be empty. Mixing is a registration error.
- **V1.3** — `version_constraint`, if present, MUST parse via `packaging.specifiers.SpecifierSet(...)`. A malformed specifier is a registration error naming the offending string.
- **V1.4** — `exclude_controls` is applied AFTER the inclusion expressions. If `exclude_controls` is non-empty AND no inclusion expression is set, that's covered by V1.1's error.

### State / lifecycle

`ComposeBlock` is read-only after TOML load. No mutation during resolution; the resolver constructs new `ControlConfig` instances from the source's controls + provenance stamps.

---

## Entity 2 — `OverrideBlock`

One `[overrides."CONTROL-ID"]` entry. Replaces specific fields of a control already present in the resolved set.

### Fields

| Field | Type | Required | Default | Notes |
|---|---|---|---|---|
| `passes` | `list[PassConfig] \| None` | no | `None` | If present, replaces the underlying control's `passes` list wholesale (FR-006). Partial pass edits are out of scope. |
| `remediation` | `RemediationConfig \| None` | no | `None` | If present, replaces the control's `remediation` block. |
| `security_severity` | `float \| None` | no | `None` | If present, replaces the control's `security_severity` field (CVSS-like 0.0–10.0). Field name matches the underlying `ControlConfig` schema exactly. |
| `description` | `str \| None` | no | `None` | If present, replaces the control's `description`. |
| `docs_url` | `str \| None` | no | `None` | If present, replaces the control's `docs_url`. Field name matches the underlying `ControlConfig` schema; v1 does NOT touch `help_md` / `help_file` separately. |
| `tags` | `dict[str, Any]` | no | `{}` | Shallow-merged into the control's `tags`. Framework-stamped provenance keys (`_composed_from`, `_original_control_id`) are NOT overwritten. |

**Key**: `OverrideBlock` instances are stored in `FrameworkConfig.overrides: dict[str, OverrideBlock]`, keyed by the target control ID.

### Validation rules

- **V2.1** — The target control ID (the dict key) MUST be present in the composite's resolved control set. An orphan override → `CompositionOrphanOverrideError` (FR-007). Checked AFTER `[[compose]]` blocks have populated the resolved set.
- **V2.2** — Every field named in the override MUST be a known field on `ControlConfig`. Unknown fields → `CompositionUnknownFieldError` (FR-008). Validated against `ControlConfig.model_fields.keys()` (Pydantic v2). Names that LOOK like aliases (e.g., `severity`, `help_url`) but don't appear on the real schema are unknown fields and rejected — the override-able names in this document match the schema's real field names.
- **V2.3** — At least one field MUST be set. An empty `[overrides."ID"]` block is a registration error: "Override for `<ID>` defines no fields."
- **V2.4** — `tags` overrides may NOT redefine `_composed_from` or `_original_control_id`. If present in the override's `tags`, the resolver silently drops them and emits a WARNING log (these keys are reserved-internal).

---

## Entity 3 — `FrameworkConfig` (existing — extended)

Two new top-level fields plus one Boolean flag.

### New fields on existing model

| Field | Type | Default | Notes |
|---|---|---|---|
| `compose` | `list[ComposeBlock]` | `[]` | TOML `[[compose]]` table-array. Presence triggers resolution at load time. |
| `overrides` | `dict[str, OverrideBlock]` | `{}` | TOML `[overrides."ID"]` blocks. Keyed by target control ID. |
| `allow_conflicts` | `bool` | `false` | Opt-out flag at the composition root (top-level TOML, NOT inside a `[[compose]]` block). When `true`, conflicts last-wins-by-file-order with an INFO log; when `false` (default), conflicts → `CompositionConflictError`. |

### Behavioral invariants

- **I3.1** — If `compose == []` AND `overrides == {}`, the framework is NOT a composite. Loader skips resolution and returns the parsed config unchanged. Composites are detected purely by presence of `[[compose]]` blocks (overrides without composes is meaningless and rejected by V2.1 — orphan overrides).
- **I3.2** — After resolution, `compose` and `overrides` are CLEARED on the returned `FrameworkConfig`. The resolved `controls` dict is the only post-resolution surface; downstream consumers MUST NOT see composition state. (Implementation note: the resolver returns a new `FrameworkConfig` rather than mutating in place, since pydantic models are immutable-by-convention here.)
- **I3.3** — Resolution is idempotent. Calling the resolver on an already-resolved `FrameworkConfig` (empty `compose`, populated `controls`) is a no-op.
- **I3.4** — `allow_conflicts = true` does NOT suppress orphan-override, unknown-field, missing-source, cycle, or version-mismatch errors. It governs ONLY the strict-conflict path (FR-009 / FR-010).

---

## Entity 4 — `ControlConfig` (existing — extended via `tags`)

No structural change. Provenance is stamped into the existing `tags: dict[str, Any]` field by the resolver:

| Stamped tag key | Type | Source | Notes |
|---|---|---|---|
| `_composed_from` | `str` | Resolver | The slug named in the composite's `[[compose]]` block that contributed this control. For recursively composed sources, this is overwritten with the ultimate non-composite source's slug (FR-018 → FR-015). |
| `_original_control_id` | `str` | Resolver | The control's ID as it appears in the originating non-composite source. In v1 this equals the control's own ID, but recording it explicitly future-proofs against rename support. |

Underscore-prefix follows Python's "internal" convention and signals to UI/serializer code that these are framework-stamped tags.

Provenance is also mirrored into `ControlSpec.tags` automatically — `ControlSpec.__post_init__` already copies `tags` from `ControlConfig` when the framework registers controls into the runtime registry.

---

## Resolution algorithm (canonical pseudocode)

```text
def resolve_composition(
    composite: FrameworkConfig,
    *,
    _source_cache: dict[str, FrameworkConfig] = None,
    _resolution_stack: list[str] = None,
) -> FrameworkConfig:
    _source_cache = _source_cache if _source_cache is not None else {}
    _resolution_stack = _resolution_stack or []

    # Idempotence (invariant I3.3)
    if not composite.compose and not composite.overrides:
        return composite

    composite_slug = composite.metadata.name

    # Self-cycle check (FR-012)
    if composite_slug in _resolution_stack:
        raise CompositionCycleError(chain=_resolution_stack + [composite_slug])
    _resolution_stack = _resolution_stack + [composite_slug]

    # Start with inline controls (preserve them as-is — they're the composite's own,
    # no provenance stamping needed beyond their natural origin)
    resolved: dict[str, ControlConfig] = dict(composite.controls)
    contributor: dict[str, str] = {cid: composite_slug for cid in resolved}

    # Walk compose blocks in TOML file order
    for block in composite.compose:
        # FR-013: version constraint check, applied to whatever the source's metadata.version is
        source_config = _load_source_with_cache(block.source, _source_cache)
        if source_config is None:
            raise CompositionMissingSourceError(source=block.source)

        # If source is itself a composite, resolve it RECURSIVELY through this
        # same resolver so the _resolution_stack and _source_cache are shared.
        # NOTE: source_loader returns a parsed-but-NOT-resolved FrameworkConfig
        # (it calls _parse_framework_only, not load_framework_config). This is
        # the load-bearing detail for cycle detection (FR-012): the only place
        # composition recursion happens is HERE, so the only stack that exists
        # is _resolution_stack.
        source_config = resolve_composition(
            source_config,
            _source_cache=_source_cache,
            _resolution_stack=_resolution_stack,
        )

        if block.version_constraint is not None:
            _check_version(block, source_config)

        # Apply inclusion/exclusion filters (R-009: intersection semantics)
        selected_ids = _select_controls(block, source_config.controls)

        # Resolve each selected control's effective source slug for provenance.
        # If the source is a composite, its controls already carry _composed_from /
        # _original_control_id pointing at their ultimate origin — preserve those.
        # Otherwise, stamp them now.
        for ctrl_id in selected_ids:
            src_ctrl = source_config.controls[ctrl_id]
            new_ctrl = _clone_with_provenance(
                src_ctrl,
                composed_from=src_ctrl.tags.get("_composed_from", block.source),
                original_id=src_ctrl.tags.get("_original_control_id", ctrl_id),
            )

            if ctrl_id in resolved:
                # Conflict path (FR-009, FR-010, FR-011)
                if ctrl_id in composite.overrides:
                    # Override will win regardless; skip the compose-block contribution
                    # silently (the override phase replaces it anyway).
                    continue
                if composite.allow_conflicts:
                    log.info(
                        "Composition conflict on %s: %s overrides %s (allow_conflicts=true)",
                        ctrl_id, block.source, contributor[ctrl_id],
                    )
                    resolved[ctrl_id] = new_ctrl
                    contributor[ctrl_id] = block.source
                else:
                    raise CompositionConflictError(
                        control_id=ctrl_id,
                        sources=[contributor[ctrl_id], block.source],
                    )
            else:
                resolved[ctrl_id] = new_ctrl
                contributor[ctrl_id] = block.source

    # Apply overrides AFTER all compose blocks (R-007)
    for override_id, override in composite.overrides.items():
        if override_id not in resolved:
            raise CompositionOrphanOverrideError(orphan_id=override_id)
        _validate_override_fields(override)  # FR-008
        resolved[override_id] = _apply_override(resolved[override_id], override)

    # Return a new FrameworkConfig with composition state cleared (invariant I3.2)
    return composite.model_copy(
        update={"controls": resolved, "compose": [], "overrides": {}},
    )
```

### Algorithm properties

- **Linear in unique-source count** thanks to `_source_cache` (R-003).
- **Cycle detection** via `_resolution_stack` membership check before recursion (R-004).
- **Strict-by-default conflicts** with two named escape hatches (R-008).
- **Provenance preserved across recursion** by reading `_composed_from` / `_original_control_id` from the source's already-stamped tags before overstamping (R-006).
- **Overrides last** so their precedence is unambiguous (R-007). When an override targets a control ID contributed by two or more compose blocks (in ANY mode — strict OR `allow_conflicts = true`), the override layers onto the **earliest** compose block's contribution; later compose blocks are skipped on the `continue` branch, never written. (The `continue` runs BEFORE the `allow_conflicts` check in the pseudocode above, so this rule is mode-independent.) Authors who need a later block's base must replicate it inside the override.
- **Idempotent** because the returned config has `compose=[]` and `overrides={}` (I3.3).

---

## Cross-references

| Entity | FRs it satisfies | SCs it supports |
|---|---|---|
| `ComposeBlock` | FR-001, FR-002, FR-003, FR-013, FR-014 | SC-001, SC-002, SC-004 |
| `OverrideBlock` | FR-006, FR-007, FR-008, FR-011 | SC-007 |
| `FrameworkConfig.compose / overrides / allow_conflicts` | FR-005, FR-009, FR-010, FR-016, FR-017, FR-018 | SC-006, SC-008 |
| `tags["_composed_from"]` + `tags["_original_control_id"]` | FR-015, FR-018 | SC-003 |
| Resolution algorithm | FR-004, FR-012 | SC-002, SC-004, SC-005 |
