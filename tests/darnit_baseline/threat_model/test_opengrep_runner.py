"""Tests for darnit_baseline.threat_model.opengrep_runner.

Uses monkeypatched ``shutil.which`` and ``subprocess.run`` to exercise every
branch of the contract in
``specs/010-threat-model-ast/contracts/opengrep-runner-contract.md``.
"""

from __future__ import annotations

import json
import subprocess
from pathlib import Path
from typing import Any

import pytest

from darnit_baseline.threat_model import opengrep_runner
from darnit_baseline.threat_model.opengrep_runner import OpengrepResult, run_opengrep


class _FakeCompleted:
    def __init__(
        self,
        returncode: int = 0,
        stdout: str = "{}",
        stderr: str = "",
    ) -> None:
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture
def rules_dir(tmp_path: Path) -> Path:
    d = tmp_path / "rules"
    d.mkdir()
    (d / "rule.yaml").write_text("rules:\n  - id: x\n    pattern: foo\n")
    return d


@pytest.fixture
def target(tmp_path: Path) -> Path:
    t = tmp_path / "src"
    t.mkdir()
    (t / "a.py").write_text("x = 1\n")
    return t


def _patch_which(monkeypatch: pytest.MonkeyPatch, answer: str | None) -> None:
    def fake_which(name: str) -> str | None:
        if answer is None:
            return None
        if name in ("opengrep", "semgrep") and name == answer:
            return f"/usr/local/bin/{name}"
        return None

    monkeypatch.setattr(opengrep_runner.shutil, "which", fake_which)


def test_missing_binary_returns_unavailable(
    monkeypatch: pytest.MonkeyPatch, target: Path, rules_dir: Path
) -> None:
    _patch_which(monkeypatch, None)
    result = run_opengrep(target=target, rules_dir=rules_dir)
    assert result.available is False
    assert "not installed" in (result.degraded_reason or "")
    assert result.findings == []
    assert result.binary_used is None


def test_semgrep_fallback_when_opengrep_missing(
    monkeypatch: pytest.MonkeyPatch, target: Path, rules_dir: Path
) -> None:
    _patch_which(monkeypatch, "semgrep")

    def fake_run(argv: list[str], **kwargs: Any) -> _FakeCompleted:
        if argv[1] == "--version":
            return _FakeCompleted(stdout="semgrep 1.0.0\n")
        return _FakeCompleted(
            stdout=json.dumps({"results": [], "errors": []}), returncode=0
        )

    monkeypatch.setattr(opengrep_runner.subprocess, "run", fake_run)
    result = run_opengrep(target=target, rules_dir=rules_dir)
    assert result.available is True
    assert result.binary_used == "semgrep"
    assert result.version == "semgrep 1.0.0"


def test_missing_rules_dir_returns_degraded(
    monkeypatch: pytest.MonkeyPatch, target: Path, tmp_path: Path
) -> None:
    _patch_which(monkeypatch, "opengrep")

    def fake_run(argv: list[str], **kwargs: Any) -> _FakeCompleted:
        return _FakeCompleted(stdout="opengrep 1.6.0\n")

    monkeypatch.setattr(opengrep_runner.subprocess, "run", fake_run)
    missing = tmp_path / "no_rules"
    result = run_opengrep(target=target, rules_dir=missing)
    assert result.available is True
    assert "rules directory not found" in (result.degraded_reason or "")


def test_successful_scan_exit_0_with_findings(
    monkeypatch: pytest.MonkeyPatch, target: Path, rules_dir: Path
) -> None:
    _patch_which(monkeypatch, "opengrep")

    sample_findings = [
        {
            "check_id": "test.rule",
            "path": str(target / "a.py"),
            "start": {"line": 1, "col": 1},
            "end": {"line": 1, "col": 10},
            "extra": {"message": "m", "severity": "ERROR", "lines": "x = 1"},
        }
    ]

    def fake_run(argv: list[str], **kwargs: Any) -> _FakeCompleted:
        if argv[1] == "--version":
            return _FakeCompleted(stdout="opengrep 1.6.0\n")
        return _FakeCompleted(
            stdout=json.dumps({"results": sample_findings, "errors": []}),
            returncode=0,
        )

    monkeypatch.setattr(opengrep_runner.subprocess, "run", fake_run)
    result = run_opengrep(target=target, rules_dir=rules_dir)
    assert result.available is True
    assert result.degraded_reason is None
    assert len(result.findings) == 1
    assert result.findings[0]["check_id"] == "test.rule"
    assert result.binary_used == "opengrep"
    assert result.version == "opengrep 1.6.0"
    assert result.scan_duration_s is not None


def test_exit_0_with_rule_schema_errors_surfaces_as_degraded(
    monkeypatch: pytest.MonkeyPatch, target: Path, rules_dir: Path
) -> None:
    """The critical invariant: errors[] must be inspected even on exit 0."""
    _patch_which(monkeypatch, "opengrep")

    sample_errors = [
        {
            "type": "InvalidRuleSchemaError",
            "long_msg": "One of these properties is missing: 'message'",
        }
    ]

    def fake_run(argv: list[str], **kwargs: Any) -> _FakeCompleted:
        if argv[1] == "--version":
            return _FakeCompleted(stdout="opengrep 1.6.0\n")
        return _FakeCompleted(
            stdout=json.dumps({"results": [], "errors": sample_errors}),
            returncode=0,
        )

    monkeypatch.setattr(opengrep_runner.subprocess, "run", fake_run)
    result = run_opengrep(target=target, rules_dir=rules_dir)
    assert result.available is True
    assert result.rule_errors == sample_errors
    assert "rule-schema error" in (result.degraded_reason or "")


