"""Fixtures for feature 040 tests."""

from __future__ import annotations

from collections.abc import Generator

import pytest


@pytest.fixture(autouse=True)
def _restore_control_registry() -> Generator[None, None, None]:
    """Audits here register framework controls globally; keep them out of later tests."""
    from darnit.sieve.registry import get_control_registry
    from darnit.tools import audit

    registry = get_control_registry()
    saved_specs = dict(registry._specs)
    saved_registered = set(audit._toml_controls_registered)
    yield
    registry._specs.clear()
    registry._specs.update(saved_specs)
    audit._toml_controls_registered.clear()
    audit._toml_controls_registered.update(saved_registered)
