"""Tests for ``darnit.core.composition`` — feature 013-plugin-composition.

US1 (this module's initial scope) exercises compose-block resolution,
inclusion/exclusion filters, source loading, memoization, provenance
stamping for both inline and composed-in controls, and the audit-pipeline
shape contract. US2/US3/US4/US5 land in subsequent PRs.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from darnit.config.framework_schema import FrameworkConfig
from darnit.config.merger import _parse_framework_only
from darnit.core.composition import (
    _TAG_COMPOSED_FROM,
    _TAG_ORIGINAL_CONTROL_ID,
    CompositionConflictError,
    CompositionCycleError,
    CompositionMissingSourceError,
    CompositionOrphanOverrideError,
    CompositionUnknownFieldError,
    CompositionVersionMismatchError,
    resolve_composition,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _composite_path(composite_fixtures_dir: Path, name: str) -> Path:
    return composite_fixtures_dir / f"{name}.toml"


def _resolve(
    composite_fixtures_dir: Path,
    fixture_source_loader,
    composite_name: str,
) -> FrameworkConfig:
    """Parse a composite fixture and resolve it against the fixture loader."""
    cfg = _parse_framework_only(_composite_path(composite_fixtures_dir, composite_name))
    return resolve_composition(cfg, source_loader=fixture_source_loader)


# ---------------------------------------------------------------------------
# T020: include_all
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_basic_include_all(composite_fixtures_dir, fixture_source_loader):
    """Compose ``include_all = true`` returns the source's full control set."""
    result = _resolve(
        composite_fixtures_dir, fixture_source_loader, "basic-include-all"
    )

    expected = {
        "MOCK-AC-01.01",
        "MOCK-AC-02.01",
        "MOCK-VM-01.01",
        "MOCK-VM-02.01",
        "MOCK-QA-01.01",
    }
    assert set(result.controls.keys()) == expected
    assert result.compose == []
    assert result.overrides == {}


# ---------------------------------------------------------------------------
# T021: include_levels filter
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_include_levels_filter(composite_fixtures_dir, fixture_source_loader):
    """``include_levels = [1, 2]`` excludes the source's L3 control."""
    result = _resolve(composite_fixtures_dir, fixture_source_loader, "include-levels")

    assert "MOCK-VM-02.01" not in result.controls, (
        "Level-3 control should not appear when include_levels = [1, 2]"
    )
    # L1 and L2 controls are present
    assert {
        "MOCK-AC-01.01",
        "MOCK-AC-02.01",
        "MOCK-VM-01.01",
        "MOCK-QA-01.01",
    } <= set(result.controls.keys())


# ---------------------------------------------------------------------------
# T022: include_controls filter
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_include_controls_filter(composite_fixtures_dir, fixture_source_loader):
    """``include_controls = [...]`` selects only the named IDs."""
    result = _resolve(
        composite_fixtures_dir, fixture_source_loader, "include-controls"
    )

    assert set(result.controls.keys()) == {"MOCK-AC-01.01", "MOCK-QA-01.01"}


# ---------------------------------------------------------------------------
# T023: exclude_controls applied after include_all
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_exclude_controls_after_include(
    composite_fixtures_dir, fixture_source_loader
):
    """``exclude_controls`` subtracts from whatever inclusion produced."""
    result = _resolve(
        composite_fixtures_dir, fixture_source_loader, "exclude-after-include"
    )

    assert "MOCK-AC-02.01" not in result.controls
    expected_remaining = {
        "MOCK-AC-01.01",
        "MOCK-VM-01.01",
        "MOCK-VM-02.01",
        "MOCK-QA-01.01",
    }
    assert set(result.controls.keys()) == expected_remaining


# ---------------------------------------------------------------------------
# T024: intersection-of-includes
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_intersection_of_includes(composite_fixtures_dir, fixture_source_loader):
    """Multiple inclusion expressions intersect (R-009)."""
    result = _resolve(
        composite_fixtures_dir, fixture_source_loader, "intersection-of-includes"
    )

    # include_levels=[1] AND include_controls=[MOCK-AC-01.01, MOCK-VM-02.01].
    # MOCK-VM-02.01 is L3 so the level filter drops it — only MOCK-AC-01.01
    # survives the intersection.
    assert set(result.controls.keys()) == {"MOCK-AC-01.01"}


