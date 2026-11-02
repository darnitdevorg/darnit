"""Unit tests for human feedback handlers (darnit.agent.feedback)."""

from __future__ import annotations

import pytest

from darnit.agent.feedback import (
    FeedbackQuestion,
    HumanFeedback,
    InteractiveFeedback,
    NonInteractiveFeedback,
    get_feedback_handler,
)


class TestFeedbackQuestion:
    """Tests for the FeedbackQuestion data model."""

    def test_default_attributes(self) -> None:
        question = FeedbackQuestion(control_id="OSPS-GV-01.01", question="Who are the maintainers?")
        assert question.control_id == "OSPS-GV-01.01"
        assert question.question == "Who are the maintainers?"
        assert question.details == ""
        assert question.answer is None

    def test_custom_attributes(self) -> None:
        question = FeedbackQuestion(
            control_id="OSPS-AC-01.01",
            question="Is 2FA enabled for all admins?",
            details="Check organization settings",
            answer="yes",
        )
        assert question.control_id == "OSPS-AC-01.01"
        assert question.question == "Is 2FA enabled for all admins?"
        assert question.details == "Check organization settings"
        assert question.answer == "yes"


class TestHumanFeedbackBase:
    """Tests for the HumanFeedback base class interface."""

    def test_ask_raises_not_implemented(self) -> None:
        handler = HumanFeedback()
        with pytest.raises(NotImplementedError):
            handler.ask("OSPS-GV-01.01", "Who are the maintainers?")

    def test_base_defaults(self) -> None:
        handler = HumanFeedback()
        assert handler.has_pending() is False
        assert handler.summarize() == []


class TestInteractiveFeedback:
    """Tests for interactive terminal prompt feedback."""

    def test_ask_with_answer(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("builtins.input", lambda _: "  alice, bob  ")
        handler = InteractiveFeedback()

        answer = handler.ask("OSPS-GV-01.01", "Who are the maintainers?", details="List usernames")

        assert answer == "alice, bob"
        assert handler.has_pending() is False
        summary = handler.summarize()
        assert len(summary) == 1
        assert summary[0].control_id == "OSPS-GV-01.01"
        assert summary[0].answer == "alice, bob"

    def test_ask_skip_empty_input(self, monkeypatch: pytest.MonkeyPatch) -> None:
        monkeypatch.setattr("builtins.input", lambda _: "   ")
        handler = InteractiveFeedback()

        answer = handler.ask("OSPS-GV-01.01", "Who are the maintainers?")

        assert answer is None
        assert handler.has_pending() is True
        summary = handler.summarize()
        assert len(summary) == 1
        assert summary[0].answer is None

    def test_ask_handles_eof_error(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_eof(_: str) -> str:
            raise EOFError

        monkeypatch.setattr("builtins.input", raise_eof)
        handler = InteractiveFeedback()

        answer = handler.ask("OSPS-GV-01.01", "Who are the maintainers?")

        assert answer is None
        assert handler.has_pending() is True
        assert handler.summarize()[0].answer is None

    def test_ask_handles_keyboard_interrupt(self, monkeypatch: pytest.MonkeyPatch) -> None:
        def raise_interrupt(_: str) -> str:
            raise KeyboardInterrupt

        monkeypatch.setattr("builtins.input", raise_interrupt)
        handler = InteractiveFeedback()

        answer = handler.ask("OSPS-GV-01.01", "Who are the maintainers?")

        assert answer is None
        assert handler.has_pending() is True
        assert handler.summarize()[0].answer is None


class TestNonInteractiveFeedback:
    """Tests for non-interactive deferred question collection."""

    def test_ask_queues_question_without_prompting(self) -> None:
        handler = NonInteractiveFeedback()
        assert handler.has_pending() is False

        answer = handler.ask(
            "OSPS-AC-02.01",
            "What is the branch protection policy?",
            details="Requires admin confirmation",
        )

        assert answer is None
        assert handler.has_pending() is True
        summary = handler.summarize()
        assert len(summary) == 1
        assert summary[0].control_id == "OSPS-AC-02.01"
        assert summary[0].question == "What is the branch protection policy?"
        assert summary[0].details == "Requires admin confirmation"
        assert summary[0].answer is None

    def test_format_summary_empty(self) -> None:
        handler = NonInteractiveFeedback()
        assert handler.format_summary() == "No human feedback required."

    def test_format_summary_with_questions(self) -> None:
        handler = NonInteractiveFeedback()
        handler.ask("OSPS-GV-01.01", "Who are maintainers?", details="Core team")
        handler.ask("OSPS-AC-01.01", "Is 2FA enabled?")

        formatted = handler.format_summary()

        assert "Human feedback required (2 items):" in formatted
        assert "Control: OSPS-GV-01.01" in formatted
        assert "Question: Who are maintainers?" in formatted
        assert "Details: Core team" in formatted
        assert "Control: OSPS-AC-01.01" in formatted
        assert "Question: Is 2FA enabled?" in formatted


class TestGetFeedbackHandler:
    """Tests for the feedback handler factory function."""

    def test_interactive_mode(self) -> None:
        handler = get_feedback_handler("interactive")
        assert isinstance(handler, InteractiveFeedback)

    def test_noninteractive_mode(self) -> None:
        handler = get_feedback_handler("noninteractive")
        assert isinstance(handler, NonInteractiveFeedback)

    def test_unknown_mode_defaults_to_noninteractive(self) -> None:
        handler = get_feedback_handler("batch_queue")
        assert isinstance(handler, NonInteractiveFeedback)
