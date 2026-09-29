"""Accepting a candidate by digest records it as the basis (feature 042, US3 scenario 4, research R6)."""

from __future__ import annotations

import asyncio
import inspect
from pathlib import Path

import pytest
import yaml

from darnit.config.context_keys import value_digest
from darnit.config.context_resolve import resolve_context
from darnit.config.context_schema import Standing
from darnit.server.tools.project_data import confirm_project_data_impl
from darnit.trust.confirmations import load_confirmations, load_context_bases

from .conftest import assert_unchanged, snapshot, write_operator_config

OWNER = "example-org"
IDENTITY = "github.com/example-org/r-maint"


def _candidate(repo: Path, key: str = "maintainers"):
    resolved = resolve_context(str(repo), owner=OWNER, repo="r-maint", target=f"{OWNER}/r-maint")
    candidate = resolved.get(key)
    assert candidate is not None and candidate.standing is Standing.CANDIDATE
    return candidate


def _accept(repo: Path, digests: dict[str, str], **values) -> str:
    return confirm_project_data_impl(
        local_path=str(repo),
        accept_candidates=digests,
        owner=OWNER,
        repo="r-maint",
        framework_name="openssf-baseline",
        **values,
    )


@pytest.fixture
def r_maint(scratch_repo) -> Path:
    return scratch_repo("R-maint")


@pytest.mark.integration
class TestMatchingDigest:
    def test_trusted_repository_records_the_candidate_as_basis(self, r_maint: Path, tmp_path: Path) -> None:
        write_operator_config(tmp_path / "operator.toml", trusted=[IDENTITY])
        candidate = _candidate(r_maint)

        message = _accept(r_maint, {"maintainers": value_digest("maintainers", candidate.value)})

        assert "maintainers: confirmed, recorded in .project/darnit.yaml" in message
        data = yaml.safe_load((r_maint / ".project" / "darnit.yaml").read_text())
        record = data["confirmations"]["maintainers"]
        assert record["basis"]["value"] == candidate.value
        assert record["basis"]["origin"]["kind"] == candidate.origin.kind.value
        assert record["basis"]["origin"]["method"] == candidate.origin.method
        assert data["context"]["maintainers"] == candidate.value
        assert resolve_context(str(r_maint), detect=False).get("maintainers").standing is Standing.CONFIRMED

    def test_untrusted_repository_records_operator_side_with_basis(self, r_maint: Path, tmp_path: Path) -> None:
        write_operator_config(tmp_path / "operator.toml")
        candidate = _candidate(r_maint)
        before = snapshot(r_maint)

        message = _accept(r_maint, {"maintainers": value_digest("maintainers", candidate.value)})

        assert "maintainers: confirmed, recorded operator-side" in message
        assert_unchanged(r_maint, before)
        [basis] = load_context_bases(IDENTITY)
        assert basis.value == candidate.value
        assert basis.origin["kind"] == candidate.origin.kind.value


@pytest.mark.integration
class TestRefusals:
    @pytest.mark.parametrize("trusted", [True, False])
    def test_mismatched_digest_refuses_and_writes_nothing(self, r_maint: Path, tmp_path: Path, trusted: bool) -> None:
        write_operator_config(tmp_path / "operator.toml", trusted=[IDENTITY] if trusted else [])
        before = snapshot(r_maint)

        message = _accept(r_maint, {"maintainers": "sha256:" + "0" * 64})

        assert "maintainers: refused:" in message
        assert "changed" in message
        assert_unchanged(r_maint, before)
        assert load_confirmations() == []

    def test_key_without_a_candidate_is_refused(self, r_maint: Path, tmp_path: Path) -> None:
        write_operator_config(tmp_path / "operator.toml", trusted=[IDENTITY])
        before = snapshot(r_maint)

        message = _accept(r_maint, {"governance_model": value_digest("governance_model", "bdfl")})

        assert "governance_model: refused: no candidate" in message
        assert_unchanged(r_maint, before)

    def test_unknown_key_is_refused(self, r_maint: Path, tmp_path: Path) -> None:
        write_operator_config(tmp_path / "operator.toml", trusted=[IDENTITY])
        before = snapshot(r_maint)

        message = _accept(r_maint, {"not_a_key": "sha256:" + "0" * 64})

        assert "not_a_key: refused:" in message
        assert_unchanged(r_maint, before)

    def test_answer_and_accepted_candidate_for_one_key_refuses_both(self, r_maint: Path, tmp_path: Path) -> None:
        write_operator_config(tmp_path / "operator.toml", trusted=[IDENTITY])
        candidate = _candidate(r_maint)
        before = snapshot(r_maint)

        message = _accept(
            r_maint, {"maintainers": value_digest("maintainers", candidate.value)}, maintainers=["@someone"]
        )

        assert "maintainers: refused:" in message
        assert "confirmed" not in message
        assert_unchanged(r_maint, before)


@pytest.mark.integration
class TestValuesAgainstVocabulary:
    def test_value_outside_the_vocabulary_is_refused(self, r_maint: Path, tmp_path: Path) -> None:
        write_operator_config(tmp_path / "operator.toml", trusted=[IDENTITY])
        before = snapshot(r_maint)

        message = confirm_project_data_impl(
            local_path=str(r_maint),
            platform="sourceforge",
            owner=OWNER,
            repo="r-maint",
            framework_name="openssf-baseline",
        )

        assert "platform: refused:" in message
        assert_unchanged(r_maint, before)

    def test_key_of_another_installed_framework_is_confirmed(self, r_maint: Path, tmp_path: Path) -> None:
        write_operator_config(tmp_path / "operator.toml", trusted=[IDENTITY])

        message = confirm_project_data_impl(
            local_path=str(r_maint),
            csl_coc_policy="umbrella",
            owner=OWNER,
            repo="r-maint",
            framework_name="openssf-baseline",
        )

        assert "csl_coc_policy: confirmed, recorded in .project/darnit.yaml" in message


BASELINE_KEYS = {
    "maintainers",
    "security_contact",
    "governance_model",
    "has_subprojects",
    "has_releases",
    "is_library",
    "has_compiled_assets",
    "ci_provider",
    "platform",
}
CSL_KEYS = {
    "csl_spec_name",
    "csl_working_group_scope",
    "csl_coc_contacts",
    "csl_coc_policy",
    "csl_coc_reference",
    "csl_governance_mode",
    "csl_governance_reference",
    "csl_code_license",
}


@pytest.mark.unit
class TestGeneratedParameters:
    def test_tool_exposes_every_context_key_and_accept_candidates(self) -> None:
        from darnit_baseline.tools import confirm_project_data_tool

        parameters = set(inspect.signature(confirm_project_data_tool()).parameters)

        assert BASELINE_KEYS | CSL_KEYS | {"accept_candidates", "owner", "repo", "host"} <= parameters

    def test_mcp_schema_exposes_them(self) -> None:
        from importlib.resources import files

        from darnit.server.factory import create_server

        server = create_server(Path(str(files("darnit_baseline") / "openssf-baseline.toml")))
        [tool] = [t for t in asyncio.run(server.list_tools()) if t.name == "confirm_project_data"]

        properties = tool.inputSchema["properties"]
        assert BASELINE_KEYS | CSL_KEYS | {"accept_candidates"} <= set(properties)
        for value in ("github", "gitlab", "bitbucket", "other"):
            assert value in properties["platform"]["description"]
