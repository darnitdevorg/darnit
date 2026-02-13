"""Tests for custom sieve handlers in darnit-example."""

import pytest

from darnit.sieve.handler_registry import HandlerContext, HandlerResultStatus
from darnit_example.handlers import (
    ci_config_handler,
    readme_description_handler,
    readme_quality_handler,
)


def _make_handler_context(tmp_path, files=None):
    """Create a HandlerContext pointing at a temp directory with optional files."""
    if files:
        for name, content in files.items():
            filepath = tmp_path / name
            filepath.parent.mkdir(parents=True, exist_ok=True)
            filepath.write_text(content, encoding="utf-8")
    return HandlerContext(local_path=str(tmp_path))


class TestReadmeHasDescription:
    """Tests for PH-DOC-03: ReadmeHasDescription handler."""

    @pytest.mark.unit
    def test_pass_with_description(self, tmp_path):
        """README with substantive content should pass."""
        ctx = _make_handler_context(tmp_path, {
            "README.md": "# My Project\n\nThis project provides a tool for managing compliance checks across open source repositories.\n"
        })
        result = readme_description_handler({}, ctx)
        assert result.status == HandlerResultStatus.PASS

    @pytest.mark.unit
    def test_fail_with_title_only(self, tmp_path):
        """README with only a title should fail."""
        ctx = _make_handler_context(tmp_path, {"README.md": "# My Project\n"})
        result = readme_description_handler({}, ctx)
        assert result.status == HandlerResultStatus.FAIL

    @pytest.mark.unit
    def test_fail_with_no_readme(self, tmp_path):
        """No README at all should fail."""
        ctx = _make_handler_context(tmp_path)
        result = readme_description_handler({}, ctx)
        assert result.status == HandlerResultStatus.FAIL

    @pytest.mark.unit
    def test_pattern_pass_with_good_structure(self, tmp_path):
        """README with multiple sections should pass quality check."""
        ctx = _make_handler_context(tmp_path, {
            "README.md": "# Project\n\nDescription here.\n\n## Installation\n\npip install it\n\n## Usage\n\nUse it.\n"
        })
        result = readme_quality_handler({}, ctx)
        assert result.status == HandlerResultStatus.PASS


class TestCIConfigExists:
    """Tests for PH-CI-01: CIConfigExists handler."""

    @pytest.mark.unit
    def test_pass_with_github_actions(self, tmp_path):
        """GitHub Actions workflow should be detected."""
        ctx = _make_handler_context(tmp_path, {
            ".github/workflows/ci.yml": "name: CI\non: push\n"
        })
        result = ci_config_handler({}, ctx)
        assert result.status == HandlerResultStatus.PASS

    @pytest.mark.unit
    def test_pass_with_gitlab_ci(self, tmp_path):
        """GitLab CI config should be detected."""
        ctx = _make_handler_context(tmp_path, {".gitlab-ci.yml": "stages:\n  - test\n"})
        result = ci_config_handler({}, ctx)
        assert result.status == HandlerResultStatus.PASS

    @pytest.mark.unit
    def test_fail_with_no_ci(self, tmp_path):
        """No CI config should fail."""
        ctx = _make_handler_context(tmp_path)
        result = ci_config_handler({}, ctx)
        assert result.status == HandlerResultStatus.FAIL
