"""Tests for get_pending_data batch context collection.

Tests the pagination, LLM directive footer, progress indicator,
presentation hint, ask_user_batch, answer_mapping, and TOML ordering
features for batched AskUserQuestion-based data gathering.
"""

import json
import subprocess
from unittest.mock import patch

import pytest

from darnit.config.context_schema import (
    ContextDefinition,
    ContextPromptRequest,
    ContextType,
    Origin,
    OriginKind,
    ResolvedValue,
    Standing,
)
from darnit_baseline.tools import (
    _LLM_DIRECTIVE_PREFIX,
    _build_context_question,
    _context_key_order,
    get_pending_data,
)


def _detected(key: str, value: object) -> ResolvedValue:
    return ResolvedValue(
        key=key,
        standing=Standing.CANDIDATE,
        value=value,
        origin=Origin(kind=OriginKind.DETECTOR, method="workflow directory", confidence=0.9),
    )


def _make_pending(count: int) -> list[ContextPromptRequest]:
    """Create a list of N mock ContextPromptRequests."""
    items = []
    for i in range(count):
        defn = ContextDefinition(
            type=ContextType.BOOLEAN,
            prompt=f"Question {i + 1}?",
            affects=[f"CTRL-{i + 1:02d}"],
        )
        items.append(ContextPromptRequest(
            key=f"key_{i + 1}",
            definition=defn,
            control_ids=[f"CTRL-{i + 1:02d}"],
            priority=count - i,  # highest priority first
        ))
    return items


def _parse_json_from_result(result: str) -> dict:
    """Strip directive prefix/footer and parse JSON from get_pending_data result."""
    # The directive prefix ends with "---\n", JSON starts after that
    return json.loads(result.split("\n---\n", 1)[-1])


class TestGetPendingContextPagination:
    """Tests for batch pagination behavior."""

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_default_limit_returns_four_questions(self, mock_get, mock_path) -> None:
        """Default limit=4 returns up to four questions in ask_user_batch."""
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        mock_get.return_value = _make_pending(5)

        result = get_pending_data(local_path="/tmp/repo")
        data = _parse_json_from_result(result)

        assert data["status"] == "pending"
        assert len(data["ask_user_batch"]) == 4

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_default_limit_returns_all_if_fewer_than_four(self, mock_get, mock_path) -> None:
        """Default limit=4 returns all questions when fewer than 4 pending."""
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        mock_get.return_value = _make_pending(2)

        result = get_pending_data(local_path="/tmp/repo")
        data = _parse_json_from_result(result)

        assert len(data["ask_user_batch"]) == 2

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_limit_zero_returns_all(self, mock_get, mock_path) -> None:
        """limit=0 returns all pending questions."""
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        mock_get.return_value = _make_pending(5)

        result = get_pending_data(local_path="/tmp/repo", limit=0)
        data = _parse_json_from_result(result)

        assert data["status"] == "pending"
        assert len(data["ask_user_batch"]) == 5

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_explicit_limit(self, mock_get, mock_path) -> None:
        """Explicit limit=3 returns at most 3 questions."""
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        mock_get.return_value = _make_pending(5)

        result = get_pending_data(local_path="/tmp/repo", limit=3)
        data = _parse_json_from_result(result)

        assert len(data["ask_user_batch"]) == 3


class TestGetPendingContextProgress:
    """Tests for progress indicator in response."""

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_progress_included(self, mock_get, mock_path) -> None:
        """Response includes progress object with answered and total."""
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        mock_get.return_value = _make_pending(8)

        result = get_pending_data(local_path="/tmp/repo")
        data = _parse_json_from_result(result)

        assert "progress" in data
        assert data["progress"]["total"] == 8
        assert data["progress"]["answered"] == 0


class TestGetPendingContextDirective:
    """Tests for LLM directive footer."""

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_directive_prepended_when_pending(self, mock_get, mock_path) -> None:
        """LLM directive prefix is prepended when questions are pending."""
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        mock_get.return_value = _make_pending(3)

        result = get_pending_data(local_path="/tmp/repo")

        assert result.startswith(_LLM_DIRECTIVE_PREFIX)
        assert "MANDATORY" in result
        assert "AskUserQuestion" in result

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_no_directive_when_complete(self, mock_get, mock_path) -> None:
        """No directive when no questions are pending."""
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        mock_get.return_value = []

        result = get_pending_data(local_path="/tmp/repo")

        assert _LLM_DIRECTIVE_PREFIX not in result
        data = json.loads(result)
        assert data["status"] == "complete"


