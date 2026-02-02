"""Sieve orchestrator - runs verification passes in order."""

import time
from typing import Any

from darnit.core.logging import get_logger

from .models import (
    CheckContext,
    ControlSpec,
    LLMConsultationResponse,
    PassAttempt,
    PassOutcome,
    SieveResult,
    VerificationPhase,
)

logger = get_logger("sieve.orchestrator")


class SieveOrchestrator:
    """
    Orchestrates the 4-phase verification pipeline.

    The sieve runs passes in order (DETERMINISTIC -> PATTERN -> LLM -> MANUAL),
    stopping as soon as a pass returns a conclusive result (PASS or FAIL).

    For LLM passes, the orchestrator can either:
    - Return a PENDING_LLM status with the consultation request (stop_on_llm=True)
    - Continue to the MANUAL pass (stop_on_llm=False)
    """

    def __init__(self, stop_on_llm: bool = True):
        """
        Args:
            stop_on_llm: If True, return consultation request instead of
                         continuing to Manual pass when LLM pass is inconclusive.
        """
        self.stop_on_llm = stop_on_llm

    def verify(self, control_spec: ControlSpec, context: CheckContext) -> SieveResult:
        """
        Run verification passes in order until conclusive.

        Args:
            control_spec: Control specification with pass definitions
            context: Check context with repo info and gathered evidence

        Returns:
            SieveResult with status and pass history
        """
        pass_history: list[PassAttempt] = []
        accumulated_evidence: dict[str, Any] = {}

        for verification_pass in control_spec.passes:
            # Execute pass
            start_time = time.time()
            try:
                result = verification_pass.execute(context)
            except (RuntimeError, ValueError, TypeError, KeyError, AttributeError, OSError) as e:
                logger.debug(f"Pass execution error: {type(e).__name__}: {e}")
                result = PassAttempt(
                    phase=verification_pass.phase,
                    checks_performed=[f"ERROR: {str(e)}"],
                    result=None,
                )
                pass_history.append(
                    PassAttempt(
                        phase=verification_pass.phase,
                        checks_performed=[verification_pass.describe()],
                        result=result,
                        duration_ms=int((time.time() - start_time) * 1000),
                    )
                )
                continue

            duration_ms = int((time.time() - start_time) * 1000)

            # Record attempt
            attempt = PassAttempt(
                phase=verification_pass.phase,
                checks_performed=[verification_pass.describe()],
                result=result,
                duration_ms=duration_ms,
            )
            pass_history.append(attempt)

            # Accumulate evidence
            if result.evidence:
                accumulated_evidence.update(result.evidence)
                context.gathered_evidence.update(result.evidence)

            # Check if conclusive
            if result.outcome == PassOutcome.PASS:
                return SieveResult(
                    control_id=control_spec.control_id,
                    status="PASS",
                    message=result.message,
                    level=control_spec.level,
                    conclusive_phase=verification_pass.phase,
                    pass_history=pass_history,
                    confidence=result.confidence,
                    evidence=accumulated_evidence,
                    source="sieve",
                )

            elif result.outcome == PassOutcome.FAIL:
                return SieveResult(
                    control_id=control_spec.control_id,
                    status="FAIL",
                    message=result.message,
                    level=control_spec.level,
                    conclusive_phase=verification_pass.phase,
                    pass_history=pass_history,
                    evidence=accumulated_evidence,
                    source="sieve",
                )

            elif result.outcome == PassOutcome.ERROR:
                return SieveResult(
                    control_id=control_spec.control_id,
                    status="ERROR",
                    message=result.message,
                    level=control_spec.level,
                    conclusive_phase=verification_pass.phase,
                    pass_history=pass_history,
                    evidence=accumulated_evidence,
                    source="sieve",
                )

            # INCONCLUSIVE - check for LLM consultation
            if (
                verification_pass.phase == VerificationPhase.LLM
                and self.stop_on_llm
                and result.details
                and "consultation_request" in result.details
            ):
                # Return with pending LLM consultation
                return SieveResult(
                    control_id=control_spec.control_id,
                    status="PENDING_LLM",  # Special status
                    message="LLM consultation required",
                    level=control_spec.level,
                    conclusive_phase=verification_pass.phase,
                    pass_history=pass_history,
                    evidence={
                        **accumulated_evidence,
                        "llm_consultation": result.details["consultation_request"],
                    },
                    source="sieve",
                )

            # Continue to next pass

        # All passes inconclusive - return WARN (manual verification needed)
        last_pass = control_spec.passes[-1] if control_spec.passes else None
        verification_steps = None
        if last_pass and last_pass.phase == VerificationPhase.MANUAL:
            last_result = pass_history[-1].result if pass_history else None
            if last_result and last_result.details:
                verification_steps = last_result.details.get("verification_steps")

        return SieveResult(
            control_id=control_spec.control_id,
            status="WARN",
            message="Could not automatically verify - manual verification required",
            level=control_spec.level,
            conclusive_phase=VerificationPhase.MANUAL,
            pass_history=pass_history,
            evidence=accumulated_evidence,
            verification_steps=verification_steps,
            source="sieve",
        )

    def verify_with_llm_response(
        self,
        control_spec: ControlSpec,
        context: CheckContext,
        llm_response: LLMConsultationResponse,
    ) -> SieveResult:
        """
        Continue verification after receiving LLM response.

        This is called after the calling LLM has analyzed the consultation request
        and provided a structured response.

        Args:
            control_spec: The control being verified
            context: Original context
            llm_response: Parsed LLM response with status, confidence, reasoning

        Returns:
            SieveResult with final status
        """
        # Find LLM pass configuration
        llm_pass = None
        for p in control_spec.passes:
            if p.phase == VerificationPhase.LLM:
                llm_pass = p
                break

        confidence_threshold = (
            getattr(llm_pass, "confidence_threshold", 0.8) if llm_pass else 0.8
        )

        # Determine outcome based on confidence
        if llm_response.status in (PassOutcome.PASS, PassOutcome.FAIL):
            if llm_response.confidence >= confidence_threshold:
                status = "PASS" if llm_response.status == PassOutcome.PASS else "FAIL"
                return SieveResult(
                    control_id=control_spec.control_id,
                    status=status,
                    message=llm_response.reasoning,
                    level=control_spec.level,
                    conclusive_phase=VerificationPhase.LLM,
                    pass_history=[],  # History from original verify call
                    confidence=llm_response.confidence,
                    evidence={
                        "llm_reasoning": llm_response.reasoning,
                        "llm_evidence": llm_response.evidence_cited,
                    },
                    source="sieve",
                )

        # Low confidence or inconclusive - fall through to manual
        # Find manual pass for verification steps
        manual_pass = None
        for p in control_spec.passes:
            if p.phase == VerificationPhase.MANUAL:
                manual_pass = p
                break

        verification_steps = None
        if manual_pass:
            verification_steps = getattr(manual_pass, "verification_steps", None)

        return SieveResult(
            control_id=control_spec.control_id,
            status="WARN",
            message=f"LLM analysis inconclusive (confidence: {llm_response.confidence:.0%}): {llm_response.reasoning}",
            level=control_spec.level,
            conclusive_phase=VerificationPhase.MANUAL,
            pass_history=[],
            confidence=llm_response.confidence,
            evidence={
                "llm_reasoning": llm_response.reasoning,
                "llm_evidence": llm_response.evidence_cited,
            },
            verification_steps=verification_steps
            or [
                "Review LLM analysis above",
                "Verify findings manually",
                f"Control: {control_spec.control_id} - {control_spec.name}",
            ],
            source="sieve",
        )

    def verify_batch(
        self,
        control_specs: list[ControlSpec],
        context_factory: callable,
    ) -> list[SieveResult]:
        """
        Verify multiple controls.

        Args:
            control_specs: List of control specifications
            context_factory: Function that creates CheckContext for a control_id

        Returns:
            List of SieveResults
        """
        results = []
        for spec in control_specs:
            context = context_factory(spec.control_id)
            result = self.verify(spec, context)
            results.append(result)
        return results