# ---------------------------------------------------------------------------
# T025: inline + compose, with provenance on both kinds
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_provenance_for_inline_and_composed_controls(
    composite_fixtures_dir, fixture_source_loader
):
    """Inline and composed controls both carry framework-stamped provenance."""
    result = _resolve(
        composite_fixtures_dir, fixture_source_loader, "inline-with-compose"
    )

    assert set(result.controls.keys()) == {"MOCK-AC-01.01", "ACME-LOCAL-01.01"}

    composed = result.controls["MOCK-AC-01.01"]
    assert composed.tags.get(_TAG_COMPOSED_FROM) == "mock-source-a"
    assert composed.tags.get(_TAG_ORIGINAL_CONTROL_ID) == "MOCK-AC-01.01"

    inline = result.controls["ACME-LOCAL-01.01"]
    assert inline.tags.get(_TAG_COMPOSED_FROM) == "test-inline-with-compose"
    assert inline.tags.get(_TAG_ORIGINAL_CONTROL_ID) == "ACME-LOCAL-01.01"


# ---------------------------------------------------------------------------
# T026: missing source raises with the slug in the error
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_missing_source_raises(composite_fixtures_dir, fixture_source_loader):
    """A compose block naming an uninstalled slug raises with that slug."""
    cfg = _parse_framework_only(
        _composite_path(composite_fixtures_dir, "missing-source")
    )

    with pytest.raises(CompositionMissingSourceError) as excinfo:
        resolve_composition(cfg, source_loader=fixture_source_loader)

    assert excinfo.value.source == "does-not-exist-impl"
    assert "does-not-exist-impl" in str(excinfo.value)


# ---------------------------------------------------------------------------
# T027: empty compose block rejected at parse time by validator V1.1
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_empty_compose_block_rejected(composite_fixtures_dir):
    """Pydantic validator V1.1 rejects a compose block with no inclusion."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as excinfo:
        _parse_framework_only(
            _composite_path(composite_fixtures_dir, "empty-compose-block")
        )

    # Error message names the offending source slug.
    assert "mock-source-a" in str(excinfo.value)


# ---------------------------------------------------------------------------
# T028: diamond — leaf loaded once via memoization
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_diamond_resolves_once(composite_fixtures_dir, fixture_source_loader):
    """Diamond composition memoizes source loads (R-003) and dedupes outputs.

    Wraps the fixture loader in a counting proxy and asserts each unique
    slug is loaded exactly once across the entire resolution, even though
    ``mock-source-c-leaf`` is reachable both directly and through
    ``mock-source-mid-composite``.
    """
    call_counts: dict[str, int] = {}

    def counting_loader(slug: str):
        call_counts[slug] = call_counts.get(slug, 0) + 1
        return fixture_source_loader(slug)

    result = _resolve_with(
        composite_fixtures_dir, counting_loader, "diamond"
    )

    # Each leaf control appears exactly once
    assert set(result.controls.keys()) == {"LEAF-01.01", "LEAF-02.01"}
    # Each unique source slug was loaded exactly once
    assert call_counts.get("mock-source-mid-composite") == 1
    assert call_counts.get("mock-source-c-leaf") == 1


def _resolve_with(composite_fixtures_dir, loader, name):
    cfg = _parse_framework_only(_composite_path(composite_fixtures_dir, name))
    return resolve_composition(cfg, source_loader=loader)


# ---------------------------------------------------------------------------
# T029: audit pipeline shape unchanged
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_audit_pipeline_unchanged(composite_fixtures_dir, fixture_source_loader):
    """A composite's resolved ``FrameworkConfig`` is shape-identical to a
    non-composite's — same fields populated, ``compose``/``overrides``
    cleared, ``controls`` populated with the resolved flat dict.

    This is a SHAPE-only assertion per F-3; we are NOT checking individual
    audit status (PASS/FAIL/WARN). The fixture sources all use
    unsatisfiable ``file_must_exist`` paths, so any actual audit would
    return FAIL across the board — which is fine for shape checking.
    """
    result = _resolve(
        composite_fixtures_dir, fixture_source_loader, "audit-pipeline"
    )

    # Compose state is fully resolved away (invariant I3.2)
    assert result.compose == []
    assert result.overrides == {}
    assert result.allow_conflicts is False

    # Resolved set: 3 composed + 1 inline
    assert set(result.controls.keys()) == {
        "MOCK-AC-01.01",
        "MOCK-VM-01.01",
        "MOCK-QA-01.01",
        "AUDITPIPE-01.01",
    }

    # Every control has the same ControlConfig shape as a non-composite:
    # `passes`, `name`, `description` populated; provenance under `tags`.
    for cid, ctrl in result.controls.items():
        assert ctrl.name, f"{cid} missing `name`"
        assert ctrl.description, f"{cid} missing `description`"
        assert ctrl.passes is not None and len(ctrl.passes) > 0, (
            f"{cid} missing `passes`"
        )
        assert _TAG_COMPOSED_FROM in ctrl.tags, (
            f"{cid} missing provenance tag"
        )

    # Metadata propagated from the composite itself (not from any source)
    assert result.metadata.name == "test-audit-pipeline"


# ---------------------------------------------------------------------------
# Idempotence (foundational invariant I3.3)
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_resolve_is_idempotent_for_non_composite():
    """``resolve_composition`` short-circuits when there's nothing to resolve."""
    from darnit.config.framework_schema import (
        FrameworkConfig,
        FrameworkMetadata,
    )

    cfg = FrameworkConfig(
        metadata=FrameworkMetadata(
            name="non-composite", display_name="N", version="0.1.0"
        )
    )
    assert resolve_composition(cfg) is cfg


