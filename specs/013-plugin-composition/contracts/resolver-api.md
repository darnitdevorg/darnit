# Contract: Composition Resolver — Internal Python API

**Feature**: 013-plugin-composition · **Status**: Authoritative for v1 · **Date**: 2026-05-13

This is the framework-internal contract for `darnit.core.composition`. It is consumed by `darnit.config.merger.load_framework_config(...)` and by unit tests. It is NOT part of the public Python API; implementation packages MUST NOT import it directly.

---

## Module: `darnit.core.composition`

### Public surface

```python
__all__ = [
    "resolve_composition",
    "CompositionError",
    "CompositionMissingSourceError",
    "CompositionConflictError",
    "CompositionOrphanOverrideError",
    "CompositionUnknownFieldError",
    "CompositionCycleError",
    "CompositionVersionMismatchError",
]
```

---

### Function: `resolve_composition`

```python
def resolve_composition(
    composite: FrameworkConfig,
    *,
    source_loader: Callable[[str], FrameworkConfig | None] | None = None,
) -> FrameworkConfig:
    ...
```

**Inputs**

- `composite` — A `FrameworkConfig` freshly parsed from a composite's TOML. May have non-empty `compose`, `overrides`, or `allow_conflicts`.
- `source_loader` — Optional injection point for tests. Default: an internal wrapper that does slug → path lookup via `PluginRegistry`, then loads the source TOML through `darnit.config.merger._parse_framework_only(path)`. **The default loader MUST return a parsed-but-NOT-resolved `FrameworkConfig`** — it must NOT itself invoke `resolve_composition`, or cycle detection (FR-012) would not catch cycles routed through composite-of-composite chains. The contract is: given a source slug, return a parsed-but-not-composition-resolved `FrameworkConfig` for that source, or `None` if the source is not installed.

**Output**

- A new `FrameworkConfig` with:
  - `controls`: the resolved flat dict, with every value provenance-stamped (R-006).
  - `compose`: `[]` (cleared per invariant I3.2).
  - `overrides`: `{}` (cleared per invariant I3.2).
  - `allow_conflicts`: preserved from input (not load-bearing post-resolution, but kept for telemetry).
  - All other fields unchanged.

**Idempotence**: calling on an input with `compose == []` and `overrides == {}` returns the input unchanged (invariant I3.3).

**Exceptions** (all subclasses of `CompositionError`):

| Exception | Trigger | Attributes |
|---|---|---|
| `CompositionMissingSourceError` | `source_loader(slug)` returned `None`. | `.source: str` |
| `CompositionConflictError` | Two `[[compose]]` blocks contribute the same control ID, no override resolves it, `allow_conflicts` is `false`. | `.control_id: str`, `.sources: tuple[str, str]` |
| `CompositionOrphanOverrideError` | `[overrides."ID"]` targets a control ID not in the resolved set. | `.orphan_id: str` |
| `CompositionUnknownFieldError` | An override names a field not on `ControlConfig`. | `.field: str`, `.control_id: str` |
| `CompositionCycleError` | The resolution stack already contains the current composite's slug. | `.chain: list[str]` |
| `CompositionVersionMismatchError` | The installed source's `metadata.version` does not satisfy a `[[compose]]` block's `version_constraint`. | `.source: str`, `.constraint: str`, `.installed: str` |

**Side effects**

- Emits `INFO`-level log messages on `darnit.core.composition` logger:
  - `"Composition conflict on %s: %s overrides %s (allow_conflicts=true)"` — once per allow_conflicts override.
- Emits `DEBUG`-level log messages:
  - `"Compose block on source %s contributed 0 controls after filtering"` — once per empty-result compose block.
  - `"Resolved composite %s: %d controls (%d composed, %d inline, %d overrides applied)"` — once per resolution.
- Emits `WARNING`-level log messages:
  - `"Override on %s defined a reserved tag key (%s); ignoring"` — once per offending override key.

**Thread-safety**: the function is pure (no shared module-level state beyond logging). Multiple resolutions can run concurrently as long as `source_loader` is thread-safe (the default — `PluginRegistry` lookup + `_parse_framework_only(path)` — is read-only over the filesystem and entry-point registry).

**Performance**: SC-002 requires ≤200 ms for 50 + 5 controls on a developer laptop. Achieved via single-pass resolution with memoized `source_loader` results across recursive entries within one top-level call.

---

### Class: `CompositionError`

```python
class CompositionError(Exception):
    """Base class for all composition-resolution errors.

    Concrete subclasses provide structured attributes; the base class
    exists for consumers that want a single catch-all clause.
    """
```

All subclasses MUST:

- Inherit from `CompositionError` directly (not from each other).
- Set `__str__` to a human-readable message that includes every attribute the subclass exposes.
- Be importable from `darnit.core.composition` at module level.

---

## Integration contract: `darnit.config.merger.load_framework_config`

`load_framework_config(path: Path) -> FrameworkConfig` is refactored into a thin wrapper around a new internal helper `_parse_framework_only(path)` that does parse + template-validate WITHOUT touching composition. The public function becomes:

```python
def _parse_framework_only(path: Path) -> FrameworkConfig:
    """Parse + template-validate a framework TOML. Does NOT resolve composition.

    This is the helper that the composition resolver's default `source_loader`
    routes through, so recursive source loads do NOT re-enter composition with
    a fresh `_resolution_stack`. Cycle detection (FR-012) depends on this split.
    """
    config = _parse_toml(path)          # existing — pydantic validation
    _validate_templates(config, path)   # existing — template path checks
    return config


def load_framework_config(path: Path) -> FrameworkConfig:
    config = _parse_framework_only(path)

    # Composition resolution runs EXACTLY ONCE at the top of this call chain.
    # The resolver's `source_loader` calls `_parse_framework_only` (not this
    # function) for recursive source loads, so the resolver's per-call
    # `_resolution_stack` is the single source of truth for cycle detection.
    if config.compose or config.overrides:
        from darnit.core.composition import resolve_composition
        config = resolve_composition(config)

    return config
```

**Properties**:

- Composition resolution is transparent to callers — they receive a `FrameworkConfig` that is shape-identical to a non-composite's.
- All `CompositionError` subclasses propagate out of `load_framework_config` unchanged.
- The framework name in error messages comes from the composite's `metadata.name`, which is set before composition runs (otherwise resolution couldn't have started).
- `load_framework_by_name(slug)` (existing, no signature change) calls `load_framework_config(resolved_path)` internally. **Callers outside the resolver MAY continue to use it** — at the top of any call chain it produces a fully-resolved config. **The resolver itself MUST NOT call it** — it calls `_parse_framework_only` via the injected `source_loader` to keep cycle detection sound.

---

## Test contract

Unit tests in `tests/darnit/test_composition.py` MUST cover at minimum:

| Test | Asserts |
|---|---|
| `test_basic_include_all` | Compose `include_all = true` from one source; resolved set equals source's full set. |
| `test_include_levels_filter` | Compose `include_levels = [1, 2]`; level-3 controls absent from resolved set. |
| `test_include_controls_filter` | Compose `include_controls = ["A", "B"]`; only those two appear. |
| `test_exclude_controls_after_include` | Compose `include_all = true` + `exclude_controls = ["X"]`; X absent, everything else present. |
| `test_intersection_of_includes` | Compose `include_levels = [1]` + `include_controls = ["L1-A", "L3-B"]`; only `L1-A` appears (intersection narrows). |
| `test_overrides_replace_fields` | Override `remediation` only; pass logic unchanged, remediation matches override. |
| `test_overrides_preserve_provenance` | After an override on a composed control, `_composed_from` still points at the original source. |
| `test_strict_conflict_raises` | Two compose blocks contribute same ID, `allow_conflicts` unset → `CompositionConflictError` with both source slugs. |
| `test_allow_conflicts_last_wins` | Same fixture with `allow_conflicts = true` → registration succeeds, later compose block's contribution wins, INFO log emitted. |
| `test_override_resolves_conflict_in_strict_mode` | Same fixture with `[overrides."ID"]` present → registration succeeds in strict mode; override fields applied. |
| `test_orphan_override_raises` | `[overrides."BOGUS"]` with no matching compose contribution → `CompositionOrphanOverrideError`. |
| `test_unknown_field_override_raises` | Override naming `nonexistent_field` → `CompositionUnknownFieldError`. |
| `test_missing_source_raises` | Compose block references uninstalled slug → `CompositionMissingSourceError`. |
| `test_self_cycle_raises` | Composite includes itself → `CompositionCycleError(chain=["A", "A"])`. |
| `test_two_cycle_raises` | A↔B → `CompositionCycleError` from whichever loads first. |
| `test_three_level_chain_resolves` | A→B→C (C non-composite) → A's resolved set includes C's selected controls. **Each control's `_composed_from` is `"C"` (the ultimate source), not `"B"`** (FR-018 + FR-015). |
| `test_diamond_resolves_once` | A includes B and C; B and C both include D. D's controls appear once in A; `source_loader` called once per unique slug. |
| `test_version_pin_satisfied` | Compose block has `version_constraint = ">=1.0"`, source's version is `1.5.0` → resolves. |
| `test_version_pin_violated` | Same constraint, source's version is `0.9.0` → `CompositionVersionMismatchError`. |
| `test_version_pin_missing_uses_floating` | No `version_constraint` → resolves with whatever version is installed. |
| `test_empty_compose_block_rejected` | `[[compose]]` with no inclusion expressions → registration error. |
| `test_empty_override_block_rejected` | `[overrides."ID"]` with no fields → registration error. |
| `test_idempotent_resolution` | Resolve a config, resolve again → identical result. |
| `test_resolution_performance` | 50 composed + 5 inline controls; resolution time < 200 ms (SC-002). |
| `test_provenance_for_inline_controls` | A composite's own inline controls carry `_composed_from = "<composite-slug>"`. |
| `test_audit_pipeline_unchanged` | End-to-end: register composite, run audit against a fixture repo, assert result shape matches a non-composite audit result. |

Each fixture is a hand-authored TOML file under `tests/darnit/fixtures/composite/`. Resolver tests load each via the real production `load_framework_config(...)` rather than constructing `FrameworkConfig` objects in Python (R-010).