class TestBuildContextQuestionPresentationHint:
    """Tests for presentation_hint in question payload."""

    def test_boolean_question_includes_hint(self) -> None:
        """Boolean question includes presentation_hint."""
        defn = ContextDefinition(
            type=ContextType.BOOLEAN,
            prompt="Has releases?",
            affects=["CTRL-01"],
        )
        req = ContextPromptRequest(
            key="has_releases",
            definition=defn,
            control_ids=["CTRL-01"],
            priority=1,
        )
        question = _build_context_question(req)

        assert "presentation_hint" in question
        assert question["presentation_hint"] == "[y/N]"

    def test_enum_question_includes_hint(self) -> None:
        """Enum question includes auto-generated presentation_hint."""
        defn = ContextDefinition(
            type=ContextType.ENUM,
            prompt="CI provider?",
            values=["github", "gitlab", "jenkins"],
            affects=["CTRL-01"],
        )
        req = ContextPromptRequest(
            key="ci_provider",
            definition=defn,
            control_ids=["CTRL-01"],
            priority=1,
        )
        question = _build_context_question(req)

        assert "presentation_hint" in question
        assert question["presentation_hint"] == "[github/gitlab/jenkins]"

    def test_string_question_no_hint(self) -> None:
        """String question without explicit hint has no presentation_hint key."""
        defn = ContextDefinition(
            type=ContextType.STRING,
            prompt="Security contact?",
            affects=["CTRL-01"],
        )
        req = ContextPromptRequest(
            key="security_contact",
            definition=defn,
            control_ids=["CTRL-01"],
            priority=1,
        )
        question = _build_context_question(req)

        assert "presentation_hint" not in question


