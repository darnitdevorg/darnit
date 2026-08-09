"""Contract tests for QuestionResolver Protocol (feature 027 T006).

Verifies contract QR-1..QR-27 from contracts/question-resolver-protocol.md
at the Protocol boundary. Driver-level assertions live in test_driver.py.
"""

from __future__ import annotations

import asyncio
from collections.abc import Callable

from darnit.harness.question_resolvers import (
    Answer,
    QuestionResolver,
)


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


class TestQR1ThroughQR4NameAndResolveShape:
    """QR-1..QR-4: name attribute + async resolve + isinstance recognition."""

    def test_mock_answering_conforms(
        self, mock_answering_resolver: QuestionResolver,
    ) -> None:
        assert isinstance(mock_answering_resolver, QuestionResolver)
        assert hasattr(mock_answering_resolver, "name")
        assert isinstance(mock_answering_resolver.name, str)

    def test_mock_skipping_conforms(
        self, mock_skipping_resolver: QuestionResolver,
    ) -> None:
        assert isinstance(mock_skipping_resolver, QuestionResolver)

    def test_mock_erroring_conforms(
        self, mock_erroring_resolver: Callable[..., QuestionResolver],
    ) -> None:
        r = mock_erroring_resolver()
        assert isinstance(r, QuestionResolver)


class TestQR5AndQR6ReturnSemantics:
    """QR-5: None => skip. QR-6: Answer(non-empty) => answered."""

    def test_none_return_produces_skip_semantic(
        self, mock_skipping_resolver: QuestionResolver,
    ) -> None:
        result = _run(mock_skipping_resolver.resolve(question=None))
        assert result is None

    def test_answer_return_carries_expected_shape(
        self, mock_answering_resolver: QuestionResolver,
    ) -> None:
        result = _run(mock_answering_resolver.resolve(question=None))
        assert isinstance(result, Answer)
        assert result.value  # non-empty
        assert result.authority == "asserted"


class TestQR9ExceptionPropagation:
    """QR-9: resolver exception is expected to propagate; the driver catches."""

    def test_erroring_resolver_raises_from_resolve(
        self, mock_erroring_resolver: Callable[..., QuestionResolver],
    ) -> None:
        r = mock_erroring_resolver(exception_message="propagates")
        try:
            _run(r.resolve(question=None))
        except RuntimeError as exc:
            assert "propagates" in str(exc)
        else:
            raise AssertionError("resolver should have raised")


class TestQR26ProtocolShapeV1:
    """QR-26: v1 exports exactly these public names from question_resolvers."""

    def test_module_exports_the_four_public_names(self) -> None:
        import darnit.harness.question_resolvers as qr

        assert set(qr.__all__) == {
            "Answer",
            "ResolutionTrailEntry",
            "QuestionResolver",
            "InteractiveAborted",
        }
