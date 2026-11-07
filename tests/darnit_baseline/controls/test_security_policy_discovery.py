"""Regression tests for security policy file discovery (issue #717).

OSPS-VM-01.01, OSPS-VM-02.01, OSPS-VM-03.01, and STAGE1-REF-SECURITY-01
previously only looked for uppercase variants (SECURITY.md, .github/SECURITY.md,
docs/SECURITY.md), missing lowercase file names that GitHub recognizes (such
as security.md, .github/security.md, and docs/security.md).
"""

from __future__ import annotations

from pathlib import Path

import pytest

from darnit.sieve.models import CheckContext, ControlSpec
from darnit.sieve.orchestrator import SieveOrchestrator

SECURITY_POLICY_CONTROLS = (
    "OSPS-VM-01.01",
    "OSPS-VM-02.01",
    "OSPS-VM-03.01",
    "STAGE1-REF-SECURITY-01",
)

SECURITY_FILENAMES = (
    "SECURITY.md",
    "security.md",
    ".github/SECURITY.md",
    ".github/security.md",
    "docs/SECURITY.md",
    "docs/security.md",
)

SECURITY_POLICY_TEXT = """# Security Policy

## Reporting a Vulnerability

Please report vulnerabilities by email to security@example.com.
We will acknowledge receipt within 48 hours and provide a timeline for fixes.
We follow a 90-day coordinated disclosure process.
"""

MIT_LICENSE_TEXT = """MIT License

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


@pytest.mark.parametrize("filename", SECURITY_FILENAMES)
def test_vm_02_01_discovers_security_policy_variants(tmp_path: Path, filename: str) -> None:
    """Issue #717: OSPS-VM-02.01 discovers all casing and location variants."""
    file_path = tmp_path / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(SECURITY_POLICY_TEXT, encoding="utf-8")

    control = _load_control("OSPS-VM-02.01")
    result = SieveOrchestrator(stop_on_llm=False).verify(control, _make_ctx(tmp_path, "OSPS-VM-02.01"))

    assert "None of the required files found" not in (result.message or "")
    assert result.status != "FAIL", f"OSPS-VM-02.01 failed on {filename}: {result.message}"
    assert result.evidence.get("relative_path") or result.evidence.get("found_file")


@pytest.mark.parametrize("filename", SECURITY_FILENAMES)
def test_stage1_ref_security_01_discovers_security_policy_variants(tmp_path: Path, filename: str) -> None:
    """Issue #717: STAGE1-REF-SECURITY-01 dispositive file_exists finds all variants."""
    file_path = tmp_path / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(SECURITY_POLICY_TEXT, encoding="utf-8")

    control = _load_control("STAGE1-REF-SECURITY-01")
    result = SieveOrchestrator(stop_on_llm=False).verify(control, _make_ctx(tmp_path, "STAGE1-REF-SECURITY-01"))

    assert "None of the required files found" not in (result.message or "")
    assert result.status != "FAIL", f"STAGE1-REF-SECURITY-01 failed on {filename}: {result.message}"


@pytest.mark.parametrize("filename", SECURITY_FILENAMES)
def test_vm_01_01_pattern_and_discover_variants(tmp_path: Path, filename: str) -> None:
    """Issue #717: OSPS-VM-01.01 locator and pattern passes find all variants."""
    file_path = tmp_path / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(SECURITY_POLICY_TEXT, encoding="utf-8")

    control = _load_control("OSPS-VM-01.01")
    result = SieveOrchestrator(stop_on_llm=False).verify(control, _make_ctx(tmp_path, "OSPS-VM-01.01"))

    assert "None of the required files found" not in (result.message or "")
    # The pattern pass matches disclosure & process keywords
    assert result.status != "FAIL", f"OSPS-VM-01.01 failed on {filename}: {result.message}"


