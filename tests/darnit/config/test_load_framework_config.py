
import pytest

from darnit.config.merger import load_framework_config


def test_load_framework_config_absolute_path_template(tmp_path):
    config_file = tmp_path / "framework.toml"
    config_file.write_text("""
[metadata]
name = "test"
display_name = "Test"
version = "1.0"
spec_version = "1.0"

[templates.abs_tmpl]
file = "/absolute/path/to/template"
""")

    with pytest.raises(ValueError, match="specifies absolute path"):
        load_framework_config(config_file)

def test_load_framework_config_path_traversal(tmp_path):
    config_file = tmp_path / "pkg" / "framework.toml"
    config_file.parent.mkdir()

    config_file.write_text("""
[metadata]
name = "test"
display_name = "Test"
version = "1.0"
spec_version = "1.0"

[templates.escape]
file = "../../../outside.tmpl"
""")

    with pytest.raises(ValueError, match="outside framework directory"):
        load_framework_config(config_file)
