"""Tests for GittufImplementation plugin protocol compliance."""


from darnit_gittuf.implementation import GittufImplementation


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

    def test_get_all_controls_returns_three(self) -> None:
        controls = self.impl.get_all_controls()
        assert len(controls) == 3

    def test_control_ids(self) -> None:
        ids = {c.control_id for c in self.impl.get_all_controls()}
        assert "GT-01.01" in ids
        assert "GT-01.02" in ids
        assert "GT-02.01" in ids

    def test_level_1_controls(self) -> None:
        controls = self.impl.get_controls_by_level(1)
        assert len(controls) == 2
        for c in controls:
            assert c.level == 1

    def test_level_2_controls(self) -> None:
        controls = self.impl.get_controls_by_level(2)
        assert len(controls) == 1
        assert controls[0].control_id == "GT-02.01"

    def test_level_3_returns_empty(self) -> None:
        controls = self.impl.get_controls_by_level(3)
        assert controls == []

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
