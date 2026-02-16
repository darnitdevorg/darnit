"""Sieve orchestrator - runs verification passes in order."""

import time
from typing import Any

from darnit.core.logging import get_logger

from .handler_registry import (
    HandlerContext,
    HandlerResult,
    HandlerResultStatus,
    get_sieve_handler_registry,
)
from .models import (
    CheckContext,
    ControlSpec,
    LLMConsultationResponse,
    PassAttempt,
    PassOutcome,
    PassResult,
    SieveResult,
    VerificationPhase,
)

logger = get_logger("sieve.orchestrator")


def evaluate_when_clause(when: dict[str, Any], context: dict[str, Any]) -> bool:
    """Evaluate a ``when`` clause against a context dict.

    Missing context keys → True (conservative: run the control).
    Mismatched value → False (skip the control).

    This is the single implementation used by both the audit pipeline
    and the remediation pipeline.

    Currently supports simple key-value equality with AND semantics.

    .. todo::
        Explore CEL expression support for ``when`` clauses to enable
        OR conditions (``platform == "github" || platform == "gitlab"``),
        negation (``platform != "bitbucket"``), and complex logic.
        The schema would need to accept ``dict | str`` and route string
        values through ``cel_evaluator.evaluate_cel()``.

    Args:
        when: Dict of key → expected_value from the TOML ``when`` field.
        context: Flat dict of context values (e.g. from ``collect_auto_context``
                 merged with user-confirmed context).

    Returns:
        True if the control should run, False if it should be skipped (N/A).
    """
    for key, expected in when.items():
        actual = context.get(key)
        if actual is None:
            # Missing context key → run normally (conservative)
            logger.debug(
                "when key '%s' missing from context, running normally", key,
            )
            continue
        if actual != expected:
            logger.debug(
                "when condition failed (%s=%r, expected %r)", key, actual, expected,
            )
            return False
    return True


