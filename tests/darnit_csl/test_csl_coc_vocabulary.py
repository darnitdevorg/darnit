"""One vocabulary for the Community Specification enum keys (#522).

``csl_coc_policy`` used to declare ``values = ["csl", "umbrella"]`` while the
tool description, the notices template, and ``scripts/csl_onboard.py`` all
used ``org``. A person could not confirm ``org`` through
``confirm_project_data``, so a confirmed value never selected the org notice.
Every place that names a value now agrees with the key's ``values``.
"""

from __future__ import annotations

import asyncio
import re
from importlib.resources import files
from pathlib import Path

import pytest
import yaml
from darnit_csl.mcp_tools import remediate_community_spec

from darnit.config import load_framework_config
from darnit.server.tools.project_data import confirm_project_data_impl
from scripts import csl_onboard

CSL_TOML = Path(str(files("darnit_csl") / "community-spec.toml"))
NOTICES_TEMPLATE = Path(str(files("darnit_csl") / "templates" / "csl_notices.tmpl"))


def _values(key: str) -> list[str]:
    return list(load_framework_config(CSL_TOML).context.definitions[key].values or [])


@pytest.mark.unit
def test_coc_policy_offers_every_mode() -> None:
    assert _values("csl_coc_policy") == ["csl", "umbrella", "org"]


@pytest.mark.unit
def test_template_branches_only_on_declared_values() -> None:
    branched = set(re.findall(r"context\.csl_coc_policy == '(\w+)'", NOTICES_TEMPLATE.read_text(encoding="utf-8")))
    assert branched, "notices template no longer branches on csl_coc_policy"
    assert branched <= set(_values("csl_coc_policy"))


@pytest.mark.unit
@pytest.mark.parametrize(("option", "key"), [("--coc-policy", "csl_coc_policy"), ("--governance-mode", "csl_governance_mode")])
def test_onboarding_script_offers_the_declared_values(option: str, key: str) -> None:
    action = csl_onboard.parser()._option_string_actions[option]
    assert list(action.choices) == _values(key)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("parameter", "value"),
    [("coc_policy", "foundation"), ("governance_mode", "org"), ("governance_mode", "CSL")],
)
def test_tool_rejects_a_value_outside_the_vocabulary(tmp_path: Path, parameter: str, value: str) -> None:
    out = asyncio.run(remediate_community_spec(local_path=str(tmp_path), scope="s", **{parameter: value}))

    assert out.startswith(f"Error: {parameter} must be one of")
    assert "Nothing was written." in out
    assert not (tmp_path / "governance").exists()


@pytest.mark.unit
@pytest.mark.parametrize("value", ["csl", "umbrella", "org"])
def test_tool_accepts_every_coc_policy_value(tmp_path: Path, value: str) -> None:
    reference = "Example follows the [Example Code of Conduct](https://example.org/coc)."
    out = asyncio.run(
        remediate_community_spec(
            local_path=str(tmp_path), scope="s", coc_policy=value, coc_reference=reference,
            coc_contacts="Jane Doe (jane@example.org), John Roe (@johnroe)",
        )
    )

    assert "must be one of" not in out


@pytest.mark.integration
def test_org_can_be_confirmed(temp_git_repo: Path, trusted_target: tuple[str, str]) -> None:
    owner, repo = trusted_target

    message = confirm_project_data_impl(
        local_path=str(temp_git_repo), owner=owner, repo=repo, framework_name="community-spec",
        csl_coc_policy="org",
    )

    assert "refused" not in message
    data = yaml.safe_load((temp_git_repo / ".project" / "darnit.yaml").read_text())
    assert data["context"]["csl_coc_policy"] == "org"
    assert "csl_coc_policy" in data["confirmations"]