class TestAskUserParams:
    """Tests for ask_user field in question payload (AskUserQuestion integration)."""

    def test_boolean_question_has_ask_user_with_yes_no(self) -> None:
        """Boolean question includes ask_user with Yes/No options."""
        defn = ContextDefinition(
            type=ContextType.BOOLEAN,
            prompt="Does this project make official releases?",
            hint="Set to true if you publish versioned releases",
            affects=["CTRL-01"],
        )
        req = ContextPromptRequest(
            key="has_releases",
            definition=defn,
            control_ids=["CTRL-01"],
            priority=1,
        )
        question = _build_context_question(req)

        assert "ask_user" in question
        ask = question["ask_user"]
        assert ask["question"] == (
            "Does this project make official releases? "
            "Set to true if you publish versioned releases"
        )
        assert ask["header"] == "Releases"
        assert len(ask["options"]) == 2
        assert ask["options"][0]["label"] == "Yes"
        assert ask["options"][0]["description"] == "Yes, this applies"
        assert ask["options"][1]["label"] == "No"
        assert ask["options"][1]["description"] == "No, this does not apply"
        assert ask["multiSelect"] is False

    def test_enum_question_with_more_than_four_values_names_every_value(self) -> None:
        """The selector shows 4 values and its question names them all, each typeable under Other (FR-015)."""
        values = ["github", "gitlab", "jenkins", "circleci", "azure", "travis"]
        defn = ContextDefinition(
            type=ContextType.ENUM,
            prompt="What CI/CD system does this project use?",
            values=values,
            affects=["CTRL-01"],
        )
        req = ContextPromptRequest(
            key="ci_provider",
            definition=defn,
            control_ids=["CTRL-01"],
            priority=1,
        )
        question = _build_context_question(req)

        ask = question["ask_user"]
        assert [o["label"] for o in ask["options"]] == values[:4]
        assert "Other" in ask["question"]
        assert question["allowed_values"] == values
        for value in values:
            assert value in ask["question"]

    def test_confirm_question_has_ask_user_accept_reject(self) -> None:
        """A detected candidate is asked as Yes/No; the options name its origin, not its value (feature 042, FR-013)."""
        defn = ContextDefinition(
            type=ContextType.STRING,
            prompt="What CI provider?",
            auto_detect=True,
            affects=["CTRL-01"],
        )
        req = ContextPromptRequest(
            key="ci_provider",
            definition=defn,
            control_ids=["CTRL-01"],
            priority=1,
            candidate=_detected("ci_provider", "github"),
        )
        question = _build_context_question(req)

        assert "ask_user" in question
        ask = question["ask_user"]
        assert ask["options"][0]["label"] == "Yes"
        assert "github" not in json.dumps(ask)
        assert "workflow directory" in ask["options"][0]["description"]
        assert ask["options"][1]["label"] == "No"

    def test_free_text_examples_are_a_format_hint_not_options(self) -> None:
        """Replaces "examples as options": examples are never offered as answers (feature 042, FR-014)."""
        defn = ContextDefinition(
            type=ContextType.STRING,
            prompt="Security contact?",
            examples=["security@example.com", "See SECURITY.md"],
            affects=["CTRL-01"],
        )
        req = ContextPromptRequest(
            key="security_contact",
            definition=defn,
            control_ids=["CTRL-01"],
            priority=1,
        )
        question = _build_context_question(req)

        ask = question["ask_user"]
        assert [o["label"] for o in ask["options"]] == ["Skip for now", "Answer in chat"]
        assert "security@example.com" not in json.dumps(ask)
        assert "See SECURITY.md" not in json.dumps(ask)
        assert question["format_hint"] == "security@example.com or See SECURITY.md"

    def test_free_text_offers_skip_and_chat_and_is_typed_under_other(self) -> None:
        """A free-text question is in the batch; its answer is typed under Other, never chosen."""
        defn = ContextDefinition(
            type=ContextType.STRING,
            prompt="What is the project name?",
            affects=["CTRL-01"],
        )
        req = ContextPromptRequest(
            key="project_name",
            definition=defn,
            control_ids=["CTRL-01"],
            priority=1,
        )
        question = _build_context_question(req)

        ask = question["ask_user"]
        assert ask["question"] == "What is the project name? Type your answer under Other."
        assert [o["label"] for o in ask["options"]] == ["Skip for now", "Answer in chat"]

    def test_header_truncated_at_word_boundary(self) -> None:
        """Header keeps complete words instead of cutting through one."""
        defn = ContextDefinition(
            type=ContextType.BOOLEAN,
            prompt="Has compiled assets?",
            affects=["CTRL-01"],
        )
        req = ContextPromptRequest(
            key="has_compiled_assets",
            definition=defn,
            control_ids=["CTRL-01"],
            priority=1,
        )
        question = _build_context_question(req)

        assert "ask_user" in question
        assert question["ask_user"]["header"] == "Compiled"

    def test_false_oriented_boolean_hint_is_in_question(self) -> None:
        """A hint recommending false is not displayed beside the Yes option."""
        defn = ContextDefinition(
            type=ContextType.BOOLEAN,
            prompt="Does this project have subprojects?",
            hint="Set to false if this is a standalone project",
            affects=["CTRL-01"],
        )
        req = ContextPromptRequest(
            key="has_subprojects",
            definition=defn,
            control_ids=["CTRL-01"],
            priority=1,
        )

        ask = _build_context_question(req)["ask_user"]

        assert ask["question"] == (
            "Does this project have subprojects? "
            "Set to false if this is a standalone project"
        )
        assert ask["options"][0]["description"] == "Yes, this applies"
        assert "false" not in ask["options"][0]["description"].lower()

    def test_boolean_question_uses_effective_no_detect_hint(self) -> None:
        """The selector uses the no-detection hint chosen by the question builder."""
        defn = ContextDefinition(
            type=ContextType.BOOLEAN,
            prompt="Does this project make official releases?",
            hint="Set to true if you publish versioned releases",
            no_detect_hint="No releases were detected. Do you plan to publish releases?",
            auto_detect=True,
            affects=["CTRL-01"],
        )
        req = ContextPromptRequest(
            key="has_releases",
            definition=defn,
            control_ids=["CTRL-01"],
            priority=1,
        )

        ask = _build_context_question(req)["ask_user"]

        assert ask["question"] == (
            "Does this project make official releases? "
            "No releases were detected. Do you plan to publish releases?"
        )
        assert "Set to true" not in ask["question"]

    def test_boolean_question_without_hint_keeps_prompt(self) -> None:
        """A boolean without a hint does not gain extra question text."""
        defn = ContextDefinition(
            type=ContextType.BOOLEAN,
            prompt="Is this project public?",
            affects=["CTRL-01"],
        )
        req = ContextPromptRequest(
            key="is_public",
            definition=defn,
            control_ids=["CTRL-01"],
            priority=1,
        )

        ask = _build_context_question(req)["ask_user"]

        assert ask["question"] == "Is this project public?"


