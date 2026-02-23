"""Tests for template file resolution in RemediationExecutor."""

from darnit.config.framework_schema import TemplateConfig
from darnit.remediation.executor import RemediationExecutor


class TestTemplateFileResolution:
    """Verify _get_template_content resolves file paths correctly."""

    def test_relative_file_resolved_to_framework_dir(self, tmp_path):
        """file= relative path resolves against framework TOML directory."""
        # Set up: framework TOML at tmp_path/pkg/framework.toml
        pkg_dir = tmp_path / "pkg"
        pkg_dir.mkdir()
        tmpl_dir = pkg_dir / "templates"
        tmpl_dir.mkdir()
        (tmpl_dir / "hello.tmpl").write_text("Hello $OWNER")

        executor = RemediationExecutor(
            local_path=str(tmp_path / "repo"),
            templates={"hello": TemplateConfig(file="templates/hello.tmpl")},
            framework_path=str(pkg_dir / "framework.toml"),
        )
        content = executor._get_template_content("hello")
        assert content == "Hello $OWNER"

    def test_absolute_file_used_as_is(self, tmp_path):
        """Absolute file= path is used directly, ignoring framework_path."""
        tmpl_file = tmp_path / "abs_template.tmpl"
        tmpl_file.write_text("Absolute content")

        executor = RemediationExecutor(
            local_path=str(tmp_path),
            templates={"abs": TemplateConfig(file=str(tmpl_file))},
            framework_path="/some/other/path/framework.toml",
        )
        content = executor._get_template_content("abs")
        assert content == "Absolute content"

    def test_missing_file_returns_none(self, tmp_path):
        """Missing template file returns None with a warning."""
        executor = RemediationExecutor(
            local_path=str(tmp_path),
            templates={"missing": TemplateConfig(file="templates/nope.tmpl")},
            framework_path=str(tmp_path / "framework.toml"),
        )
        content = executor._get_template_content("missing")
        assert content is None

    def test_fallback_to_local_path_when_no_framework_path(self, tmp_path):
        """When framework_path is None, file resolves relative to local_path."""
        tmpl_dir = tmp_path / "templates"
        tmpl_dir.mkdir()
        (tmpl_dir / "fallback.tmpl").write_text("Fallback content")

        executor = RemediationExecutor(
            local_path=str(tmp_path),
            templates={"fb": TemplateConfig(file="templates/fallback.tmpl")},
            # framework_path defaults to None
        )
        content = executor._get_template_content("fb")
        assert content == "Fallback content"

    def test_inline_content_still_works(self, tmp_path):
        """Inline content= is unaffected by framework_path."""
        executor = RemediationExecutor(
            local_path=str(tmp_path),
            templates={"inline": TemplateConfig(content="Inline text")},
            framework_path="/does/not/matter/framework.toml",
        )
        content = executor._get_template_content("inline")
        assert content == "Inline text"

    def test_unknown_template_returns_none(self, tmp_path):
        """Requesting a non-existent template name returns None."""
        executor = RemediationExecutor(
            local_path=str(tmp_path),
            templates={},
        )
        assert executor._get_template_content("nonexistent") is None
