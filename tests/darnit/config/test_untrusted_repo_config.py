"""A repository's own .baseline.toml is untrusted input.

The audited repository is chosen by the operator, but its contents are
controlled by whoever can write to it -- any contributor to an org being
swept by audit_org, or the author of a fork pull request audited in CI.
Nothing it contains may change what darnit executes, which servers or
adapters it trusts, or which framework definition it loads. Only scope
declarations (per-control status and reason) are honored unless the
operator explicitly opts in.
"""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from darnit.config import merger
from darnit.config.merger import load_user_config

EVIL = """
version = "1.0"
extends = "./evil-framework.toml"

[plugins]
allow_unsigned = true
trusted_publishers = ["https://github.com/attacker"]

[adapters.evil]
type = "command"
command = "sh"

[mcp_servers.scanner]
command = ["sh", "-c", "id"]

[stores.report]
backend = "filesystem"

[control_groups.all]
controls = ["OSPS-DO-01.01"]

[control_groups.all.check]
adapter = "evil"

[controls."OSPS-DO-01.01"]
passes = [ { handler = "exec", command = ["sh", "-c", "echo pwned"] } ]
config = { anything = true }

[controls."OSPS-DO-01.01".check]
adapter = "evil"
handler = "run"

[controls."OSPS-DO-01.01".remediation]
config = { command = "sh" }

[controls."OSPS-VM-02.01"]
status = "n/a"
reason = "we have no vulnerability process"

[controls."CUSTOM-01"]
name = "custom"
level = 1
domain = "XX"
passes = [ { handler = "exec", command = ["true"] } ]
"""


def _write(tmp_path: Path, text: str) -> Path:
    (tmp_path / ".baseline.toml").write_text(text, encoding="utf-8")
    return tmp_path


class TestUntrustedByDefault:
    @pytest.mark.unit
    def test_pass_override_is_ignored(self, tmp_path: Path) -> None:
        user = load_user_config(_write(tmp_path, EVIL))
        override = user.get_control_override("OSPS-DO-01.01")
        assert override is None or not override.passes

    @pytest.mark.unit
    def test_check_remediation_and_config_overrides_are_ignored(self, tmp_path: Path) -> None:
        user = load_user_config(_write(tmp_path, EVIL))
        override = user.get_control_override("OSPS-DO-01.01")
        assert override is None or (override.check is None and override.remediation is None and not override.config)

    @pytest.mark.unit
    def test_custom_controls_are_ignored(self, tmp_path: Path) -> None:
        user = load_user_config(_write(tmp_path, EVIL))
        assert "CUSTOM-01" not in user.controls

    @pytest.mark.unit
    def test_execution_affecting_sections_are_ignored(self, tmp_path: Path) -> None:
        user = load_user_config(_write(tmp_path, EVIL))
        assert user.adapters == {}
        assert user.mcp_servers == {}
        assert user.control_groups == {}
        assert user.stores.model_dump(exclude_none=True) == {}
        assert "plugins" not in (user.model_extra or {})

    @pytest.mark.unit
    def test_extends_path_is_ignored(self, tmp_path: Path) -> None:
        user = load_user_config(_write(tmp_path, EVIL))
        assert user.extends is None

    @pytest.mark.unit
    def test_extends_framework_name_is_kept(self, tmp_path: Path) -> None:
        user = load_user_config(_write(tmp_path, 'extends = "openssf-baseline"\n'))
        assert user.extends == "openssf-baseline"

    @pytest.mark.unit
    def test_status_exclusions_are_kept(self, tmp_path: Path) -> None:
        user = load_user_config(_write(tmp_path, EVIL))
        override = user.get_control_override("OSPS-VM-02.01")
        assert override is not None
        assert override.status is not None and override.status.value == "n/a"
        assert override.reason == "we have no vulnerability process"

    @pytest.mark.unit
    def test_ignored_keys_are_reported(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        with caplog.at_level(logging.WARNING):
            load_user_config(_write(tmp_path, EVIL))
        text = caplog.text
        assert "operator configuration" in text
        for key in ("passes", "mcp_servers", "adapters", "extends", "plugins"):
            assert key in text

    @pytest.mark.unit
    def test_benign_file_logs_nothing(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        benign = '[controls."OSPS-VM-02.01"]\nstatus = "n/a"\nreason = "library"\n'
        with caplog.at_level(logging.WARNING):
            load_user_config(_write(tmp_path, benign))
        assert caplog.text == ""


class TestOperatorOptIn:
    @pytest.mark.unit
    def test_trusted_argument_keeps_everything(self, tmp_path: Path) -> None:
        user = load_user_config(_write(tmp_path, EVIL), trusted=True)
        assert user.get_control_override("OSPS-DO-01.01").passes
        assert "scanner" in user.mcp_servers
        assert user.extends == "./evil-framework.toml"

    @pytest.mark.unit
    @pytest.mark.parametrize("value", ["1", "true", "yes"])
    def test_environment_cannot_opt_in(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, value: str) -> None:
        """There is no environment switch; trust comes from operator configuration."""
        monkeypatch.setenv("DARNIT_TRUST_REPO_CONFIG", value)
        user = load_user_config(_write(tmp_path, EVIL))
        override = user.get_control_override("OSPS-DO-01.01")
        assert override is None or not override.passes


class TestEndToEnd:
    """The reported attack, through the MCP audit tool: the repository swaps a
    control's passes for an exec command. The unrestricted case (restriction
    disabled) proves the test reaches the code path that used to execute it."""

    @pytest.mark.integration
    @pytest.mark.parametrize(("restricted", "should_run"), [(True, False), (False, True)])
    def test_repo_supplied_command_is_not_run(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, restricted: bool, should_run: bool
    ) -> None:
        pytest.importorskip("darnit_baseline")
        from darnit_baseline.tools import audit_openssf_baseline

        marker = tmp_path / "marker.txt"
        repo = tmp_path / "repo"
        repo.mkdir()
        (repo / "README.md").write_text("# x\n", encoding="utf-8")
        (repo / ".baseline.toml").write_text(
            '[controls."OSPS-DO-01.01"]\n'
            f'passes = [ {{ handler = "exec", command = ["sh", "-c", "echo pwned > {marker}"] }} ]\n',
            encoding="utf-8",
        )
        if not restricted:
            monkeypatch.setattr(merger, "_restrict_untrusted_user_config", lambda data: (data, []))

        audit_openssf_baseline(owner="o", repo="r", local_path=str(repo), output_format="json")

        assert marker.exists() is should_run
