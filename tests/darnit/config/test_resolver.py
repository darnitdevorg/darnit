"""Tests for config resolver module.

Tests for darnit.config.resolver - rendering the ``.project/`` update that
records a created file's reference (feature 043, framework-design 4.3).
"""

import pytest
import yaml

from darnit.config.loader import (
    PROJECT_DIR,
    PROJECT_FILE,
    clear_config_cache,
    save_project_config,
)
from darnit.config.resolver import render_reference_update
from darnit.config.schema import (
    PathRef,
    SecurityConfig,
    create_minimal_config,
)

# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------


@pytest.fixture(autouse=True)
def clear_cache():
    """Ensure config cache is clear before and after each test."""
    clear_config_cache()
    yield
    clear_config_cache()


def _project_file(temp_dir) -> str:
    return str(temp_dir / PROJECT_DIR / PROJECT_FILE)


# ---------------------------------------------------------------------------
# render_reference_update
# ---------------------------------------------------------------------------


class TestRenderReferenceUpdate:
    def test_creates_new_config_when_none_exists(self, temp_dir):
        (temp_dir / "SECURITY.md").write_text("# Security Policy")

        rendered, kept = render_reference_update(str(temp_dir), "security.policy", "SECURITY.md")

        assert kept is None
        assert list(rendered) == [_project_file(temp_dir)]
        assert yaml.safe_load(rendered[_project_file(temp_dir)])["security"] == {"policy": {"path": "SECURITY.md"}}
        assert not (temp_dir / PROJECT_DIR).exists()

    def test_updates_existing_config(self, temp_dir):
        (temp_dir / "SECURITY.md").write_text("# Security Policy")
        config = create_minimal_config(name="my-project")
        save_project_config(config, str(temp_dir))

        rendered, kept = render_reference_update(str(temp_dir), "security.policy", "SECURITY.md")

        assert kept is None
        data = yaml.safe_load(rendered[_project_file(temp_dir)])
        assert data["name"] == "my-project"
        assert data["security"] == {"policy": {"path": "SECURITY.md"}}

    def test_renders_nothing_when_path_already_set(self, temp_dir):
        (temp_dir / "SECURITY.md").write_text("# Security Policy")
        config = create_minimal_config(name="my-project")
        config.security = SecurityConfig(policy=PathRef(path="SECURITY.md"))
        save_project_config(config, str(temp_dir))

        assert render_reference_update(str(temp_dir), "security.policy", "SECURITY.md") == ({}, None)

    def test_keeps_a_different_existing_reference_fr015(self, temp_dir):
        config = create_minimal_config(name="my-project")
        config.security = SecurityConfig(policy=PathRef(path="docs/SECURITY.md"))
        save_project_config(config, str(temp_dir))
        before = (temp_dir / PROJECT_DIR / PROJECT_FILE).read_text(encoding="utf-8")

        rendered, kept = render_reference_update(str(temp_dir), "security.policy", "SECURITY.md")

        assert rendered == {}
        assert kept == "security.policy already names docs/SECURITY.md"
        assert (temp_dir / PROJECT_DIR / PROJECT_FILE).read_text(encoding="utf-8") == before

    def test_renders_nothing_for_invalid_ref_path_format(self, temp_dir):
        rendered, kept = render_reference_update(str(temp_dir), "no-dot-separator", "somefile.md")

        assert rendered == {}
        assert kept == "no-dot-separator is not a project path field"
