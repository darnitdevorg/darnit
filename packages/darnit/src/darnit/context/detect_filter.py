"""Evaluate `detect_filter` expressions against auto-detected context candidates.

A context key may declare a CEL expression that rejects unwanted detected
values -- `security_contact` declares one to keep `security@example.com` out of
projects whose SECURITY.md came from a template. See issues #165 and #150.

Two distinctions this module exists to preserve:

1. `REJECT` and `UNEVALUABLE` are different outcomes. One means the filter
   judged the value and said no; the other means the filter could not judge it
   at all. Both discard the value, and collapsing them would reproduce the
   defect this module was written to fix -- a guard that does not run looking
   exactly like a guard that passed.

2. A list candidate is filtered element-wise and is NEVER bound whole. CEL's
   `contains` on a list is membership rather than substring, so
   `["a@example.com"].contains("example.com")` is false and the negated filter
   returns true -- binding a list whole KEEPS the value the filter exists to
   reject. That is the same failing-open shape as the original bug.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from enum import Enum
from typing import Any

from darnit.core.logging import get_logger
from darnit.sieve.cel_evaluator import (
    CELCompilationError,
    CELEvaluationError,
    CELEvaluator,
    CELProgram,
    CELTimeoutError,
)

logger = get_logger("context.detect_filter")


class FilterDecision(str, Enum):
    """The outcome of evaluating one candidate against a filter."""

    KEEP = "keep"
    REJECT = "reject"
    UNEVALUABLE = "unevaluable"


@dataclass
class FilterOutcome:
    """What the filter concluded about a candidate.

    ``value`` is the surviving candidate, which for a list is the subset of
    elements that passed. ``discarded`` names what was dropped so the caller can
    report it -- a maintainer list arriving shorter than the evidence suggests
    should be explicable.
    """

    decision: FilterDecision
    value: Any = None
    discarded: list[Any] = field(default_factory=list)
    reason: str = ""


def _compile(expression: str, key: str) -> CELProgram | None:
    """Compile once per key, not once per element.

    A malformed expression is then reported once naming the key, rather than
    once for every element of a list.
    """
    try:
        return CELEvaluator().compile(expression)
    except (CELCompilationError, Exception) as exc:  # noqa: BLE001 - see below
        # `evaluate_cel` raises CELCompilationError on a syntax error rather
        # than returning a failed result, so this path is not optional. A
        # framework author's typo must not propagate out of context collection
        # and abort the audit.
        logger.warning(
            "context key '%s': detect_filter could not be compiled, so no "
            "detected value can be accepted for this key: %s: %s",
            key,
            type(exc).__name__,
            exc,
        )
        return None


def _evaluate_scalar(program: CELProgram, candidate: Any, key: str) -> FilterDecision:
    """Evaluate one scalar candidate. Never returns KEEP on failure."""
    try:
        result = CELEvaluator().evaluate(program, {"value": candidate})
    except (CELEvaluationError, CELTimeoutError) as exc:
        logger.warning(
            "context key '%s': detect_filter could not be evaluated against a detected value; discarding it: %s",
            key,
            exc,
        )
        return FilterDecision.UNEVALUABLE

    if not result.success:
        # A wrong-typed value or a missing binding lands here rather than
        # raising. Checking only for exceptions would silently treat this as
        # having passed.
        logger.warning(
            "context key '%s': detect_filter could not be evaluated against a detected value; discarding it: %s",
            key,
            result.error,
        )
        return FilterDecision.UNEVALUABLE

    return FilterDecision.KEEP if bool(result.value) else FilterDecision.REJECT


def apply_filter(expression: str | None, candidate: Any, key: str) -> FilterOutcome:
    """Apply a key's detect_filter to one detected candidate.

    Returns the surviving value. A key with no filter is returned untouched --
    no evaluation happens and behaviour is unchanged.
    """
    if not expression:
        return FilterOutcome(decision=FilterDecision.KEEP, value=candidate)

    program = _compile(expression, key)
    if program is None:
        return FilterOutcome(
            decision=FilterDecision.UNEVALUABLE,
            discarded=[candidate],
            reason="filter expression could not be compiled",
        )

    if isinstance(candidate, list):
        kept: list[Any] = []
        dropped: list[Any] = []
        for element in candidate:
            if _evaluate_scalar(program, element, key) is FilterDecision.KEEP:
                kept.append(element)
            else:
                dropped.append(element)

        if not kept:
            return FilterOutcome(
                decision=FilterDecision.REJECT,
                discarded=dropped,
                reason=f"all {len(dropped)} detected value(s) were filtered out",
            )
        return FilterOutcome(
            decision=FilterDecision.KEEP,
            value=kept,
            discarded=dropped,
            reason=(f"{len(dropped)} detected value(s) filtered out" if dropped else ""),
        )

    decision = _evaluate_scalar(program, candidate, key)
    if decision is FilterDecision.KEEP:
        return FilterOutcome(decision=decision, value=candidate)
    return FilterOutcome(
        decision=decision,
        discarded=[candidate],
        reason=(
            "value rejected by detect_filter"
            if decision is FilterDecision.REJECT
            else "detect_filter could not be evaluated against this value"
        ),
    )
