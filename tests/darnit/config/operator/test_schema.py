"""OperatorConfig model (feature 040, contracts/operator-config.md)."""

from __future__ import annotations

import pytest
from pydantic import ValidationError

from darnit.config.operator.schema import OperatorConfig


def _cfg(**overrides):
    data = {"schema_version": 1}
    data.update(overrides)
    return OperatorConfig.model_validate(data)


@pytest.mark.unit
def test_minimal_config_uses_documented_defaults() -> None:
    cfg = _cfg()
    assert cfg.plugins.allowed == []
    assert cfg.plugins.allow_unsigned is False
    assert cfg.trust.repos == []
    assert cfg.trust.ci == []
    assert cfg.policy.confirmation_expiry_days == 180
    assert cfg.policy.strict_permissions is False
    assert cfg.operator.identity is None


@pytest.mark.unit
def test_schema_version_is_required() -> None:
    with pytest.raises(ValidationError) as exc:
        OperatorConfig.model_validate({})
    assert ("schema_version",) in [e["loc"] for e in exc.value.errors()]


@pytest.mark.unit
@pytest.mark.parametrize("version", [0, 2, "1"])
def test_unknown_schema_version_is_rejected(version) -> None:
    with pytest.raises(ValidationError):
        OperatorConfig.model_validate({"schema_version": version})


@pytest.mark.unit
@pytest.mark.parametrize(
    ("data", "loc"),
    [
        ({"unknown": 1}, ("unknown",)),
        ({"trust": {"repo": []}}, ("trust", "repo")),
        ({"policy": {"strict": True}}, ("policy", "strict")),
        ({"mcp_servers": {"s": {"command": ["x"], "args": []}}}, ("mcp_servers", "s", "args")),
        ({"controls": {"C-1": {"status": "n/a"}}}, ("controls", "C-1", "status")),
    ],
)
def test_unknown_keys_are_rejected_with_their_path(data, loc) -> None:
    with pytest.raises(ValidationError) as exc:
        _cfg(**data)
    assert loc in [e["loc"] for e in exc.value.errors()]


@pytest.mark.unit
def test_trust_booleans_are_strict() -> None:
    """A string like "false" must not be coerced on a trust-relevant field."""
    with pytest.raises(ValidationError):
        _cfg(plugins={"allow_unsigned": "false"})
    with pytest.raises(ValidationError):
        _cfg(policy={"strict_permissions": "yes"})


@pytest.mark.unit
def test_ci_rule_event_is_restricted_to_known_rules() -> None:
    assert _cfg(trust={"ci": [{"event": "push-default-branch"}]}).trust.ci[0].event == "push-default-branch"
    with pytest.raises(ValidationError):
        _cfg(trust={"ci": [{"event": "pull_request"}]})


@pytest.mark.unit
def test_full_example_parses() -> None:
    cfg = _cfg(
        operator={"identity": "alice@example.com"},
        plugins={"allowed": ["openssf-baseline"], "trusted_publishers": ["https://github.com/darnitdevorg"]},
        mcp_servers={"scanner": {"command": ["scanner-mcp", "--stdio"], "env": {"TOKEN": "$SCANNER_TOKEN"}}},
        controls={"OSPS-DO-01.01": {"passes": [{"handler": "file_exists", "files": ["README.md"]}]}},
        stores={"report": {"backend": "filesystem"}},
        llm={"provider": "anthropic", "model": "claude-sonnet-5", "max_cost_usd_per_run": 2.0},
        trust={"repos": ["github.com/example/project"], "ci": [{"event": "push-default-branch"}]},
        policy={"confirmation_expiry_days": 30, "strict_permissions": True},
    )
    assert cfg.controls["OSPS-DO-01.01"].passes[0].handler == "file_exists"
    assert cfg.mcp_servers["scanner"].command == ["scanner-mcp", "--stdio"]
    assert cfg.llm.max_cost_usd_per_run == 2.0


@pytest.mark.unit
@pytest.mark.parametrize("days", [0, -1])
def test_expiry_must_be_positive(days: int) -> None:
    with pytest.raises(ValidationError):
        _cfg(policy={"confirmation_expiry_days": days})