class SieveOrchestrator:
    """
    Orchestrates the verification pipeline via handler dispatch.

    The sieve iterates a flat ordered list of handler invocations per control,
    stopping as soon as a handler returns a conclusive result (PASS, FAIL, ERROR).

    For LLM handlers, the orchestrator can either:
    - Return a PENDING_LLM status with the consultation request (stop_on_llm=True)
    - Continue to the next handler (stop_on_llm=False)
    """

    def __init__(self, stop_on_llm: bool = True):
        """
        Args:
            stop_on_llm: If True, return consultation request instead of
                         continuing to Manual pass when LLM pass is inconclusive.
        """
        self.stop_on_llm = stop_on_llm
        # Shared handler cache: keyed by shared handler name, populated on first
        # execution, reused for subsequent references within the same audit run
        self._shared_cache: dict[str, HandlerResult] = {}
        # Dependency results: keyed by control ID, populated as controls are verified
        self._dependency_results: dict[str, SieveResult] = {}

    def reset_caches(self) -> None:
        """Reset shared handler cache and dependency results.

        Call this at the start of each audit run.
        """
        self._shared_cache.clear()
        self._dependency_results.clear()

    def _evaluate_when(
        self, control_spec: ControlSpec, context: CheckContext
    ) -> bool:
        """Evaluate when clause for conditional applicability.

        Returns True if the control should run, False if N/A.
        Delegates to the module-level :func:`evaluate_when_clause`.
        """
        when = control_spec.metadata.get("when")
        if not when:
            return True

        # Merge project_context and control_metadata for lookup
        merged = {**context.control_metadata, **context.project_context}
        return evaluate_when_clause(when, merged)

    def _check_inferred_from(
        self, control_spec: ControlSpec
    ) -> SieveResult | None:
        """Check if this control can be auto-passed via inferred_from.

        If the referenced control PASSED, return an auto-PASS result.
        Otherwise return None to run normal verification.
        """
        inferred_from = control_spec.metadata.get("inferred_from")
        if not inferred_from:
            return None

        source_result = self._dependency_results.get(inferred_from)
        if source_result and source_result.status == "PASS":
            return SieveResult(
                control_id=control_spec.control_id,
                status="PASS",
                message=f"Inferred from {inferred_from} (passed)",
                level=control_spec.level,
                evidence={"inferred_from": inferred_from},
                source="sieve",
            )

        return None

    def _dispatch_handler_invocations(
        self,
        control_spec: ControlSpec,
        context: CheckContext,
    ) -> SieveResult | None:
        """Dispatch handler invocations from metadata.

        Iterates the flat handler invocation list in order, stops at the
        first conclusive result (PASS, FAIL, ERROR).

        Returns SieveResult if dispatch produced a result, None if no
        handler invocations are configured.
        """
        handler_invocations = control_spec.metadata.get("handler_invocations")
        if not handler_invocations:
            return None

        registry = get_sieve_handler_registry()
        pass_history: list[PassAttempt] = []
        accumulated_evidence: dict[str, Any] = {}

        # Build handler context
        handler_ctx = HandlerContext(
            local_path=context.local_path,
            owner=context.owner,
            repo=context.repo,
            default_branch=context.default_branch,
            control_id=control_spec.control_id,
            project_context=dict(context.project_context),
            gathered_evidence=dict(context.gathered_evidence),
            shared_cache=self._shared_cache,
            dependency_results={
                cid: r.status for cid, r in self._dependency_results.items()
            },
        )

        for invocation in handler_invocations:
            handler_info = registry.get(invocation.handler)
            if not handler_info:
                logger.warning(
                    "Control %s: handler '%s' not found in registry",
                    control_spec.control_id,
                    invocation.handler,
                )
                continue

            # Use handler's registered phase for recording, or DETERMINISTIC as default
            phase = getattr(handler_info, "phase", None)
            if phase:
                # Map HandlerPhase to VerificationPhase
                phase_map = {
                    "deterministic": VerificationPhase.DETERMINISTIC,
                    "pattern": VerificationPhase.PATTERN,
                    "llm": VerificationPhase.LLM,
                    "manual": VerificationPhase.MANUAL,
                }
                phase = phase_map.get(phase.value, VerificationPhase.DETERMINISTIC)
            else:
                phase = VerificationPhase.DETERMINISTIC

            # Check shared cache
            if invocation.shared and invocation.shared in self._shared_cache:
                handler_result = self._shared_cache[invocation.shared]
            else:
                # Build handler config from invocation's extra fields
                handler_config = dict(invocation.model_extra or {})
                handler_config["handler"] = invocation.handler

                start_time = time.time()
                try:
                    handler_result = handler_info.fn(handler_config, handler_ctx)
                except Exception as e:
                    logger.debug(
                        "Handler %s error: %s: %s",
                        invocation.handler,
                        type(e).__name__,
                        e,
                    )
                    handler_result = HandlerResult(
                        status=HandlerResultStatus.ERROR,
                        message=f"Handler error: {e}",
                    )
                duration_ms = int((time.time() - start_time) * 1000)

                # Cache shared handler result
                if invocation.shared:
                    self._shared_cache[invocation.shared] = handler_result

                # Record attempt
                pass_result = PassResult(
                    phase=phase,
                    outcome=_handler_status_to_outcome(handler_result.status),
                    message=handler_result.message,
                    evidence=handler_result.evidence,
                    confidence=handler_result.confidence,
                    details=handler_result.details,
                )
                pass_history.append(
                    PassAttempt(
                        phase=phase,
                        checks_performed=[
                            f"handler:{invocation.handler}"
                        ],
                        result=pass_result,
                        duration_ms=duration_ms,
                    )
                )

            # Accumulate evidence
            if handler_result.evidence:
                accumulated_evidence.update(handler_result.evidence)
                handler_ctx.gathered_evidence.update(handler_result.evidence)
                context.gathered_evidence.update(handler_result.evidence)

            # Check conclusiveness
            if handler_result.status == HandlerResultStatus.PASS:
                sieve_result = SieveResult(
                    control_id=control_spec.control_id,
                    status="PASS",
                    message=handler_result.message,
                    level=control_spec.level,
                    conclusive_phase=phase,
                    pass_history=pass_history,
                    confidence=handler_result.confidence,
                    evidence=accumulated_evidence,
                    source="sieve",
                )
                self._apply_on_pass(control_spec, context, accumulated_evidence)
                return sieve_result

            elif handler_result.status == HandlerResultStatus.FAIL:
                return SieveResult(
                    control_id=control_spec.control_id,
                    status="FAIL",
                    message=handler_result.message,
                    level=control_spec.level,
                    conclusive_phase=phase,
                    pass_history=pass_history,
                    evidence=accumulated_evidence,
                    source="sieve",
                )

            elif handler_result.status == HandlerResultStatus.ERROR:
                return SieveResult(
                    control_id=control_spec.control_id,
                    status="ERROR",
                    message=handler_result.message,
                    level=control_spec.level,
                    conclusive_phase=phase,
                    pass_history=pass_history,
                    evidence=accumulated_evidence,
                    source="sieve",
                )

            # INCONCLUSIVE — check for LLM consultation
            if (
                phase == VerificationPhase.LLM
                and self.stop_on_llm
                and handler_result.details
                and "consultation_request" in handler_result.details
            ):
                return SieveResult(
                    control_id=control_spec.control_id,
                    status="PENDING_LLM",
                    message="LLM consultation required",
                    level=control_spec.level,
                    conclusive_phase=phase,
                    pass_history=pass_history,
                    evidence={
                        **accumulated_evidence,
                        "llm_consultation": handler_result.details[
                            "consultation_request"
                        ],
                    },
                    source="sieve",
                )

            # Continue to next handler

        # All handler invocations inconclusive
        return SieveResult(
            control_id=control_spec.control_id,
            status="WARN",
            message="Could not automatically verify - manual verification required",
            level=control_spec.level,
            conclusive_phase=VerificationPhase.MANUAL,
            pass_history=pass_history,
            evidence=accumulated_evidence,
            source="sieve",
        )

    def verify(self, control_spec: ControlSpec, context: CheckContext) -> SieveResult:
        """
        Run verification passes in order until conclusive.

        Evaluation order:
        1. Check when clause → return N/A if condition is false
        2. Check inferred_from → auto-PASS if source control passed
        3. Inject dependency results into context
        4. Dispatch handler invocations (flat list) → WARN if none configured

        Args:
            control_spec: Control specification with pass definitions
            context: Check context with repo info and gathered evidence

        Returns:
            SieveResult with status and pass history
        """
        # Step 1: Evaluate when clause
        if not self._evaluate_when(control_spec, context):
            result = SieveResult(
                control_id=control_spec.control_id,
                status="N/A",
                message="Not applicable (when condition not met)",
                level=control_spec.level,
                evidence={"when": control_spec.metadata.get("when")},
                source="sieve",
            )
            self._dependency_results[control_spec.control_id] = result
            return result

        # Step 2: Check inferred_from
        inferred = self._check_inferred_from(control_spec)
        if inferred:
            self._dependency_results[control_spec.control_id] = inferred
            return inferred

        # Step 3: Inject dependency results into context
        if self._dependency_results:
            for dep_id, dep_result in self._dependency_results.items():
                context.gathered_evidence[f"dependency.{dep_id}.status"] = dep_result.status

        # Step 4: Dispatch handler invocations
        handler_result = self._dispatch_handler_invocations(control_spec, context)
        if handler_result:
            self._dependency_results[control_spec.control_id] = handler_result
            return handler_result

        # No handler invocations configured — return WARN
        sieve_result = SieveResult(
            control_id=control_spec.control_id,
            status="WARN",
            message="No handler invocations configured for this control",
            level=control_spec.level,
            source="sieve",
        )
        self._dependency_results[control_spec.control_id] = sieve_result
        return sieve_result

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

        Reads LLM/manual configuration from handler_invocations metadata.

        Args:
            control_spec: The control being verified
            context: Original context
            llm_response: Parsed LLM response with status, confidence, reasoning

        Returns:
            SieveResult with final status
        """
        # Find confidence_threshold from llm_eval handler invocation
        confidence_threshold = 0.8
        handler_invocations = control_spec.metadata.get("handler_invocations", [])
        for inv in handler_invocations:
            if inv.handler == "llm_eval":
                extra = inv.model_extra or {}
                confidence_threshold = extra.get(
                    "confidence_threshold", 0.8
                )
                break

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
        # Find verification_steps from manual handler invocation
        verification_steps = None
        for inv in handler_invocations:
            if inv.handler == "manual":
                extra = inv.model_extra or {}
                steps = extra.get("steps")
                if steps:
                    verification_steps = steps
                break

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
        Verify multiple controls in dependency-aware order.

        Performs topological sort based on depends_on and inferred_from,
        then verifies in order so dependency results are available.

        Args:
            control_specs: List of control specifications
            context_factory: Function that creates CheckContext for a control_id

        Returns:
            List of SieveResults in original order
        """
        # Reset caches for this audit run
        self.reset_caches()

        # Resolve execution order
        ordered = _resolve_execution_order(control_specs)

        # Execute in dependency order, collect results
        result_map: dict[str, SieveResult] = {}
        for spec in ordered:
            context = context_factory(spec.control_id)
            result = self.verify(spec, context)
            result_map[spec.control_id] = result

        # Return in original order
        return [
            result_map[spec.control_id]
            for spec in control_specs
            if spec.control_id in result_map
        ]

    def _apply_on_pass(
        self,
        control_spec: ControlSpec,
        context: CheckContext,
        evidence: dict[str, Any],
    ) -> None:
        """Apply on_pass project_update when a control passes.

        Reads on_pass config from control_spec.metadata and updates
        .project/project.yaml with the specified values.

        Values can reference evidence using $EVIDENCE.<key> syntax.

        Args:
            control_spec: The control that passed
            context: Check context with local_path
            evidence: Accumulated evidence from passes
        """
        on_pass = control_spec.metadata.get("on_pass")
        if not on_pass:
            return

        # on_pass can be an OnPassConfig pydantic model or a dict
        if hasattr(on_pass, "project_update"):
            updates = on_pass.project_update
        elif isinstance(on_pass, dict):
            updates = on_pass.get("project_update", {})
        else:
            return

        if not updates:
            return

        # Substitute $EVIDENCE references
        resolved: dict[str, Any] = {}
        for key, value in updates.items():
            if isinstance(value, str) and value.startswith("$EVIDENCE."):
                evidence_key = value[len("$EVIDENCE."):]
                resolved[key] = evidence.get(evidence_key, value)
            else:
                resolved[key] = value

        # Apply updates to .project/project.yaml
        local_path = context.local_path
        if not local_path:
            return

        try:
            from darnit.remediation.executor import (
                ProjectUpdateRemediationConfig,
                apply_project_update,
            )

            config = ProjectUpdateRemediationConfig(set=resolved)
            apply_project_update(local_path, config, control_spec.control_id)
            logger.debug(
                f"Applied on_pass for {control_spec.control_id}: "
                f"set {len(resolved)} values"
            )
        except ImportError:
            logger.debug("Remediation executor not available for on_pass")
        except Exception as e:
            logger.warning(
                f"Failed to apply on_pass for {control_spec.control_id}: {e}"
            )


