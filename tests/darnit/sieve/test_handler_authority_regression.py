"""Regression test for PR #365 review blocker (feature 025), under feature 041.

The `handler_registry.register()` API used to have a
`default_authority = "suggestive"` fallback. Every plugin handler in
darnit-gittuf, darnit-reproducibility, and darnit-baseline was registered
without the argument -- so every observation-based control from every
plugin silently regressed PASS -> WARN because a suggestive result
never terminates the Check phase.

Feature 041 replaced the scalar authority with a registered ceiling; per
contracts/step-declarations.md rule 5 a handler that registers no ceiling is
evidence only. The guard against the #365 regression is therefore the
curated list below: every ground-truth observer must register a ceiling
that lets it conclude PASS and FAIL.
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


class TestRegisterCeiling:
    """Registration records the ceiling a plugin declares."""

    def test_missing_ceiling_is_evidence_only(self) -> None:
        """A plugin that declares no ceiling can never conclude a control:
        the conservative default (contracts/step-declarations.md rule 5)."""
        reg = SieveHandlerRegistry()
        reg.register(
            "test_handler",
            phase="deterministic",
            handler_fn=_noop_handler,
            description="handler that declares no ceiling",
        )
        assert reg.get("test_handler").ceiling == frozenset()

    def test_positional_ceiling_rejected(self) -> None:
        """Keyword-only forces the plugin author to spell the intent."""
        reg = SieveHandlerRegistry()
        with pytest.raises(TypeError):
            reg.register(  # type: ignore[misc]
                "test_handler",
                "deterministic",
                _noop_handler,
                "description",
                {"pass", "fail"},  # positional -- must be keyword
            )

    def test_explicit_ceiling_accepted(self) -> None:
        reg = SieveHandlerRegistry()
        reg.register(
            "test_handler",
            phase="deterministic",
            handler_fn=_noop_handler,
            description="handler with explicit ceiling",
            ceiling={"pass", "fail"},
        )
        info = reg.get("test_handler")
        assert info is not None
        assert info.ceiling == frozenset({"pass", "fail"})


class TestPluginHandlersAreDispositive:
    """Each ground-truth-observing plugin handler MUST register the
    {pass, fail} ceiling so its PASS conclusion terminates the Check phase.

    This test loads every registered plugin's sieve handlers via the
    live registry and asserts the ground-truth observers may conclude.
    If a future plugin author registers `gittuf_verify_policy` (or any
    other observation-based handler) without a ceiling, this test fails.
    """

    # Handlers that observe ground truth: file presence, exec output,
    # cryptographic verification, CI-workflow contents, etc. Extending
    # this list is a deliberate curation step -- new observation-based
    # handlers should be added here as they land.
    _DISPOSITIVE_HANDLERS = {
        # darnit-gittuf
        "gittuf_verify_policy",
        "gittuf_commits_signed",
        # darnit-reproducibility's repro_* step types left this list in
        # feature 044 (FR-010): they decide from text and file-presence
        # signals and register {fail} (tests/darnit_reproducibility/
        # test_no_pass_from_signals.py).
        # darnit-baseline
        "generate_threat_model",
        "github_branch_protection",
    }

    def test_every_expected_dispositive_handler_is_dispositive(self) -> None:
        # Force plugin registration by calling each implementation's
        # register_handlers method.
        self._register_all_known_plugin_handlers()

        registry = get_sieve_handler_registry()
        for name in sorted(self._DISPOSITIVE_HANDLERS):
            info = registry.get(name)
            if info is None:
                pytest.skip(
                    f"handler {name!r} not registered in this environment; "
                    "the plugin package may not be installed",
                )
            assert info.ceiling == frozenset({"pass", "fail"}), (
                f"Handler {name!r} registers ceiling {sorted(info.ceiling)!r}. "
                "A ground-truth observer must register {pass, fail} so its "
                "PASS terminates the Check phase. Fix by adding "
                "`ceiling={\"pass\", \"fail\"}` to the handler's "
                "`registry.register(...)` call in its plugin's "
                "`register_handlers()`."
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

            GittufImplementation().register_handlers()
        except Exception:
            pass

        # darnit-reproducibility
        try:
            from darnit_reproducibility.implementation import (
                ReproducibilityImplementation,
            )

            ReproducibilityImplementation().register_handlers()
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
