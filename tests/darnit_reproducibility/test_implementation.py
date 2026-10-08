"""Tests for ReproducibilityImplementation plugin protocol compliance."""

from darnit_reproducibility.implementation import ReproducibilityImplementation


def _framework_controls(impl):
    """Controls as the audit loads them, from the implementation's framework TOML."""
    from darnit.config import load_controls_from_framework
    from darnit.config.merger import load_framework_config

    return load_controls_from_framework(load_framework_config(impl.get_framework_config_path()))


class TestReproducibilityImplementation:
    """Tests that ReproducibilityImplementation satisfies the plugin protocol."""

    def setup_method(self):
        self.impl = ReproducibilityImplementation()

    def test_name(self) -> None:
        assert self.impl.name == "reproducibility"

    def test_display_name(self) -> None:
        assert len(self.impl.display_name) > 0

    def test_framework_toml_defines_five_controls(self) -> None:
        assert len(_framework_controls(self.impl)) == 5

    def test_control_ids(self) -> None:
        ids = {c.control_id for c in _framework_controls(self.impl)}
        assert ids == {"RE-01.01", "RE-01.02", "RE-02.01", "RE-02.02", "RE-03.01"}

    def test_control_levels(self) -> None:
        levels = {c.control_id: c.level for c in _framework_controls(self.impl)}
        assert levels == {"RE-01.01": 1, "RE-01.02": 1, "RE-02.01": 2, "RE-02.02": 2, "RE-03.01": 3}

    def test_framework_config_path_exists(self) -> None:
        path = self.impl.get_framework_config_path()
        assert path is not None
        assert path.exists()

    def test_check_handlers_covers_all_controls(self) -> None:
        from darnit.sieve.handler_registry import (
            get_sieve_handler_registry,
            reset_sieve_handler_registry,
        )
        reset_sieve_handler_registry()
        self.impl.register_handlers()
        registry = get_sieve_handler_registry()
        expected = {
            "repro_deps_pinned", "repro_build_env_declared",
            "repro_hermetic_build", "repro_provenance_exists",
            "repro_bit_for_bit", "repro_witness_attestation",
        }
        for name in expected:
            assert registry.get(name) is not None, f"{name} not registered"

    def test_all_check_handlers_are_callable(self) -> None:
        from darnit.sieve.handler_registry import (
            get_sieve_handler_registry,
            reset_sieve_handler_registry,
        )
        reset_sieve_handler_registry()
        self.impl.register_handlers()
        registry = get_sieve_handler_registry()
        for name in [
            "repro_deps_pinned", "repro_build_env_declared",
            "repro_hermetic_build", "repro_provenance_exists",
            "repro_bit_for_bit", "repro_witness_attestation",
        ]:
            info = registry.get(name)
            assert info is not None and callable(info.fn), f"{name} not callable"
