"""Composition resolution for darnit compliance implementations.

This module is the framework-internal entrypoint for the TOML-only composition
primitive defined in feature 013-plugin-composition. A composite implementation
declares ``[[compose]]`` blocks, ``[overrides."ID"]`` blocks, and an optional
``allow_conflicts`` flag in its TOML; this module resolves all of that into a
flat ``FrameworkConfig.controls`` dict that the rest of the framework can
consume without knowing composition exists.

Canonical references:

- Spec:  ``specs/013-plugin-composition/spec.md``
- Plan:  ``specs/013-plugin-composition/plan.md``
- TOML schema contract:
  ``specs/013-plugin-composition/contracts/toml-schema.md``
- Resolver API contract:
  ``specs/013-plugin-composition/contracts/resolver-api.md``
- Data model + resolution algorithm:
  ``specs/013-plugin-composition/data-model.md``

This module MUST NOT import any implementation package (Constitution
Principle I: Plugin Separation). Source frameworks are resolved via the
``darnit.implementations`` entry-point group through a parse-only loader
helper (``darnit.config.merger._parse_framework_only``); composition
recursion is the resolver's exclusive responsibility so its
``_resolution_stack`` is the single source of truth for cycle detection
(F-1 fix; research.md R-002).
"""

from __future__ import annotations

import logging
from collections.abc import Callable
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    from darnit.config.framework_schema import (
        ComposeBlock,
        ControlConfig,
        FrameworkConfig,
    )

log = logging.getLogger("darnit.core.composition")


# =============================================================================
# Exception hierarchy
# =============================================================================


class CompositionError(Exception):
    """Base class for all composition-resolution errors.

    Concrete subclasses provide structured attributes; this base class
    exists so consumers can ``except CompositionError`` to catch every
    composition failure with a single clause.
    """


class CompositionMissingSourceError(CompositionError):
    """A ``[[compose]]`` block names a source slug not installed on the host.

    Attributes:
        source: The missing source slug.
    """

    def __init__(self, source: str) -> None:
        self.source = source
        super().__init__(
            f"Composition source not installed: {source!r}. "
            f"Install the package providing this source implementation, or "
            f"remove the [[compose]] block referencing it."
        )


class CompositionConflictError(CompositionError):
    """Two ``[[compose]]`` blocks contribute the same control ID in strict mode.

    Attributes:
        control_id: The conflicting control ID.
        sources: A 2-tuple ``(earlier_source, later_source)`` naming the two
            contributing slugs in TOML file order.
    """

    def __init__(self, control_id: str, sources: tuple[str, str]) -> None:
        self.control_id = control_id
        self.sources = sources
        earlier, later = sources
        super().__init__(
            f"Composition conflict on control {control_id!r}: contributed by "
            f"both {earlier!r} and {later!r}. Resolve explicitly by either "
            f"(a) adding `allow_conflicts = true` at the composition root "
            f"(later compose block wins by TOML file order; INFO log emitted), "
            f"or (b) adding an explicit `[overrides.\"{control_id}\"]` block "
            f"(overrides always win and resolve conflicts in any mode)."
        )


class CompositionOrphanOverrideError(CompositionError):
    """An ``[overrides."ID"]`` block targets an ID not in the resolved set.

    Attributes:
        orphan_id: The control ID the override targets.
    """

    def __init__(self, orphan_id: str) -> None:
        self.orphan_id = orphan_id
        super().__init__(
            f"Override targets control {orphan_id!r} but no [[compose]] block "
            f"or inline [controls.\"{orphan_id}\"] entry contributes it. "
            f"Remove the orphan override, or add a compose block / inline "
            f"control that includes this ID."
        )


class CompositionUnknownFieldError(CompositionError):
    """An override block names a field not present on the ``ControlConfig`` schema.

    Attributes:
        control_id: The override target.
        field: The unknown field name.
    """

    def __init__(self, control_id: str, field: str) -> None:
        self.control_id = control_id
        self.field = field
        super().__init__(
            f"Override for control {control_id!r} names unknown field "
            f"{field!r}. Override field names match the real ControlConfig "
            f"schema exactly — common confusions: use `security_severity` "
            f"(not `severity`) and `docs_url` (not `help_url`)."
        )


class CompositionCycleError(CompositionError):
    """The composition graph contains a cycle.

    Attributes:
        chain: The full cycle chain in resolution order, ending with the
            slug that re-entered the stack. For example, ``["A", "B", "A"]``
            for an A→B→A cycle.
    """

    def __init__(self, chain: list[str]) -> None:
        self.chain = list(chain)
        rendered = " → ".join(self.chain)
        super().__init__(
            f"Composition cycle detected: {rendered}. Composites cannot "
            f"transitively include themselves; remove or rewire one of the "
            f"[[compose]] blocks in the chain."
        )


