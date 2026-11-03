"""Control-level `when` through the shared evaluator (framework-design 5.1.1)."""

from darnit.config.when_evaluator import evaluate_when


class TestEvaluateWhenClause:
    """Control-level semantics: a missing key does not exclude."""

    def test_empty_when_returns_true(self):
        assert evaluate_when({}, {}) is True

    def test_matching_value_returns_true(self):
        assert evaluate_when(
            {"platform": "github"},
            {"platform": "github"},
        ) is True

    def test_mismatched_value_returns_false(self):
        assert evaluate_when(
            {"platform": "github"},
            {"platform": "gitlab"},
        ) is False

    def test_missing_key_returns_true(self):
        """Missing context key → conservative, run the control."""
        assert evaluate_when(
            {"platform": "github"},
            {},
        ) is True

    def test_multiple_keys_all_match(self):
        assert evaluate_when(
            {"has_releases": True, "platform": "github"},
            {"has_releases": True, "platform": "github"},
        ) is True

    def test_multiple_keys_one_mismatch(self):
        assert evaluate_when(
            {"has_releases": True, "platform": "github"},
            {"has_releases": True, "platform": "gitlab"},
        ) is False

    def test_multiple_keys_one_missing(self):
        """One matching, one missing → still True (conservative)."""
        assert evaluate_when(
            {"has_releases": True, "platform": "github"},
            {"has_releases": True},
        ) is True

    def test_boolean_true(self):
        assert evaluate_when(
            {"has_subprojects": True},
            {"has_subprojects": True},
        ) is True

    def test_boolean_false(self):
        assert evaluate_when(
            {"has_subprojects": True},
            {"has_subprojects": False},
        ) is False
