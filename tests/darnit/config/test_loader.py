"""Tests for config loader module.

Tests for darnit.config.loader - loading, saving, and caching
.project/ configuration files.
"""

import yaml

from darnit.config.loader import (
    EXTENSION_FILE,
    PROJECT_DIR,
    PROJECT_FILE,
    _split_config_data,
    clear_config_cache,
    config_exists,
    get_config_path,
    get_default_extension,
    get_extension_by_key,
    get_extension_path,
    get_project_config,
    list_extension_files,
    load_project_config,
    save_project_config,
)
from darnit.config.schema import (
    PathRef,
    SecurityConfig,
    create_minimal_config,
)

# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------


def _write_project_yaml(project_dir, data: dict) -> None:
    project_dir.mkdir(parents=True, exist_ok=True)
    path = project_dir / PROJECT_FILE
    path.write_text(yaml.dump(data))


# ---------------------------------------------------------------------------
# load_project_config
# ---------------------------------------------------------------------------


class TestLoadProjectConfig:
    def test_returns_none_when_no_project_dir(self, temp_dir):
        result = load_project_config(str(temp_dir))
        assert result is None

    def test_returns_none_when_no_project_yaml(self, temp_dir):
        (temp_dir / PROJECT_DIR).mkdir()

        result = load_project_config(str(temp_dir))

        assert result is None

    def test_returns_none_for_empty_yaml(self, temp_dir):
        project_dir = temp_dir / PROJECT_DIR
        project_dir.mkdir()
        (project_dir / PROJECT_FILE).write_text("")

        result = load_project_config(str(temp_dir))

        assert result is None

    def test_returns_none_for_invalid_yaml(self, temp_dir):
        project_dir = temp_dir / PROJECT_DIR
        project_dir.mkdir()
        (project_dir / PROJECT_FILE).write_text(": invalid: yaml: ][")

        result = load_project_config(str(temp_dir))

        assert result is None

    def test_loads_minimal_valid_config(self, temp_dir):
        project_dir = temp_dir / PROJECT_DIR
        _write_project_yaml(project_dir, {"name": "my-project", "type": "software"})

        result = load_project_config(str(temp_dir))

        assert result is not None
        assert result.name == "my-project"

    def test_config_path_set_on_loaded_config(self, temp_dir):
        project_dir = temp_dir / PROJECT_DIR
        _write_project_yaml(project_dir, {"name": "my-project"})

        result = load_project_config(str(temp_dir))

        assert result.config_path is not None
        assert PROJECT_FILE in result.config_path

    def test_local_path_set_on_loaded_config(self, temp_dir):
        project_dir = temp_dir / PROJECT_DIR
        _write_project_yaml(project_dir, {"name": "my-project"})

        result = load_project_config(str(temp_dir))

        assert result.local_path == str(temp_dir)

    def test_loads_extension_file_when_present(self, temp_dir):
        project_dir = temp_dir / PROJECT_DIR
        project_dir.mkdir()
        (project_dir / PROJECT_FILE).write_text(yaml.dump({"name": "my-project"}))
        (project_dir / EXTENSION_FILE).write_text(yaml.dump({"ci": {"provider": "github"}}))

        result = load_project_config(str(temp_dir))

        assert result is not None
        # Extension data should be merged into x-openssf-baseline
        assert result.x_openssf_baseline is not None

    def test_returns_none_for_schema_validation_failure(self, temp_dir):
        project_dir = temp_dir / PROJECT_DIR
        project_dir.mkdir()
        # 'name' is required by ProjectConfig; omitting it causes ValidationError
        (project_dir / PROJECT_FILE).write_text(yaml.dump({"type": "software"}))

        result = load_project_config(str(temp_dir))

        assert result is None


# ---------------------------------------------------------------------------
# save_project_config / round-trip
# ---------------------------------------------------------------------------


class TestSaveProjectConfig:
    def test_creates_project_dir(self, temp_dir):
        config = create_minimal_config(name="my-project")

        save_project_config(config, str(temp_dir))

        assert (temp_dir / PROJECT_DIR).is_dir()

    def test_creates_project_yaml(self, temp_dir):
        config = create_minimal_config(name="my-project")

        save_project_config(config, str(temp_dir))

        assert (temp_dir / PROJECT_DIR / PROJECT_FILE).exists()

    def test_round_trip_preserves_name(self, temp_dir):
        config = create_minimal_config(name="round-trip-project")
        save_project_config(config, str(temp_dir))

        loaded = load_project_config(str(temp_dir))

        assert loaded is not None
        assert loaded.name == "round-trip-project"

    def test_round_trip_preserves_security_policy(self, temp_dir):
        (temp_dir / "SECURITY.md").write_text("# Security Policy")
        config = create_minimal_config(name="secure-project")
        config.security = SecurityConfig(policy=PathRef(path="SECURITY.md"))

        save_project_config(config, str(temp_dir))
        loaded = load_project_config(str(temp_dir))

        assert loaded is not None
        assert loaded.security is not None
        assert loaded.security.policy is not None

    def test_returns_path_to_project_yaml(self, temp_dir):
        config = create_minimal_config(name="my-project")

        returned_path = save_project_config(config, str(temp_dir))

        assert returned_path.endswith(PROJECT_FILE)
        assert (temp_dir / PROJECT_DIR / PROJECT_FILE).exists()


# ---------------------------------------------------------------------------
# get_project_config (caching)
# ---------------------------------------------------------------------------


