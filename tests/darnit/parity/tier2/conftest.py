"""Tier 2 conftest (PR #371 review fix).

Adds the `integration` pytest marker to every test collected under this
directory. Tier 2 tests exercise the coding-agent parity flow (skill
prompt + provider backend + parser), which never satisfies the `unit`
marker's contract. Without the mark, CI's `-m unit / -m integration`
split silently deselected the entire suite.
"""

from __future__ import annotations

import pytest


def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
    integration_mark = pytest.mark.integration
    for item in items:
        item.add_marker(integration_mark)
