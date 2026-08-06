"""Tests for the sieve orchestrator."""

from darnit.config.framework_schema import HandlerInvocation
from darnit.sieve.models import (
    CheckContext,
    ControlSpec,
    LLMConsultationResponse,
    PassOutcome,
)
from darnit.sieve.orchestrator import SieveOrchestrator


def _make_context(
    local_path: str = "/tmp/test",
    project_context: dict | None = None,
) -> CheckContext:
    return CheckContext(
        owner="test-org",
        repo="test-repo",
        local_path=local_path,
        default_branch="main",
        control_id="TEST-01",
        project_context=project_context or {},
    )


class TestVerifyWithLlmResponse:
    """Test verify_with_llm_response reads config from handler_invocations."""

    def test_confidence_threshold_from_llm_eval_handler(self):
        """confidence_threshold is read from the llm_eval handler invocation."""
        orchestrator = SieveOrchestrator(stop_on_llm=True)

        spec = ControlSpec(
            control_id="TEST-01",
            level=1,
            domain="TEST",
            name="TestControl",
            description="Test",
            metadata={
                "handler_invocations": [
                    HandlerInvocation(handler="llm_eval", confidence_threshold=0.9),
                ],
            },
        )

        # Confidence 0.85 is below 0.9 threshold → should WARN
        response = LLMConsultationResponse(
            status=PassOutcome.PASS,
            confidence=0.85,
            reasoning="Looks good",
        )

        result = orchestrator.verify_with_llm_response(spec, _make_context(), response)
        assert result.status == "WARN"

    def test_default_confidence_threshold(self):
        """LLM response cannot conclude under RFC-0001 Stage 1 (feature 025).

        This test previously asserted that a confidence-above-threshold LLM
        response converts to PASS. Under Stage 1's authority model
        (FR-001/FR-004), LLM output is `suggestive` and cannot conclude
        regardless of confidence. The confidence threshold remains a
        presentation filter but is no longer a decision input. Test
        preserved with updated assertion to lock the safe behavior.
        """
        orchestrator = SieveOrchestrator(stop_on_llm=True)

        spec = ControlSpec(
            control_id="TEST-01",
            level=1,
            domain="TEST",
            name="TestControl",
            description="Test",
            metadata={
                "handler_invocations": [
                    HandlerInvocation(handler="manual", steps=["Check it"]),
                ],
            },
        )

        # Confidence 0.85 is above the historical 0.8 threshold, but Stage 1
        # rejects any LLM conclusion. Result MUST be WARN.
        response = LLMConsultationResponse(
            status=PassOutcome.PASS,
            confidence=0.85,
            reasoning="Looks good",
        )

        result = orchestrator.verify_with_llm_response(spec, _make_context(), response)
        assert result.status == "WARN"

    def test_verification_steps_from_manual_handler(self):
        """verification_steps are read from the manual handler invocation."""
        orchestrator = SieveOrchestrator(stop_on_llm=True)

        expected_steps = ["Step 1", "Step 2", "Step 3"]
        spec = ControlSpec(
            control_id="TEST-01",
            level=1,
            domain="TEST",
            name="TestControl",
            description="Test",
            metadata={
                "handler_invocations": [
                    HandlerInvocation(handler="llm_eval", confidence_threshold=0.95),
                    HandlerInvocation(handler="manual", steps=expected_steps),
                ],
            },
        )

        # Low confidence → falls through to manual → should use custom steps
        response = LLMConsultationResponse(
            status=PassOutcome.PASS,
            confidence=0.5,
            reasoning="Not sure",
        )

        result = orchestrator.verify_with_llm_response(spec, _make_context(), response)
        assert result.status == "WARN"
        assert result.verification_steps == expected_steps

    def test_missing_handler_invocations_uses_defaults(self):
        """When no handler_invocations, uses default threshold and generic steps."""
        orchestrator = SieveOrchestrator(stop_on_llm=True)

        spec = ControlSpec(
            control_id="TEST-01",
            level=1,
            domain="TEST",
            name="TestControl",
            description="Test",
            metadata={},
        )

        # Low confidence → should WARN with generic steps
        response = LLMConsultationResponse(
            status=PassOutcome.PASS,
            confidence=0.5,
            reasoning="Not sure",
        )

        result = orchestrator.verify_with_llm_response(spec, _make_context(), response)
        assert result.status == "WARN"
        assert result.verification_steps is not None
        assert "Review LLM analysis above" in result.verification_steps[0]

    def test_high_confidence_pass(self):
        """High confidence LLM PASS is DOWNGRADED to WARN under RFC-0001 Stage 1.

        Feature 025 (Slice A): `llm_eval` registers with default_authority =
        "suggestive". `is_terminal_authority("suggestive")` is False, so
        `resolve_step_result` refuses to CONCLUDE_PASS regardless of the
        LLM's confidence. The LLM's output is preserved as evidence but the
        control status is WARN (inconclusive) -- the SAFETY property FR-001
        establishes. This test previously pinned the OLD unsafe behavior
        (high-confidence LLM concluding PASS); it now pins the NEW safe
        behavior. See specs/025-rfc0001-stage1/spec.md SC-001.
        """
        orchestrator = SieveOrchestrator(stop_on_llm=True)

        spec = ControlSpec(
            control_id="TEST-01",
            level=1,
            domain="TEST",
            name="TestControl",
            description="Test",
            metadata={
                "handler_invocations": [
                    HandlerInvocation(handler="llm_eval", confidence_threshold=0.8),
                ],
            },
        )

        response = LLMConsultationResponse(
            status=PassOutcome.PASS,
            confidence=0.95,
            reasoning="Verified",
        )

        result = orchestrator.verify_with_llm_response(spec, _make_context(), response)
        # Under Stage 1, an LLM step (suggestive) can never conclude.
        assert result.status == "WARN", (
            "LLM authority is suggestive; suggestive results cannot conclude PASS "
            "(feature 025 FR-001 / SC-001 safety property)"
        )
        # LLM reasoning is preserved as evidence for human review.
        assert "Verified" in result.message or "confidence" in result.message.lower()

    def test_high_confidence_fail(self):
        """High confidence LLM FAIL is DOWNGRADED to WARN under RFC-0001 Stage 1.

        Same safety property as test_high_confidence_pass, symmetric side.
        """
        orchestrator = SieveOrchestrator(stop_on_llm=True)

        spec = ControlSpec(
            control_id="TEST-01",
            level=1,
            domain="TEST",
            name="TestControl",
            description="Test",
            metadata={
                "handler_invocations": [
                    HandlerInvocation(handler="llm_eval", confidence_threshold=0.8),
                ],
            },
        )

        response = LLMConsultationResponse(
            status=PassOutcome.FAIL,
            confidence=0.95,
            reasoning="Not compliant",
        )

        result = orchestrator.verify_with_llm_response(spec, _make_context(), response)
        # Under Stage 1, an LLM step (suggestive) can never conclude.
        assert result.status == "WARN"


