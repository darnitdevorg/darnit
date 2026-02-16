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


class TestFlattenUserContext:
    """Test the flatten_user_context helper."""

    def test_ci_provider_remapped(self):
        from darnit.config.context_schema import ContextValue
        from darnit.config.context_storage import flatten_user_context

        context = {
            "ci": {"provider": ContextValue.user_confirmed("github")},
        }
        flat = flatten_user_context(context)
        assert flat == {"ci_provider": "github"}

    def test_bare_keys_preserved(self):
        from darnit.config.context_schema import ContextValue
        from darnit.config.context_storage import flatten_user_context

        context = {
            "build": {
                "has_releases": ContextValue.user_confirmed(True),
                "has_compiled_assets": ContextValue.user_confirmed(False),
            },
            "platform": {
                "platform": ContextValue.user_confirmed("github"),
                "primary_language": ContextValue.user_confirmed("python"),
            },
        }
        flat = flatten_user_context(context)
        assert flat["has_releases"] is True
        assert flat["has_compiled_assets"] is False
        assert flat["platform"] == "github"
        assert flat["primary_language"] == "python"

    def test_empty_context(self):
        from darnit.config.context_storage import flatten_user_context

        assert flatten_user_context({}) == {}
