"""remediate_community_spec does not default judgment parameters (feature 042, US2, FR-008; research R11)."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path
from typing import Any

import pytest
import yaml

from darnit.config.context_keys import value_digest

pytestmark = pytest.mark.unit

JUDGMENT_PARAMETERS = {
    "scope": "csl_working_group_scope",
    "coc_contacts": "csl_coc_contacts",
    "code_license": "csl_code_license",
    "governance_mode": "csl_governance_mode",
    "governance_reference": "csl_governance_reference",
    "coc_policy": "csl_coc_policy",
    "coc_reference": "csl_coc_reference",
    "spec_name": "csl_spec_name",
}
COMPLETE = {
    "scope": "This Working Group standardizes the Foo metadata format.",
    "coc_contacts": "Jane Roe (jane@realcorp.io), John Poe (john@realcorp.io)",
    "code_license": "MIT",
    "governance_mode": "csl",
    "coc_policy": "csl",
}


def _run(repo: Path, **params: Any) -> str:
    from darnit_csl.mcp_tools import remediate_community_spec

    return asyncio.run(remediate_community_spec(local_path=str(repo), add_readme_links=False, **params))


def _without(*names: str) -> dict[str, Any]:
    return {k: v for k, v in COMPLETE.items() if k not in names}


def _store(repo: Path, key: str, value: Any, *, confirmed: bool) -> None:
    data: dict[str, Any] = {"context": {key: value}}
    if confirmed:
        data["confirmations"] = {
            key: {
                "value_digest": value_digest(key, value),
                "confirmed_by": "alice",
                "confirmed_at": "2026-09-01T00:00:00Z",
                "last_validated": "2026-09-01T00:00:00Z",
            }
        }
    (repo / ".project").mkdir()
    (repo / ".project" / "darnit.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")


def _written(repo: Path) -> list[str]:
    return sorted(p.relative_to(repo).as_posix() for p in repo.rglob("*") if p.is_file() and ".project" not in p.parts)


class TestSignature:
    @pytest.mark.parametrize("name", sorted(JUDGMENT_PARAMETERS))
    def test_judgment_parameter_has_no_default_value(self, name: str) -> None:
        from darnit_csl.mcp_tools import remediate_community_spec

        assert inspect.signature(remediate_community_spec).parameters[name].default is None


class TestOmittedParameters:
    @pytest.mark.parametrize(
        ("omitted", "key"),
        [
            ("code_license", "csl_code_license"),
            ("governance_mode", "csl_governance_mode"),
            ("coc_policy", "csl_coc_policy"),
            ("scope", "csl_working_group_scope"),
            ("coc_contacts", "csl_coc_contacts"),
        ],
    )
    def test_confirmation_required_and_nothing_written(self, tmp_path: Path, omitted: str, key: str) -> None:
        out = _run(tmp_path, **_without(omitted))

        assert f"confirmation required: {key}" in out
        assert _written(tmp_path) == []

    def test_umbrella_governance_needs_its_reference(self, tmp_path: Path) -> None:
        out = _run(tmp_path, **{**COMPLETE, "governance_mode": "umbrella"})

        assert "confirmation required: csl_governance_reference" in out
        assert _written(tmp_path) == []

    def test_unconfirmed_stored_value_is_not_used(self, tmp_path: Path) -> None:
        _store(tmp_path, "csl_code_license", "Apache-2.0", confirmed=False)

        out = _run(tmp_path, **_without("code_license"))

        assert "confirmation required: csl_code_license" in out
        assert _written(tmp_path) == []


class TestConfirmedContext:
    def test_confirmed_value_fills_an_omitted_parameter(self, tmp_path: Path) -> None:
        _store(tmp_path, "csl_code_license", "Apache-2.0", confirmed=True)

        out = _run(tmp_path, **_without("code_license"))

        assert "confirmation required" not in out
        assert "Apache-2.0" in (tmp_path / "governance" / "04-license.md").read_text(encoding="utf-8")

    def test_explicit_parameter_wins(self, tmp_path: Path) -> None:
        _store(tmp_path, "csl_code_license", "Apache-2.0", confirmed=True)

        _run(tmp_path, **{**COMPLETE, "code_license": "BSD-3-Clause"})

        license_text = (tmp_path / "governance" / "04-license.md").read_text(encoding="utf-8")
        assert "BSD-3-Clause" in license_text
        assert "Apache-2.0" not in license_text

    def test_all_parameters_supplied(self, tmp_path: Path) -> None:
        out = _run(tmp_path, **COMPLETE)

        assert "confirmation required" not in out
        assert "governance/04-license.md" in _written(tmp_path)