class TestGetProjectConfig:
    def setup_method(self):
        clear_config_cache()

    def teardown_method(self):
        clear_config_cache()

    def test_returns_none_when_no_config(self, temp_dir):
        result = get_project_config(str(temp_dir))
        assert result is None

    def test_returns_config_when_present(self, temp_dir):
        config = create_minimal_config(name="cached-project")
        save_project_config(config, str(temp_dir))

        result = get_project_config(str(temp_dir))

        assert result is not None
        assert result.name == "cached-project"

    def test_caches_result_on_second_call(self, temp_dir):
        config = create_minimal_config(name="cached-project")
        save_project_config(config, str(temp_dir))

        first = get_project_config(str(temp_dir))
        second = get_project_config(str(temp_dir))

        assert first is second  # Same object from cache

    def test_force_reload_bypasses_cache(self, temp_dir):
        config = create_minimal_config(name="original")
        save_project_config(config, str(temp_dir))
        get_project_config(str(temp_dir))  # Populate cache

        # Modify on disk
        config2 = create_minimal_config(name="updated")
        save_project_config(config2, str(temp_dir))

        result = get_project_config(str(temp_dir), force_reload=True)

        assert result.name == "updated"


# ---------------------------------------------------------------------------
# clear_config_cache
# ---------------------------------------------------------------------------


class TestClearConfigCache:
    def test_clear_removes_cached_entry(self, temp_dir):
        config = create_minimal_config(name="my-project")
        save_project_config(config, str(temp_dir))

        first = get_project_config(str(temp_dir))
        clear_config_cache()

        # After clearing, a new load happens — different object
        second = get_project_config(str(temp_dir))
        assert first is not second


# ---------------------------------------------------------------------------
# config_exists / get_config_path
# ---------------------------------------------------------------------------


class TestConfigExists:
    def test_returns_false_when_missing(self, temp_dir):
        assert config_exists(str(temp_dir)) is False

    def test_returns_true_when_present(self, temp_dir):
        config = create_minimal_config(name="my-project")
        save_project_config(config, str(temp_dir))

        assert config_exists(str(temp_dir)) is True


class TestGetConfigPath:
    def test_returns_none_when_missing(self, temp_dir):
        assert get_config_path(str(temp_dir)) is None

    def test_returns_path_when_present(self, temp_dir):
        config = create_minimal_config(name="my-project")
        save_project_config(config, str(temp_dir))

        path = get_config_path(str(temp_dir))

        assert path is not None
        assert path.endswith(PROJECT_FILE)


# ---------------------------------------------------------------------------
# get_extension_path / list_extension_files
# ---------------------------------------------------------------------------


class TestGetExtensionPath:
    def test_returns_none_when_missing(self, temp_dir):
        assert get_extension_path(str(temp_dir)) is None

    def test_returns_path_when_extension_exists(self, temp_dir):
        project_dir = temp_dir / PROJECT_DIR
        project_dir.mkdir()
        (project_dir / EXTENSION_FILE).write_text(yaml.dump({}))

        path = get_extension_path(str(temp_dir))

        assert path is not None
        assert EXTENSION_FILE in path


class TestListExtensionFiles:
    def test_returns_empty_when_no_extensions(self, temp_dir):
        project_dir = temp_dir / PROJECT_DIR
        project_dir.mkdir()

        result = list_extension_files(str(temp_dir))

        assert result == []

    def test_lists_present_extension_files(self, temp_dir):
        project_dir = temp_dir / PROJECT_DIR
        project_dir.mkdir()
        (project_dir / EXTENSION_FILE).write_text(yaml.dump({}))

        result = list_extension_files(str(temp_dir))

        assert EXTENSION_FILE in result


# ---------------------------------------------------------------------------
# Extension registry helpers
# ---------------------------------------------------------------------------


class TestExtensionRegistry:
    def test_get_extension_by_key_returns_spec(self):
        spec = get_extension_by_key("x-openssf-baseline")
        assert spec is not None
        assert spec.filename == EXTENSION_FILE

    def test_get_extension_by_key_returns_none_for_unknown(self):
        assert get_extension_by_key("x-nonexistent") is None

    def test_get_default_extension_returns_spec(self):
        spec = get_default_extension()
        assert spec is not None
        assert spec.is_default is True


# ---------------------------------------------------------------------------
# _split_config_data
# ---------------------------------------------------------------------------


class TestSplitConfigData:
    def test_cncf_fields_go_to_project_data(self):
        data = {"name": "test", "type": "software", "description": "desc"}

        project_data, ext_files = _split_config_data(data)

        assert "name" in project_data
        assert "type" in project_data
        assert ext_files == {}

    def test_extension_key_split_into_extension_file(self):
        data = {
            "name": "test",
            "x-openssf-baseline": {"ci": {"provider": "github"}},
        }

        project_data, ext_files = _split_config_data(data)

        assert "name" in project_data
        assert "x-openssf-baseline" not in project_data
        assert EXTENSION_FILE in ext_files

    def test_unknown_fields_go_to_default_extension(self):
        data = {"name": "test", "custom_field": "custom_value"}

        project_data, ext_files = _split_config_data(data)

        assert "name" in project_data
        assert "custom_field" not in project_data
        assert EXTENSION_FILE in ext_files
        assert ext_files[EXTENSION_FILE]["custom_field"] == "custom_value"
