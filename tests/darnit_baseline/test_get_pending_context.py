"""Tests for get_pending_context batch context collection.

Tests the pagination, LLM directive footer, progress indicator,
presentation hint, ask_user_batch, answer_mapping, and TOML ordering
features for batched AskUserQuestion-based context gathering.
"""

import json
from unittest.mock import patch

from darnit.config.context_schema import (
    ContextDefinition,
    ContextPromptRequest,
    ContextType,
    ContextValue,
)
from darnit_baseline.tools import (
    _CONTEXT_KEY_ORDER,
    _LLM_DIRECTIVE,
    _build_context_question,
    get_pending_context,
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
    """Strip directive footer and parse JSON from get_pending_context result."""
    json_str = result.split("\n---")[0].rstrip()
    return json.loads(json_str)


class TestGetPendingContextPagination:
    """Tests for batch pagination behavior."""

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_default_limit_returns_four_questions(self, mock_get, mock_path) -> None:
        """Default limit=4 returns up to four questions."""
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        mock_get.return_value = _make_pending(5)

        result = get_pending_context(local_path="/tmp/repo")
        data = _parse_json_from_result(result)

        assert data["status"] == "pending"
        assert len(data["questions"]) == 4

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_default_limit_returns_all_if_fewer_than_four(self, mock_get, mock_path) -> None:
        """Default limit=4 returns all questions when fewer than 4 pending."""
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        mock_get.return_value = _make_pending(2)

        result = get_pending_context(local_path="/tmp/repo")
        data = _parse_json_from_result(result)

        assert len(data["questions"]) == 2

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_limit_zero_returns_all(self, mock_get, mock_path) -> None:
        """limit=0 returns all pending questions."""
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        mock_get.return_value = _make_pending(5)

        result = get_pending_context(local_path="/tmp/repo", limit=0)
        data = _parse_json_from_result(result)

        assert data["status"] == "pending"
        assert len(data["questions"]) == 5

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_explicit_limit(self, mock_get, mock_path) -> None:
        """Explicit limit=3 returns at most 3 questions."""
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        mock_get.return_value = _make_pending(5)

        result = get_pending_context(local_path="/tmp/repo", limit=3)
        data = _parse_json_from_result(result)

        assert len(data["questions"]) == 3


class TestGetPendingContextProgress:
    """Tests for progress indicator in response."""

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_progress_included(self, mock_get, mock_path) -> None:
        """Response includes progress object with answered and total."""
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        mock_get.return_value = _make_pending(8)

        result = get_pending_context(local_path="/tmp/repo")
        data = _parse_json_from_result(result)

        assert "progress" in data
        assert data["progress"]["total"] == 8
        assert data["progress"]["answered"] == 0


class TestGetPendingContextDirective:
    """Tests for LLM directive footer."""

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_directive_appended_when_pending(self, mock_get, mock_path) -> None:
        """LLM directive footer is appended when questions are pending."""
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        mock_get.return_value = _make_pending(3)

        result = get_pending_context(local_path="/tmp/repo")

        assert result.endswith(_LLM_DIRECTIVE)
        assert "IMPORTANT" in result
        assert "ask_user_batch" in result

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_no_directive_when_complete(self, mock_get, mock_path) -> None:
        """No directive footer when no questions are pending."""
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        mock_get.return_value = []

        result = get_pending_context(local_path="/tmp/repo")

        assert _LLM_DIRECTIVE not in result
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
        assert ask["question"] == "Does this project make official releases?"
        assert ask["header"] == "Releases"
        assert len(ask["options"]) == 2
        assert ask["options"][0]["label"] == "Yes"
        assert ask["options"][1]["label"] == "No"
        assert ask["multiSelect"] is False

    def test_enum_question_has_ask_user_with_values(self) -> None:
        """Enum question includes ask_user with value options (max 4)."""
        defn = ContextDefinition(
            type=ContextType.ENUM,
            prompt="What CI/CD system does this project use?",
            values=["github", "gitlab", "jenkins", "circleci", "azure", "travis"],
            affects=["CTRL-01"],
        )
        req = ContextPromptRequest(
            key="ci_provider",
            definition=defn,
            control_ids=["CTRL-01"],
            priority=1,
        )
        question = _build_context_question(req)

        assert "ask_user" in question
        ask = question["ask_user"]
        assert ask["header"] == "Ci Provider"
        # Max 4 options shown
        assert len(ask["options"]) == 4
        assert ask["options"][0]["label"] == "github"
        assert ask["options"][3]["label"] == "circleci"

    def test_confirm_question_has_ask_user_accept_reject(self) -> None:
        """Auto-detected confirm question includes ask_user with Accept/Reject."""
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
            current_value=ContextValue.auto_detected(
                value="github", method="detected from .github/workflows/"
            ),
        )
        question = _build_context_question(req)

        assert "ask_user" in question
        ask = question["ask_user"]
        assert ask["options"][0]["label"] == "Yes"
        assert "github" in ask["options"][0]["description"]
        assert ask["options"][1]["label"] == "No"

    def test_free_text_with_examples_has_ask_user(self) -> None:
        """Free text question with examples includes ask_user using examples as options."""
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

        assert "ask_user" in question
        ask = question["ask_user"]
        assert len(ask["options"]) == 2
        assert ask["options"][0]["label"] == "security@example.com"

    def test_free_text_without_examples_has_no_ask_user(self) -> None:
        """Free text question without examples has no ask_user field."""
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

        assert "ask_user" not in question

    def test_header_truncated_to_12_chars(self) -> None:
        """Header is truncated to 12 characters max."""
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
        assert len(question["ask_user"]["header"]) <= 12


