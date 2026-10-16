"""Evaluate ``when`` clauses against project context.

The one evaluator for control-level ``when`` (applicability), verification
step ``when``, and remediation handler ``when`` (framework-design 5.1.1).

Evaluation rules:
- str context + str when  → exact equality
- str context + list when → context value in the list
- bool context + bool when → exact equality
- list context + str when  → scalar is contained in the list
- list context + list when → all when-values are in the context list (subset)
- missing key (absent or None) → does not exclude; with
  ``missing_excludes=True`` (remediation handlers) → condition not met

Multiple keys in a single ``when`` clause are AND-ed.
"""

from __future__ import annotations

from collections.abc import Mapping
from typing import Any

from darnit.core.logging import get_logger

logger = get_logger("config.when_evaluator")


def evaluate_when(
    when_clause: Mapping[str, Any] | None,
    context: Mapping[str, Any],
    *,
    missing_excludes: bool = False,
) -> bool:
    """Evaluate a ``when`` clause against a flat context mapping.

    Args:
        when_clause: Mapping of context keys to expected values.
            ``None`` or empty dict means "always matches".
        context: Flat mapping of context key → value. Membership is tested
            before the value is read, so a guarded mapping (the remediation
            executor's) can refuse a key that has no usable value.
        missing_excludes: A key the context does not hold makes the clause
            false. Only remediation handlers set it: acting on an unknown
            value is the damaging direction there. Otherwise a missing key
            does not exclude (the control applies, the step runs).

    Returns:
        ``True`` if no condition excludes, ``False`` otherwise.
    """
    if not when_clause:
        return True

    for key, expected in when_clause.items():
        actual = context.get(key)
        if actual is None:
            if missing_excludes:
                logger.debug("when clause key '%s' not found in context — condition not met", key)
                return False
            logger.debug("when clause key '%s' not found in context — does not exclude", key)
            continue

        if not _match_value(key, actual, expected):
            logger.debug(
                "when clause '%s': actual=%r does not match expected=%r",
                key,
                actual,
                expected,
            )
            return False

    return True


def _match_value(key: str, actual: Any, expected: Any) -> bool:
    """Check if a single context value matches the when-clause expectation."""
    # list context + str expected → containment
    if isinstance(actual, list) and isinstance(expected, str):
        return expected in actual

    # list context + list expected → subset check
    if isinstance(actual, list) and isinstance(expected, list):
        return all(v in actual for v in expected)

    # str context + list expected → membership
    if isinstance(actual, str) and isinstance(expected, list):
        return actual in expected

    # scalar equality (str==str, bool==bool, int==int, etc.)
    return actual == expected
