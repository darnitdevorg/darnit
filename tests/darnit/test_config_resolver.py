"""Tests for config-aware file resolution."""

import pytest

from darnit.config.loader import clear_config_cache, save_project_config
from darnit.config.resolver import (
    resolve_file_for_control,
    sync_discovered_file_to_config,
    update_config_after_file_create,
)
from darnit.config.schema import PathRef, SecurityConfig, create_minimal_config

# Test mappings (subset of the real mappings for testing)
TEST_CONTROL_REFERENCE_MAPPING = {
    "OSPS-VM-01.01": "security.policy",
    "OSPS-GV-03.01": "governance.contributing",
    "OSPS-DO-03.01": "documentation.support",
}

TEST_FILE_LOCATIONS = {
    "security.policy": ["SECURITY.md", ".github/SECURITY.md", "docs/SECURITY.md"],
    "governance.contributing": ["CONTRIBUTING.md", ".github/CONTRIBUTING.md"],
    "documentation.support": ["SUPPORT.md", ".github/SUPPORT.md"],
}


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear config cache before each test."""
    clear_config_cache()
    yield
    clear_config_cache()


class TestResolveFileForControl:
    """Tests for resolve_file_for_control function."""

    def test_resolve_from_config_reference(self, tmp_path):
        """Test that file is resolved from .project/ reference first."""
        # Create .project/ config with a reference
        project_dir = tmp_path / ".project"
        project_dir.mkdir()

        config = create_minimal_config(name="test", project_type="software")
        config.security = SecurityConfig(policy=PathRef(path="docs/security/SECURITY.md"))
        save_project_config(config, str(tmp_path))

        # Create the referenced file
        docs_dir = tmp_path / "docs" / "security"
        docs_dir.mkdir(parents=True)
        (docs_dir / "SECURITY.md").write_text("# Security Policy")

        # Resolve - should find via config
        path, source = resolve_file_for_control(
            local_path=str(tmp_path),
            control_id="OSPS-VM-01.01",
            file_locations=TEST_FILE_LOCATIONS,
            control_reference_mapping=TEST_CONTROL_REFERENCE_MAPPING,
        )

        assert path == "docs/security/SECURITY.md"
        assert source == "config"

    def test_resolve_fallback_to_discovery(self, tmp_path):
        """Test that file is discovered when not in config."""
        # Create a SECURITY.md at root (standard location)
        (tmp_path / "SECURITY.md").write_text("# Security Policy")

        # No .project/ config exists

        # Resolve - should find via discovery
        path, source = resolve_file_for_control(
            local_path=str(tmp_path),
            control_id="OSPS-VM-01.01",
            file_locations=TEST_FILE_LOCATIONS,
            control_reference_mapping=TEST_CONTROL_REFERENCE_MAPPING,
        )

        assert path == "SECURITY.md"
        assert source == "discovered"

    def test_resolve_config_reference_missing_file(self, tmp_path):
        """Test fallback when config reference points to non-existent file."""
        # Create .project/ config with a reference to non-existent file
        project_dir = tmp_path / ".project"
        project_dir.mkdir()

        config = create_minimal_config(name="test", project_type="software")
        config.security = SecurityConfig(policy=PathRef(path="docs/MISSING.md"))
        save_project_config(config, str(tmp_path))

        # Create a SECURITY.md at standard location as fallback
        (tmp_path / "SECURITY.md").write_text("# Security Policy")

        # Resolve - should fall back to discovery
        path, source = resolve_file_for_control(
            local_path=str(tmp_path),
            control_id="OSPS-VM-01.01",
            file_locations=TEST_FILE_LOCATIONS,
            control_reference_mapping=TEST_CONTROL_REFERENCE_MAPPING,
        )

        assert path == "SECURITY.md"
        assert source == "discovered"

    def test_resolve_no_file_found(self, tmp_path):
        """Test when no file is found anywhere."""
        # No config, no files

        path, source = resolve_file_for_control(
            local_path=str(tmp_path),
            control_id="OSPS-VM-01.01",
            file_locations=TEST_FILE_LOCATIONS,
            control_reference_mapping=TEST_CONTROL_REFERENCE_MAPPING,
        )

        assert path is None
        assert source == "none"

    def test_resolve_unknown_control(self, tmp_path):
        """Test resolution for unknown control ID."""
        (tmp_path / "SECURITY.md").write_text("# Security Policy")

        path, source = resolve_file_for_control(
            local_path=str(tmp_path),
            control_id="UNKNOWN-01.01",  # Not in mapping
            file_locations=TEST_FILE_LOCATIONS,
            control_reference_mapping=TEST_CONTROL_REFERENCE_MAPPING,
        )

        assert path is None
        assert source == "none"


class TestUpdateConfigAfterFileCreate:
    """Tests for update_config_after_file_create function."""

    def test_update_creates_config_if_missing(self, tmp_path):
        """Test that config is created if it doesn't exist."""
        # No .project/ directory

        # Update config after creating SECURITY.md
        result = update_config_after_file_create(
            local_path=str(tmp_path),
            control_id="OSPS-VM-01.01",
            created_file_path="SECURITY.md",
            control_reference_mapping=TEST_CONTROL_REFERENCE_MAPPING,
        )

        assert result is True

        # Verify config was created
        assert (tmp_path / ".project" / "project.yaml").exists()

    def test_update_existing_config(self, tmp_path):
        """Test updating existing config with new reference."""
        # Create existing .project/ config
        project_dir = tmp_path / ".project"
        project_dir.mkdir()

        config = create_minimal_config(name="test-project", project_type="software")
        save_project_config(config, str(tmp_path))

        # Update config after creating SECURITY.md
        result = update_config_after_file_create(
            local_path=str(tmp_path),
            control_id="OSPS-VM-01.01",
            created_file_path="SECURITY.md",
            control_reference_mapping=TEST_CONTROL_REFERENCE_MAPPING,
        )

        assert result is True

        # Clear cache and reload config
        clear_config_cache()
        from darnit.config.loader import load_project_config

        config = load_project_config(str(tmp_path))
        assert config is not None
        assert config.security is not None
        assert config.security.policy is not None
        assert config.security.policy.path == "SECURITY.md"

    def test_update_skips_if_already_set(self, tmp_path):
        """Test that update is skipped if reference already matches."""
        # Create config with existing reference
        project_dir = tmp_path / ".project"
        project_dir.mkdir()

        config = create_minimal_config(name="test", project_type="software")
        config.security = SecurityConfig(policy=PathRef(path="SECURITY.md"))
        save_project_config(config, str(tmp_path))

        # Try to update with same path
        result = update_config_after_file_create(
            local_path=str(tmp_path),
            control_id="OSPS-VM-01.01",
            created_file_path="SECURITY.md",
            control_reference_mapping=TEST_CONTROL_REFERENCE_MAPPING,
        )

        # Should return False since no change was needed
        assert result is False

    def test_update_unknown_control_returns_false(self, tmp_path):
        """Test that unknown control ID returns False."""
        result = update_config_after_file_create(
            local_path=str(tmp_path),
            control_id="UNKNOWN-01.01",
            created_file_path="SECURITY.md",
            control_reference_mapping=TEST_CONTROL_REFERENCE_MAPPING,
        )

        assert result is False

    def test_update_contributing_guide(self, tmp_path):
        """Test updating config for contributing guide."""
        project_dir = tmp_path / ".project"
        project_dir.mkdir()

        config = create_minimal_config(name="test", project_type="software")
        save_project_config(config, str(tmp_path))

        result = update_config_after_file_create(
            local_path=str(tmp_path),
            control_id="OSPS-GV-03.01",
            created_file_path="CONTRIBUTING.md",
            control_reference_mapping=TEST_CONTROL_REFERENCE_MAPPING,
        )

        assert result is True

        # Verify
        clear_config_cache()
        from darnit.config.loader import load_project_config

        config = load_project_config(str(tmp_path))
        assert config is not None
        assert config.governance is not None
        assert config.governance.contributing is not None
        assert config.governance.contributing.path == "CONTRIBUTING.md"


class TestSyncDiscoveredFileToConfig:
    """Tests for sync_discovered_file_to_config function."""

    def test_sync_discovered_file(self, tmp_path):
        """Test syncing a discovered file to config."""
        project_dir = tmp_path / ".project"
        project_dir.mkdir()

        config = create_minimal_config(name="test", project_type="software")
        save_project_config(config, str(tmp_path))

        # Sync discovered file
        result = sync_discovered_file_to_config(
            local_path=str(tmp_path),
            control_id="OSPS-VM-01.01",
            discovered_path=".github/SECURITY.md",
            control_reference_mapping=TEST_CONTROL_REFERENCE_MAPPING,
        )

        assert result is True

        # Verify
        clear_config_cache()
        from darnit.config.loader import load_project_config

        config = load_project_config(str(tmp_path))
        assert config.security.policy.path == ".github/SECURITY.md"
