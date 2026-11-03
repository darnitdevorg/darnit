"""Tests for recording a created file's reference in ``.project/``."""

import pytest
import yaml

from darnit.config.loader import clear_config_cache, save_project_config
from darnit.config.resolver import render_reference_update
from darnit.config.schema import PathRef, SecurityConfig, create_minimal_config


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear config cache before each test."""
    clear_config_cache()
    yield
    clear_config_cache()


def _project_yaml(rendered: dict[str, str], tmp_path) -> dict:
    return yaml.safe_load(rendered[str(tmp_path / ".project" / "project.yaml")])


class TestRenderReferenceUpdate:
    """Tests for render_reference_update."""

    def test_update_creates_config_if_missing(self, tmp_path):
        """A missing project.yaml is rendered, and nothing is written."""
        # No .project/ directory

        rendered, kept = render_reference_update(str(tmp_path), "security.policy", "SECURITY.md")

        assert kept is None
        assert _project_yaml(rendered, tmp_path)["security"]["policy"]["path"] == "SECURITY.md"
        assert not (tmp_path / ".project").exists()

    def test_update_existing_config(self, tmp_path):
        """Test updating existing config with new reference."""
        # Create existing .project/ config
        project_dir = tmp_path / ".project"
        project_dir.mkdir()

        config = create_minimal_config(name="test-project", project_type="software")
        save_project_config(config, str(tmp_path))

        rendered, kept = render_reference_update(str(tmp_path), "security.policy", "SECURITY.md")

        assert kept is None
        assert _project_yaml(rendered, tmp_path)["security"]["policy"]["path"] == "SECURITY.md"

    def test_update_skips_if_already_set(self, tmp_path):
        """Test that update is skipped if reference already matches."""
        # Create config with existing reference
        project_dir = tmp_path / ".project"
        project_dir.mkdir()

        config = create_minimal_config(name="test", project_type="software")
        config.security = SecurityConfig(policy=PathRef(path="SECURITY.md"))
        save_project_config(config, str(tmp_path))

        # Nothing to render since no change is needed
        assert render_reference_update(str(tmp_path), "security.policy", "SECURITY.md") == ({}, None)

    def test_update_contributing_guide(self, tmp_path):
        """Test updating config for contributing guide."""
        project_dir = tmp_path / ".project"
        project_dir.mkdir()

        config = create_minimal_config(name="test", project_type="software")
        save_project_config(config, str(tmp_path))

        rendered, kept = render_reference_update(str(tmp_path), "governance.contributing", "CONTRIBUTING.md")

        assert kept is None
        assert _project_yaml(rendered, tmp_path)["governance"]["contributing"]["path"] == "CONTRIBUTING.md"