class CompositionVersionMismatchError(CompositionError):
    """A ``[[compose]]`` block's ``version_constraint`` is not satisfied.

    Attributes:
        source: The source slug.
        constraint: The PEP 440 specifier string from the composite's TOML.
        installed: The source's installed ``metadata.version``.
    """

    def __init__(self, source: str, constraint: str, installed: str) -> None:
        self.source = source
        self.constraint = constraint
        self.installed = installed
        super().__init__(
            f"Composition version mismatch for source {source!r}: "
            f"installed version {installed!r} does not satisfy constraint "
            f"{constraint!r}. Install a compatible source version or relax "
            f"the constraint in the [[compose]] block."
        )


__all__ = [
    "CompositionError",
    "CompositionMissingSourceError",
    "CompositionConflictError",
    "CompositionOrphanOverrideError",
    "CompositionUnknownFieldError",
    "CompositionCycleError",
    "CompositionVersionMismatchError",
    "resolve_composition",
]


# =============================================================================
# Internal helpers
# =============================================================================


# Sentinel: framework-stamped tag keys carrying provenance. UI / serializer
# code can identify these because of the leading underscore. The override
# application path (US2 / T031) preserves them across `tags` merges.
_TAG_COMPOSED_FROM = "_composed_from"
_TAG_ORIGINAL_CONTROL_ID = "_original_control_id"


def _select_controls(
    block: ComposeBlock,
    source_controls: dict[str, ControlConfig],
) -> set[str]:
    """Apply a compose block's inclusion/exclusion filters to a source.

    Semantics per R-009 (intersection of all named inclusion expressions,
    then ``exclude_controls`` subtracted from the result):

    1. If ``include_all`` is True, start with every control ID in the source.
    2. Else start with the union of: controls matching ``include_levels``,
       controls matching ``include_controls`` by exact ID, controls whose
       ``tags`` satisfy every key/value pair in ``include_tags`` — but
       evaluated as the **intersection** across the named expressions (so
       ``include_levels = [1]`` AND ``include_controls = ["L1-X", "L3-Y"]``
       yields only ``L1-X``).
    3. Subtract ``exclude_controls`` from whatever set survived inclusion.

    An empty result is NOT an error — it is a no-op contribution and emits
    a DEBUG log so the composite author can spot accidental over-narrowing
    without the framework treating it as a failure.
    """
    if block.include_all:
        selected = set(source_controls.keys())
    else:
        # Start with "all" only if a specific filter is set; otherwise
        # each filter contributes its own narrowing. We compute every
        # individual filter as a set, then intersect.
        individual_sets: list[set[str]] = []

        if block.include_levels:
            levels = set(block.include_levels)
            individual_sets.append(
                {
                    cid
                    for cid, ctrl in source_controls.items()
                    if ctrl.level is not None and ctrl.level in levels
                }
            )

        if block.include_controls:
            wanted = set(block.include_controls)
            individual_sets.append(
                {cid for cid in source_controls if cid in wanted}
            )

        if block.include_tags:
            tagged: set[str] = set()
            for cid, ctrl in source_controls.items():
                if all(
                    ctrl.tags.get(key) == value
                    for key, value in block.include_tags.items()
                ):
                    tagged.add(cid)
            individual_sets.append(tagged)

        # ComposeBlock validators (V1.1, V1.2) guarantee at least one
        # inclusion expression is present and that include_all is exclusive
        # with the others — so `individual_sets` is non-empty here.
        selected = set.intersection(*individual_sets) if individual_sets else set()

    if block.exclude_controls:
        selected -= set(block.exclude_controls)

    if not selected:
        log.debug(
            "Compose block on source %s contributed 0 controls after filtering",
            block.source,
        )

    return selected


def _load_source_with_cache(
    slug: str,
    cache: dict[str, FrameworkConfig],
    loader: Callable[[str], FrameworkConfig | None],
) -> FrameworkConfig | None:
    """Memoize a parse-only source-loader call by slug.

    The cache is scoped to one top-level ``resolve_composition`` invocation
    (R-003), so diamonds (A → B → leaf and A → C → leaf) load the leaf
    exactly once. Returns ``None`` when the loader returns ``None``; the
    caller is responsible for raising :class:`CompositionMissingSourceError`.

    IMPORTANT: ``loader`` MUST be a parse-only function (e.g.
    ``darnit.config.merger._parse_framework_only``). The default loader
    constructed by :func:`_default_source_loader` honors this; tests that
    inject custom loaders MUST also honor it (see
    ``tests/darnit/conftest.py``). Cycle detection (FR-012) is broken if
    the loader re-enters composition with a fresh ``_resolution_stack``.
    """
    if slug in cache:
        return cache[slug]
    cfg = loader(slug)
    if cfg is not None:
        cache[slug] = cfg
    return cfg


