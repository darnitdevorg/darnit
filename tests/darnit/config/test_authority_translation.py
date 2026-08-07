"""Legacy TOML authority auto-inference tests (feature 025 T013b, SC-006).

Under RFC-0001 Stage 1, existing controls that omit an explicit `authority`
on their pass steps rely on the handler's registered `default_authority` as
the effective value at dispatch time. This test suite verifies that:

1. Loading a legacy-shape TOML control produces HandlerInvocation objects
   with `authority=None` (unset).
2. The orchestrator's effective-authority resolution consults the handler's
   `default_authority` when the invocation's authority is None.
3. Loosening (a step declaring an authority STRONGER than the handler's
   default) is rejected at load time with `AuthorityViolation`.
4. Tightening (a step declaring an authority WEAKER-or-equal to the default)
   is accepted.

Covers spec.md FR-015 + SC-006.
"""

from __future__ import annotations

import pytest

from darnit.config.control_loader import _validate_and_log_authority
from darnit.config.framework_schema import HandlerInvocation
from darnit.core.errors import AuthorityViolation
from darnit.sieve.handler_registry import get_sieve_handler_registry


class TestAuthorityAutoInference:
    """Case (a): a control TOML without explicit authority loads cleanly and
    the orchestrator uses the handler's default at dispatch time."""

    def test_single_file_exists_step_no_explicit_authority(self) -> None:
        """A single-step control using file_exists loads with authority=None
        on the invocation; handler default (dispositive) is used at dispatch."""
        registry = get_sieve_handler_registry()
        info = registry.get("file_exists")
        assert info is not None
        assert info.default_authority == "dispositive"

        inv = HandlerInvocation(handler="file_exists", files=["README.md"])
        assert inv.authority is None

        # Load-time validation: no explicit authority -> passes silently.
        _validate_and_log_authority("TEST-01", [inv])

    def test_mixed_phases_no_explicit_authority(self) -> None:
        """A control with file_exists -> llm_eval -> manual loads cleanly;
        each step's effective authority derives from its handler default."""
        inv_file = HandlerInvocation(handler="file_exists", files=["SECURITY.md"])
        inv_llm = HandlerInvocation(handler="llm_eval", prompt="Check security")
        inv_manual = HandlerInvocation(handler="manual", steps=["Confirm"])

        _validate_and_log_authority("TEST-02", [inv_file, inv_llm, inv_manual])

        # Handler defaults per feature 025 migration table
        registry = get_sieve_handler_registry()
        assert registry.get("file_exists").default_authority == "dispositive"
        assert registry.get("llm_eval").default_authority == "suggestive"
        assert registry.get("manual").default_authority == "asserted"

    def test_regex_step_no_explicit_authority(self) -> None:
        """A control using the regex/pattern handler loads cleanly."""
        inv = HandlerInvocation(
            handler="regex",
            files=["**/*.py"],
            pattern="secret",
        )
        _validate_and_log_authority("TEST-03", [inv])


class TestAuthorityTightening:
    """Case (d): a step MAY declare an authority WEAKER-or-equal to the
    handler's default (tightening = more cautious). Verify accepted."""

    def test_dispositive_handler_marked_suggestive_step(self) -> None:
        """file_exists (default: dispositive) marked suggestive at TOML: allowed."""
        inv = HandlerInvocation(
            handler="file_exists",
            files=["README.md"],
            authority="suggestive",
        )
        # Should not raise.
        _validate_and_log_authority("TEST-TIGHTEN-01", [inv])

    def test_dispositive_handler_marked_dispositive_step(self) -> None:
        """Explicit same-authority declaration: allowed."""
        inv = HandlerInvocation(
            handler="file_exists",
            files=["README.md"],
            authority="dispositive",
        )
        _validate_and_log_authority("TEST-TIGHTEN-02", [inv])

    def test_asserted_handler_marked_suggestive_step(self) -> None:
        """manual (default: asserted) marked suggestive at TOML: allowed
        (still tighter than asserted)."""
        inv = HandlerInvocation(
            handler="manual",
            steps=["Check"],
            authority="suggestive",
        )
        _validate_and_log_authority("TEST-TIGHTEN-03", [inv])


class TestAuthorityLoosening:
    """Case (c): a step MUST NOT declare an authority STRONGER than the
    handler's default (loosening = claiming more authority than the handler
    has). Verify rejected with AuthorityViolation."""

    def test_llm_eval_marked_dispositive_rejected(self) -> None:
        """llm_eval (default: suggestive) marked dispositive at TOML: rejected.

        This is the exact false-PASS lever RFC-0001 Stage 1 removes. A TOML
        author cannot claim an LLM output is dispositive.
        """
        inv = HandlerInvocation(
            handler="llm_eval",
            prompt="Check",
            authority="dispositive",
        )
        with pytest.raises(AuthorityViolation) as excinfo:
            _validate_and_log_authority("BAD-LLM-01", [inv])
        assert excinfo.value.control_id == "BAD-LLM-01"
        assert "llm_eval" in str(excinfo.value)
        assert "dispositive" in str(excinfo.value)

    def test_llm_eval_marked_asserted_rejected(self) -> None:
        """llm_eval marked asserted: rejected (Constitution IV: asserted is human-only)."""
        inv = HandlerInvocation(
            handler="llm_eval",
            prompt="Check",
            authority="asserted",
        )
        with pytest.raises(AuthorityViolation):
            _validate_and_log_authority("BAD-LLM-02", [inv])

    def test_file_exists_marked_asserted_rejected(self) -> None:
        """A dispositive handler marked asserted (stronger): rejected."""
        inv = HandlerInvocation(
            handler="file_exists",
            files=["X"],
            authority="asserted",
        )
        with pytest.raises(AuthorityViolation):
            _validate_and_log_authority("BAD-FILE-01", [inv])


class TestUnknownHandler:
    """Case: a step names a handler not in the registry -> validation
    silently skips (the orchestrator warns and skips at dispatch time)."""

    def test_unknown_handler_does_not_raise_at_validation(self) -> None:
        inv = HandlerInvocation(handler="nonexistent_handler_xyz")
        # No AuthorityViolation; orchestrator handles unknown handlers.
        _validate_and_log_authority("TEST-UNKNOWN", [inv])
