"""Tests for darnit.config.when_evaluator module."""

from darnit.config.when_evaluator import evaluate_when


class TestEvaluateWhenBasic:
    """Basic matching rules."""

    def test_none_when_returns_true(self):
        assert evaluate_when(None, {"a": 1}) is True

    def test_empty_when_returns_true(self):
        assert evaluate_when({}, {"a": 1}) is True

    def test_str_equality_match(self):
        assert evaluate_when(
            {"primary_language": "go"},
            {"primary_language": "go"},
        ) is True

    def test_str_equality_mismatch(self):
        assert evaluate_when(
            {"primary_language": "go"},
            {"primary_language": "python"},
        ) is False

    def test_bool_equality_match(self):
        assert evaluate_when(
            {"is_library": True},
            {"is_library": True},
        ) is True

    def test_bool_equality_mismatch(self):
        assert evaluate_when(
            {"is_library": True},
            {"is_library": False},
        ) is False

    def test_missing_key_returns_false(self):
        """Handler-level: missing context key → skip handler (conservative)."""
        assert evaluate_when(
            {"primary_language": "go"},
            {},
        ) is False

    def test_missing_key_among_others(self):
        """If any key is missing, the whole clause fails."""
        assert evaluate_when(
            {"primary_language": "go", "platform": "github"},
            {"platform": "github"},
        ) is False


class TestEvaluateWhenListContext:
    """List-valued context (e.g., languages)."""

    def test_scalar_in_list_context(self):
        assert evaluate_when(
            {"languages": "go"},
            {"languages": ["go", "typescript"]},
        ) is True

    def test_scalar_not_in_list_context(self):
        assert evaluate_when(
            {"languages": "rust"},
            {"languages": ["go", "typescript"]},
        ) is False

    def test_empty_list_context_matches_nothing(self):
        assert evaluate_when(
            {"languages": "go"},
            {"languages": []},
        ) is False

    def test_subset_check_passes(self):
        assert evaluate_when(
            {"languages": ["go", "typescript"]},
            {"languages": ["go", "typescript", "python"]},
        ) is True

    def test_subset_check_fails(self):
        assert evaluate_when(
            {"languages": ["go", "rust"]},
            {"languages": ["go", "typescript"]},
        ) is False


class TestEvaluateWhenListWhen:
    """List-valued when clause (e.g., ci_provider = ["github", "gitlab"])."""

    def test_str_context_in_list_when(self):
        assert evaluate_when(
            {"ci_provider": ["github", "gitlab"]},
            {"ci_provider": "gitlab"},
        ) is True

    def test_str_context_not_in_list_when(self):
        assert evaluate_when(
            {"ci_provider": ["github", "gitlab"]},
            {"ci_provider": "circleci"},
        ) is False


class TestEvaluateWhenANDSemantics:
    """Multiple keys are AND-ed."""

    def test_all_match(self):
        assert evaluate_when(
            {"primary_language": "go", "platform": "github"},
            {"primary_language": "go", "platform": "github"},
        ) is True

    def test_one_mismatch(self):
        assert evaluate_when(
            {"primary_language": "go", "platform": "github"},
            {"primary_language": "go", "platform": "gitlab"},
        ) is False

    def test_mixed_types(self):
        assert evaluate_when(
            {"is_library": True, "languages": "go"},
            {"is_library": True, "languages": ["go", "python"]},
        ) is True
