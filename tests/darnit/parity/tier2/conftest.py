"""Tier 2 conftest (PR #371 review fix).

Adds the `integration` pytest marker to every test collected under this
directory. Tier 2 tests exercise the coding-agent parity flow (skill
prompt + provider backend + parser), which never satisfies the `unit`
marker's contract. Without the mark, CI's `-m unit / -m integration`
split silently deselected the entire suite.
"""

from __future__ import annotations

from pathlib import Path

import pytest

_CONFTEST_DIR = Path(__file__).parent.resolve()


def pytest_collection_modifyitems(config: pytest.Config, items: list) -> None:
    """Mark tier2 items as `integration`.

    The `items` list pytest passes here contains EVERY collected test
    in the workspace, not just items under this conftest. Only mark
    items whose file path is under ``_CONFTEST_DIR`` -- otherwise this
    hook silently applies the `integration` marker to unrelated tests
    (see issue #395).
    """
    integration_mark = pytest.mark.integration
    for item in items:
        try:
            item_path = Path(str(item.fspath)).resolve()
        except (OSError, ValueError):
            continue
        if _CONFTEST_DIR == item_path or _CONFTEST_DIR in item_path.parents:
            item.add_marker(integration_mark)
