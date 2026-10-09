"""Plugin sieve-handler registration and control ordering.

Covers issues #427 and #428, both reported against the
`darnit-reproducibility` plugin but rooted in the framework.

#427: plugin-provided sieve handlers never reached the registry outside
the MCP server path, so every control referencing one fell through to
`manual` and reported WARN. The WARN text ("Could not automatically
verify - manual verification required") is indistinguishable from a
control that genuinely could not be determined, which is what made this
hard to spot -- the audit looked like it ran.

#428: control iteration order came from a `set`, so the same repo
audited twice listed its controls differently.
"""

from __future__ import annotations

import pytest

from darnit.core.discovery import register_implementation_handlers
from darnit.sieve.handler_registry import get_sieve_handler_registry

# Handlers shipped by darnit-reproducibility, the plugin #427 was reported against.
_REPRO_HANDLERS = (
    "repro_deps_pinned",
    "repro_build_env_declared",
    "repro_hermetic_build",
    "repro_witness_attestation",
    "repro_provenance_exists",
    "repro_bit_for_bit",
)


class TestRegisterImplementationHandlers:
    """#427: registration must be explicit, not a side effect of discovery."""

    @pytest.mark.unit
    def test_registers_reproducibility_handlers(self) -> None:
        assert register_implementation_handlers("reproducibility") is True

        registry = get_sieve_handler_registry()
        missing = [h for h in _REPRO_HANDLERS if registry.get(h) is None]
        assert missing == [], f"handlers absent from registry: {missing}"

    @pytest.mark.unit
    def test_registers_baseline_handlers(self) -> None:
        assert register_implementation_handlers("openssf-baseline") is True

    @pytest.mark.unit
    def test_works_when_discovery_cache_is_already_warm(self) -> None:
        """The regression that made #427 intermittent.

        `discover_implementations()` is cached, and plugins that registered
        from their `register()` entry point did so once, during the first
        discovery. Any caller that warmed the cache earlier in the process
        therefore left handlers unregistered.
        That timing dependence is why the bug presented as "3 of 5
        handlers missing" on one run and "5 of 5" on the next.

        Registration must not depend on cache state.
        """
        from darnit.core.discovery import discover_implementations

        discover_implementations()  # warm the cache first
        assert register_implementation_handlers("reproducibility") is True

        registry = get_sieve_handler_registry()
        assert all(registry.get(h) is not None for h in _REPRO_HANDLERS)

    @pytest.mark.unit
    def test_none_framework_is_a_noop(self) -> None:
        """Callers that never resolved a framework must not need a guard."""
        assert register_implementation_handlers(None) is False

    @pytest.mark.unit
    def test_unknown_framework_is_a_noop(self) -> None:
        assert register_implementation_handlers("no-such-framework") is False

    @pytest.mark.unit
    def test_is_idempotent(self) -> None:
        """Called once per audit; repeat calls must not raise."""
        assert register_implementation_handlers("reproducibility") is True
        assert register_implementation_handlers("reproducibility") is True

    @pytest.mark.unit
    def test_plugin_exception_is_contained(self) -> None:
        """A broken plugin degrades the audit; it must not abort it.

        Constitution Principle I: missing or failing implementations
        degrade gracefully rather than crashing the framework.
        """
        from unittest.mock import MagicMock, patch

        broken = MagicMock()
        broken.register_handlers.side_effect = RuntimeError("plugin is broken")

        with patch("darnit.core.discovery.get_implementation", return_value=broken):
            assert register_implementation_handlers("anything") is False