# ---------------------------------------------------------------------------
# Self-cycle smoke (foundational — full F-1 regression lands in US4 / T046b)
# ---------------------------------------------------------------------------


# ---------------------------------------------------------------------------
# US2 — Override application
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_overrides_replace_fields(composite_fixtures_dir, fixture_source_loader):
    """US2 / T033: override replaces the named field only; passes untouched."""
    result = _resolve(
        composite_fixtures_dir, fixture_source_loader, "override-remediation"
    )

    ctrl = result.controls["MOCK-AC-01.01"]
    # Description matches the override
    assert ctrl.description == (
        "ACME's internal description overrides the upstream one."
    )
    # Pass logic untouched — still a single file_must_exist pass with
    # the unsatisfiable fixture path
    assert ctrl.passes is not None
    assert len(ctrl.passes) == 1
    assert ctrl.passes[0].handler == "file_must_exist"


@pytest.mark.unit
def test_overrides_preserve_provenance(composite_fixtures_dir, fixture_source_loader):
    """US2 / T034: provenance tags survive override unchanged.

    Even if the override touches `tags` (or `docs_url` in this fixture),
    the framework-stamped `_composed_from` and `_original_control_id`
    must still identify the original source.
    """
    result = _resolve(
        composite_fixtures_dir,
        fixture_source_loader,
        "override-preserves-provenance",
    )

    ctrl = result.controls["MOCK-AC-01.01"]
    assert ctrl.tags.get(_TAG_COMPOSED_FROM) == "mock-source-a"
    assert ctrl.tags.get(_TAG_ORIGINAL_CONTROL_ID) == "MOCK-AC-01.01"
    # The overridden docs_url field also took effect
    assert ctrl.docs_url == "https://internal.acme.example/runbooks/ac-01-01"


@pytest.mark.unit
def test_orphan_override_raises(composite_fixtures_dir, fixture_source_loader):
    """US2 / T035: override targeting an absent ID raises with that ID."""
    cfg = _parse_framework_only(
        _composite_path(composite_fixtures_dir, "orphan-override")
    )

    with pytest.raises(CompositionOrphanOverrideError) as excinfo:
        resolve_composition(cfg, source_loader=fixture_source_loader)

    assert excinfo.value.orphan_id == "DOES-NOT-EXIST-99.99"
    assert "DOES-NOT-EXIST-99.99" in str(excinfo.value)


@pytest.mark.unit
def test_unknown_field_override_raises(
    composite_fixtures_dir, fixture_source_loader
):
    """US2 / T036: override naming an unknown ControlConfig field raises."""
    cfg = _parse_framework_only(
        _composite_path(composite_fixtures_dir, "unknown-field-override")
    )

    with pytest.raises(CompositionUnknownFieldError) as excinfo:
        resolve_composition(cfg, source_loader=fixture_source_loader)

    assert excinfo.value.field == "bogus_field"
    assert excinfo.value.control_id == "MOCK-AC-01.01"


