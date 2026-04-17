"""Tests for template file resolution in RemediationExecutor."""

from unittest.mock import patch

import pytest

from darnit.config.framework_schema import TemplateConfig
from darnit.remediation.executor import RemediationExecutor


@pytest.fixture
def executor_factory(tmp_path):
    """Fixture that builds RemediationExecutor with explicit framework_path and local_path."""
    def _factory(templates, framework_path_str=None, local_path_str=None):
        if local_path_str is None:
            local_path_str = str(tmp_path)

        return RemediationExecutor(
            local_path=local_path_str,
            templates=templates,
            framework_path=framework_path_str
        )
    return _factory


class TestTemplateFileResolution:
    """Verify _get_template_content resolves file paths correctly."""

    def test_relative_file_resolved_to_framework_dir(self, tmp_path, executor_factory):
        """file= relative path resolves against framework TOML directory."""
        # Set up: framework TOML at tmp_path/pkg/framework.toml
        pkg_dir = tmp_path / "pkg"
        pkg_dir.mkdir()
        tmpl_dir = pkg_dir / "templates"
        tmpl_dir.mkdir()
        (tmpl_dir / "hello.tmpl").write_text("Hello $OWNER")

        executor = executor_factory(
            local_path_str=str(tmp_path / "repo"),
            templates={"hello": TemplateConfig(file="templates/hello.tmpl")},
            framework_path_str=str(pkg_dir / "framework.toml"),
        )
        content = executor._get_template_content("hello")
        assert content == "Hello $OWNER"

    def test_absolute_file_rejected(self, tmp_path, executor_factory):
        """Absolute file= path is rejected with ValueError."""
        tmpl_file = tmp_path / "abs_template.tmpl"
        tmpl_file.write_text("Absolute content")

        executor = executor_factory(
            local_path_str=str(tmp_path),
            templates={"abs": TemplateConfig(file=str(tmpl_file))},
            framework_path_str="/some/other/path/framework.toml",
        )
        with pytest.raises(ValueError, match="specifies absolute path"):
            executor._get_template_content("abs")

    def test_path_traversal_dotdot_rejected(self, tmp_path):
        """Parent directory escape attempts are rejected."""
        executor = RemediationExecutor(
            local_path=str(tmp_path),
            templates={"escape": TemplateConfig(file="../outside.tmpl")},
            framework_path=str(tmp_path / "pkg" / "framework.toml"),
        )
        with pytest.raises(ValueError, match="outside framework directory"):
            executor._get_template_content("escape")

    def test_path_traversal_symlink_rejected(self, tmp_path):
        """Symlinks traversing outside the directory are rejected."""
        base_dir = tmp_path / "pkg"
        base_dir.mkdir()
        outside_file = tmp_path / "outside.tmpl"
        outside_file.write_text("outside")

        symlink_file = base_dir / "symlink.tmpl"
        # Create a symlink pointing outside
        symlink_file.symlink_to(outside_file)

        executor = RemediationExecutor(
            local_path=str(tmp_path),
            templates={"symlink": TemplateConfig(file="symlink.tmpl")},
            framework_path=str(base_dir / "framework.toml"),
        )
        with pytest.raises(ValueError, match="resolves to .* outside framework directory"):
            executor._get_template_content("symlink")

    def test_missing_file_returns_none(self, tmp_path, executor_factory):
        """Missing template file returns None with a warning."""
        executor = executor_factory(
            local_path_str=str(tmp_path),
            templates={"missing": TemplateConfig(file="templates/nope.tmpl")},
            framework_path_str=str(tmp_path / "framework.toml"),
        )
        content = executor._get_template_content("missing")
        assert content is None

    def test_fallback_to_local_path_when_no_framework_path(self, tmp_path, executor_factory):
        """When framework_path is None, file resolves relative to local_path."""
        tmpl_dir = tmp_path / "templates"
        tmpl_dir.mkdir()
        (tmpl_dir / "fallback.tmpl").write_text("Fallback content")

        executor = executor_factory(
            local_path_str=str(tmp_path),
            templates={"fb": TemplateConfig(file="templates/fallback.tmpl")},
            # framework_path defaults to None
        )
        content = executor._get_template_content("fb")
        assert content == "Fallback content"

    def test_inline_content_still_works(self, tmp_path, executor_factory):
        """Inline content= is unaffected by framework_path."""
        executor = executor_factory(
            local_path_str=str(tmp_path),
            templates={"inline": TemplateConfig(content="Inline text")},
            framework_path_str="/does/not/matter/framework.toml",
        )
        content = executor._get_template_content("inline")
        assert content == "Inline text"

    def test_unknown_template_returns_none(self, tmp_path, executor_factory):
        """Requesting a non-existent template name returns None."""
        executor = executor_factory(
            local_path_str=str(tmp_path),
            templates={},
        )
        assert executor._get_template_content("nonexistent") is None

    def test_oserror_at_read_time_logs_warning(self, tmp_path, executor_factory, caplog):
        """Simulates race condition: file exists at init but is deleted before read."""
        executor = executor_factory(
            local_path_str=str(tmp_path),
            templates={"race": TemplateConfig(file="templates/race_condition.tmpl")},
            framework_path_str=str(tmp_path / "framework.toml"),
        )

        with patch("builtins.open", side_effect=OSError("Simulated race condition")):
            content = executor._get_template_content("race")

        assert content is None
        assert "Failed to read template file" in caplog.text
        assert "Simulated race condition" in caplog.text
