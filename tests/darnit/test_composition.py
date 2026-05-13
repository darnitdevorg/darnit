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
    CompositionMissingSourceError,
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


@pytest.mark.unit
def test_self_cycle_in_stack_raises():
    """``resolve_composition`` detects when its slug is already on the stack.

    Full F-1 regression (via the public ``load_framework_config`` path)
    lands in US4 / T046b; this is the foundational smoke that the stack
    check itself fires.
    """
    from darnit.config.framework_schema import (
        ComposeBlock,
        FrameworkConfig,
        FrameworkMetadata,
    )
    from darnit.core.composition import CompositionCycleError

    cfg = FrameworkConfig(
        metadata=FrameworkMetadata(name="cycle-a", display_name="A", version="0.1"),
        compose=[ComposeBlock(source="x", include_all=True)],
    )
    with pytest.raises(CompositionCycleError) as excinfo:
        resolve_composition(
            cfg,
            source_loader=lambda _: None,
            _resolution_stack=["cycle-a"],
        )
    assert excinfo.value.chain == ["cycle-a", "cycle-a"]