class TestAskUserBatch:
    """Tests for ask_user_batch and answer_mapping in response."""

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_batch_contains_all_ask_user_questions(self, mock_get, mock_path) -> None:
        """ask_user_batch is an array of AskUserQuestion-compatible question objects."""
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        mock_get.return_value = _make_pending(3)

        result = get_pending_data(local_path="/tmp/repo")
        data = _parse_json_from_result(result)

        assert "ask_user_batch" in data
        batch = data["ask_user_batch"]
        assert isinstance(batch, list)
        assert len(batch) == 3
        # Each batch question has the AskUserQuestion structure
        for q in batch:
            assert "question" in q
            assert "header" in q
            assert "options" in q
            assert "multiSelect" in q

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_answer_mapping_matches_batch_indices(self, mock_get, mock_path) -> None:
        """answer_mapping has correct question_index and context_key for each question."""
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        mock_get.return_value = _make_pending(3)

        result = get_pending_data(local_path="/tmp/repo")
        data = _parse_json_from_result(result)

        assert "answer_mapping" in data
        mappings = data["answer_mapping"]
        assert len(mappings) == 3
        for i, m in enumerate(mappings):
            assert m["question_index"] == i
            assert "context_key" in m

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_boolean_answer_mapping_has_value_map(self, mock_get, mock_path) -> None:
        """Boolean questions include value_map for Yes→true, No→false."""
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        # Single boolean question
        defn = ContextDefinition(
            type=ContextType.BOOLEAN,
            prompt="Has releases?",
            affects=["CTRL-01"],
        )
        mock_get.return_value = [ContextPromptRequest(
            key="has_releases",
            definition=defn,
            control_ids=["CTRL-01"],
            priority=1,
        )]

        result = get_pending_data(local_path="/tmp/repo")
        data = _parse_json_from_result(result)

        mapping = data["answer_mapping"][0]
        assert mapping["value_map"] == {"Yes": True, "No": False}

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_confirm_answer_mapping_accepts_by_digest_placeholder(self, mock_get, mock_path) -> None:
        """Replaces "Yes maps to the detected value": Yes accepts the candidate by digest (feature 042, R6)."""
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        defn = ContextDefinition(
            type=ContextType.STRING,
            prompt="CI provider?",
            auto_detect=True,
            affects=["CTRL-01"],
        )
        mock_get.return_value = [ContextPromptRequest(
            key="ci_provider",
            definition=defn,
            control_ids=["CTRL-01"],
            priority=1,
            candidate=_detected("ci_provider", "github"),
        )]

        result = get_pending_data(local_path="/tmp/repo")
        data = _parse_json_from_result(result)

        mapping = data["answer_mapping"][0]
        assert mapping["value_map"]["Yes"] == {"accept_candidates": {"ci_provider": "<candidate.digest>"}}
        assert mapping["value_map"]["No"] == "ASK_USER_FOR_VALUE"

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_free_text_question_is_in_the_batch(self, mock_get, mock_path) -> None:
        """A free-text question is asked in the same round as the others."""
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        defn = ContextDefinition(
            type=ContextType.STRING,
            prompt="Project name?",
            affects=["CTRL-01"],
        )
        mock_get.return_value = [ContextPromptRequest(
            key="project_name",
            definition=defn,
            control_ids=["CTRL-01"],
            priority=1,
        )]

        result = get_pending_data(local_path="/tmp/repo")
        data = _parse_json_from_result(result)

        assert len(data["ask_user_batch"]) == 1
        assert data["answer_mapping"] == [
            {
                "question_index": 0,
                "context_key": "project_name",
                "value_map": {"Skip for now": "SKIP", "Answer in chat": "ASK_USER_FOR_VALUE"},
            }
        ]


class TestTomlDefinitionOrder:
    """Tests for TOML definition order sorting."""

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_questions_sorted_by_toml_order(self, mock_get, mock_path) -> None:
        """Questions are sorted by TOML definition order, not priority."""
        mock_path.return_value.resolve.return_value = "/tmp/repo"

        # Create questions with keys in reverse TOML order but high priority
        items = []
        for key in reversed(["has_subprojects", "maintainers", "ci_provider"]):
            defn = ContextDefinition(
                type=ContextType.BOOLEAN,
                prompt=f"{key}?",
                affects=["CTRL-01"],
            )
            items.append(ContextPromptRequest(
                key=key,
                definition=defn,
                control_ids=["CTRL-01"],
                priority=10,  # all same priority
            ))
        mock_get.return_value = items

        result = get_pending_data(local_path="/tmp/repo", limit=0)
        data = _parse_json_from_result(result)

        # answer_mapping preserves the order of ask_user_batch
        keys = [m["context_key"] for m in data["answer_mapping"]]
        # Should be in TOML order: maintainers, has_subprojects, ci_provider
        assert keys == ["maintainers", "has_subprojects", "ci_provider"]

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_unknown_keys_sort_to_end(self, mock_get, mock_path) -> None:
        """Keys not in TOML order list sort after known keys."""
        mock_path.return_value.resolve.return_value = "/tmp/repo"

        items = []
        for key in ["custom_key", "maintainers"]:
            defn = ContextDefinition(
                type=ContextType.BOOLEAN,
                prompt=f"{key}?",
                affects=["CTRL-01"],
            )
            items.append(ContextPromptRequest(
                key=key,
                definition=defn,
                control_ids=["CTRL-01"],
                priority=1,
            ))
        mock_get.return_value = items

        result = get_pending_data(local_path="/tmp/repo", limit=0)
        data = _parse_json_from_result(result)

        keys = [m["context_key"] for m in data["answer_mapping"]]
        assert keys == ["maintainers", "custom_key"]

    def test_context_key_order_is_every_framework_key(self) -> None:
        """Replaces the fixed list of eight keys: the order comes from the definitions (feature 042, R7)."""
        order = _context_key_order()
        assert order[0] == "maintainers"
        assert "platform" in order
        assert "license_type" in order, "feature 043 T055c: a LICENSE is created only for a confirmed license"
        assert len(order) == len(set(order)) == 10


