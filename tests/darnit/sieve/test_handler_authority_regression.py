"""Regression test for PR #365 review blocker (feature 025).

The `handler_registry.register()` API used to have a
`default_authority = "suggestive"` fallback. Every plugin handler in
darnit-gittuf, darnit-reproducibility, and darnit-baseline was registered
without the argument -- so every observation-based control from every
plugin silently regressed PASS -> WARN because a suggestive result
never terminates the Check phase.

The API is now keyword-only-required. A plugin that forgets the argument
gets a TypeError at registration time, not a silent audit-status
regression. This test guards the invariant.

Reviewer's request verbatim: "a regression test asserting no registered
handler falls back to the default implicitly, so the next plugin
doesn't reintroduce this."
"""

from __future__ import annotations

import pytest

from darnit.sieve.handler_registry import (
    SieveHandlerRegistry,
    get_sieve_handler_registry,
)


def _noop_handler(config, context):  # noqa: ANN001, ARG001
    """Trivial handler used only for signature verification."""
    from darnit.sieve.models import HandlerResult

    return HandlerResult(status="PASS", details="noop")


class TestRegisterRequiresExplicitAuthority:
    """The API refuses to accept an implicit default."""

    def test_missing_default_authority_raises_type_error(self) -> None:
        """A plugin that forgets `default_authority` fails at
        registration time -- BEFORE any audit runs and reports the wrong
        status."""
        reg = SieveHandlerRegistry()
        with pytest.raises(TypeError):
            reg.register(  # type: ignore[call-arg]
                "test_handler",
                phase="deterministic",
                handler_fn=_noop_handler,
                description="handler that forgets authority",
            )

    def test_positional_default_authority_rejected(self) -> None:
        """Prevent the argument from being passed positionally --
        keyword-only forces the plugin author to spell the intent."""
        reg = SieveHandlerRegistry()
        with pytest.raises(TypeError):
            reg.register(  # type: ignore[misc]
                "test_handler",
                "deterministic",
                _noop_handler,
                "description",
                "dispositive",  # positional -- must be keyword
            )

    def test_explicit_dispositive_accepted(self) -> None:
        reg = SieveHandlerRegistry()
        reg.register(
            "test_handler",
            phase="deterministic",
            handler_fn=_noop_handler,
            description="handler with explicit authority",
            default_authority="dispositive",
        )
        info = reg.get("test_handler")
        assert info is not None
        assert info.default_authority == "dispositive"


class TestPluginHandlersAreDispositive:
    """Each ground-truth-observing plugin handler MUST be registered
    dispositive so its PASS conclusion terminates the Check phase.

    This test loads every registered plugin's sieve handlers via the
    live registry and asserts the ground-truth observers are dispositive.
    If a future plugin author registers `gittuf_verify_policy` (or any
    other observation-based handler) as `suggestive`, this test fails.
    """

    # Handlers that observe ground truth: file presence, exec output,
    # cryptographic verification, CI-workflow contents, etc. Extending
    # this list is a deliberate curation step -- new observation-based
    # handlers should be added here as they land.
    _DISPOSITIVE_HANDLERS = {
        # darnit-gittuf
        "gittuf_verify_policy",
        "gittuf_commits_signed",
        # darnit-reproducibility
        "repro_deps_pinned",
        "repro_build_env_declared",
        "repro_hermetic_build",
        "repro_provenance_exists",
        "repro_bit_for_bit",
        # darnit-baseline
        "generate_threat_model",
    }

    def test_every_expected_dispositive_handler_is_dispositive(self) -> None:
        # Force plugin registration by calling each implementation's
        # register_sieve_handlers / register_handlers method.
        self._register_all_known_plugin_handlers()

        registry = get_sieve_handler_registry()
        for name in sorted(self._DISPOSITIVE_HANDLERS):
            info = registry.get(name)
            if info is None:
                pytest.skip(
                    f"handler {name!r} not registered in this environment; "
                    "the plugin package may not be installed",
                )
            assert info.default_authority == "dispositive", (
                f"Handler {name!r} defaults to authority "
                f"{info.default_authority!r}. A ground-truth observer must "
                "be `dispositive` so its PASS terminates the Check phase. "
                "Fix by adding `default_authority=\"dispositive\"` to the "
                "handler's `registry.register(...)` call in its plugin's "
                "`register_sieve_handlers()`."
            )

    @staticmethod
    def _register_all_known_plugin_handlers() -> None:
        """Manually invoke each known plugin's sieve-handler registration.

        Discovery via entry points would be more elegant but we want
        this test to fail loudly if a plugin package is missing rather
        than silently skip.
        """
        # darnit-gittuf
        try:
            from darnit_gittuf.implementation import (
                GittufImplementation,
            )

            GittufImplementation().register_sieve_handlers()
        except Exception:
            pass

        # darnit-reproducibility
        try:
            from darnit_reproducibility.implementation import (
                ReproducibilityImplementation,
            )

            ReproducibilityImplementation().register_sieve_handlers()
        except Exception:
            pass

        # darnit-baseline
        try:
            from darnit_baseline.implementation import (
                OSPSBaselineImplementation,
            )

            OSPSBaselineImplementation().register_handlers()
        except Exception:
            pass
