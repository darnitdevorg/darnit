"""The onboarding driver must not supply choices the user omitted."""

import importlib.util
from pathlib import Path
from unittest.mock import AsyncMock, Mock

import pytest

CHOICES = {
    "--code-license": "MIT",
    "--governance-mode": "umbrella",
    "--coc-policy": "org",
    "--spec-name": "Explicit Specification Name",
}


@pytest.fixture
def driver(monkeypatch):
    path = Path(__file__).resolve().parents[2] / "scripts" / "csl_onboard.py"
    spec = importlib.util.spec_from_file_location("csl_onboard", path)
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    monkeypatch.setattr(module, "sh", Mock(return_value="existing branch"))
    monkeypatch.setattr(module, "audit", Mock(return_value={}))
    return module


def args(tmp_path, choices):
    argv = ["csl_onboard.py", "--repo", "example/project", "--workdir", str(tmp_path)]
    for flag, value in choices.items():
        argv.extend([flag, value])
    return argv


@pytest.mark.parametrize("omitted", CHOICES)
def test_missing_choice_stops_before_repository_operations(driver, monkeypatch, tmp_path, capsys, omitted):
    choices = {flag: value for flag, value in CHOICES.items() if flag != omitted}
    monkeypatch.setattr("sys.argv", args(tmp_path, choices) + ["--scope-file", "not-read.md"])

    with pytest.raises(SystemExit) as error:
        driver.main()

    assert error.value.code == 2
    assert f"remediation requires explicit choices for: {omitted}" in capsys.readouterr().err
    driver.sh.assert_not_called()
    driver.audit.assert_not_called()
    assert list(tmp_path.iterdir()) == []


def test_reports_all_missing_choices_together(driver, monkeypatch, tmp_path, capsys):
    monkeypatch.setattr("sys.argv", args(tmp_path, {}) + ["--scope-file", "not-read.md"])

    with pytest.raises(SystemExit):
        driver.main()

    output = capsys.readouterr().err
    assert "remediation requires explicit choices for:" in output
    assert "Example values only — choose what fits your project:" in output
    assert '--code-license MIT --governance-mode csl --coc-policy csl --spec-name "My Specification"' in output
    for flag in CHOICES:
        assert flag in output
    driver.sh.assert_not_called()


def test_blank_specification_name_does_not_fall_back_to_repository_name(driver, monkeypatch, tmp_path, capsys):
    choices = {**CHOICES, "--spec-name": "   "}
    monkeypatch.setattr("sys.argv", args(tmp_path, choices) + ["--scope-file", "not-read.md"])

    with pytest.raises(SystemExit):
        driver.main()

    assert "--spec-name" in capsys.readouterr().err
    driver.sh.assert_not_called()


@pytest.mark.parametrize("extra", [[], ["--audit-only", "--scope-file", "not-read.md"]])
def test_initial_audit_does_not_require_remediation_choices(driver, monkeypatch, tmp_path, extra):
    (tmp_path / "project").mkdir()
    monkeypatch.setattr("sys.argv", args(tmp_path, {}) + extra)

    assert driver.main() == 0

    driver.audit.assert_called_once()
    assert (tmp_path / "project-scope.md").exists()


def test_explicit_choices_are_forwarded_unchanged(driver, monkeypatch, tmp_path):
    from darnit_csl import mcp_tools

    (tmp_path / "project").mkdir()
    scope = tmp_path / "scope.md"
    scope.write_text("This working group specifies an interoperable message format.")
    remediate = AsyncMock(return_value="Preview complete")
    monkeypatch.setattr(mcp_tools, "remediate_community_spec", remediate)
    monkeypatch.setattr(driver, "scan_placeholders", lambda path: [])
    monkeypatch.setattr("sys.argv", args(tmp_path, CHOICES) + ["--scope-file", str(scope)])

    assert driver.main() == 0

    remediate.assert_awaited_once()
    for flag, value in CHOICES.items():
        assert remediate.call_args.kwargs[flag[2:].replace("-", "_")] == value
