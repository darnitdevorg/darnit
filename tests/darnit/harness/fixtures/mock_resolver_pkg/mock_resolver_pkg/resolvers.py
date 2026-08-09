"""Fixture QuestionResolver implementations for feature 027 SC-002 enforcement.

This package lives OUTSIDE `packages/darnit/src/darnit/harness/` on purpose:
SC-002 requires that a resolver defined outside that directory can be discovered
and invoked without modifying anything under it. See spec.md SC-002 and
test_extensibility_sc002.py.
"""

from __future__ import annotations

from darnit.harness.question_resolvers import Answer, QuestionResolver


class AnsweringResolver:
    """Returns a fixed Answer to every question."""

    name = "mock_answer"

    async def resolve(self, question: object) -> Answer | None:
        return Answer(value="fixed", origin="mock_answer")


class ErroringResolver:
    """Raises on every resolve() call."""

    name = "mock_error"

    async def resolve(self, question: object) -> Answer | None:
        raise RuntimeError("fixture failure")


def build_answer() -> QuestionResolver:
    return AnsweringResolver()


def build_error() -> QuestionResolver:
    return ErroringResolver()
