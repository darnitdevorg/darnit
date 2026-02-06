"""Tests for remediation actions in darnit-example."""

import pytest

from darnit_example.remediation.actions import create_gitignore, create_readme


class TestCreateReadme:
    """Tests for create_readme remediation action."""

    @pytest.mark.unit
    def test_dry_run(self, empty_project):
        result = create_readme(empty_project, dry_run=True)
        assert result["status"] == "dry_run"
        assert "README.md" in result["message"]

    @pytest.mark.unit
    def test_creates_file(self, empty_project):
        result = create_readme(empty_project, dry_run=False)
        assert result["status"] == "created"

        import os
        assert os.path.exists(os.path.join(empty_project, "README.md"))

    @pytest.mark.unit
    def test_skips_existing(self, full_project):
        result = create_readme(full_project, dry_run=False)
        assert result["status"] == "skipped"

    @pytest.mark.unit
    def test_content_has_project_name(self, empty_project):
        create_readme(empty_project, dry_run=False)

        import os
        with open(os.path.join(empty_project, "README.md")) as f:
            content = f.read()
        # Should include the directory name as the title
        assert content.startswith("# ")
        assert len(content) > 10


class TestCreateGitignore:
    """Tests for create_gitignore remediation action."""

    @pytest.mark.unit
    def test_dry_run(self, empty_project):
        result = create_gitignore(empty_project, dry_run=True)
        assert result["status"] == "dry_run"

    @pytest.mark.unit
    def test_creates_file(self, empty_project):
        result = create_gitignore(empty_project, dry_run=False)
        assert result["status"] == "created"

        import os
        assert os.path.exists(os.path.join(empty_project, ".gitignore"))

    @pytest.mark.unit
    def test_skips_existing(self, full_project):
        result = create_gitignore(full_project, dry_run=False)
        assert result["status"] == "skipped"

    @pytest.mark.unit
    def test_content_has_common_patterns(self, empty_project):
        create_gitignore(empty_project, dry_run=False)

        import os
        with open(os.path.join(empty_project, ".gitignore")) as f:
            content = f.read()
        assert "__pycache__" in content
        assert ".DS_Store" in content