@pytest.mark.unit
def test_alias_field_names_rejected(composite_fixtures_dir, fixture_source_loader):
    """US2 / T036 sub-test: the 'no friendly aliases' guarantee from F-2.

    A composite author who types `severity` (rather than the real schema
    field name `security_severity`) must hit ``CompositionUnknownFieldError``
    — there are no silent renames.
    """
    cfg = _parse_framework_only(
        _composite_path(composite_fixtures_dir, "alias-field-override")
    )

    with pytest.raises(CompositionUnknownFieldError) as excinfo:
        resolve_composition(cfg, source_loader=fixture_source_loader)

    assert excinfo.value.field == "severity"


@pytest.mark.unit
def test_empty_override_block_rejected(composite_fixtures_dir):
    """US2 / T037: empty override block (no fields) rejected by V2.3."""
    from pydantic import ValidationError

    with pytest.raises(ValidationError) as excinfo:
        _parse_framework_only(
            _composite_path(composite_fixtures_dir, "empty-override")
        )

    # Error message names the at-least-one-field rule
    assert "at least one field" in str(excinfo.value).lower() or "no fields" in str(
        excinfo.value
    ).lower()


# ---------------------------------------------------------------------------
# US3 — Conflict resolution
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_strict_conflict_raises(composite_fixtures_dir, fixture_source_loader):
    """US3 / T040: two compose blocks contributing the same ID raise in strict mode.

    The error names both source slugs in TOML file order
    (``(earlier, later)``), the conflicting control ID, and the message
    surfaces the two opt-out mechanisms so the composite author knows
    how to resolve the conflict.
    """
    cfg = _parse_framework_only(
        _composite_path(composite_fixtures_dir, "strict-conflict")
    )

    with pytest.raises(CompositionConflictError) as excinfo:
        resolve_composition(cfg, source_loader=fixture_source_loader)

    err = excinfo.value
    assert err.control_id == "MOCK-AC-01.01"
    assert err.sources == ("mock-source-a", "mock-source-a-variant")

    rendered = str(err)
    assert "MOCK-AC-01.01" in rendered
    assert "mock-source-a" in rendered
    assert "mock-source-a-variant" in rendered
    # Both opt-out mechanisms are surfaced
    assert "allow_conflicts" in rendered
    assert "overrides" in rendered


@pytest.mark.unit
def test_allow_conflicts_last_wins(
    composite_fixtures_dir, fixture_source_loader, caplog
):
    """US3 / T041: ``allow_conflicts = true`` makes the later block win.

    The LATER ``[[compose]]`` block (TOML file order) overwrites the
    earlier contribution. An INFO log line names both sources and the
    winner. Resolved control's content comes from the later source
    (``mock-source-a-variant``).
    """
    import logging

    caplog.set_level(logging.INFO, logger="darnit.core.composition")

    result = _resolve(
        composite_fixtures_dir, fixture_source_loader, "allow-conflicts-last-wins"
    )

    ctrl = result.controls["MOCK-AC-01.01"]
    # The variant's content wins because it was the later compose block.
    assert "VARIANT" in ctrl.description
    # Provenance also reflects the later source
    assert ctrl.tags.get(_TAG_COMPOSED_FROM) == "mock-source-a-variant"

    # INFO log mentions both sources
    info_lines = [
        rec.message
        for rec in caplog.records
        if rec.levelno == logging.INFO and "MOCK-AC-01.01" in rec.message
    ]
    assert info_lines, "Expected INFO log line on allow_conflicts conflict"
    assert "mock-source-a-variant" in info_lines[0]
    assert "mock-source-a" in info_lines[0]


@pytest.mark.unit
def test_override_resolves_conflict_in_strict_mode(
    composite_fixtures_dir, fixture_source_loader, caplog
):
    """US3 / T042: an explicit override resolves a strict-mode conflict.

    In strict mode (``allow_conflicts = false``), an
    ``[overrides."ID"]`` block targeting the conflicting ID makes
    registration succeed. The override's fields are applied to the
    EARLIEST compose block's contribution (FR-011 + F-11
    clarification). No ``CompositionConflictError`` raised, no INFO log
    emitted.
    """
    import logging

    caplog.set_level(logging.INFO, logger="darnit.core.composition")

    result = _resolve(
        composite_fixtures_dir,
        fixture_source_loader,
        "override-resolves-conflict",
    )

    ctrl = result.controls["MOCK-AC-01.01"]
    # The override's description wins
    assert ctrl.description == (
        "OVERRIDE: the composite author's resolution of the conflict."
    )
    # Provenance points at the EARLIER compose block's source
    # (mock-source-a, the first one to write into resolved[]).
    assert ctrl.tags.get(_TAG_COMPOSED_FROM) == "mock-source-a"
    # The pass logic also comes from the earlier source: that's the path
    # with `DOES_NOT_EXIST.fixture` (variant uses `DOES_NOT_EXIST.variant.fixture`).
    assert ctrl.passes is not None and len(ctrl.passes) == 1
    pass_paths = ctrl.passes[0].model_dump().get("paths", [])
    assert pass_paths == ["DOES_NOT_EXIST.fixture"]

    # No INFO log line on this path — overrides resolve conflicts silently
    info_lines = [
        rec.message
        for rec in caplog.records
        if rec.levelno == logging.INFO and "MOCK-AC-01.01" in rec.message
    ]
    assert not info_lines, (
        f"Expected no INFO log on override-resolves path, got: {info_lines}"
    )


