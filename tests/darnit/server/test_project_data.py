"""Tests for darnit.server.tools.project_data (feature 041, feature 042).

Covers context parameter reflection, expiry parsing, usage instructions,
repository trust boundaries, and PASS candidate confirmation.
"""

from __future__ import annotations

import inspect
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from darnit.config.context_schema import ContextDefinition
from darnit.server.tools.judgments import submit_judgment_impl
from darnit.server.tools.project_data import (
    _parse_expiry,
    confirm_not_applicable_impl,
    confirm_pass_candidates_impl,
    confirm_project_data_impl,
    confirmable_definitions,
    context_parameters,
    with_context_parameters,
)
from darnit.trust.confirmations import load_confirmations
from tests.darnit.trust.judgment_repo import (
    CI_VARS,
    CONTROL,
    EXCERPT,
    FRAMEWORK,
    IDENTITY,
    OWNER,
    REPO,
    make_repo,
    write_operator_config,
)


@pytest.fixture(autouse=True)
def _outside_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in CI_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = make_repo(tmp_path)
    write_operator_config(tmp_path)
    return path


@pytest.mark.unit
class TestParseExpiry:
    def test_future_datetime_returned_utc(self) -> None:
        now = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        future = datetime(2027, 6, 15, 12, 0, tzinfo=UTC)
        assert _parse_expiry(future, now) == future

    def test_naive_datetime_assigned_utc(self) -> None:
        now = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        naive = datetime(2027, 6, 15, 12, 0)
        parsed = _parse_expiry(naive, now)
        assert parsed.tzinfo == UTC
        assert parsed == datetime(2027, 6, 15, 12, 0, tzinfo=UTC)

    def test_date_converted_to_utc_datetime(self) -> None:
        now = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        target = date(2027, 10, 1)
        parsed = _parse_expiry(target, now)
        assert parsed == datetime(2027, 10, 1, 0, 0, tzinfo=UTC)

    def test_iso_string_parsed(self) -> None:
        now = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        parsed = _parse_expiry("2028-12-31T23:59:59Z", now)
        assert parsed == datetime(2028, 12, 31, 23, 59, 59, tzinfo=UTC)

    def test_past_date_raises_value_error(self) -> None:
        now = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="is not in the future"):
            _parse_expiry(datetime(2025, 1, 1, tzinfo=UTC), now)

    def test_now_date_raises_value_error(self) -> None:
        now = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="is not in the future"):
            _parse_expiry(now, now)

    def test_invalid_date_format_raises_value_error(self) -> None:
        now = datetime(2026, 1, 1, 0, 0, tzinfo=UTC)
        with pytest.raises(ValueError, match="is not a date"):
            _parse_expiry("invalid-date-string", now)


@pytest.mark.unit
class TestConfirmableDefinitions:
    def test_baseline_definitions_loaded(self) -> None:
        definitions = confirmable_definitions("openssf-baseline")
        assert "maintainers" in definitions
        assert "security_contact" in definitions
        assert "governance_model" in definitions
        assert isinstance(definitions["maintainers"], ContextDefinition)

    def test_unknown_framework_returns_empty_dict(self) -> None:
        definitions = confirmable_definitions("non_existent_framework_xyz")
        assert definitions == {}

    def test_default_definitions_from_local_path(self, repo: Path) -> None:
        definitions = confirmable_definitions(None, local_path=str(repo))
        assert isinstance(definitions, dict)


@pytest.mark.unit
class TestContextParameters:
    def test_parameters_generated_for_definitions(self) -> None:
        defs = {
            "is_lib": ContextDefinition(prompt="Is library", type="boolean"),
            "tags": ContextDefinition(prompt="Tag list", type="list"),
            "contact": ContextDefinition(prompt="Security contact", type="string"),
        }
        params = context_parameters(defs)
        assert len(params) == 3
        param_map = {p.name: p for p in params}

        assert param_map["is_lib"].kind == inspect.Parameter.KEYWORD_ONLY
        assert param_map["is_lib"].default is None
        assert param_map["tags"].kind == inspect.Parameter.KEYWORD_ONLY
        assert param_map["contact"].kind == inspect.Parameter.KEYWORD_ONLY

    def test_with_context_parameters_decorates_signature(self) -> None:
        defs = {
            "custom_key": ContextDefinition(prompt="A custom key", type="string"),
        }

        def dummy_tool(local_path: str = ".", **kwargs) -> str:
            return f"handled {local_path} with {kwargs}"

        exposed = with_context_parameters(dummy_tool, defs)
        sig = inspect.signature(exposed)

        assert "local_path" in sig.parameters
        assert "custom_key" in sig.parameters
        assert sig.parameters["custom_key"].kind == inspect.Parameter.KEYWORD_ONLY
        assert exposed(local_path="foo", custom_key="bar") == "handled foo with {'custom_key': 'bar'}"