class TestHandlerWhenClause:
    """Test handler-level when clause in dispatch_handler_invocations."""

    def test_handler_skipped_when_condition_false(self, tmp_path):
        """Handler with when={primary_language: 'go'} is skipped when context is 'python'."""
        (tmp_path / "README.md").write_text("# Test")
        orchestrator = SieveOrchestrator(stop_on_llm=True)

        spec = ControlSpec(
            control_id="TEST-01",
            level=1,
            domain="TEST",
            name="TestControl",
            description="Test",
            metadata={
                "handler_invocations": [
                    HandlerInvocation(
                        handler="file_exists",
                        files=["README.md"],
                        when={"primary_language": "go"},
                    ),
                ],
            },
        )

        ctx = _make_context(
            local_path=str(tmp_path),
            project_context={"primary_language": "python"},
        )
        result = orchestrator.verify(spec, ctx)
        # Handler skipped → no conclusive result → WARN
        assert result.status == "WARN"

    def test_handler_runs_when_condition_true(self, tmp_path):
        """Handler with when={primary_language: 'go'} runs when context matches."""
        (tmp_path / "README.md").write_text("# Test")
        orchestrator = SieveOrchestrator(stop_on_llm=True)

        spec = ControlSpec(
            control_id="TEST-01",
            level=1,
            domain="TEST",
            name="TestControl",
            description="Test",
            metadata={
                "handler_invocations": [
                    HandlerInvocation(
                        handler="file_exists",
                        files=["README.md"],
                        when={"primary_language": "go"},
                    ),
                ],
            },
        )

        ctx = _make_context(
            local_path=str(tmp_path),
            project_context={"primary_language": "go"},
        )
        result = orchestrator.verify(spec, ctx)
        assert result.status == "PASS"

    def test_handler_runs_unconditionally_when_no_when(self, tmp_path):
        """Handler without when clause runs regardless of context."""
        (tmp_path / "README.md").write_text("# Test")
        orchestrator = SieveOrchestrator(stop_on_llm=True)

        spec = ControlSpec(
            control_id="TEST-01",
            level=1,
            domain="TEST",
            name="TestControl",
            description="Test",
            metadata={
                "handler_invocations": [
                    HandlerInvocation(
                        handler="file_exists",
                        files=["README.md"],
                    ),
                ],
            },
        )

        ctx = _make_context(
            local_path=str(tmp_path),
            project_context={"primary_language": "python"},
        )
        result = orchestrator.verify(spec, ctx)
        assert result.status == "PASS"

    def test_handler_when_with_list_context(self, tmp_path):
        """Handler with when={languages: 'go'} matches list context containing 'go'."""
        (tmp_path / "README.md").write_text("# Test")
        orchestrator = SieveOrchestrator(stop_on_llm=True)

        spec = ControlSpec(
            control_id="TEST-01",
            level=1,
            domain="TEST",
            name="TestControl",
            description="Test",
            metadata={
                "handler_invocations": [
                    HandlerInvocation(
                        handler="file_exists",
                        files=["README.md"],
                        when={"languages": "go"},
                    ),
                ],
            },
        )

        ctx = _make_context(
            local_path=str(tmp_path),
            project_context={"languages": ["go", "typescript"]},
        )
        result = orchestrator.verify(spec, ctx)
        assert result.status == "PASS"

    def test_first_handler_skipped_second_runs(self, tmp_path):
        """First handler skipped by when, second runs unconditionally."""
        (tmp_path / "README.md").write_text("# Test")
        orchestrator = SieveOrchestrator(stop_on_llm=True)

        spec = ControlSpec(
            control_id="TEST-01",
            level=1,
            domain="TEST",
            name="TestControl",
            description="Test",
            metadata={
                "handler_invocations": [
                    HandlerInvocation(
                        handler="file_exists",
                        files=["NONEXISTENT.md"],
                        when={"primary_language": "go"},
                    ),
                    HandlerInvocation(
                        handler="file_exists",
                        files=["README.md"],
                    ),
                ],
            },
        )

        ctx = _make_context(
            local_path=str(tmp_path),
            project_context={"primary_language": "python"},
        )
        result = orchestrator.verify(spec, ctx)
        # First handler skipped (go != python), second runs and finds README.md
        assert result.status == "PASS"


