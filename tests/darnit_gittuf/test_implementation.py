"""Tests for GittufImplementation plugin protocol compliance."""


from darnit_gittuf.implementation import GittufImplementation


def _framework_controls(impl):
    """Controls as the audit loads them, from the implementation's framework TOML."""
    from darnit.config import load_controls_from_framework
    from darnit.config.merger import load_framework_config

    return load_controls_from_framework(load_framework_config(impl.get_framework_config_path()))


class TestGittufImplementation:
    """Tests that GittufImplementation satisfies the plugin protocol."""

    def setup_method(self):
        self.impl = GittufImplementation()

    def test_name(self) -> None:
        assert self.impl.name == "gittuf"

    def test_display_name(self) -> None:
        assert "Gittuf" in self.impl.display_name

    def test_version_is_string(self) -> None:
        assert isinstance(self.impl.version, str)
        assert len(self.impl.version) > 0

    def test_framework_toml_defines_three_controls(self) -> None:
        controls = _framework_controls(self.impl)
        assert len(controls) == 3

    def test_control_ids(self) -> None:
        ids = {c.control_id for c in _framework_controls(self.impl)}
        assert "GT-01.01" in ids
        assert "GT-01.02" in ids
        assert "GT-02.01" in ids

    def test_control_levels(self) -> None:
        levels = {c.control_id: c.level for c in _framework_controls(self.impl)}
        assert levels == {"GT-01.01": 1, "GT-01.02": 1, "GT-02.01": 2}

    def test_framework_config_path_exists(self) -> None:
        path = self.impl.get_framework_config_path()
        assert path is not None
        assert path.exists()
        assert path.suffix == ".toml"

    def test_get_check_handlers_returns_dict(self) -> None:
        handlers = self.impl.get_check_handlers()
        assert isinstance(handlers, dict)
        assert "gittuf_verify_policy" in handlers
        assert "gittuf_commits_signed" in handlers

    def test_get_context_handlers_returns_empty_dict(self) -> None:
        assert self.impl.get_context_handlers() == {}

    def test_get_remediation_handlers_returns_empty_dict(self) -> None:
        assert self.impl.get_remediation_handlers() == {}
