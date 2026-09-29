"""Tests for evaluate_when_clause and context pipeline integration."""

from darnit.sieve.orchestrator import evaluate_when_clause


class TestEvaluateWhenClause:
    """Test the module-level evaluate_when_clause function."""

    def test_empty_when_returns_true(self):
        assert evaluate_when_clause({}, {}) is True

    def test_matching_value_returns_true(self):
        assert evaluate_when_clause(
            {"platform": "github"},
            {"platform": "github"},
        ) is True

    def test_mismatched_value_returns_false(self):
        assert evaluate_when_clause(
            {"platform": "github"},
            {"platform": "gitlab"},
        ) is False

    def test_missing_key_returns_true(self):
        """Missing context key → conservative, run the control."""
        assert evaluate_when_clause(
            {"platform": "github"},
            {},
        ) is True

    def test_multiple_keys_all_match(self):
        assert evaluate_when_clause(
            {"has_releases": True, "platform": "github"},
            {"has_releases": True, "platform": "github"},
        ) is True

    def test_multiple_keys_one_mismatch(self):
        assert evaluate_when_clause(
            {"has_releases": True, "platform": "github"},
            {"has_releases": True, "platform": "gitlab"},
        ) is False

    def test_multiple_keys_one_missing(self):
        """One matching, one missing → still True (conservative)."""
        assert evaluate_when_clause(
            {"has_releases": True, "platform": "github"},
            {"has_releases": True},
        ) is True

    def test_boolean_true(self):
        assert evaluate_when_clause(
            {"has_subprojects": True},
            {"has_subprojects": True},
        ) is True

    def test_boolean_false(self):
        assert evaluate_when_clause(
            {"has_subprojects": True},
            {"has_subprojects": False},
        ) is False
