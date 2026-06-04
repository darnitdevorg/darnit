"""Pytest fixtures shared across tests in ``tests/darnit/``.

Currently scoped to the composition feature (013-plugin-composition).
"""

from __future__ import annotations

from collections.abc import Callable
from pathlib import Path

import pytest

from darnit.config.framework_schema import FrameworkConfig


@pytest.fixture
def composite_fixtures_dir() -> Path:
    """Absolute path to the per-test composite-fixture sources directory.

    Tests load source TOMLs from ``tests/darnit/fixtures/composite/_sources/``
    and composite TOMLs from ``tests/darnit/fixtures/composite/``.
    """
    return Path(__file__).parent / "fixtures" / "composite"


@pytest.fixture
def fixture_source_loader(
    composite_fixtures_dir: Path,
) -> Callable[[str], FrameworkConfig | None]:
    """Return a parse-only ``source_loader`` for composition tests.

    The loader maps a source slug (e.g. ``"mock-source-a"``) to the TOML
    file at ``_sources/<slug>.toml`` and parses it via
    :func:`darnit.config.merger._parse_framework_only`.

    IMPORTANT — the loader MUST be parse-only (F-1 fix). It is intentionally
    routed through ``_parse_framework_only`` rather than
    ``load_framework_config`` so that recursive composite-of-composite source
    loads do NOT re-enter composition with a fresh ``_resolution_stack``.
    Cycle detection (FR-012) and recursive composition (FR-018) both depend
    on the resolver owning the single shared stack.

    Do not switch this back to a resolving loader without explicitly
    documenting why; the F-1 regression test (T046b) relies on parse-only
    semantics here.
    """
    from darnit.config.merger import _parse_framework_only

    sources_dir = composite_fixtures_dir / "_sources"

    def _load(slug: str) -> FrameworkConfig | None:
        path = sources_dir / f"{slug}.toml"
        if not path.exists():
            return None
        return _parse_framework_only(path)

    return _load
