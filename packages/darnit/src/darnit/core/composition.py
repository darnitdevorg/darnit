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
from typing import TYPE_CHECKING

if TYPE_CHECKING:
    pass

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
# Resolver (skeleton — Foundational phase only; full body lands in US1+)
# =============================================================================


def resolve_composition(
    composite,
    *,
    source_loader=None,
    _source_cache: dict | None = None,
    _resolution_stack: list[str] | None = None,
):
    """Resolve a composite ``FrameworkConfig`` into a flat control set.

    See ``specs/013-plugin-composition/contracts/resolver-api.md`` for the
    full contract and ``specs/013-plugin-composition/data-model.md``
    §Resolution algorithm for the canonical pseudocode.

    This is the Foundational-phase skeleton: idempotence (invariant I3.3),
    cycle-stack threading (invariant feeding FR-012), and the "clear
    composition state on return" pattern (invariant I3.2) are wired up.
    The compose-block iteration body and the override-application body are
    placeholders raised as :class:`NotImplementedError`; US1 fills the
    former, US2 fills the latter.
    """
    # Import inside to avoid an import cycle: composition.py is imported by
    # merger.py, and merger.py defines FrameworkConfig.
    from darnit.config.framework_schema import FrameworkConfig  # noqa: F401

    if _source_cache is None:
        _source_cache = {}
    if _resolution_stack is None:
        _resolution_stack = []

    # Pure short-circuit (invariant I3.3): a non-composite config returns
    # unchanged. This is also what makes the resolver safe to call twice on
    # the same already-resolved config.
    if not composite.compose and not composite.overrides:
        return composite

    composite_slug = composite.metadata.name

    # Cycle detection (FR-012) — check BEFORE pushing onto the stack so a
    # self-cycle (A → A) is caught on the first repeat, not on a hypothetical
    # second one. See R-004.
    if composite_slug in _resolution_stack:
        raise CompositionCycleError(chain=_resolution_stack + [composite_slug])

    # Recursive calls in US1 will pass `_resolution_stack + [composite_slug]`
    # into themselves so any source that re-enters this slug raises
    # CompositionCycleError. Stored locally below once the iteration body
    # lands (T017); for the skeleton we just confirm the slug is not
    # already on the stack above.

    # ---------------------------------------------------------------------
    # Foundational phase body intentionally minimal. The full pseudocode
    # from data-model.md §Resolution algorithm lands across US1 (compose
    # iteration), US2 (override application), and US3 (conflict detection).
    # ---------------------------------------------------------------------
    if composite.compose:
        # US1 (T017) replaces this with the compose-block iteration loop.
        raise NotImplementedError(
            "Compose-block iteration not yet implemented (lands in US1 / T017). "
            f"Composite {composite_slug!r} declares {len(composite.compose)} "
            f"[[compose]] block(s) but the resolver body is still the "
            f"Foundational skeleton."
        )

    if composite.overrides:
        # US2 (T032) replaces this with the override-application loop. Orphan
        # detection (V2.1 / FR-007) catches "overrides without composes" here
        # in the meantime once US2 lands.
        raise NotImplementedError(
            "Override application not yet implemented (lands in US2 / T032). "
            f"Composite {composite_slug!r} declares "
            f"{len(composite.overrides)} [overrides.\"…\"] block(s)."
        )

    # Unreachable today because both branches above raise; left in place so
    # the structure is obvious for the US1 / US2 fill-ins.
    return composite.model_copy(  # pragma: no cover
        update={
            "controls": dict(composite.controls),
            "compose": [],
            "overrides": {},
        }
    )
