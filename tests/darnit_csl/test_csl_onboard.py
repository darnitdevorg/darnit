"""Check that onboarding asks for choices instead of guessing them."""

from unittest.mock import Mock

import pytest

from scripts import csl_onboard


def test_missing_choices(monkeypatch, capsys):
    commands = Mock()
    monkeypatch.setattr(csl_onboard, "sh", commands)
    monkeypatch.setattr("sys.argv", [
        "csl_onboard.py", "--repo", "example/project", "--scope-file", "scope.md",
    ])

    with pytest.raises(SystemExit) as error:
        csl_onboard.main()

    assert error.value.code == 2
    output = capsys.readouterr().err
    assert "remediation requires explicit choices for: --code-license, --governance-mode, --coc-policy, --spec-name" in output
    assert "Example values only" in output
    commands.assert_not_called()


def test_audit_only_needs_no_choices(monkeypatch, tmp_path):
    (tmp_path / "project").mkdir()
    monkeypatch.setattr(csl_onboard, "sh", lambda *args, **kwargs: "")
    monkeypatch.setattr(csl_onboard, "audit", lambda path: {})
    monkeypatch.setattr("sys.argv", [
        "csl_onboard.py", "--repo", "example/project", "--workdir", str(tmp_path),
        "--audit-only", "--scope-file", "not-read.md",
    ])

    assert csl_onboard.main() == 0
    assert (tmp_path / "project-scope.md").exists()


def test_supplied_choices_reach_tool(monkeypatch, tmp_path):
    from darnit_csl import mcp_tools

    (tmp_path / "project").mkdir()
    scope = tmp_path / "scope.md"
    scope.write_text("This specification defines an interoperable message format.")
    received = {}

    async def remediate(**kwargs):
        received.update(kwargs)
        return "Preview complete"

    monkeypatch.setattr(mcp_tools, "remediate_community_spec", remediate)
    monkeypatch.setattr(csl_onboard, "sh", lambda *args, **kwargs: "")
    monkeypatch.setattr(csl_onboard, "audit", lambda path: {})
    monkeypatch.setattr(csl_onboard, "scan_placeholders", lambda path: [])
    monkeypatch.setattr("sys.argv", [
        "csl_onboard.py", "--repo", "example/project", "--workdir", str(tmp_path),
        "--scope-file", str(scope), "--code-license", "MIT", "--governance-mode", "umbrella",
        "--coc-policy", "org", "--spec-name", "My Specification",
    ])

    assert csl_onboard.main() == 0
    assert received["code_license"] == "MIT"
    assert received["governance_mode"] == "umbrella"
    assert received["coc_policy"] == "org"
    assert received["spec_name"] == "My Specification"