@pytest.mark.unit
class TestConfirmProjectDataImplValidation:
    def test_invalid_path_returns_error(self) -> None:
        result = confirm_project_data_impl(local_path="/path/that/does/not/exist/at/all")
        assert "❌ Error:" in result

    def test_no_values_returns_usage_instructions(self, repo: Path) -> None:
        result = confirm_project_data_impl(local_path=str(repo), framework_name="openssf-baseline")
        assert "No data values provided." in result
        assert "confirm_project_data(" in result
        assert "`maintainers`" in result

    def test_answers_without_owner_and_repo_refused(self, repo: Path) -> None:
        result = confirm_project_data_impl(
            local_path=str(repo),
            framework_name="openssf-baseline",
            maintainers=["@alice"],
        )
        assert "refused: name the repository: owner and repo" in result

    def test_invalid_expiry_returns_error(self, repo: Path) -> None:
        result = confirm_project_data_impl(
            local_path=str(repo),
            owner=OWNER,
            repo=REPO,
            framework_name="openssf-baseline",
            maintainers=["@alice"],
            expires_at={"maintainers": "not-a-valid-date"},
        )
        assert "refused: expires_at 'not-a-valid-date' is not a date" in result

    def test_past_expiry_returns_error(self, repo: Path) -> None:
        result = confirm_project_data_impl(
            local_path=str(repo),
            owner=OWNER,
            repo=REPO,
            framework_name="openssf-baseline",
            maintainers=["@alice"],
            expires_at={"maintainers": "2020-01-01"},
        )
        assert "refused: expires_at '2020-01-01' is not in the future" in result

    def test_delegates_to_confirm_pass_candidates(self, repo: Path) -> None:
        result = confirm_project_data_impl(
            local_path=str(repo),
            owner=OWNER,
            repo=REPO,
            framework_name=FRAMEWORK,
            confirm_pass_candidate=[CONTROL],
        )
        assert f"- {CONTROL}: no PASS candidate for the current evidence; nothing confirmed" in result


@pytest.mark.unit
class TestConfirmNotApplicable:
    def test_missing_framework_returns_error(self, repo: Path) -> None:
        result = confirm_not_applicable_impl(
            str(repo),
            ["OSPS-AC-01.01"],
            owner=OWNER,
            repo=REPO,
            framework_name=None,
        )
        assert result == "Error: no framework is configured for confirming claims."

    def test_unnamed_repository_returns_error(self, repo: Path) -> None:
        result = confirm_not_applicable_impl(
            str(repo),
            ["OSPS-AC-01.01"],
            owner=None,
            repo=None,
            framework_name="openssf-baseline",
        )
        assert "Error: name the repository whose claims you are confirming" in result


@pytest.mark.integration
class TestConfirmPassCandidates:
    def test_missing_framework_returns_error(self, repo: Path) -> None:
        result = confirm_pass_candidates_impl(
            str(repo),
            [CONTROL],
            owner=OWNER,
            repo=REPO,
            framework_name=None,
        )
        assert result == "Error: no framework is configured for confirming PASS candidates."

    def test_unnamed_repository_returns_error(self, repo: Path) -> None:
        result = confirm_pass_candidates_impl(
            str(repo),
            [CONTROL],
            owner=None,
            repo=None,
            framework_name=FRAMEWORK,
        )
        assert "Error: name the repository whose PASS candidates you are confirming" in result

    def test_control_not_reaching_model_step_reported(self, repo: Path) -> None:
        result = confirm_pass_candidates_impl(
            str(repo),
            ["NONEXISTENT_CONTROL"],
            owner=OWNER,
            repo=REPO,
            framework_name=FRAMEWORK,
        )
        assert "- NONEXISTENT_CONTROL: does not reach a model judgment step; nothing confirmed" in result

    def test_missing_candidate_reported(self, repo: Path) -> None:
        result = confirm_pass_candidates_impl(
            str(repo),
            [CONTROL],
            owner=OWNER,
            repo=REPO,
            framework_name=FRAMEWORK,
        )
        assert f"- {CONTROL}: no PASS candidate for the current evidence; nothing confirmed" in result

    def test_successful_pass_candidate_confirmation(self, repo: Path) -> None:
        # 1. Submit a valid judgment candidate
        submit_res = submit_judgment_impl(
            control_id=CONTROL,
            verdict="pass",
            reasoning="The README states what the project is.",
            cited_evidence=[EXCERPT],
            model="claude-opus-5-5",
            model_version="claude-opus-5-5",
            owner=OWNER,
            repo=REPO,
            local_path=str(repo),
            framework_name=FRAMEWORK,
        )
        assert submit_res["status"] == "candidate"
        assert submit_res["stored"] is True

        # 2. Confirm the pass candidate via confirm_pass_candidates_impl
        result = confirm_pass_candidates_impl(
            str(repo),
            [CONTROL],
            owner=OWNER,
            repo=REPO,
            framework_name=FRAMEWORK,
        )
        assert f"- {CONTROL}: confirmed by" in result
        assert "claude-opus-5-5" in result
        assert "The README states what the project is." in result

        # 3. Verify confirmation was recorded in operator store
        confirmations = load_confirmations(IDENTITY)
        assert len(confirmations) == 1
        assert confirmations[0].control_id == CONTROL
        assert confirmations[0].claim == "pass_candidate"
