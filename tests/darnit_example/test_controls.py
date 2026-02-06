"""Tests for Python-defined controls in darnit-example."""

import pytest

from darnit.sieve.models import PassOutcome


class TestReadmeHasDescription:
    """Tests for PH-DOC-03: ReadmeHasDescription."""

    @pytest.mark.unit
    def test_pass_with_description(self, make_context):
        """README with substantive content should pass."""
        ctx = make_context({
            "README.md": "# My Project\n\nThis project provides a tool for managing compliance checks across open source repositories.\n"
        })
        # Import the module to register controls, then get the check
        from darnit.sieve.registry import get_control_registry
        from darnit_example.controls import level1  # noqa: F401

        registry = get_control_registry()
        spec = registry.get("PH-DOC-03")
        assert spec is not None

        # Execute the deterministic pass (first pass)
        result = spec.passes[0].execute(ctx)
        assert result.outcome == PassOutcome.PASS

    @pytest.mark.unit
    def test_fail_with_title_only(self, make_context):
        """README with only a title should fail."""
        ctx = make_context({"README.md": "# My Project\n"})
        from darnit.sieve.registry import get_control_registry
        from darnit_example.controls import level1  # noqa: F401

        registry = get_control_registry()
        spec = registry.get("PH-DOC-03")
        result = spec.passes[0].execute(ctx)
        assert result.outcome == PassOutcome.FAIL

    @pytest.mark.unit
    def test_fail_with_no_readme(self, make_context):
        """No README at all should fail."""
        ctx = make_context()
        from darnit.sieve.registry import get_control_registry
        from darnit_example.controls import level1  # noqa: F401

        registry = get_control_registry()
        spec = registry.get("PH-DOC-03")
        result = spec.passes[0].execute(ctx)
        assert result.outcome == PassOutcome.FAIL

    @pytest.mark.unit
    def test_pattern_pass_with_good_structure(self, make_context):
        """README with multiple sections should pass pattern check."""
        ctx = make_context({
            "README.md": "# Project\n\nDescription here.\n\n## Installation\n\npip install it\n\n## Usage\n\nUse it.\n"
        })
        from darnit.sieve.registry import get_control_registry
        from darnit_example.controls import level1  # noqa: F401

        registry = get_control_registry()
        spec = registry.get("PH-DOC-03")
        # Pattern pass is the second pass
        result = spec.passes[1].execute(ctx)
        assert result.outcome == PassOutcome.PASS


class TestCIConfigExists:
    """Tests for PH-CI-01: CIConfigExists."""

    @pytest.mark.unit
    def test_pass_with_github_actions(self, make_context):
        """GitHub Actions workflow should be detected."""
        ctx = make_context({
            ".github/workflows/ci.yml": "name: CI\non: push\n"
        })
        from darnit.sieve.registry import get_control_registry
        from darnit_example.controls import level1  # noqa: F401

        registry = get_control_registry()
        spec = registry.get("PH-CI-01")
        assert spec is not None

        result = spec.passes[0].execute(ctx)
        assert result.outcome == PassOutcome.PASS

    @pytest.mark.unit
    def test_pass_with_gitlab_ci(self, make_context):
        """GitLab CI config should be detected."""
        ctx = make_context({".gitlab-ci.yml": "stages:\n  - test\n"})
        from darnit.sieve.registry import get_control_registry
        from darnit_example.controls import level1  # noqa: F401

        registry = get_control_registry()
        spec = registry.get("PH-CI-01")
        result = spec.passes[0].execute(ctx)
        assert result.outcome == PassOutcome.PASS

    @pytest.mark.unit
    def test_fail_with_no_ci(self, make_context):
        """No CI config should fail."""
        ctx = make_context()
        from darnit.sieve.registry import get_control_registry
        from darnit_example.controls import level1  # noqa: F401

        registry = get_control_registry()
        spec = registry.get("PH-CI-01")
        result = spec.passes[0].execute(ctx)
        assert result.outcome == PassOutcome.FAIL
