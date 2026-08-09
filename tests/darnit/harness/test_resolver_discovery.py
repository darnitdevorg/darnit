"""Tests for QuestionResolver entry-point discovery (feature 027 T020).

Covers contract QR-14..QR-16 and research decision R2.
"""

from __future__ import annotations

from importlib.metadata import EntryPoint
from unittest.mock import patch

import pytest

from darnit.harness.driver import HarnessSetupError
from darnit.harness.question_resolvers import QuestionResolver
from darnit.harness.resolver_discovery import (
    ENTRY_POINT_GROUP,
    build_default_resolver_chain,
    discover_registered_resolvers,
)


class TestDiscovery:
    def test_interactive_terminal_is_registered_by_darnit_core(self) -> None:
        """darnit-core's own pyproject.toml registers `interactive_terminal`."""
        resolvers = discover_registered_resolvers()
        assert "interactive_terminal" in resolvers

    def test_returned_instances_conform_to_protocol(self) -> None:
        resolvers = discover_registered_resolvers()
        for name, instance in resolvers.items():
            assert isinstance(instance, QuestionResolver), (
                f"resolver {name!r} does not satisfy the Protocol"
            )

    def test_broken_entry_point_is_skipped_with_warning(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """QR-16: an entry point that fails to load is logged and skipped;
        other entry points still register."""
        import logging

        # Craft a real EntryPoint pointing at a nonexistent module.
        broken_ep = EntryPoint(
            name="broken_resolver",
            value="darnit_nonexistent_module_xyz:factory",
            group=ENTRY_POINT_GROUP,
        )

        # Also craft a good EntryPoint pointing at the interactive-terminal
        # factory so the "other resolvers still register" claim is verifiable.
        good_ep = EntryPoint(
            name="_test_good",
            value="darnit.harness.interactive_resolver:build",
            group=ENTRY_POINT_GROUP,
        )

        class _FakeEntryPoints:
            def __init__(self, items: list[EntryPoint]) -> None:
                self._items = items

            def __iter__(self):
                return iter(self._items)

        with patch(
            "darnit.harness.resolver_discovery.metadata.entry_points",
            return_value=_FakeEntryPoints([broken_ep, good_ep]),
        ):
            caplog.set_level(logging.WARNING, logger="darnit.harness.resolver_discovery")
            resolvers = discover_registered_resolvers()

        # Broken skipped; good registered
        assert "broken_resolver" not in resolvers
        assert "_test_good" in resolvers

        # Warning was logged
        warn_msgs = [
            r.getMessage() for r in caplog.records
            if r.name == "darnit.harness.resolver_discovery"
        ]
        assert any("broken_resolver" in m for m in warn_msgs)

    def test_factory_returning_wrong_type_is_skipped_with_warning(
        self, caplog: pytest.LogCaptureFixture,
    ) -> None:
        """QR-16: a factory that returns a non-Protocol object is skipped."""
        import logging

        class _MockEntryPoint:
            """Mock that implements the minimal EntryPoint API we call."""

            name = "wrong_type"

            def load(self):
                # Return the factory; harness will call it and see object().
                return lambda: object()

        class _MockEntryPoints:
            def __iter__(self):
                return iter([_MockEntryPoint()])

        with patch(
            "darnit.harness.resolver_discovery.metadata.entry_points",
            return_value=_MockEntryPoints(),
        ):
            caplog.set_level(
                logging.WARNING,
                logger="darnit.harness.resolver_discovery",
            )
            resolvers = discover_registered_resolvers()

        assert "wrong_type" not in resolvers
        assert any(
            "does not satisfy the QuestionResolver Protocol" in r.getMessage()
            for r in caplog.records
        )


class TestBuildDefaultResolverChain:
    def test_interactive_true_puts_terminal_first(self) -> None:
        chain = build_default_resolver_chain(interactive=True)
        assert chain, "chain should be non-empty when interactive=True"
        assert chain[0].name == "interactive_terminal"

    def test_interactive_false_omits_terminal(self) -> None:
        """QR-21: --interactive controls whether the terminal is in the chain."""
        chain = build_default_resolver_chain(interactive=False)
        names = [r.name for r in chain]
        assert "interactive_terminal" not in names

    def test_interactive_true_raises_if_terminal_missing(self) -> None:
        """Explicit failure mode when a fleet installs without the terminal
        resolver's entry point (should be impossible in practice, defensive)."""
        with patch(
            "darnit.harness.resolver_discovery.discover_registered_resolvers",
            return_value={},
        ):
            with pytest.raises(HarnessSetupError):
                build_default_resolver_chain(interactive=True)
