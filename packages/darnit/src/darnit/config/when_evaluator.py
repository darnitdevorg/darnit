"""Evaluate ``when`` clauses against project context.

Provides a single ``evaluate_when()`` function used by both the sieve
orchestrator (for pass handler dispatch) and the remediation executor
(for remediation handler dispatch).

Evaluation rules:
- str context + str when  → exact equality
- str context + list when → context value in the list
- bool context + bool when → exact equality
- list context + str when  → scalar is contained in the list
- list context + list when → all when-values are in the context list (subset)
- missing key             → condition not met (returns False)

Multiple keys in a single ``when`` clause are AND-ed.
"""

from __future__ import annotations

from typing import Any

from darnit.core.logging import get_logger

logger = get_logger("config.when_evaluator")


def evaluate_when(when_clause: dict[str, Any] | None, context: dict[str, Any]) -> bool:
    """Evaluate a ``when`` clause against a flat context dict.

    Args:
        when_clause: Mapping of context keys to expected values.
            ``None`` or empty dict means "always matches".
        context: Flat dict of context key → value (auto-detected +
            user-confirmed, merged by the caller).

    Returns:
        ``True`` if all conditions match (or no conditions), ``False`` otherwise.
    """
    if not when_clause:
        return True

    for key, expected in when_clause.items():
        if key not in context:
            logger.debug(
                "when clause key '%s' not found in context — condition not met",
                key,
            )
            return False

        actual = context[key]

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