# =============================================================================
# Module-level helpers
# =============================================================================


def _handler_status_to_outcome(status: HandlerResultStatus) -> PassOutcome:
    """Convert HandlerResultStatus to PassOutcome."""
    mapping = {
        HandlerResultStatus.PASS: PassOutcome.PASS,
        HandlerResultStatus.FAIL: PassOutcome.FAIL,
        HandlerResultStatus.ERROR: PassOutcome.ERROR,
        HandlerResultStatus.INCONCLUSIVE: PassOutcome.INCONCLUSIVE,
    }
    return mapping.get(status, PassOutcome.INCONCLUSIVE)


def _resolve_execution_order(
    control_specs: list[ControlSpec],
) -> list[ControlSpec]:
    """Topological sort of controls based on depends_on and inferred_from.

    Cycle detection: warns and removes back-edges to break cycles.
    Unknown references: silently ignored (already validated at load time).

    Args:
        control_specs: Controls to sort

    Returns:
        Controls in dependency-respecting order
    """
    specs_by_id = {s.control_id: s for s in control_specs}
    in_scope = set(specs_by_id.keys())

    # Build adjacency: control_id -> set of control_ids it depends on
    deps: dict[str, set[str]] = {}
    for spec in control_specs:
        spec_deps: set[str] = set()
        depends_on = spec.metadata.get("depends_on", [])
        if depends_on:
            spec_deps.update(d for d in depends_on if d in in_scope)
        inferred_from = spec.metadata.get("inferred_from")
        if inferred_from and inferred_from in in_scope:
            spec_deps.add(inferred_from)
        deps[spec.control_id] = spec_deps

    # DFS-based topological sort
    visited: set[str] = set()
    in_stack: set[str] = set()
    order: list[str] = []

    def _visit(cid: str) -> None:
        if cid in visited:
            return
        if cid in in_stack:
            logger.warning("Dependency cycle detected involving control '%s'", cid)
            return  # Break cycle
        in_stack.add(cid)
        for dep in deps.get(cid, set()):
            _visit(dep)
        in_stack.remove(cid)
        visited.add(cid)
        order.append(cid)

    for cid in deps:
        _visit(cid)

    # Map back to specs in dependency order
    ordered = [specs_by_id[cid] for cid in order if cid in specs_by_id]

    # Append any specs not covered (shouldn't happen, but defensive)
    seen = {s.control_id for s in ordered}
    for spec in control_specs:
        if spec.control_id not in seen:
            ordered.append(spec)

    return ordered
