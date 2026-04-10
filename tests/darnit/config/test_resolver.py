"""Tests for config resolver module.

Tests for darnit.config.resolver - two-phase file resolution
(config reference → pattern discovery) and post-remediation config updates.
"""

import pytest

from darnit.config.loader import (
    PROJECT_DIR,
    PROJECT_FILE,
    clear_config_cache,
    load_project_config,
    save_project_config,
)
from darnit.config.resolver import (
    resolve_file_for_control,
    sync_discovered_file_to_config,
    update_config_after_file_create,
)
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


CONTROL_REFERENCE_MAPPING = {
    "OSPS-DO-02.01": "security.policy",
    "OSPS-LE-01.01": "legal.license",
}

FILE_LOCATIONS = {
    "security.policy": ["SECURITY.md", "SECURITY.rst", "docs/SECURITY.md"],
    "legal.license": ["LICENSE", "LICENSE.md", "LICENSE.txt"],
}


# ---------------------------------------------------------------------------
# resolve_file_for_control
# ---------------------------------------------------------------------------


class TestResolveFileForControl:
    def test_returns_none_and_none_source_when_not_found(self, temp_dir):
        file_path, source = resolve_file_for_control(
            str(temp_dir),
            "OSPS-DO-02.01",
            FILE_LOCATIONS,
            CONTROL_REFERENCE_MAPPING,
        )

        assert file_path is None
        assert source == "none"

    def test_resolves_via_config_reference(self, temp_dir):
        (temp_dir / "SECURITY.md").write_text("# Security Policy")
        config = create_minimal_config(name="my-project")
        config.security = SecurityConfig(policy=PathRef(path="SECURITY.md"))
        save_project_config(config, str(temp_dir))

        file_path, source = resolve_file_for_control(
            str(temp_dir),
            "OSPS-DO-02.01",
            FILE_LOCATIONS,
            CONTROL_REFERENCE_MAPPING,
        )

        assert file_path == "SECURITY.md"
        assert source == "config"

    def test_falls_back_to_discovery_when_config_ref_missing_file(self, temp_dir):
        """Config declares a path but the file doesn't exist; fall back to discovery."""
        (temp_dir / "SECURITY.md").write_text("# Security Policy")
        config = create_minimal_config(name="my-project")
        # Declare a different (non-existent) path in config
        config.security = SecurityConfig(policy=PathRef(path="SECURITY_DECLARED.md"))
        save_project_config(config, str(temp_dir))

        file_path, source = resolve_file_for_control(
            str(temp_dir),
            "OSPS-DO-02.01",
            FILE_LOCATIONS,
            CONTROL_REFERENCE_MAPPING,
        )

        # Should discover SECURITY.md via pattern
        assert file_path == "SECURITY.md"
        assert source == "discovered"

    def test_resolves_via_pattern_discovery_when_no_config(self, temp_dir):
        (temp_dir / "SECURITY.md").write_text("# Security Policy")

        file_path, source = resolve_file_for_control(
            str(temp_dir),
            "OSPS-DO-02.01",
            FILE_LOCATIONS,
            CONTROL_REFERENCE_MAPPING,
        )

        assert file_path == "SECURITY.md"
        assert source == "discovered"

    def test_returns_none_for_control_without_mapping(self, temp_dir):
        (temp_dir / "SECURITY.md").write_text("# Security")

        file_path, source = resolve_file_for_control(
            str(temp_dir),
            "OSPS-NO-MAPPING",
            FILE_LOCATIONS,
            CONTROL_REFERENCE_MAPPING,
        )

        assert file_path is None
        assert source == "none"

    def test_discovers_alternative_pattern(self, temp_dir):
        # SECURITY.md not present but docs/SECURITY.md is
        (temp_dir / "docs").mkdir()
        (temp_dir / "docs" / "SECURITY.md").write_text("# Security Policy")

        file_path, source = resolve_file_for_control(
            str(temp_dir),
            "OSPS-DO-02.01",
            FILE_LOCATIONS,
            CONTROL_REFERENCE_MAPPING,
        )

        assert file_path is not None
        assert source == "discovered"


# ---------------------------------------------------------------------------
# update_config_after_file_create
# ---------------------------------------------------------------------------


class TestUpdateConfigAfterFileCreate:
    def test_returns_false_for_control_without_mapping(self, temp_dir):
        result = update_config_after_file_create(
            str(temp_dir),
            "OSPS-NO-MAPPING",
            "SECURITY.md",
            CONTROL_REFERENCE_MAPPING,
        )

        assert result is False

    def test_creates_new_config_when_none_exists(self, temp_dir):
        (temp_dir / "SECURITY.md").write_text("# Security Policy")

        result = update_config_after_file_create(
            str(temp_dir),
            "OSPS-DO-02.01",
            "SECURITY.md",
            CONTROL_REFERENCE_MAPPING,
        )

        assert result is True
        assert (temp_dir / PROJECT_DIR / PROJECT_FILE).exists()

    def test_updates_existing_config(self, temp_dir):
        (temp_dir / "SECURITY.md").write_text("# Security Policy")
        config = create_minimal_config(name="my-project")
        save_project_config(config, str(temp_dir))

        update_config_after_file_create(
            str(temp_dir),
            "OSPS-DO-02.01",
            "SECURITY.md",
            CONTROL_REFERENCE_MAPPING,
        )

        loaded = load_project_config(str(temp_dir))
        assert loaded is not None
        assert loaded.security is not None
        assert loaded.security.policy is not None

    def test_returns_false_when_path_already_set(self, temp_dir):
        (temp_dir / "SECURITY.md").write_text("# Security Policy")
        config = create_minimal_config(name="my-project")
        config.security = SecurityConfig(policy=PathRef(path="SECURITY.md"))
        save_project_config(config, str(temp_dir))

        result = update_config_after_file_create(
            str(temp_dir),
            "OSPS-DO-02.01",
            "SECURITY.md",
            CONTROL_REFERENCE_MAPPING,
        )

        assert result is False

    def test_returns_false_for_invalid_ref_path_format(self, temp_dir):
        bad_mapping = {"CTRL-01": "no-dot-separator"}

        result = update_config_after_file_create(
            str(temp_dir),
            "CTRL-01",
            "somefile.md",
            bad_mapping,
        )

        assert result is False


# ---------------------------------------------------------------------------
# sync_discovered_file_to_config
# ---------------------------------------------------------------------------


class TestSyncDiscoveredFileToConfig:
    def test_delegates_to_update_config(self, temp_dir):
        (temp_dir / "SECURITY.md").write_text("# Security Policy")

        result = sync_discovered_file_to_config(
            str(temp_dir),
            "OSPS-DO-02.01",
            "SECURITY.md",
            CONTROL_REFERENCE_MAPPING,
        )

        assert result is True
        loaded = load_project_config(str(temp_dir))
        assert loaded is not None
        assert loaded.security is not None