class TestAskUserBatch:
    """Tests for ask_user_batch and answer_mapping in response."""

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_batch_contains_all_ask_user_questions(self, mock_get, mock_path) -> None:
        """ask_user_batch.questions aggregates per-question ask_user params."""
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        mock_get.return_value = _make_pending(3)

        result = get_pending_context(local_path="/tmp/repo")
        data = _parse_json_from_result(result)

        assert "ask_user_batch" in data
        batch = data["ask_user_batch"]["questions"]
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

        result = get_pending_context(local_path="/tmp/repo")
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

        result = get_pending_context(local_path="/tmp/repo")
        data = _parse_json_from_result(result)

        mapping = data["answer_mapping"][0]
        assert mapping["value_map"] == {"Yes": True, "No": False}

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_confirm_answer_mapping_has_detected_value(self, mock_get, mock_path) -> None:
        """Confirm questions include value_map with detected value for Yes."""
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
            current_value=ContextValue.auto_detected(value="github", method="detected"),
        )]

        result = get_pending_context(local_path="/tmp/repo")
        data = _parse_json_from_result(result)

        mapping = data["answer_mapping"][0]
        assert mapping["value_map"]["Yes"] == "github"
        assert mapping["value_map"]["No"] == "ASK_USER_FOR_VALUE"

    @patch("darnit_baseline.tools.Path")
    @patch("darnit.config.context_storage.get_pending_context")
    def test_no_batch_when_no_ask_user(self, mock_get, mock_path) -> None:
        """No ask_user_batch field when questions lack ask_user params."""
        mock_path.return_value.resolve.return_value = "/tmp/repo"
        # Free text without examples → no ask_user
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

        result = get_pending_context(local_path="/tmp/repo")
        data = _parse_json_from_result(result)

        assert "ask_user_batch" not in data
        assert "answer_mapping" not in data


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

        result = get_pending_context(local_path="/tmp/repo", limit=0)
        data = _parse_json_from_result(result)

        keys = [q["key"] for q in data["questions"]]
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

        result = get_pending_context(local_path="/tmp/repo", limit=0)
        data = _parse_json_from_result(result)

        keys = [q["key"] for q in data["questions"]]
        assert keys == ["maintainers", "custom_key"]

    def test_context_key_order_has_all_eight_keys(self) -> None:
        """_CONTEXT_KEY_ORDER contains all 8 expected context keys."""
        assert len(_CONTEXT_KEY_ORDER) == 8
        assert _CONTEXT_KEY_ORDER[0] == "maintainers"
        assert _CONTEXT_KEY_ORDER[-1] == "ci_provider"
