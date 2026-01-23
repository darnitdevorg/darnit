"""Tests for the UnifiedLocator class."""

import pytest
from pathlib import Path

from darnit.locate import UnifiedLocator, FoundEvidence, LocateResult
from darnit.config.framework_schema import LocatorConfig, LocatorLLMHints
from darnit.config.loader import clear_config_cache, save_project_config
from darnit.config.schema import create_minimal_config, SecurityConfig, PathRef


@pytest.fixture(autouse=True)
def clear_cache():
    """Clear config cache before each test."""
    clear_config_cache()
    yield
    clear_config_cache()


class TestUnifiedLocatorLocate:
    """Tests for UnifiedLocator.locate()."""

    def test_locate_via_config_reference(self, tmp_path):
        """Test locating file via .project/ reference."""
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

        # Create locator and config
        locator = UnifiedLocator(str(tmp_path))
        locator_config = LocatorConfig(
            project_path="security.policy",
            discover=["SECURITY.md", ".github/SECURITY.md"],
            kind="file",
        )

        # Locate - should find via config
        result = locator.locate("OSPS-VM-01.01", locator_config)

        assert result.success
        assert result.source == "config"
        assert result.found.path == "docs/security/SECURITY.md"
        assert not result.needs_sync  # Already in config

    def test_locate_via_discovery(self, tmp_path):
        """Test locating file via pattern discovery."""
        # Create SECURITY.md at root (no .project/ config)
        (tmp_path / "SECURITY.md").write_text("# Security Policy")

        # Create locator and config
        locator = UnifiedLocator(str(tmp_path))
        locator_config = LocatorConfig(
            project_path="security.policy",
            discover=["SECURITY.md", ".github/SECURITY.md"],
            kind="file",
        )

        # Locate - should find via discovery
        result = locator.locate("OSPS-VM-01.01", locator_config)

        assert result.success
        assert result.source == "discovered"
        assert result.found.path == "SECURITY.md"
        assert result.needs_sync  # Should be synced to config

    def test_locate_config_reference_missing_file(self, tmp_path):
        """Test fallback when config reference points to non-existent file."""
        # Create .project/ config with a reference to non-existent file
        project_dir = tmp_path / ".project"
        project_dir.mkdir()

        config = create_minimal_config(name="test", project_type="software")
        config.security = SecurityConfig(policy=PathRef(path="docs/MISSING.md"))
        save_project_config(config, str(tmp_path))

        # Create a SECURITY.md at root as fallback
        (tmp_path / "SECURITY.md").write_text("# Security Policy")

        # Create locator and config
        locator = UnifiedLocator(str(tmp_path))
        locator_config = LocatorConfig(
            project_path="security.policy",
            discover=["SECURITY.md", ".github/SECURITY.md"],
            kind="file",
        )

        # Locate - should fall back to discovery
        result = locator.locate("OSPS-VM-01.01", locator_config)

        assert result.success
        assert result.source == "discovered"
        assert result.found.path == "SECURITY.md"

    def test_locate_not_found(self, tmp_path):
        """Test when file is not found anywhere."""
        locator = UnifiedLocator(str(tmp_path))
        locator_config = LocatorConfig(
            project_path="security.policy",
            discover=["SECURITY.md", ".github/SECURITY.md"],
            kind="file",
        )

        result = locator.locate("OSPS-VM-01.01", locator_config)

        assert not result.success
        assert result.source == "none"
        assert result.found is None

    def test_locate_github_security_md(self, tmp_path):
        """Test locating SECURITY.md in .github directory."""
        github_dir = tmp_path / ".github"
        github_dir.mkdir()
        (github_dir / "SECURITY.md").write_text("# Security Policy")

        locator = UnifiedLocator(str(tmp_path))
        locator_config = LocatorConfig(
            project_path="security.policy",
            discover=["SECURITY.md", ".github/SECURITY.md"],
            kind="file",
        )

        result = locator.locate("OSPS-VM-01.01", locator_config)

        assert result.success
        assert result.found.path == ".github/SECURITY.md"


