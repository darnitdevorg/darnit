"""Shared fixtures for threat_model tests.

By default, ``discover_all`` invokes the real Opengrep binary on every
call, adding ~2.5s per invocation. Most tests don't need real Opengrep
results, so we auto-mock the enrichment step to return "binary not
installed" for tests that don't opt into the real binary.

Tests that explicitly test Opengrep integration should use the
``real_opengrep`` marker: ``@pytest.mark.real_opengrep``.
"""
from __future__ import annotations

from unittest.mock import patch

import pytest

try:
    import tree_sitter_language_pack  # noqa: F401
except ImportError:
    collect_ignore_glob = ["*.py"]
else:
    from darnit_baseline.threat_model.opengrep_runner import OpengrepResult

    @pytest.fixture(autouse=True)
    def _mock_opengrep_enrichment(request: pytest.FixtureRequest):
        """Auto-mock the Opengrep enrichment step unless the test opts in
        to the real binary via ``@pytest.mark.real_opengrep``."""
        if "real_opengrep" in {m.name for m in request.node.iter_markers()}:
            yield
            return

        noop_result = OpengrepResult(
            available=False,
            degraded_reason="mocked for test speed",
        )
        with patch(
            "darnit_baseline.threat_model.ts_discovery._run_opengrep_enrichment",
            return_value=noop_result,
        ):
            yield
