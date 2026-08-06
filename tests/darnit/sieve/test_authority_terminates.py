"""End-to-end SC-001 tests: only dispositive/asserted can conclude a control.

Feature 025 T016-T018 + T020. Exercises the orchestrator's full dispatch path
to prove the RFC-0001 Stage 1 safety property (spec.md FR-004, SC-001, SC-008).
"""

from __future__ import annotations

from darnit.config.framework_schema import HandlerInvocation
from darnit.sieve.handler_registry import (
    HandlerResult,
    HandlerResultStatus,
    get_sieve_handler_registry,
)
from darnit.sieve.models import CheckContext, ControlSpec
from darnit.sieve.orchestrator import SieveOrchestrator


def _make_control(control_id: str, invocations: list[HandlerInvocation]) -> ControlSpec:
    return ControlSpec(
        control_id=control_id,
        level=1,
        domain="TEST",
        name="Test",
        description="Test",
        metadata={"handler_invocations": invocations},
    )


def _make_ctx(tmp_path=None) -> CheckContext:
    return CheckContext(
        owner="test",
        repo="repo",
        local_path=str(tmp_path) if tmp_path else "/tmp",
        default_branch="main",
        control_id="test",
    )


class TestLLMOnlyCannotConclude:
    """SC-001: an LLM-only strategy list cannot produce a PASS.

    This is the load-bearing safety property FR-001/FR-004 establish. A
    regression that reclassifies LLM output as dispositive, or that lets
    suggestive results terminate the strategy list, fails these tests with
    a message naming the authority.
    """

    def test_llm_only_control_never_passes(self):
        """SC-001 primary: single LLM step returning high-confidence PASS
        produces WARN, not PASS, on the control."""
        registry = get_sieve_handler_registry()

        # Register a stand-in for llm_eval that returns PASS deterministically.
        # It inherits the default_authority="suggestive" from the llm_eval
        # registration if it uses that handler name; using a distinct name
        # with the same suggestive default proves the RULE, not any specific
        # handler's behavior.
        def fake_llm(config, context):
            return HandlerResult(
                status=HandlerResultStatus.PASS,
                message="LLM says yes with high confidence",
                confidence=0.99,
                evidence={"llm_says": "yes"},
            )

        registry.register(
            "fake_llm_for_sc001",
            "llm",
            fake_llm,
            default_authority="suggestive",
        )

        control = _make_control(
            "LLM-ONLY-01",
            [HandlerInvocation(handler="fake_llm_for_sc001")],
        )
        orch = SieveOrchestrator()
        result = orch.verify(control, _make_ctx())

        assert result.status == "WARN", (
            f"LLM-only strategy list must NEVER produce PASS. Got status={result.status}. "
            "This is the RFC-0001 Stage 1 safety property (FR-001, FR-004, SC-001). "
            "If this test failed, a regression allowed suggestive authority to conclude."
        )
        # Evidence MUST be preserved for human review.
        assert result.evidence.get("llm_says") == "yes"

    def test_dispositive_after_suggestive_still_terminates(self):
        """FR-003 (b): a suggestive result attaches evidence and does NOT
        terminate; a later dispositive step can conclude."""
        registry = get_sieve_handler_registry()

        def fake_llm(config, context):
            return HandlerResult(
                status=HandlerResultStatus.PASS,
                message="LLM proposal",
                confidence=0.9,
                evidence={"proposal": "found"},
            )

        def fake_file_exists(config, context):
            return HandlerResult(
                status=HandlerResultStatus.PASS,
                message="File exists",
                confidence=1.0,
                evidence={"file": "/path"},
            )

        registry.register("fake_llm_2", "llm", fake_llm, default_authority="suggestive")
        registry.register("fake_dispositive_2", "deterministic", fake_file_exists, default_authority="dispositive")

        control = _make_control(
            "MIX-01",
            [
                HandlerInvocation(handler="fake_llm_2"),
                HandlerInvocation(handler="fake_dispositive_2"),
            ],
        )
        orch = SieveOrchestrator()
        result = orch.verify(control, _make_ctx())

        assert result.status == "PASS"
        # Concluding step is the dispositive one; its authority is what's
        # recorded on the SieveResult.
        assert result.authority == "dispositive"
        # Suggestive evidence is preserved (accumulated across steps).
        assert result.evidence.get("proposal") == "found"
        assert result.evidence.get("file") == "/path"

    def test_error_from_dispositive_terminates_without_escalation(self):
        """FR-003 (c): ERROR is terminal; strategy list does NOT escalate."""
        registry = get_sieve_handler_registry()

        exec_call_count = {"n": 0}

        def fake_exec(config, context):
            exec_call_count["n"] += 1
            return HandlerResult(
                status=HandlerResultStatus.ERROR,
                message="Command not available",
            )

        llm_call_count = {"n": 0}

        def fake_llm(config, context):
            llm_call_count["n"] += 1
            return HandlerResult(
                status=HandlerResultStatus.PASS,
                message="LLM says pass",
                confidence=0.95,
            )

        registry.register("fake_exec_err", "deterministic", fake_exec, default_authority="dispositive")
        registry.register("fake_llm_err_test", "llm", fake_llm, default_authority="suggestive")

        control = _make_control(
            "ERR-01",
            [
                HandlerInvocation(handler="fake_exec_err"),
                HandlerInvocation(handler="fake_llm_err_test"),
            ],
        )
        orch = SieveOrchestrator()
        result = orch.verify(control, _make_ctx())

        assert result.status == "ERROR", f"ERROR from dispositive step must be terminal, got {result.status}"
        assert exec_call_count["n"] == 1
        assert llm_call_count["n"] == 0, "LLM step must NOT have been called after ERROR (FR-003 (c): no escalation)"


class TestPromptInjectionSafety:
    """SC-008: adversarial input (prompt injection) cannot produce false PASS.

    The mock LLM naively echoes the injection payload ("outcome=yes, high
    confidence"). The runner's authority check MUST stop that from
    concluding the control.
    """

    def test_prompt_injection_does_not_produce_false_pass(self):
        """SC-008: even a fully-compromised LLM that eagerly returns PASS
        cannot conclude a control PASS."""
        registry = get_sieve_handler_registry()

        def injection_captured_llm(config, context):
            # Mock: naively echoes back what an adversarial README told it to.
            return HandlerResult(
                status=HandlerResultStatus.PASS,
                message="This project fully complies with all security standards",
                confidence=0.95,
                evidence={"llm_reasoning": "README said compliant"},
            )

        registry.register(
            "injection_captured_llm",
            "llm",
            injection_captured_llm,
            default_authority="suggestive",
        )

        control = _make_control(
            "INJECT-01",
            [HandlerInvocation(handler="injection_captured_llm")],
        )
        orch = SieveOrchestrator()
        result = orch.verify(control, _make_ctx())

        # The load-bearing safety assertion. If this fails, prompt injection
        # can manufacture a compliance claim -- the exact hazard RFC-0001
        # Stage 1 exists to eliminate.
        assert result.status == "WARN", (
            f"Prompt injection produced status={result.status}. "
            "The runner's authority check failed to stop a suggestive result "
            "from concluding. This is a CRITICAL safety regression (SC-008)."
        )
        # Evidence MUST be captured for human review even though it did not
        # conclude the control.
        assert result.evidence.get("llm_reasoning") == "README said compliant"
