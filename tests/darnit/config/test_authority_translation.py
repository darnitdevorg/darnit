"""Legacy TOML ``authority`` step field under per-claim authority.

Feature 025 T013b / SC-006 introduced a per-step ``authority``; feature 041
replaced per-handler authority with registered ceilings. This suite verifies
the legacy field still loads with a well-defined meaning:

1. Steps that omit ``authority`` load cleanly; the step type's ceiling
   applies at dispatch time.
2. ``authority = "suggestive"`` narrows a step to evidence only (always
   accepted).
3. ``authority = "dispositive"`` is accepted where the ceiling is non-empty
   and rejected where the step type concludes nothing (the false-PASS lever
   Stage 1 removed).
4. ``authority = "asserted"`` is rejected: no step type is a person's
   confirmation.
"""

from __future__ import annotations

import pytest

from darnit.config.control_loader import validate_step_authority
from darnit.config.framework_schema import HandlerInvocation
from darnit.core.errors import AuthorityViolation
from darnit.sieve.handler_registry import get_sieve_handler_registry


class TestAuthorityAutoInference:
    """Case (a): a control TOML without explicit authority loads cleanly and
    the orchestrator uses the step type's ceiling at dispatch time."""

    def test_single_file_exists_step_no_explicit_authority(self) -> None:
        """A single-step control using file_exists loads with authority=None
        on the invocation; the file_exists ceiling applies at dispatch."""
        registry = get_sieve_handler_registry()
        info = registry.get("file_exists")
        assert info is not None
        assert info.ceiling == frozenset({"fail"})

        inv = HandlerInvocation(handler="file_exists", files=["README.md"])
        assert inv.authority is None

        # Load-time validation: no explicit authority -> passes silently.
        validate_step_authority(None, "TEST-01", [inv])

    def test_mixed_phases_no_explicit_authority(self) -> None:
        """A control with file_exists -> llm_eval -> manual loads cleanly;
        each step's effective set derives from its step type's ceiling."""
        inv_file = HandlerInvocation(handler="file_exists", files=["SECURITY.md"])
        inv_llm = HandlerInvocation(handler="llm_eval", prompt="Check security")
        inv_manual = HandlerInvocation(handler="manual", steps=["Confirm"])

        validate_step_authority(None, "TEST-02", [inv_file, inv_llm, inv_manual])

        # Ceilings per feature 041 data-model.md
        registry = get_sieve_handler_registry()
        assert registry.get("file_exists").ceiling == frozenset({"fail"})
        assert registry.get("llm_eval").ceiling == frozenset()
        assert registry.get("manual").ceiling == frozenset()

    def test_regex_step_no_explicit_authority(self) -> None:
        """A control using the regex/pattern handler loads cleanly."""
        inv = HandlerInvocation(
            handler="regex",
            files=["**/*.py"],
            pattern="secret",
        )
        validate_step_authority(None, "TEST-03", [inv])


class TestAuthorityTightening:
    """Case (d): a step MAY narrow what it concludes (tightening = more
    cautious). Verify accepted."""

    def test_dispositive_handler_marked_suggestive_step(self) -> None:
        """file_exists marked suggestive at TOML: allowed (evidence only)."""
        inv = HandlerInvocation(
            handler="file_exists",
            files=["README.md"],
            authority="suggestive",
        )
        # Should not raise.
        validate_step_authority(None, "TEST-TIGHTEN-01", [inv])

    def test_dispositive_handler_marked_dispositive_step(self) -> None:
        """dispositive on a step type with a non-empty ceiling: allowed, no change."""
        inv = HandlerInvocation(
            handler="file_exists",
            files=["README.md"],
            authority="dispositive",
        )
        validate_step_authority(None, "TEST-TIGHTEN-02", [inv])

    def test_asserted_handler_marked_suggestive_step(self) -> None:
        """manual marked suggestive at TOML: allowed (it concludes nothing anyway)."""
        inv = HandlerInvocation(
            handler="manual",
            steps=["Check"],
            authority="suggestive",
        )
        validate_step_authority(None, "TEST-TIGHTEN-03", [inv])


class TestAuthorityLoosening:
    """Case (c): a step MUST NOT claim to conclude what its step type cannot
    (loosening). Verify rejected with AuthorityViolation."""

    def test_llm_eval_marked_dispositive_rejected(self) -> None:
        """llm_eval (ceiling: nothing) marked dispositive at TOML: rejected.

        This is the exact false-PASS lever RFC-0001 Stage 1 removes. A TOML
        author cannot claim an LLM output is dispositive.
        """
        inv = HandlerInvocation(
            handler="llm_eval",
            prompt="Check",
            authority="dispositive",
        )
        with pytest.raises(AuthorityViolation) as excinfo:
            validate_step_authority(None, "BAD-LLM-01", [inv])
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
            validate_step_authority(None, "BAD-LLM-02", [inv])

    def test_file_exists_marked_asserted_rejected(self) -> None:
        """A presence step marked asserted: rejected (asserted is a person's confirmation)."""
        inv = HandlerInvocation(
            handler="file_exists",
            files=["X"],
            authority="asserted",
        )
        with pytest.raises(AuthorityViolation):
            validate_step_authority(None, "BAD-FILE-01", [inv])


class TestUnknownHandler:
    """Case: a step names a handler not in the registry -> loading fails
    (feature 044, FR-009, replacing the silent skip)."""

    def test_unknown_handler_raises_at_validation(self) -> None:
        inv = HandlerInvocation(handler="nonexistent_handler_xyz")
        with pytest.raises(AuthorityViolation, match="nonexistent_handler_xyz"):
            validate_step_authority(None, "TEST-UNKNOWN", [inv])

    def test_operator_supplied_unknown_handler_loads(self) -> None:
        inv = HandlerInvocation(handler="nonexistent_handler_xyz")
        validate_step_authority(None, "TEST-UNKNOWN", [inv], operator_supplied=True)