@pytest.mark.unit
def test_override_with_allow_conflicts_still_uses_earliest_base(
    composite_fixtures_dir, fixture_source_loader
):
    """US3 / T042 companion: F-11 mode-independence guarantee.

    Even with ``allow_conflicts = true``, the override's earliest-base
    rule holds. The override layers onto the FIRST compose block's
    contribution, NOT the last-wins one. If this test fails, the
    docs/code consistency captured in F-11 is broken.
    """
    result = _resolve(
        composite_fixtures_dir,
        fixture_source_loader,
        "override-with-allow-conflicts",
    )

    ctrl = result.controls["MOCK-AC-01.01"]
    assert ctrl.description == (
        "OVERRIDE: still wins over allow_conflicts last-wins."
    )
    # Same as the strict-mode case: base comes from the earlier source.
    assert ctrl.tags.get(_TAG_COMPOSED_FROM) == "mock-source-a"
    pass_paths = ctrl.passes[0].model_dump().get("paths", [])
    assert pass_paths == ["DOES_NOT_EXIST.fixture"]


# ---------------------------------------------------------------------------
# US4 — Cycle detection + recursive composition
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_self_cycle_raises(composite_fixtures_dir, fixture_source_loader):
    """US4 / T044: a composite that composes from itself raises with the chain.

    The cycle chain is rendered ``cycle-a → cycle-a`` in the error
    message; the structured ``.chain`` attribute is the same list.
    """
    cfg = _parse_framework_only(
        composite_fixtures_dir / "_sources" / "cycle-a.toml"
    )

    with pytest.raises(CompositionCycleError) as excinfo:
        resolve_composition(cfg, source_loader=fixture_source_loader)

    assert excinfo.value.chain == ["cycle-a", "cycle-a"]
    assert "cycle-a → cycle-a" in str(excinfo.value)


@pytest.mark.unit
def test_two_cycle_raises(composite_fixtures_dir, fixture_source_loader):
    """US4 / T045: A composes B which composes A — raises with the full chain.

    Whichever side loads first becomes the chain root; the test asserts
    on length and end-points rather than a fixed order so it is robust
    against either resolution direction.
    """
    cfg = _parse_framework_only(
        composite_fixtures_dir / "_sources" / "cycle-x.toml"
    )

    with pytest.raises(CompositionCycleError) as excinfo:
        resolve_composition(cfg, source_loader=fixture_source_loader)

    chain = excinfo.value.chain
    assert len(chain) == 3, f"Expected 3-element chain, got: {chain}"
    assert chain[0] == chain[-1], (
        f"Chain should start+end with the same slug: {chain}"
    )
    assert set(chain) == {"cycle-x", "cycle-y"}


@pytest.mark.unit
def test_three_level_chain_resolves(composite_fixtures_dir, fixture_source_loader):
    """US4 / T046: non-cyclic 3-level chain (A → B → leaf) resolves cleanly.

    Critical assertion (FR-018 + FR-015): every resolved control's
    ``_composed_from`` points at the ULTIMATE non-composite source
    (``mock-source-c-leaf``), NOT at the intermediate composite
    (``mock-source-mid-composite``). Provenance traces to the
    originating implementation, never to a middle layer.
    """
    result = _resolve(
        composite_fixtures_dir, fixture_source_loader, "three-level-chain"
    )

    # Leaf's two controls are present
    assert set(result.controls.keys()) == {"LEAF-01.01", "LEAF-02.01"}

    # Provenance traces to the ULTIMATE non-composite source (leaf),
    # not to the intermediate composite.
    for cid, ctrl in result.controls.items():
        assert ctrl.tags.get(_TAG_COMPOSED_FROM) == "mock-source-c-leaf", (
            f"{cid}: _composed_from should point at the leaf, not the "
            f"intermediate composite; got "
            f"{ctrl.tags.get(_TAG_COMPOSED_FROM)!r}"
        )
        assert ctrl.tags.get(_TAG_ORIGINAL_CONTROL_ID) == cid