def test_exit_2_scan_failure(
    monkeypatch: pytest.MonkeyPatch, target: Path, rules_dir: Path
) -> None:
    _patch_which(monkeypatch, "opengrep")

    def fake_run(argv: list[str], **kwargs: Any) -> _FakeCompleted:
        if argv[1] == "--version":
            return _FakeCompleted(stdout="opengrep 1.6.0\n")
        return _FakeCompleted(returncode=2, stdout="", stderr="fatal: something")

    monkeypatch.setattr(opengrep_runner.subprocess, "run", fake_run)
    result = run_opengrep(target=target, rules_dir=rules_dir)
    assert result.available is True
    assert result.findings == []
    assert "exit 2" in (result.degraded_reason or "")
    assert "fatal" in (result.degraded_reason or "")


def test_malformed_json_on_stdout(
    monkeypatch: pytest.MonkeyPatch, target: Path, rules_dir: Path
) -> None:
    _patch_which(monkeypatch, "opengrep")

    def fake_run(argv: list[str], **kwargs: Any) -> _FakeCompleted:
        if argv[1] == "--version":
            return _FakeCompleted(stdout="opengrep 1.6.0\n")
        return _FakeCompleted(stdout="not-json-at-all", returncode=0)

    monkeypatch.setattr(opengrep_runner.subprocess, "run", fake_run)
    result = run_opengrep(target=target, rules_dir=rules_dir)
    assert result.available is True
    assert "malformed JSON" in (result.degraded_reason or "")


def test_timeout_is_captured(
    monkeypatch: pytest.MonkeyPatch, target: Path, rules_dir: Path
) -> None:
    _patch_which(monkeypatch, "opengrep")

    def fake_run(argv: list[str], **kwargs: Any) -> _FakeCompleted:
        if argv[1] == "--version":
            return _FakeCompleted(stdout="opengrep 1.6.0\n")
        raise subprocess.TimeoutExpired(cmd=argv, timeout=1.0)

    monkeypatch.setattr(opengrep_runner.subprocess, "run", fake_run)
    result = run_opengrep(target=target, rules_dir=rules_dir, timeout_s=1)
    assert result.available is True
    assert "timed out" in (result.degraded_reason or "")
    assert result.scan_duration_s is not None


def test_os_error_on_start(
    monkeypatch: pytest.MonkeyPatch, target: Path, rules_dir: Path
) -> None:
    _patch_which(monkeypatch, "opengrep")

    def fake_run(argv: list[str], **kwargs: Any) -> _FakeCompleted:
        if argv[1] == "--version":
            return _FakeCompleted(stdout="opengrep 1.6.0\n")
        raise OSError("permission denied")

    monkeypatch.setattr(opengrep_runner.subprocess, "run", fake_run)
    result = run_opengrep(target=target, rules_dir=rules_dir)
    assert result.available is True
    assert "failed to start" in (result.degraded_reason or "")


def test_opengrep_result_is_frozen() -> None:
    result = OpengrepResult(available=True, findings=[], rule_errors=[])
    with pytest.raises((AttributeError, Exception)):
        result.available = False  # type: ignore[misc]


def test_clean_opengrep_check_id() -> None:
    """Issue #776: Opengrep prefixes the --config path to check_id.
    clean_opengrep_check_id must strip install path and preserve clean rule id."""
    from darnit_baseline.threat_model.opengrep_runner import clean_opengrep_check_id

    # macOS / Linux dotted paths
    mac_id = "Users.alice..local.share.virtualenvs.darnit-baseline.src.darnit_baseline.threat_model.opengrep_rules.darnit.entry.flask-route"
    assert clean_opengrep_check_id(mac_id) == "darnit.entry.flask-route"

    linux_id = "home.bob..local.share.pipx.venvs.darnit.packages.darnit_baseline.threat_model.opengrep_rules.darnit.datastore.sqlite"
    assert clean_opengrep_check_id(linux_id) == "darnit.datastore.sqlite"

    # Windows paths
    win_id = "C:.Users.carol.AppData.Local.darnit.threat_model.opengrep_rules.darnit.taint.external-input-to-subprocess"
    assert clean_opengrep_check_id(win_id) == "darnit.taint.external-input-to-subprocess"

    # Slash-separated paths
    slash_id = "/home/dave/.local/share/darnit/opengrep_rules/darnit.entry.fastapi-route"
    assert clean_opengrep_check_id(slash_id) == "darnit.entry.fastapi-route"

    # Dotted path with YAML filename intermediate
    yaml_id = "Users.eve..local.share.opengrep_rules.entry_points.darnit.entry.flask-route"
    assert clean_opengrep_check_id(yaml_id) == "darnit.entry.flask-route"

    # Already clean or custom rule id
    assert clean_opengrep_check_id("darnit.entry.flask-route") == "darnit.entry.flask-route"
    assert clean_opengrep_check_id("test.rule") == "test.rule"
    assert clean_opengrep_check_id("") == ""

