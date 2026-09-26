"""Fixtures for operator configuration tests."""

from __future__ import annotations

import pytest


@pytest.fixture(autouse=True)
def _no_cli_logging_setup(monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep ``darnit.cli.main`` from replacing the darnit logger's default NullHandler for later tests."""
    monkeypatch.setattr("darnit.cli.configure_logging", lambda level: None)