@pytest.mark.unit
def test_loader_path_cycle_through_public_loader(
    composite_fixtures_dir, monkeypatch
):
    """US4 / T046b: F-1 REGRESSION TEST.

    The canonical regression for the F-1 design fix. Loads a
    composite-of-composite cycle through the PRODUCTION
    ``load_framework_config`` path — not through the injected
    ``fixture_source_loader``. Before the F-1 fix this test would have
    hung indefinitely (each recursive ``load_framework_by_name`` call
    would have started a fresh ``_resolution_stack``); after the fix
    the resolver owns the single shared stack and detects the cycle in
    bounded time.

    The default ``source_loader`` looks slugs up via ``PluginRegistry``,
    which does NOT know about fixture files. We monkey-patch it to
    point at the fixture ``_sources/`` directory so the production
    code path can still find ``loader-cycle-{x,y}.toml``. This is
    deliberately narrow: only ``_default_source_loader`` is patched,
    not ``load_framework_config`` itself.
    """
    import time

    from darnit.config.merger import _parse_framework_only, load_framework_config
    from darnit.core import composition as comp_mod

    sources_dir = composite_fixtures_dir / "_sources"

    def fake_default_loader(slug):
        path = sources_dir / f"{slug}.toml"
        return _parse_framework_only(path) if path.exists() else None

    monkeypatch.setattr(comp_mod, "_default_source_loader", fake_default_loader)
    # ``load_framework_config`` imports the resolver lazily; the patch
    # above is what actually gets called when the resolver's
    # ``source_loader`` defaults at runtime, so no further patching is
    # needed.

    t0 = time.perf_counter()
    with pytest.raises(CompositionCycleError) as excinfo:
        load_framework_config(sources_dir / "loader-cycle-x.toml")
    elapsed = time.perf_counter() - t0

    # Bounded time guarantee — pre-F-1 this would have hung
    assert elapsed < 1.0, f"Cycle detection took {elapsed:.3f}s (expected <1s)"

    # Chain identifies both slugs and starts+ends with the same one
    chain = excinfo.value.chain
    assert chain[0] == chain[-1]
    assert set(chain) == {"loader-cycle-x", "loader-cycle-y"}


# ---------------------------------------------------------------------------
# US5 — Version pinning
# ---------------------------------------------------------------------------


@pytest.mark.unit
def test_version_pin_satisfied(composite_fixtures_dir, fixture_source_loader):
    """US5 / T048: a satisfied PEP 440 constraint resolves normally.

    ``mock-source-a`` is at version 1.5.0; ``>=1.0,<2.0`` matches.
    """
    result = _resolve(
        composite_fixtures_dir, fixture_source_loader, "version-pin-satisfied"
    )

    # The source's 5 controls are all included
    assert len(result.controls) == 5


@pytest.mark.unit
def test_version_pin_violated(composite_fixtures_dir, fixture_source_loader):
    """US5 / T049: a violated PEP 440 constraint raises with details.

    ``mock-source-a`` is at version 1.5.0; ``>=2.0`` is unsatisfiable.
    """
    cfg = _parse_framework_only(
        _composite_path(composite_fixtures_dir, "version-pin-violated")
    )

    with pytest.raises(CompositionVersionMismatchError) as excinfo:
        resolve_composition(cfg, source_loader=fixture_source_loader)

    err = excinfo.value
    assert err.source == "mock-source-a"
    assert err.constraint == ">=2.0"
    assert err.installed == "1.5.0"


@pytest.mark.unit
def test_version_pin_missing_uses_floating(
    composite_fixtures_dir, fixture_source_loader
):
    """US5 / T050: no ``version_constraint`` → resolves against installed version.

    Reuses the ``basic-include-all`` fixture (which has no
    ``version_constraint``) and confirms it resolves cleanly.
    """
    result = _resolve(
        composite_fixtures_dir, fixture_source_loader, "basic-include-all"
    )
    # The source's full 5 controls are included
    assert len(result.controls) == 5
