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
    ["LICENSE", "LICENSE.md", "LICENSE.txt", "LICENCE", "LICENCE.md", "LICENCE.txt", "COPYING"],
)
def test_license_filename_variants_pass(
    tmp_path: Path,
    control_id: str,
    filename: str,
) -> None:
    """Both controls accept US and British spellings and common suffixes."""
    (tmp_path / filename).write_text(MIT_TEXT, encoding="utf-8")

    control = _load_control(control_id)
    result = SieveOrchestrator(stop_on_llm=False).verify(control, _make_ctx(tmp_path, control_id))

    assert result.status == "PASS", f"{control_id} failed on {filename}: {result.details}"


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
