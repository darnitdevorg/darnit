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

# Handlers shipped by darnit-reproducibility. It is the in-tree plugin that
# exercises the `register_sieve_handlers` spelling (see the naming note in
# TestProtocolMethodNaming below).
_REPRO_HANDLERS = (
    "repro_deps_pinned",
    "repro_build_env_declared",
    "repro_hermetic_build",
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
        """darnit-baseline uses the other spelling; both must work."""
        assert register_implementation_handlers("openssf-baseline") is True

    @pytest.mark.unit
    def test_works_when_discovery_cache_is_already_warm(self) -> None:
        """The regression that made #427 intermittent.

        `discover_implementations()` is cached, and the plugins that
        self-register do so from their `register()` entry point -- which
        runs once, during the first discovery. Any caller that warmed the
        cache earlier in the process therefore left handlers unregistered.
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
    """Both in-tree spellings of the registration method must be honored.

    `CLAUDE.md` documents `register_handlers()`, and darnit-baseline
    implements it. darnit-gittuf and darnit-reproducibility implement
    `register_sieve_handlers()` instead. Until those converge, the
    framework accepts either -- otherwise two of four in-tree plugins
    register nothing.

    Reconciling the plugins onto one name is tracked separately; this
    test pins current behavior so the tolerance is deliberate and
    visible rather than accidental.
    """

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
    def test_implementation_with_neither_is_a_noop(self) -> None:
        from unittest.mock import MagicMock, patch

        impl = MagicMock(spec=["name"])
        with patch("darnit.core.discovery.get_implementation", return_value=impl):
            assert register_implementation_handlers("x") is False


class TestControlOrderDeterminism:
    """#428: merged control order must be stable across runs."""

    def _merge(self):
        from darnit.config.merger import load_effective_config_by_name

        return load_effective_config_by_name("openssf-baseline", repo_path=None)

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