def _clone_with_provenance(
    ctrl: ControlConfig,
    composed_from: str,
    original_id: str,
) -> ControlConfig:
    """Return a copy of ``ctrl`` with framework-stamped provenance tags.

    The two stamped tags are:

    - ``_composed_from``: the slug of the source the control originated in
      (the ULTIMATE non-composite source for recursive composition — see
      :func:`resolve_composition`'s handling of the recursive case).
    - ``_original_control_id``: the control's ID as it appears in the
      originating source.

    These travel inside the existing ``ControlConfig.tags`` dict, so any
    downstream consumer that serializes ``tags`` (audit results,
    list-controls output, SARIF formatters) inherits provenance for free.
    """
    new_tags = {
        **ctrl.tags,
        _TAG_COMPOSED_FROM: composed_from,
        _TAG_ORIGINAL_CONTROL_ID: original_id,
    }
    return ctrl.model_copy(update={"tags": new_tags})


def _default_source_loader(slug: str) -> FrameworkConfig | None:
    """Default ``source_loader`` for :func:`resolve_composition`.

    Looks up the source slug via the existing ``PluginRegistry``
    (slug → TOML path), then loads the TOML through
    :func:`darnit.config.merger._parse_framework_only` — NOT through
    :func:`darnit.config.merger.load_framework_config`, which would
    re-enter composition with a fresh ``_resolution_stack`` and break
    cycle detection (F-1 fix; research.md R-002).
    """
    # Late imports keep this module free of import-time dependencies on
    # config.merger and core.registry.
    from darnit.config.merger import _parse_framework_only

    try:
        from darnit.core.registry import get_plugin_registry
    except ImportError:
        return None

    registry = get_plugin_registry()
    path = registry.get_framework_path(slug)
    if path is None:
        return None
    return _parse_framework_only(path)


def _check_version_constraint(
    block: ComposeBlock,
    source_config: FrameworkConfig,
) -> None:
    """Enforce ``[[compose]].version_constraint`` against the loaded source.

    No-op when the block has no constraint (FR-014: default-floating).
    Raises :class:`CompositionVersionMismatchError` on miss.

    Specifier syntax was already validated by
    :func:`ComposeBlock._validate_version_constraint_syntax` at TOML parse
    time, so we can construct the ``SpecifierSet`` here without a
    try/except for ``InvalidSpecifier``. The PEP 440 ``Version`` of the
    source's ``metadata.version``, however, may not parse — we surface
    that as a clear ``CompositionVersionMismatchError`` describing the
    problem rather than letting ``InvalidVersion`` propagate.
    """
    if block.version_constraint is None:
        return

    from packaging.specifiers import SpecifierSet
    from packaging.version import InvalidVersion, Version

    spec = SpecifierSet(block.version_constraint)
    installed = source_config.metadata.version
    try:
        installed_v = Version(installed)
    except InvalidVersion as exc:
        raise CompositionVersionMismatchError(
            source=block.source,
            constraint=block.version_constraint,
            installed=installed,
        ) from exc

    if installed_v not in spec:
        raise CompositionVersionMismatchError(
            source=block.source,
            constraint=block.version_constraint,
            installed=installed,
        )


# =============================================================================
# Resolver
# =============================================================================


