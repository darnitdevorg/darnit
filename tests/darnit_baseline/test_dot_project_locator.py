"""Tests for dot-project locator configuration and mappings (issue #502).

Ensures OSPS-DO-02.01 ("Document bug reporting process") does not resolve through
security.policy since upstream CNCF dot-project schema has no bug-reporting field.
"""

from __future__ import annotations

import tomllib
from pathlib import Path

import pytest

from darnit_baseline.config.mappings import CONTROL_REFERENCE_MAPPING

REPO_ROOT = Path(__file__).resolve().parents[2]
BASELINE_TOML = REPO_ROOT / "packages" / "darnit-baseline" / "src" / "darnit_baseline" / "openssf-baseline.toml"


@pytest.mark.unit
def test_osps_do_02_01_locator_has_no_project_path():
    """OSPS-DO-02.01 locator must not define project_path (issue #502)."""
    with open(BASELINE_TOML, "rb") as f:
        data = tomllib.load(f)

    control = data["controls"]["OSPS-DO-02.01"]
    locator = control.get("locator", {})

    assert "project_path" not in locator, (
        f"OSPS-DO-02.01 locator should not have project_path, found: {locator.get('project_path')}"
    )
    # Ensure discover globs are retained
    assert "discover" in locator
    assert any("bug" in glob_pattern for glob_pattern in locator["discover"])


@pytest.mark.unit
def test_control_reference_mapping_excludes_osps_do_02_01():
    """CONTROL_REFERENCE_MAPPING must not map OSPS-DO-02.01 to security.policy (issue #502)."""
    assert "OSPS-DO-02.01" not in CONTROL_REFERENCE_MAPPING
