"""Tests for darnit.config.when_evaluator module."""

import pytest

from darnit.config.when_evaluator import evaluate_when
from darnit.remediation.executor import ConfirmationRequired, GuardedContext


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

    def test_missing_key_does_not_exclude(self):
        """Controls and verification steps: a missing key runs them (framework-design 5.1.1)."""
        assert evaluate_when({"primary_language": "go"}, {}) is True
        assert evaluate_when({"primary_language": "go"}, {"primary_language": None}) is True

    def test_missing_key_among_others_does_not_exclude(self):
        assert evaluate_when(
            {"primary_language": "go", "platform": "github"},
            {"platform": "github"},
        ) is True

    def test_missing_key_does_not_hide_a_mismatch(self):
        assert evaluate_when(
            {"primary_language": "go", "platform": "github"},
            {"platform": "gitlab"},
        ) is False

    def test_missing_key_excludes_a_remediation_handler(self):
        """Remediation handlers: a missing key skips the handler."""
        assert evaluate_when({"primary_language": "go"}, {}, missing_excludes=True) is False
        assert evaluate_when({"primary_language": "go"}, {"primary_language": None}, missing_excludes=True) is False
        assert evaluate_when(
            {"primary_language": "go", "platform": "github"},
            {"platform": "github"},
            missing_excludes=True,
        ) is False

    def test_guarded_context_refuses_a_key_with_no_usable_value(self):
        """The membership test reaches a guarded mapping, so it can stop the remediation."""
        with pytest.raises(ConfirmationRequired):
            evaluate_when({"license_type": "mit"}, GuardedContext({}, {"license_type"}), missing_excludes=True)


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