class TestProtocolMethodNaming:
    """`register_handlers()` is the hook; `register_sieve_handlers()` is a compatibility shim (#451).

    Every in-tree plugin uses `register_handlers()`. The framework still
    calls `register_sieve_handlers()` so out-of-tree plugins written
    against the old name keep their step types.
    """

    @pytest.mark.unit
    @pytest.mark.parametrize(
        ("module", "cls"),
        [
            ("darnit_baseline.implementation", "OSPSBaselineImplementation"),
            ("darnit_csl.implementation", "CommunitySpecImplementation"),
            ("darnit_gittuf.implementation", "GittufImplementation"),
            ("darnit_hello.implementation", "HelloImplementation"),
            ("darnit_reproducibility.implementation", "ReproducibilityImplementation"),
            ("darnit_testchecks.implementation", "CustomStepsImplementation"),
        ],
    )
    def test_in_tree_plugins_use_only_register_handlers(self, module: str, cls: str) -> None:
        import importlib

        implementation = getattr(importlib.import_module(module), cls)
        assert callable(getattr(implementation, "register_handlers", None))
        assert not hasattr(implementation, "register_sieve_handlers")

    @pytest.mark.unit
    def test_plugin_with_only_the_compatibility_name_registers_its_step_types(
        self, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        """An out-of-tree plugin that predates #451 still gets its step types registered."""
        from unittest.mock import patch

        import darnit.sieve.handler_registry as handler_registry
        from darnit.sieve.handler_registry import HandlerResult, HandlerResultStatus

        monkeypatch.setattr(handler_registry, "_sieve_handler_registry", None)

        class LegacyPlugin:
            name = "legacy"

            def register_sieve_handlers(self) -> None:
                registry = get_sieve_handler_registry()
                registry.set_plugin_context(self.name)
                registry.register(
                    "legacy_check",
                    phase="deterministic",
                    handler_fn=lambda config, context: HandlerResult(status=HandlerResultStatus.FAIL, message="x"),
                    ceiling={"fail"},
                    settings=frozenset(),
                )
                registry.set_plugin_context(None)

        with patch("darnit.core.discovery.get_implementation", return_value=LegacyPlugin()):
            assert register_implementation_handlers("legacy") is True
        info = get_sieve_handler_registry().get("legacy_check")
        assert info is not None
        assert info.plugin == "legacy"

    @pytest.mark.unit
    def test_csl_step_type_registers_through_the_hook(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """darnit-csl registered at import before #451; a registry reset must not lose its step type."""
        import darnit.sieve.handler_registry as handler_registry

        monkeypatch.setattr(handler_registry, "_sieve_handler_registry", None)
        assert get_sieve_handler_registry().get("csl_llm_if_present") is None

        assert register_implementation_handlers("community-spec") is True
        assert get_sieve_handler_registry().get("csl_llm_if_present") is not None

    @pytest.mark.unit
    def test_accepts_register_handlers_spelling(self) -> None:
        from unittest.mock import MagicMock, patch

        impl = MagicMock(spec=["register_handlers"])
        with patch("darnit.core.discovery.get_implementation", return_value=impl):
            assert register_implementation_handlers("x") is True
        impl.register_handlers.assert_called_once()

    @pytest.mark.unit
    def test_accepts_register_sieve_handlers_spelling(self) -> None:
        from unittest.mock import MagicMock, patch

        impl = MagicMock(spec=["register_sieve_handlers"])
        with patch("darnit.core.discovery.get_implementation", return_value=impl):
            assert register_implementation_handlers("x") is True
        impl.register_sieve_handlers.assert_called_once()

    @pytest.mark.unit
    def test_implementation_with_both_spellings_calls_both(self) -> None:
        """A plugin may define both names; neither is skipped."""
        from unittest.mock import MagicMock, patch

        impl = MagicMock(spec=["register_handlers", "register_sieve_handlers"])
        with patch("darnit.core.discovery.get_implementation", return_value=impl):
            assert register_implementation_handlers("x") is True
        impl.register_handlers.assert_called_once()
        impl.register_sieve_handlers.assert_called_once()

    @pytest.mark.unit
    def test_plugin_step_types_load_with_a_fresh_registry(self, monkeypatch: pytest.MonkeyPatch) -> None:
        """Strict loading (044) must find a plugin's step types without a manual registration."""
        import darnit.sieve.handler_registry as handler_registry
        from darnit.config.control_loader import load_controls_from_effective
        from darnit.config.merger import load_effective_config_by_name

        monkeypatch.setattr(handler_registry, "_sieve_handler_registry", None)
        config = load_effective_config_by_name("testchecks-steps")

        assert len(load_controls_from_effective(config)) == len(config.controls)
        assert get_sieve_handler_registry().get("testchecks_readme_description") is not None

    @pytest.mark.unit
    def test_implementation_with_neither_is_a_noop(self) -> None:
        from unittest.mock import MagicMock, patch

        impl = MagicMock(spec=["name"])
        with patch("darnit.core.discovery.get_implementation", return_value=impl):
            assert register_implementation_handlers("x") is False


class TestControlOrderDeterminism:
    """#428: merged control order must be stable across runs."""

    def _merge(self):
        from darnit.config.merger import load_effective_config_by_name

        return load_effective_config_by_name("openssf-baseline")

    @pytest.mark.unit
    def test_control_order_is_stable_across_merges(self) -> None:
        """A `set` here randomized order per PYTHONHASHSEED."""
        first = list(self._merge().controls.keys())
        for _ in range(5):
            assert list(self._merge().controls.keys()) == first

    @pytest.mark.unit
    def test_order_follows_toml_declaration_not_alphabetical(self) -> None:
        """Declaration order groups controls by domain the way the
        framework author wrote them. Sorting would have been stable too,
        but would discard that grouping.
        """
        ids = list(self._merge().controls.keys())
        assert ids != sorted(ids), (
            "control order is alphabetical; expected TOML declaration order"
        )

    @pytest.mark.unit
    def test_no_duplicate_control_ids_after_merge(self) -> None:
        """Guards the set -> list change: dedup must still happen."""
        ids = list(self._merge().controls.keys())
        assert len(ids) == len(set(ids))
