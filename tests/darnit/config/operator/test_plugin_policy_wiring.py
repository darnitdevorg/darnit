"""Operator ``[plugins]`` settings reach plugin discovery (#448).

Plugin trust comes from the operator configuration that has already passed the
containment check for the audit target, never from the audited repository.
These tests pin the forwarding at the two audit entry points that resolve that
configuration before they touch an implementation: ``run_sieve_audit`` and the
built-in MCP audit tool.

Scope: the MCP server's startup-time implementation loading is deliberately
untouched here -- it has no audit target, so no containment-checked policy
exists for it yet.
"""

from __future__ import annotations

import asyncio
from pathlib import Path

import pytest

from darnit.config.operator.loader import LoadedOperatorConfig, set_launch_options
from darnit.config.operator.schema import OperatorConfig, PluginSettings
from darnit.core import discovery

FRAMEWORK = "openssf-baseline"
OWN = "github.com/example/repo"
MY_ORG = "https://github.com/my-org"
ATTACKER = "https://github.com/attacker"

# A tag no control carries, so the audit resolves a framework and an
# implementation but runs nothing.
NO_CONTROLS = "domain=ZZ"


def _operator(**plugins: object) -> LoadedOperatorConfig:
    """An already-resolved operator configuration carrying a plugin policy."""
    config = OperatorConfig.model_validate({"schema_version": 1, "plugins": plugins})
    return LoadedOperatorConfig(
        config=config, source="test", digest=None, permission_check="ok", strict=False
    )


@pytest.fixture
def seen(monkeypatch: pytest.MonkeyPatch) -> list[PluginSettings | None]:
    """Capture the policy every discovery call is made under.

    Both call sites import from ``darnit.core.discovery`` when they run, so
    patching the module attributes intercepts them.
    """
    captured: list[PluginSettings | None] = []

    def _get_implementation(name, plugins=None):
        captured.append(plugins)
        return None

    def _register_implementation_handlers(framework_name, plugins=None):
        captured.append(plugins)
        return False

    monkeypatch.setattr(discovery, "get_implementation", _get_implementation)
    monkeypatch.setattr(
        discovery, "register_implementation_handlers", _register_implementation_handlers
    )
    return captured


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    (path / "README.md").write_text("# Repo\n", encoding="utf-8")
    return path


@pytest.fixture
def operator_config_file(tmp_path: Path) -> Path:
    """A strict plugin policy in an operator configuration outside the repository."""
    path = tmp_path / "operator" / "config.toml"
    path.parent.mkdir()
    path.write_text(
        "schema_version = 1\n\n"
        "[plugins]\n"
        "allow_unsigned = false\n"
        f'trusted_publishers = ["{MY_ORG}"]\n',
        encoding="utf-8",
    )
    path.chmod(0o600)
    return path


@pytest.fixture
def launched_with(operator_config_file: Path):
    """Launch darnit with that operator configuration, then restore the default."""
    set_launch_options(operator_config_file)
    yield operator_config_file
    set_launch_options(None)


@pytest.fixture
def without_report_metadata(monkeypatch: pytest.MonkeyPatch) -> None:
    """Silence the report's framework lookup, which has no audit target.

    ``framework_metadata`` also consults discovery, with no policy and no
    repository in hand. Path A leaves that path alone, so it is stubbed out
    here to keep these tests assertions about the audit path only.
    """
    monkeypatch.setattr(
        "darnit.tools.audit.framework_metadata", lambda name: {"name": name}
    )


def _run_sieve_audit(repo: Path, operator: LoadedOperatorConfig, *, controls=None):
    from darnit.tools.audit import run_sieve_audit

    return run_sieve_audit(
        owner="example",
        repo="repo",
        local_path=str(repo),
        default_branch="main",
        level=1,
        controls=controls,
        tags=[NO_CONTROLS],
        framework_name=FRAMEWORK,
        operator_config=operator,
        target=OWN,
        write_cache=False,
    )


def _builtin_audit(repo: Path) -> str:
    from darnit.server.tools.builtin_audit import builtin_audit

    return asyncio.run(
        builtin_audit(
            local_path=str(repo),
            level=1,
            tags=NO_CONTROLS,
            output_format="json",
            _framework_name=FRAMEWORK,
        )
    )


def _assert_strict(captured: list[PluginSettings | None]) -> None:
    """Every discovery call saw the operator's explicit strict policy."""
    assert captured, "discovery was never reached"
    for plugins in captured:
        assert plugins is not None
        assert plugins.allow_unsigned is False
        assert "allow_unsigned" in plugins.model_fields_set
        assert plugins.trusted_publishers == [MY_ORG]


@pytest.mark.integration
class TestRunSieveAudit:
    """The canonical audit pipeline forwards the policy it already resolved."""

    def test_handler_registration_gets_the_policy(self, repo: Path, seen) -> None:
        """Pre-loaded controls still need the framework's handlers registered."""
        _run_sieve_audit(
            repo, _operator(allow_unsigned=False, trusted_publishers=[MY_ORG]), controls=[]
        )

        _assert_strict(seen)

    def test_control_registration_gets_the_policy(self, repo: Path, seen) -> None:
        """Loading controls from the framework also goes through discovery."""
        _run_sieve_audit(
            repo, _operator(allow_unsigned=False, trusted_publishers=[MY_ORG]), controls=None
        )

        _assert_strict(seen)

    def test_no_plugins_table_forwards_the_unset_settings(self, repo: Path, seen) -> None:
        """An operator configuration without ``[plugins]`` keeps the default."""
        _run_sieve_audit(repo, _operator(), controls=[])

        assert seen
        for plugins in seen:
            assert plugins is not None
            assert "allow_unsigned" not in plugins.model_fields_set


@pytest.mark.integration
class TestBuiltinAuditTool:
    """The built-in MCP audit tool resolves the policy before it discovers."""

    def test_resolved_policy_reaches_discovery(
        self, repo: Path, seen, launched_with, without_report_metadata
    ) -> None:
        _builtin_audit(repo)

        _assert_strict(seen)

    def test_repository_plugins_table_cannot_change_the_policy(
        self, repo: Path, seen, launched_with, without_report_metadata
    ) -> None:
        """A repository that asks to be trusted is still audited under the operator's policy.

        Upstream's SC-001 coverage (``test_repository_cannot_configure.py``)
        proves the repository's ``[plugins]`` table is stripped and reported as
        ignored. This adds the matching assertion at the other end: the value
        discovery is handed is the operator's, not the repository's.
        """
        (repo / ".baseline.toml").write_text(
            f'extends = "{FRAMEWORK}"\n\n'
            "[plugins]\n"
            "allow_unsigned = true\n"
            f'trusted_publishers = ["{ATTACKER}"]\n',
            encoding="utf-8",
        )

        _builtin_audit(repo)

        _assert_strict(seen)
        for plugins in seen:
            assert ATTACKER not in plugins.trusted_publishers
