"""Regression tests for license-file discovery (issues #403, #404).

LE-01.01 and LE-03.01 previously used different `discover` lists and
neither accepted the British spelling, so a repository shipping `LICENCE`
failed both controls despite having a valid license file.
"""

from __future__ import annotations

from pathlib import Path

import pytest

from darnit.sieve.models import CheckContext, ControlSpec
from darnit.sieve.orchestrator import SieveOrchestrator

LICENSE_CONTROLS = ("OSPS-LE-01.01", "OSPS-LE-03.01")

MIT_TEXT = """MIT License

Copyright (c) 2026 Example Project

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction.
"""


def _load_control(control_id: str) -> ControlSpec:
    from darnit.config.control_loader import control_from_framework
    from darnit.config.merger import load_framework_by_name

    config = load_framework_by_name("openssf-baseline")
    return control_from_framework(control_id, config.controls[control_id])


def _make_ctx(local_path: Path, control_id: str) -> CheckContext:
    return CheckContext(
        owner="test",
        repo="test-repo",
        local_path=str(local_path),
        default_branch="main",
        control_id=control_id,
    )


@pytest.mark.parametrize("control_id", LICENSE_CONTROLS)
@pytest.mark.parametrize(
    "filename",
    [
        "LICENSE",
        "LICENSE.md",
        "LICENSE.txt",
        "LICENCE",
        "LICENCE.md",
        "LICENCE.txt",
        "COPYING",
        "COPYING.md",
        "COPYING.txt",
        "license",
        "license.md",
        "license.txt",
        "licence",
        "licence.md",
        "licence.txt",
        "copying",
        "copying.md",
        "copying.txt",
    ],
)
def test_license_filename_variants_found(
    tmp_path: Path,
    control_id: str,
    filename: str,
) -> None:
    """Both controls accept US and British spellings, lowercase names, and common suffixes.

    Feature 041: finding the file is evidence; whether it concludes PASS
    depends on the control's step declarations, so this asserts discovery
    (not FAIL, and the file recorded), not the final verdict.
    """
    (tmp_path / filename).write_text(MIT_TEXT, encoding="utf-8")

    control = _load_control(control_id)
    result = SieveOrchestrator(stop_on_llm=False).verify(control, _make_ctx(tmp_path, control_id))

    assert result.status != "FAIL", f"{control_id} failed on {filename}: {result.message}"
    assert result.evidence["relative_path"].lower() == filename.lower()


@pytest.mark.parametrize("control_id", LICENSE_CONTROLS)
def test_missing_license_still_fails(tmp_path: Path, control_id: str) -> None:
    """Broadening the list must not make the controls pass on a repo with
    no license file at all."""
    (tmp_path / "README.md").write_text("# proj\n", encoding="utf-8")

    control = _load_control(control_id)
    result = SieveOrchestrator(stop_on_llm=False).verify(control, _make_ctx(tmp_path, control_id))

    assert result.status != "PASS"


def test_both_controls_share_one_discover_list() -> None:
    """#403: LE-01.01 and LE-03.01 must not drift apart again."""
    from darnit.config.merger import load_framework_by_name

    config = load_framework_by_name("openssf-baseline")
    lists = [config.controls[c].locator.discover for c in LICENSE_CONTROLS]
    assert lists[0] == lists[1]
    assert "LICENCE" in lists[0]
    assert "license" in lists[0]


@pytest.mark.parametrize(
    "filename",
    ["license", "license.md", "licence", "copying"],
)
def test_le_02_01_matches_lowercase_license_files(tmp_path: Path, filename: str) -> None:
    """Issue #717: OSPS-LE-02.01 regex pass detects SPDX identifiers in lowercase license files."""
    (tmp_path / filename).write_text(
        "// SPDX-License-Identifier: MIT\n" + MIT_TEXT,
        encoding="utf-8",
    )

    control = _load_control("OSPS-LE-02.01")
    result = SieveOrchestrator(stop_on_llm=False).verify(control, _make_ctx(tmp_path, "OSPS-LE-02.01"))

    assert result.pass_history, f"No pass history for OSPS-LE-02.01 on {filename}"
    pattern_attempt = result.pass_history[0]
    assert pattern_attempt.result.outcome.value == "pass"
    assert pattern_attempt.result.evidence.get("any_match") is True