class TestExecutionContextPropagation:
    """Test that ExecutionContext correctly propagates through the orchestrator to handlers."""

    def test_execution_context_propagates_to_handler(self):
        from darnit.core.models import ExecutionContext
        from darnit.sieve.handler_registry import (
            HandlerResult,
            HandlerResultStatus,
            get_sieve_handler_registry,
        )

        exec_ctx = ExecutionContext(owner="test", repo="test", local_path="/test")

        # We need a custom handler to capture the HandlerContext passed to it
        captured_ctx = None

        def spy_handler(config, handler_ctx):
            nonlocal captured_ctx
            captured_ctx = handler_ctx
            return HandlerResult(status=HandlerResultStatus.PASS, message="Spy done")

        registry = get_sieve_handler_registry()
        # Register with default_authority="dispositive" so the spy's PASS
        # concludes the control. Under RFC-0001 Stage 1 (feature 025), a
        # handler that omits default_authority defaults to "suggestive" and
        # its PASS is downgraded to WARN. This test cares about
        # ExecutionContext propagation, not the verdict rule, so dispositive
        # is the honest label for a spy that observes ground truth.
        registry.register(
            "spy_tool", phase="deterministic", handler_fn=spy_handler,
            default_authority="dispositive",
        )

        # Inject our spy handler into the control spec
        spec = ControlSpec(
            control_id="TEST-01",
            level=1,
            domain="TEST",
            name="TestControl",
            description="Test",
            metadata={
                "handler_invocations": [HandlerInvocation(handler="spy_tool")],
            },
        )

        check_ctx = CheckContext(
            owner="test",
            repo="repo",
            local_path="/path",
            default_branch="main",
            control_id="TEST-01",
            execution_context=exec_ctx,
        )

        orchestrator = SieveOrchestrator()
        # Mock any other behavior if needed
        res = orchestrator.verify(spec, check_ctx)

        assert captured_ctx is not None
        assert captured_ctx.execution_context is exec_ctx, "ExecutionContext was not propagated to HandlerContext!"
        assert res.to_legacy_dict()["status"] == "PASS"