def resolve_composition(
    composite: FrameworkConfig,
    *,
    source_loader: Callable[[str], FrameworkConfig | None] | None = None,
    _source_cache: dict[str, FrameworkConfig] | None = None,
    _resolution_stack: list[str] | None = None,
) -> FrameworkConfig:
    """Resolve a composite ``FrameworkConfig`` into a flat control set.

    See ``specs/013-plugin-composition/contracts/resolver-api.md`` for the
    full surface contract and ``specs/013-plugin-composition/data-model.md``
    §Resolution algorithm for the canonical pseudocode this implements.

    US1 (this commit) fills the compose-block iteration loop, source
    loading, memoization, and provenance stamping for both inline and
    composed-in controls. Override application (US2 / T032) and
    strict-conflict detection (US3 / T038) land in subsequent PRs; until
    then the resolver raises :class:`NotImplementedError` if those
    branches would be entered, so partial-composition is impossible.
    """
    if _source_cache is None:
        _source_cache = {}
    if _resolution_stack is None:
        _resolution_stack = []
    if source_loader is None:
        source_loader = _default_source_loader

    # Idempotence (invariant I3.3): a non-composite config returns unchanged.
    # This is also what makes the resolver safe to call twice on the same
    # already-resolved config — and what lets the recursive case below
    # short-circuit when a source happens to have its composition cleared
    # already.
    if not composite.compose and not composite.overrides:
        return composite

    composite_slug = composite.metadata.name

    # Cycle detection (FR-012) — check BEFORE pushing onto the stack so a
    # self-cycle (A → A) is caught on the first repeat. See R-004.
    if composite_slug in _resolution_stack:
        raise CompositionCycleError(chain=_resolution_stack + [composite_slug])

    new_stack = _resolution_stack + [composite_slug]

    # -------------------------------------------------------------------------
    # Stage 1: seed `resolved` with the composite's INLINE controls, each
    # stamped with provenance pointing at the composite itself. They are
    # treated as if they came from a `compose source = <composite>` block
    # so conflict-detection tracking (US3) sees a uniform shape.
    # -------------------------------------------------------------------------
    resolved: dict[str, ControlConfig] = {}
    contributor: dict[str, str] = {}
    for cid, ctrl in composite.controls.items():
        resolved[cid] = _clone_with_provenance(
            ctrl,
            composed_from=composite_slug,
            original_id=cid,
        )
        contributor[cid] = composite_slug

    # -------------------------------------------------------------------------
    # Stage 2: walk `[[compose]]` blocks in TOML file order.
    # -------------------------------------------------------------------------
    for block in composite.compose:
        # Source resolution. The loader is parse-only by contract, so the
        # returned config still has its own `compose`/`overrides` set if
        # the source is itself a composite — that gets resolved on the
        # recursive call below, under the SHARED `_resolution_stack`.
        raw_source = _load_source_with_cache(block.source, _source_cache, source_loader)
        if raw_source is None:
            raise CompositionMissingSourceError(source=block.source)

        # Version-constraint check runs against the SOURCE's own metadata,
        # not its (eventually) resolved version. This matches what the
        # composite author can reason about — the package they installed.
        _check_version_constraint(block, raw_source)

        # Recursive composition (FR-018). If the source has composition
        # state, recursion drives it under our shared stack; idempotence
        # short-circuits the non-composite case so this is a cheap call.
        source_config = resolve_composition(
            raw_source,
            source_loader=source_loader,
            _source_cache=_source_cache,
            _resolution_stack=new_stack,
        )

        # Apply this block's filters against the source's RESOLVED control
        # set (per FR-018 — composing on effective behavior, not raw config).
        selected_ids = _select_controls(block, source_config.controls)

        for cid in selected_ids:
            src_ctrl = source_config.controls[cid]
            # Preserve ultimate-source provenance across recursion (R-006 /
            # FR-018): if the source's control is already stamped, those
            # tags identify the ULTIMATE non-composite origin, so don't
            # overwrite them. Otherwise stamp this block's source slug as
            # the origin.
            effective_from = src_ctrl.tags.get(_TAG_COMPOSED_FROM, block.source)
            effective_id = src_ctrl.tags.get(_TAG_ORIGINAL_CONTROL_ID, cid)
            new_ctrl = _clone_with_provenance(
                src_ctrl,
                composed_from=effective_from,
                original_id=effective_id,
            )

            if cid in resolved:
                # Conflict path. US3 (T038) wires the full strict/allow_conflicts
                # decision tree here. For US1 we only support the no-conflict
                # case; any cross-block contribution to the same ID raises
                # NotImplementedError until US3 lands, so partial-composition
                # is impossible.
                raise NotImplementedError(
                    f"Composition conflict on {cid!r} between sources "
                    f"{contributor[cid]!r} and {block.source!r}: "
                    f"strict/allow_conflicts handling lands in US3 (T038). "
                    f"Until that PR merges, composites whose [[compose]] blocks "
                    f"produce overlapping control IDs are not supported."
                )

            resolved[cid] = new_ctrl
            contributor[cid] = block.source

    # -------------------------------------------------------------------------
    # Stage 3: override application. US2 (T032) wires this loop. For US1 we
    # already short-circuited above when overrides are present alongside no
    # compose blocks; if overrides come together with compose blocks the
    # body would reach this section, so we keep the NotImplementedError
    # placeholder until US2.
    # -------------------------------------------------------------------------
    if composite.overrides:
        raise NotImplementedError(
            "Override application not yet implemented (lands in US2 / T032). "
            f"Composite {composite_slug!r} declares "
            f"{len(composite.overrides)} [overrides.\"…\"] block(s)."
        )

    log.debug(
        "Resolved composite %s: %d controls (%d inline + %d composed)",
        composite_slug,
        len(resolved),
        len(composite.controls),
        len(resolved) - len(composite.controls),
    )

    return composite.model_copy(
        update={
            "controls": resolved,
            "compose": [],
            "overrides": {},
        }
    )


# Re-export for callers that need to introspect provenance tags by name
# rather than hard-coding strings.
__all__ += [
    "_TAG_COMPOSED_FROM",
    "_TAG_ORIGINAL_CONTROL_ID",
]