class TestGetPendingDataProcedure:
    """The result carries the steps to follow (framework-design 7.10)."""

    def _candidate_request(self) -> ContextPromptRequest:
        return ContextPromptRequest(
            key="ci_provider",
            definition=ContextDefinition(
                type=ContextType.STRING, prompt="What CI provider?", auto_detect=True, affects=["CTRL-01"]
            ),
            control_ids=["CTRL-01"],
            priority=1,
            candidate=_detected("ci_provider", "detected-ci-value"),
        )

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_procedure_names_the_repository_the_caller_named(self, mock_get, mock_path) -> None:
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        mock_get.return_value = _make_pending(2)

        data = _parse_json_from_result(get_pending_data(local_path="/tmp/repo", owner="acme", repo="widget"))

        text = "\n".join(data["procedure"])
        assert 'confirm_project_data(owner="acme", repo="widget", local_path="/tmp/repo"' in text
        assert 'get_pending_data(owner="acme", repo="widget", local_path="/tmp/repo")' in text

    @patch("darnit.core.utils.detect_owner_repo", return_value=("remote-owner", "remote-repo"))
    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_procedure_never_names_a_repository_read_from_the_remote(self, mock_get, mock_path, _detect) -> None:
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        mock_get.return_value = _make_pending(2)

        data = _parse_json_from_result(get_pending_data(local_path="/tmp/repo"))

        text = "\n".join(data["procedure"])
        assert "remote-owner" not in text
        assert "remote-repo" not in text
        assert "owner=<owner of the audited repository>" in text

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_procedure_holds_no_candidate_value(self, mock_get, mock_path) -> None:
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        mock_get.return_value = [self._candidate_request()]

        data = _parse_json_from_result(get_pending_data(local_path="/tmp/repo", owner="acme", repo="widget"))

        assert "detected-ci-value" not in json.dumps(data["procedure"])
        assert "accept_candidates" in "\n".join(data["procedure"])

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_complete_result_carries_the_procedure(self, mock_get, mock_path) -> None:
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        mock_get.return_value = []

        data = json.loads(get_pending_data(local_path="/tmp/repo", owner="acme", repo="widget"))

        assert data["status"] == "complete"
        assert any("stored_unconfirmed" in step for step in data["procedure"])

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_directive_defers_to_the_procedure(self, mock_get, mock_path) -> None:
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        mock_get.return_value = _make_pending(1)

        result = get_pending_data(local_path="/tmp/repo")

        assert result.startswith(_LLM_DIRECTIVE_PREFIX)
        assert '"procedure"' in _LLM_DIRECTIVE_PREFIX


class TestConfirmProjectDataNextStep:
    @pytest.fixture(autouse=True)
    def _git_repo(self, tmp_path) -> None:
        subprocess.run(["git", "init", "-q", str(tmp_path)], check=True)

    def test_result_names_the_next_get_pending_data_call(self, tmp_path) -> None:
        from darnit_baseline.tools import confirm_project_data

        result = confirm_project_data(local_path=str(tmp_path), maintainers="@someone")

        assert "refused" in result
        assert "Next: call get_pending_data(owner=<owner of the audited repository>" in result
        assert f'local_path="{tmp_path.resolve()}"' in result

    def test_neutral_tool_names_no_get_pending_data_call(self, tmp_path) -> None:
        from darnit.server.tools.project_data import confirm_project_data_impl

        result = confirm_project_data_impl(str(tmp_path), maintainers="@someone", framework_name="openssf-baseline")

        assert "get_pending_data" not in result
