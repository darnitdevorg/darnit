"""The ``[remediation]`` operator policy (feature 043, contracts section 1, T006)."""

from __future__ import annotations

from pathlib import Path

import pytest
from pydantic import ValidationError

from darnit.cli import main as cli_main
from darnit.config.operator.loader import OperatorConfigError, load_operator_config
from darnit.config.operator.schema import OperatorConfig, RemediationSettings


def _write(path: Path, text: str) -> Path:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")
    path.chmod(0o600)
    return path


@pytest.mark.unit
def test_absent_section_means_prompt_for_both() -> None:
    cfg = OperatorConfig.model_validate({"schema_version": 1})

    assert cfg.remediation == RemediationSettings(platform="prompt", high_impact="prompt")


@pytest.mark.unit
@pytest.mark.parametrize("value", ["prompt", "manual", "auto"])
def test_every_policy_value_is_accepted(value: str) -> None:
    cfg = OperatorConfig.model_validate({"schema_version": 1, "remediation": {"platform": value, "high_impact": value}})

    assert cfg.remediation.platform == value
    assert cfg.remediation.high_impact == value


@pytest.mark.unit
def test_sections_are_independent() -> None:
    cfg = OperatorConfig.model_validate({"schema_version": 1, "remediation": {"high_impact": "manual"}})

    assert cfg.remediation.platform == "prompt"
    assert cfg.remediation.high_impact == "manual"


@pytest.mark.unit
@pytest.mark.parametrize(
    ("section", "loc"),
    [
        ({"platform": "always"}, ("remediation", "platform")),
        ({"high_impact": "yes"}, ("remediation", "high_impact")),
        ({"high_impact": True}, ("remediation", "high_impact")),
        ({"policy": "auto"}, ("remediation", "policy")),
    ],
)
def test_unknown_keys_or_values_are_rejected(section: dict, loc: tuple) -> None:
    with pytest.raises(ValidationError) as exc:
        OperatorConfig.model_validate({"schema_version": 1, "remediation": section})

    assert loc in [e["loc"] for e in exc.value.errors()]


@pytest.mark.unit
def test_unknown_value_in_the_file_stops_loading(tmp_path: Path) -> None:
    cfg = _write(tmp_path / "config.toml", 'schema_version = 1\n\n[remediation]\nplatform = "sometimes"\n')

    with pytest.raises(OperatorConfigError, match="remediation.platform"):
        load_operator_config(cfg)


@pytest.mark.unit
def test_config_show_prints_the_section(tmp_path: Path, capsys) -> None:
    cfg = _write(
        tmp_path / "config.toml", 'schema_version = 1\n\n[remediation]\nplatform = "auto"\nhigh_impact = "manual"\n'
    )

    assert cli_main(["config", "show", "--operator-config", str(cfg)]) == 0
    out = capsys.readouterr().out

    assert "remediation policy: platform=auto high_impact=manual" in out
    assert '"remediation"' in out


@pytest.mark.unit
def test_config_show_prints_the_default_section(capsys) -> None:
    assert cli_main(["config", "show"]) == 0

    assert "remediation policy: platform=prompt high_impact=prompt" in capsys.readouterr().out