class TestUnifiedLocatorSync:
    """Tests for UnifiedLocator.sync_to_project()."""

    def test_sync_creates_config(self, tmp_path):
        """Test that sync creates .project/ if it doesn't exist."""
        # Create a file but no .project/
        (tmp_path / "SECURITY.md").write_text("# Security Policy")

        locator = UnifiedLocator(str(tmp_path))
        locator_config = LocatorConfig(
            project_path="security.policy",
            discover=["SECURITY.md"],
            kind="file",
        )

        found = FoundEvidence(path="SECURITY.md", kind="file")

        result = locator.sync_to_project("OSPS-VM-01.01", found, locator_config)

        assert result is True
        assert (tmp_path / ".project" / "project.yaml").exists()

    def test_sync_updates_existing_config(self, tmp_path):
        """Test that sync updates existing .project/ config."""
        # Create .project/ config without security reference
        project_dir = tmp_path / ".project"
        project_dir.mkdir()

        config = create_minimal_config(name="test-project", project_type="software")
        save_project_config(config, str(tmp_path))

        locator = UnifiedLocator(str(tmp_path))
        locator_config = LocatorConfig(
            project_path="security.policy",
            discover=["SECURITY.md"],
            kind="file",
        )

        found = FoundEvidence(path="SECURITY.md", kind="file")

        result = locator.sync_to_project("OSPS-VM-01.01", found, locator_config)

        assert result is True

        # Reload and verify
        clear_config_cache()
        from darnit.config.loader import load_project_config

        config = load_project_config(str(tmp_path))
        assert config.security.policy.path == "SECURITY.md"

    def test_sync_skips_if_already_set(self, tmp_path):
        """Test that sync is skipped if reference already matches."""
        # Create .project/ config with existing reference
        project_dir = tmp_path / ".project"
        project_dir.mkdir()

        config = create_minimal_config(name="test", project_type="software")
        config.security = SecurityConfig(policy=PathRef(path="SECURITY.md"))
        save_project_config(config, str(tmp_path))

        locator = UnifiedLocator(str(tmp_path))
        locator_config = LocatorConfig(
            project_path="security.policy",
            discover=["SECURITY.md"],
            kind="file",
        )

        found = FoundEvidence(path="SECURITY.md", kind="file")

        result = locator.sync_to_project("OSPS-VM-01.01", found, locator_config)

        # Should return False since no change was needed
        assert result is False


class TestUnifiedLocatorLocateAndSync:
    """Tests for UnifiedLocator.locate_and_sync()."""

    def test_locate_and_auto_sync(self, tmp_path):
        """Test that locate_and_sync automatically syncs discovered files."""
        # Create a file but no .project/
        (tmp_path / "SECURITY.md").write_text("# Security Policy")

        locator = UnifiedLocator(str(tmp_path))
        locator_config = LocatorConfig(
            project_path="security.policy",
            discover=["SECURITY.md"],
            kind="file",
        )

        result = locator.locate_and_sync("OSPS-VM-01.01", locator_config, auto_sync=True)

        assert result.success
        assert result.found.path == "SECURITY.md"

        # Verify config was created
        assert (tmp_path / ".project" / "project.yaml").exists()

    def test_locate_and_sync_disabled(self, tmp_path):
        """Test that locate_and_sync respects auto_sync=False."""
        # Create a file but no .project/
        (tmp_path / "SECURITY.md").write_text("# Security Policy")

        locator = UnifiedLocator(str(tmp_path))
        locator_config = LocatorConfig(
            project_path="security.policy",
            discover=["SECURITY.md"],
            kind="file",
        )

        result = locator.locate_and_sync("OSPS-VM-01.01", locator_config, auto_sync=False)

        assert result.success
        assert result.needs_sync  # Should still indicate sync is recommended

        # Verify config was NOT created
        assert not (tmp_path / ".project" / "project.yaml").exists()


class TestLocateResult:
    """Tests for LocateResult properties."""

    def test_success_property(self):
        """Test success property."""
        result = LocateResult(found=FoundEvidence(path="file.txt"))
        assert result.success is True

        result = LocateResult(found=None)
        assert result.success is False

    def test_needs_sync_property(self):
        """Test needs_sync property."""
        # Discovered and sync recommended
        result = LocateResult(
            found=FoundEvidence(path="file.txt"),
            source="discovered",
            sync_recommended=True,
        )
        assert result.needs_sync is True

        # Config reference - no sync needed
        result = LocateResult(
            found=FoundEvidence(path="file.txt"),
            source="config",
            sync_recommended=False,
        )
        assert result.needs_sync is False


class TestFoundEvidence:
    """Tests for FoundEvidence."""

    def test_location_property_file(self):
        """Test location property for file."""
        fe = FoundEvidence(path="SECURITY.md", kind="file")
        assert fe.location == "SECURITY.md"

    def test_location_property_url(self):
        """Test location property for URL."""
        fe = FoundEvidence(url="https://docs.example.com/security", kind="url")
        assert fe.location == "https://docs.example.com/security"

    def test_location_property_api(self):
        """Test location property for API endpoint."""
        fe = FoundEvidence(api_endpoint="/repos/owner/repo/branches/main/protection", kind="api")
        assert fe.location == "/repos/owner/repo/branches/main/protection"