@pytest.mark.parametrize("filename", SECURITY_FILENAMES)
def test_vm_03_01_pattern_and_discover_variants(tmp_path: Path, filename: str) -> None:
    """Issue #717: OSPS-VM-03.01 locator and pattern passes find all variants."""
    file_path = tmp_path / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(SECURITY_POLICY_TEXT, encoding="utf-8")

    control = _load_control("OSPS-VM-03.01")
    result = SieveOrchestrator(stop_on_llm=False).verify(control, _make_ctx(tmp_path, "OSPS-VM-03.01"))

    assert "None of the required files found" not in (result.message or "")
    assert result.status != "FAIL", f"OSPS-VM-03.01 failed on {filename}: {result.message}"


def test_missing_security_policy_fails(tmp_path: Path) -> None:
    """A repository without a security policy must still fail."""
    (tmp_path / "README.md").write_text("# Test Repo\n", encoding="utf-8")

    for control_id in ("OSPS-VM-02.01", "STAGE1-REF-SECURITY-01"):
        control = _load_control(control_id)
        result = SieveOrchestrator(stop_on_llm=False).verify(control, _make_ctx(tmp_path, control_id))
        assert result.status == "FAIL", f"{control_id} should fail when no security policy exists"
        assert "None of the required files found" in (result.message or "")


def test_sindresorhus_slash_regression(tmp_path: Path) -> None:
    """Issue #717 regression: sindresorhus/slash has root 'license' and '.github/security.md'.

    Neither should fail with 'None of the required files found'.
    """
    (tmp_path / "license").write_text(
        "// SPDX-License-Identifier: MIT\n" + MIT_LICENSE_TEXT,
        encoding="utf-8",
    )
    gh_dir = tmp_path / ".github"
    gh_dir.mkdir(parents=True, exist_ok=True)
    (gh_dir / "security.md").write_text(SECURITY_POLICY_TEXT, encoding="utf-8")

    orchestrator = SieveOrchestrator(stop_on_llm=False)

    for control_id in ("OSPS-LE-01.01", "OSPS-LE-03.01", "OSPS-VM-02.01", "STAGE1-REF-SECURITY-01"):
        control = _load_control(control_id)
        result = orchestrator.verify(control, _make_ctx(tmp_path, control_id))
        assert "None of the required files found" not in (result.message or ""), (
            f"{control_id} failed to discover file on sindresorhus/slash layout: {result.message}"
        )
        assert result.status != "FAIL", (
            f"{control_id} unexpectedly failed on sindresorhus/slash layout: {result.message}"
        )


def test_security_contact_hint_sources_include_lowercase() -> None:
    """Issue #717: context.security_contact hint_sources includes lowercase variants."""
    from darnit.config.merger import load_framework_by_name

    config = load_framework_by_name("openssf-baseline")
    hint_sources = config.context.definitions["security_contact"].hint_sources
    assert "security.md" in hint_sources
    assert ".github/security.md" in hint_sources
    assert "docs/security.md" in hint_sources


@pytest.mark.parametrize("filename", SECURITY_FILENAMES)
def test_vm_05_01_pattern_matches_security_policy_variants(tmp_path: Path, filename: str) -> None:
    """OSPS-VM-05.01 pattern pass finds SCA policy across casing and directory variants."""
    file_path = tmp_path / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        "# Security Policy\n\nDependencies and SCA findings are remediated promptly.\n",
        encoding="utf-8",
    )

    control = _load_control("OSPS-VM-05.01")
    result = SieveOrchestrator(stop_on_llm=False).verify(control, _make_ctx(tmp_path, "OSPS-VM-05.01"))
    assert result.pass_history
    assert result.pass_history[0].result.outcome.value == "pass"


@pytest.mark.parametrize("filename", SECURITY_FILENAMES)
def test_vm_06_01_pattern_matches_security_policy_variants(tmp_path: Path, filename: str) -> None:
    """OSPS-VM-06.01 pattern pass finds SAST policy across casing and directory variants."""
    file_path = tmp_path / filename
    file_path.parent.mkdir(parents=True, exist_ok=True)
    file_path.write_text(
        "# Security Policy\n\nSAST findings are remediated promptly.\n",
        encoding="utf-8",
    )

    control = _load_control("OSPS-VM-06.01")
    result = SieveOrchestrator(stop_on_llm=False).verify(control, _make_ctx(tmp_path, "OSPS-VM-06.01"))
    assert result.pass_history
    assert result.pass_history[0].result.outcome.value == "pass"
