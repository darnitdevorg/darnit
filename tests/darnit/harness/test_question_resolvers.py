"""Tests for the QuestionResolver Protocol + entities (feature 027 T005).

Covers data-model.md sections 1-3, 8. Contract QR-1..QR-4, QR-26.
"""

from __future__ import annotations

import json

import pytest
from pydantic import ValidationError

from darnit.harness.question_resolvers import (
    Answer,
    InteractiveAborted,
    QuestionResolver,
    ResolutionTrailEntry,
)


class TestAnswer:
    def test_accepts_non_empty_string(self) -> None:
        a = Answer(value="v", origin="o")
        assert a.value == "v"
        assert a.origin == "o"

    def test_default_authority_is_asserted(self) -> None:
        """SC-003 at the model layer: every Answer defaults to authority='asserted'."""
        a = Answer(value="v", origin="o")
        assert a.authority == "asserted"

    def test_rejects_other_authority_dispositive(self) -> None:
        """FR-009 enforcement: Literal['asserted'] blocks any other value."""
        with pytest.raises(ValidationError):
            Answer(value="v", origin="o", authority="dispositive")  # type: ignore[arg-type]

    def test_rejects_other_authority_suggestive(self) -> None:
        with pytest.raises(ValidationError):
            Answer(value="v", origin="o", authority="suggestive")  # type: ignore[arg-type]

    def test_extra_fields_forbidden(self) -> None:
        with pytest.raises(ValidationError):
            Answer(value="v", origin="o", extra_field="nope")  # type: ignore[call-arg]

    def test_json_roundtrip_includes_authority(self) -> None:
        a = Answer(value="v", origin="o")
        payload = json.loads(a.model_dump_json())
        assert payload == {"value": "v", "origin": "o", "authority": "asserted"}


class TestResolutionTrailEntry:
    def test_accepts_answered(self) -> None:
        e = ResolutionTrailEntry(resolver_name="r", outcome="answered")
        assert e.outcome == "answered"
        assert e.error_summary is None

    def test_accepts_skipped(self) -> None:
        e = ResolutionTrailEntry(resolver_name="r", outcome="skipped")
        assert e.outcome == "skipped"

    def test_accepts_errored_with_summary(self) -> None:
        e = ResolutionTrailEntry(
            resolver_name="r", outcome="errored", error_summary="boom",
        )
        assert e.error_summary == "boom"

    def test_errored_without_summary_rejected(self) -> None:
        """RT-6: outcome='errored' requires a non-empty error_summary."""
        with pytest.raises(ValidationError):
            ResolutionTrailEntry(resolver_name="r", outcome="errored")

    def test_errored_with_empty_summary_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ResolutionTrailEntry(
                resolver_name="r", outcome="errored", error_summary="",
            )

    def test_answered_with_summary_rejected(self) -> None:
        """The reverse invariant: only errored may carry a summary."""
        with pytest.raises(ValidationError):
            ResolutionTrailEntry(
                resolver_name="r", outcome="answered", error_summary="oops",
            )

    def test_skipped_with_summary_rejected(self) -> None:
        with pytest.raises(ValidationError):
            ResolutionTrailEntry(
                resolver_name="r", outcome="skipped", error_summary="oops",
            )

    def test_json_roundtrip(self) -> None:
        e = ResolutionTrailEntry(
            resolver_name="r", outcome="errored", error_summary="boom",
        )
        payload = json.loads(e.model_dump_json())
        assert payload == {
            "resolver_name": "r",
            "outcome": "errored",
            "error_summary": "boom",
        }


class TestQuestionResolverProtocol:
    def test_class_with_name_and_resolve_conforms(self) -> None:
        class Good:
            name = "good"

            async def resolve(self, question: object) -> Answer | None:
                return None

        assert isinstance(Good(), QuestionResolver)

    def test_class_missing_resolve_does_not_conform(self) -> None:
        class Bad:
            name = "bad"

        assert not isinstance(Bad(), QuestionResolver)

    def test_class_missing_name_does_not_conform(self) -> None:
        class NoName:
            async def resolve(self, question: object) -> Answer | None:
                return None

        assert not isinstance(NoName(), QuestionResolver)


class TestInteractiveAborted:
    def test_is_exception_subclass(self) -> None:
        assert issubclass(InteractiveAborted, Exception)

    def test_can_be_raised_and_caught(self) -> None:
        with pytest.raises(InteractiveAborted):
            raise InteractiveAborted("test")
