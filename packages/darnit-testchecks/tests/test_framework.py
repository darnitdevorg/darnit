"""Tests for testchecks framework loading and configuration."""

import sys
from pathlib import Path


# Add package paths for testing without installation
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "darnit" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from darnit.config.merger import load_framework_config
from darnit_testchecks import get_framework_path, __version__


class TestFrameworkLoading:
    """Tests for framework TOML loading."""

    def test_get_framework_path_exists(self):
        """Framework path should exist."""
        path = get_framework_path()
        assert path.exists(), f"Framework file not found at {path}"

    def test_get_framework_path_is_toml(self):
        """Framework path should be a TOML file."""
        path = get_framework_path()
        assert path.suffix == ".toml"

    def test_load_framework_config(self):
        """Should load framework config from TOML."""
        path = get_framework_path()
        framework = load_framework_config(path)

        assert framework is not None
        assert framework.metadata.name == "testchecks"
        assert framework.metadata.version == "0.1.0"

    def test_framework_has_controls(self):
        """Framework should define controls."""
        framework = load_framework_config(get_framework_path())

        assert len(framework.controls) == 12
        assert "TEST-DOC-01" in framework.controls
        assert "TEST-SEC-01" in framework.controls

    def test_framework_control_levels(self):
        """Controls should have correct levels."""
        framework = load_framework_config(get_framework_path())

        # Level 1 controls
        assert framework.controls["TEST-DOC-01"].level == 1
        assert framework.controls["TEST-LIC-01"].level == 1

        # Level 2 controls
        assert framework.controls["TEST-QA-01"].level == 2
        assert framework.controls["TEST-CFG-01"].level == 2

        # Level 3 controls
        assert framework.controls["TEST-SEC-01"].level == 3
        assert framework.controls["TEST-CI-01"].level == 3

    def test_framework_control_domains(self):
        """Controls should have domains."""
        framework = load_framework_config(get_framework_path())

        assert framework.controls["TEST-DOC-01"].domain == "DOC"
        assert framework.controls["TEST-QA-01"].domain == "QA"
        assert framework.controls["TEST-SEC-01"].domain == "SEC"
        assert framework.controls["TEST-CI-01"].domain == "CI"

    def test_framework_has_adapters(self):
        """Framework should define adapters."""
        framework = load_framework_config(get_framework_path())

        assert "builtin" in framework.adapters
        adapter = framework.adapters["builtin"]
        # Adapter might be dict or AdapterConfig depending on parsing
        if hasattr(adapter, "type"):
            assert adapter.type == "python"
        else:
            assert adapter.get("type") == "python"

    def test_framework_has_defaults(self):
        """Framework should have defaults."""
        framework = load_framework_config(get_framework_path())

        assert framework.defaults.check_adapter == "builtin"
        assert framework.defaults.remediation_adapter == "builtin"

    def test_package_version(self):
        """Package version should match framework version."""
        framework = load_framework_config(get_framework_path())
        assert __version__ == framework.metadata.version
