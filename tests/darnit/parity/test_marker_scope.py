"""Regression guard for issue #395.

Both the tier1 and tier2 conftests contribute a
``pytest_collection_modifyitems`` hook that adds the ``integration``
marker. Pytest passes the FULL workspace item list to every hook, so
without an explicit scope check the hook would silently mark unrelated
tests -- for example, the ``@pytest.mark.upstream`` CNCF-drift canary
at ``tests/darnit/context/test_dot_project_upstream.py`` would end up
selected under ``-m integration`` and block PR CI on unrelated
upstream churn.

The fix scopes each hook to items under its own conftest directory.
This test locks that behavior in place by invoking pytest in a
subprocess with ``-m integration --collect-only`` targeted at
`test_dot_project_upstream.py` (which carries only the ``upstream``
marker) and asserting zero tests are collected.
"""

from __future__ import annotations

import subprocess
import sys
from pathlib import Path

import pytest

_REPO_ROOT = Path(__file__).resolve().parents[3]
_UPSTREAM_TEST_FILE = (
    _REPO_ROOT
    / "tests"
    / "darnit"
    / "context"
    / "test_dot_project_upstream.py"
)


@pytest.mark.unit
def test_upstream_only_tests_are_not_collected_under_integration():
    """`-m integration` MUST NOT pick up `@pytest.mark.upstream`-only tests.

    If either parity conftest regresses and re-broadens its
    modify_items hook, this test will fail because the collect-only
    output will show more than zero collected items.
    """
    if not _UPSTREAM_TEST_FILE.exists():
        pytest.skip("upstream-marker canary test file not present")

    proc = subprocess.run(
        [
            sys.executable,
            "-m",
            "pytest",
            str(_UPSTREAM_TEST_FILE),
            "-m",
            "integration",
            "--collect-only",
            "-q",
        ],
        cwd=str(_REPO_ROOT),
        capture_output=True,
        text=True,
    )
    output = proc.stdout + proc.stderr
    assert "no tests collected" in output, (
        "Expected `-m integration` to deselect every test in the "
        "upstream-marker canary file, but pytest reported otherwise:\n\n"
        + output
    )
