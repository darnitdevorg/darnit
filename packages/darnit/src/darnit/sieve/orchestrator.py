"""Sieve orchestrator - runs verification passes in order."""

import json
import logging
import time
from enum import Enum
from pathlib import Path
from typing import Any

from darnit.config.when_evaluator import evaluate_when
from darnit.core.logging import get_logger

from .handler_registry import (
    HandlerContext,
    HandlerResult,
    HandlerResultStatus,
    effective_outcomes,
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

# ``darnit.harness`` logger is where feature 026 emits ``dispatching_llm``
# INFO progress lines; feature 031 emits its ``dispatching_mcp`` twin on
# the same logger so a harness watcher subscribes to one channel for both.
_harness_logger = logging.getLogger("darnit.harness")


# =============================================================================
# Check execution rule: RFC-0001 Stage 1 (feature 025), per-claim authority
# (feature 041)
# =============================================================================


class StepDisposition(str, Enum):
    """Result of applying the Check-phase execution rule to one step.

    See specs/025-rfc0001-stage1/data-model.md "Check-phase execution rule".
    """

    CONCLUDE_PASS = "conclude_pass"
    CONCLUDE_FAIL = "conclude_fail"
    # Feature 037 (FR-016): the handler determined the evidence is incomplete.
    # Conclusive under the same permission as FAIL (feature 041).
    CONCLUDE_WARN = "conclude_warn"
    ATTACH_EVIDENCE_AND_CONTINUE = "attach_and_continue"
    # Feature 041: a broken measurement never concludes FAIL. The error is
    # recorded and later steps still run; the control ends ERROR only when
    # no later step concludes.
    RECORD_ERROR_AND_CONTINUE = "record_error_and_continue"
    TERMINATE_INCONCLUSIVE = "terminate_inconclusive"
    TERMINATE_ERROR = "terminate_error"


def resolve_step_result(
    handler_status: HandlerResultStatus,
    allowed: frozenset[str],
    is_last_step: bool = False,
) -> StepDisposition:
    """Apply the Check-phase execution rule to one step.

    ``allowed`` is the step's effective set (feature 041): the outcomes it
    may conclude for its control. A PASS concludes only when ``pass`` is in
    it; a FAIL, or a WARN (a non-compliant conclusion like FAIL), only when
    ``fail`` is in it. Anything else is evidence: execution continues, or
    ends inconclusive on the last step. An ERROR never concludes: it is
    recorded and execution continues, or ends ERROR on the last step,
    whatever the effective set.
    """
    if handler_status == HandlerResultStatus.ERROR:
        return StepDisposition.TERMINATE_ERROR if is_last_step else StepDisposition.RECORD_ERROR_AND_CONTINUE

    _CONCLUSIVE = {
        HandlerResultStatus.PASS: ("pass", StepDisposition.CONCLUDE_PASS),
        HandlerResultStatus.FAIL: ("fail", StepDisposition.CONCLUDE_FAIL),
        HandlerResultStatus.WARN: ("fail", StepDisposition.CONCLUDE_WARN),
    }
    if handler_status in _CONCLUSIVE:
        outcome, disposition = _CONCLUSIVE[handler_status]
        if outcome in allowed:
            return disposition

    if is_last_step:
        return StepDisposition.TERMINATE_INCONCLUSIVE
    return StepDisposition.ATTACH_EVIDENCE_AND_CONTINUE


# Handlers that evaluate ``expr`` themselves over their own binding
# (``gh_api`` binds ``response``, ``mcp`` binds ``result``); the post-step
# would re-evaluate it over ``output`` and fail.
STEP_TYPES_EVALUATING_OWN_EXPR = frozenset({"gh_api", "mcp"})


def _expression_project(project: dict[str, Any]) -> dict[str, Any]:
    """``project`` as CEL can bind it: values that are not JSON-shaped are read as strings."""
    return json.loads(json.dumps(project, default=str))


def _apply_cel_expr(
    handler_config: dict[str, Any],
    handler_result: "HandlerResult",
    *,
    project: dict[str, Any] | None = None,
    repo_path: str | Path | None = None,
    decides: bool = False,
) -> "HandlerResult":
    """Evaluate a step's CEL ``expr`` against its handler evidence (framework-design 3.7).

    Only runs when ``handler_config`` contains ``expr`` and the handler returned
    PASS or FAIL; any other result is returned unchanged. The expression sees
    ``output`` (the handler's evidence) and ``project`` (the step's usable
    project values, feature 042), and ``file_exists`` answers for
    ``repo_path``.

    Transition table (handler status x expression result -> step status):

    +-----------+----------+----------------------------------------------+
    | Handler   | CEL true | CEL false                                    |
    +===========+==========+==============================================+
    | PASS      | PASS     | INCONCLUSIVE (handler and CEL disagree)      |
    +-----------+----------+----------------------------------------------+
    | FAIL      | INCONC.  | FAIL (both agree; conclusive non-compliance) |
    +-----------+----------+----------------------------------------------+

    Feature 044 (FR-001): an expression that does not compile, cannot be
    evaluated, or is not boolean makes the step ERROR, class
    ``evaluation``, whatever the handler returned: a broken measurement is
    neither PASS nor FAIL. Its evidence keeps the handler's and adds
    ``expr`` and ``expr_error``.

    Rationale for the table: when the handler and CEL agree, keep the
    conclusion. When they disagree, defer to INCONCLUSIVE so the pipeline
    continues to the next pass (Principle V; issue #343).

    With ``decides`` (the step's ``expr_decides``, feature 044 FR-015) the
    expression runs only on a handler PASS and alone decides: true is
    PASS, false is FAIL. Any other handler result is returned unchanged.

    See ``specs/020-definitive-fail-verdict/contracts/cel-post-step.md``.
    """
    expr = handler_config.get("expr")
    if not expr or handler_config.get("handler") in STEP_TYPES_EVALUATING_OWN_EXPR:
        return handler_result

    # Only override conclusive verdicts — ERROR and INCONCLUSIVE pass through
    evaluated = (HandlerResultStatus.PASS,) if decides else (HandlerResultStatus.PASS, HandlerResultStatus.FAIL)
    if handler_result.status not in evaluated:
        return handler_result

    evidence = dict(handler_result.evidence or {})
    evidence["expr"] = expr

    def broken(error: str) -> HandlerResult:
        logger.warning("Expression %r could not be evaluated: %s", expr, error)
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message=f"Could not evaluate expr {expr!r}: {error}",
            evidence={**evidence, "expr_error": error},
            authority=handler_result.authority,
            error_class="evaluation",
        )

    from .cel_evaluator import evaluate_cel

    try:
        cel_context = {"output": handler_result.evidence or {}, "project": _expression_project(project or {})}
        cel_result = evaluate_cel(expr, cel_context, repo_path=Path(repo_path) if repo_path else None)
    except Exception as e:  # noqa: BLE001 - any failure to evaluate is a broken measurement
        return broken(f"{type(e).__name__}: {e}")
    if not cel_result.success:
        return broken(cel_result.error or "evaluation failed")
    if not isinstance(cel_result.value, bool):
        return broken(f"expr evaluated to {type(cel_result.value).__name__}, not a boolean")

    if decides:
        return HandlerResult(
            status=HandlerResultStatus.PASS if cel_result.value else HandlerResultStatus.FAIL,
            message=f"expr {'holds' if cel_result.value else 'does not hold'}: {expr}",
            confidence=1.0,
            evidence=evidence,
            authority=handler_result.authority,
            error_class=handler_result.error_class,
        )

    agreement = (handler_result.status == HandlerResultStatus.PASS and cel_result.value) or (
        handler_result.status == HandlerResultStatus.FAIL and not cel_result.value
    )
    if agreement:
        # Both handler and CEL point at the same verdict — preserve it.
        # Feature 026 bug fix: carry the incoming handler_result.authority
        # through so downstream reporting doesn't see "unknown".
        # Feature 036: same treatment for error_class -- every branch here
        # builds a NEW HandlerResult, so any field not threaded explicitly
        # is silently dropped.
        if handler_result.status == HandlerResultStatus.PASS:
            return HandlerResult(
                status=HandlerResultStatus.PASS,
                message="Handler and CEL agree: pass",
                confidence=1.0,
                evidence=evidence,
                authority=handler_result.authority,
                error_class=handler_result.error_class,
            )
        # Handler FAIL + CEL false: definitive non-compliance (issue #343).
        return HandlerResult(
            status=HandlerResultStatus.FAIL,
            message="Handler and CEL agree: fail",
            confidence=1.0,
            evidence=evidence,
            authority=handler_result.authority,
            error_class=handler_result.error_class,
        )
    # Disagreement (PASS+false or FAIL+true) -> defer to next pass.
    return HandlerResult(
        status=HandlerResultStatus.INCONCLUSIVE,
        message="Handler and CEL disagree, evaluation inconclusive",
        evidence=evidence,
        authority=handler_result.authority,
        error_class=handler_result.error_class,
    )


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
                "when key '%s' missing from context, running normally",
                key,
            )
            continue
        if actual != expected:
            logger.debug(
                "when condition failed (%s=%r, expected %r)",
                key,
                actual,
                expected,
            )
            return False
    return True


class SieveOrchestrator:
    """
    Orchestrates the verification pipeline via handler dispatch.

    The sieve iterates a flat ordered list of handler invocations per control,
    stopping as soon as a step concludes (PASS, FAIL, or WARN within its
    effective set). An ERROR is recorded and later steps still run; the
    control ends ERROR when none of them concludes (feature 041).

    For LLM handlers, the orchestrator can either:
    - Return PENDING (pending.kind = llm_judgment) with the consultation
      request (stop_on_llm=True)
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
        # MCP client-session pool. Constructed lazily on the first dispatch
        # that references ``handler = "mcp"``; torn down in
        # ``verify_batch``'s finally block or on ``reset_caches``.
        self._mcp_pool: Any | None = None

    def reset_caches(self) -> None:
        """Reset shared handler cache and dependency results.

        Call this at the start of each audit run.
        """
        self._shared_cache.clear()
        self._dependency_results.clear()
        if self._mcp_pool is not None:
            try:
                self._mcp_pool.teardown_all()
            except Exception as err:  # noqa: BLE001 - best-effort teardown
                logger.warning("MCP pool teardown during reset raised: %s", err)
            self._mcp_pool = None

    def record_result(self, result: SieveResult) -> None:
        """Make ``result`` the control's result for controls verified after it.

        For a result settled outside ``verify`` (a confirmed PASS candidate),
        so ``inferred_from`` and dependency evidence see what was reported.
        """
        self._dependency_results[result.control_id] = result

    def _evaluate_when(self, control_spec: ControlSpec, context: CheckContext) -> bool:
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

    def _check_inferred_from(self, control_spec: ControlSpec) -> SieveResult | None:
        """Check if this control can be auto-passed via inferred_from.

        If the referenced control's PASS was concluded (by a step allowed to
        conclude it, or confirmed by a person), return an auto-PASS result.
        Otherwise return None to run normal verification (feature 041: an
        inferred PASS is held to the same rule as any other PASS).
        """
        inferred_from = control_spec.metadata.get("inferred_from")
        if not inferred_from:
            return None

        source_result = self._dependency_results.get(inferred_from)
        if (
            source_result
            and source_result.status == "PASS"
            and source_result.authority in ("dispositive", "asserted")
        ):
            return SieveResult(
                control_id=control_spec.control_id,
                status="PASS",
                message=f"Inferred from {inferred_from} (passed)",
                level=control_spec.level,
                evidence={"inferred_from": inferred_from},
                source="sieve",
                # Feature 026 bug fix: inherit the source control's authority.
                # An inferred PASS is only as authoritative as what it's
                # inferred from -- if OSPS-LE-03.01 passed dispositively
                # (file_exists observed LICENSE), the inferred LE-03.02
                # PASS is also dispositive by inheritance. Never `unknown`.
                authority=source_result.authority,
                concluded_by="inferred_from",
            )

        return None

    def _dispatch_handler_invocations(
        self,
        control_spec: ControlSpec,
        context: CheckContext,
    ) -> SieveResult | None:
        """Dispatch handler invocations from metadata.

        Iterates the flat handler invocation list in order, stops at the
        first conclusive result. An ERROR step does not stop it (feature
        041): the first error is recorded and later steps run; if none
        concludes, the control ends ERROR with that first cause.

        Returns SieveResult if dispatch produced a result, None if no
        handler invocations are configured.
        """
        handler_invocations = control_spec.metadata.get("handler_invocations")
        if not handler_invocations:
            return None

        registry = get_sieve_handler_registry()
        pass_history: list[PassAttempt] = []
        accumulated_evidence: dict[str, Any] = {}
        last_error_class: str | None = None
        first_error: dict[str, Any] | None = None

        # Build handler context
        handler_ctx = HandlerContext(
            local_path=context.local_path,
            owner=context.owner,
            repo=context.repo,
            default_branch=context.default_branch,
            control_id=control_spec.control_id,
            project_context=dict(context.project_context),
            usable_project=dict(context.usable_project),
            gathered_evidence=dict(context.gathered_evidence),
            shared_cache=self._shared_cache,
            dependency_results={cid: r.status for cid, r in self._dependency_results.items()},
            execution_context=context.execution_context,
        )

        # Assemble flat context for when-clause evaluation
        when_context = dict(handler_ctx.project_context)

        for pass_index, invocation in enumerate(handler_invocations):
            # Evaluate when clause — skip handler if condition not met
            if invocation.when and not evaluate_when(invocation.when, when_context):
                logger.debug(
                    "Control %s: handler '%s' skipped (when clause not met)",
                    control_spec.control_id,
                    invocation.handler,
                )
                continue

            handler_info = registry.get(invocation.handler)
            if not handler_info:
                # Feature 044 (FR-009): never skip a step silently. Loading
                # rejects unregistered step types in framework files, so only
                # an operator-supplied step (a plugin not installed) gets here.
                message = f"step type {invocation.handler!r} is not registered"
                logger.warning("Control %s: %s", control_spec.control_id, message)
                pass_history.append(
                    PassAttempt(
                        phase=VerificationPhase.DETERMINISTIC,
                        checks_performed=[f"handler:{invocation.handler}"],
                        result=PassResult(
                            phase=VerificationPhase.DETERMINISTIC,
                            outcome=PassOutcome.ERROR,
                            message=message,
                            evidence={"handler": invocation.handler},
                        ),
                    )
                )
                last_error_class = "missing_tool"
                if first_error is None:
                    first_error = {
                        "message": message,
                        "error_class": "missing_tool",
                        "phase": VerificationPhase.DETERMINISTIC,
                        "pass_index": pass_index,
                        "handler": invocation.handler,
                        "authority": "suggestive",
                    }
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
                # Feature 041: the two step declarations a handler reads.
                if getattr(invocation, "fail_on_miss", False):
                    handler_config["fail_on_miss"] = True
                if getattr(invocation, "fail_on_status", None) is not None:
                    handler_config["fail_on_status"] = list(invocation.fail_on_status)

                # Feature 031: for the built-in mcp handler, lazily
                # construct the pool, assign it to the HandlerContext, and
                # emit the [N/M] dispatching_mcp progress line on the
                # darnit.harness logger BEFORE the handler runs. Emission
                # here (not inside the handler) mirrors feature 026's
                # dispatching_llm pattern and gives us the (idx, total)
                # counter from the enumerate loop directly.
                if invocation.handler == "mcp":
                    if self._mcp_pool is None:
                        self._mcp_pool = _build_mcp_pool(handler_ctx)
                    handler_ctx.mcp_pool = self._mcp_pool
                    server = handler_config.get("server", "?")
                    tool_name = handler_config.get("tool", "?")
                    total = len(handler_invocations)
                    _harness_logger.info(
                        "[%d/%d] %s dispatching_mcp %s.%s",
                        pass_index + 1,
                        total,
                        control_spec.control_id,
                        server,
                        tool_name,
                    )

                start_time = time.time()
                try:
                    handler_result = handler_info.fn(handler_config, handler_ctx)
                except Exception as e:
                    # Feature 036: a handler that raised did not complete, so
                    # this is an environmental failure, not a verdict. WARN
                    # rather than DEBUG -- a crashed handler and a genuine
                    # ERROR verdict were previously indistinguishable to
                    # anyone reading default-level logs.
                    logger.warning(
                        "%s: %s handler could not complete (error_class=crashed): %s: %s",
                        control_spec.control_id,
                        invocation.handler,
                        type(e).__name__,
                        e,
                    )
                    handler_result = HandlerResult(
                        status=HandlerResultStatus.ERROR,
                        message=f"Handler error: {e}",
                        error_class="crashed",
                    )

                handler_result = _apply_cel_expr(
                    handler_config,
                    handler_result,
                    project=handler_ctx.usable_project,
                    repo_path=context.local_path,
                    decides=getattr(invocation, "expr_decides", False),
                )

                # Feature 036: remember the most recent environmental
                # classification for the all-inconclusive WARN fallthrough
                # below. Last non-None rather than simply last, because most
                # controls end with a `manual` pass -- a "ask a human"
                # placeholder that always returns INCONCLUSIVE and can never
                # conclude anything. Treating that as "the final attempt ran
                # cleanly" would wipe the real exec failure that preceded it,
                # which is the common shape for a degraded audit.
                if handler_result.error_class is not None:
                    last_error_class = handler_result.error_class

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
                        checks_performed=[f"handler:{invocation.handler}"],
                        result=pass_result,
                        duration_ms=duration_ms,
                    )
                )

            # Accumulate evidence
            if handler_result.evidence:
                accumulated_evidence.update(handler_result.evidence)
                handler_ctx.gathered_evidence.update(handler_result.evidence)
                context.gathered_evidence.update(handler_result.evidence)

            # Feature 041: what this step may conclude for this control is its
            # type's ceiling narrowed by the step's declarations (widened only
            # by a recorded promotion). A handler may narrow its own result
            # to evidence only; it can never widen.
            allowed = effective_outcomes(handler_info, invocation)
            if handler_result.authority == "suggestive":
                allowed = frozenset()
            effective_authority = "dispositive" if allowed else "suggestive"

            is_last_step = pass_index == len(handler_invocations) - 1
            disposition = resolve_step_result(
                handler_status=handler_result.status,
                allowed=allowed,
                is_last_step=is_last_step,
            )

            if disposition == StepDisposition.CONCLUDE_PASS:
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
                    resolving_pass_index=pass_index,
                    resolving_pass_handler=invocation.handler,
                    authority=effective_authority,
                    concluded_by=invocation.handler,
                )
                self._apply_on_pass(control_spec, context, accumulated_evidence)
                return sieve_result

            # Feature 036 (FR-009a): error_class propagates from the RESOLVING
            # pass only. CONCLUDE_PASS above is deliberately excluded -- it
            # fires only when handler_status is PASS, and HandlerResult
            # rejects PASS + error_class, so there is provably nothing to
            # carry there.
            if disposition == StepDisposition.CONCLUDE_FAIL:
                return SieveResult(
                    control_id=control_spec.control_id,
                    status="FAIL",
                    message=handler_result.message,
                    level=control_spec.level,
                    conclusive_phase=phase,
                    pass_history=pass_history,
                    evidence=accumulated_evidence,
                    source="sieve",
                    resolving_pass_index=pass_index,
                    resolving_pass_handler=invocation.handler,
                    authority=effective_authority,
                    error_class=handler_result.error_class,
                    concluded_by=invocation.handler,
                )

            # Feature 037 (FR-016): a conclusive WARN carries the handler's
            # own message. That is the entire point -- the all-inconclusive
            # fallthrough below substitutes a fixed string, which cannot say
            # WHY a control is short. error_class is threaded because, unlike
            # CONCLUDE_PASS, nothing forbids WARN + error_class.
            if disposition == StepDisposition.CONCLUDE_WARN:
                return SieveResult(
                    control_id=control_spec.control_id,
                    status="WARN",
                    message=handler_result.message,
                    level=control_spec.level,
                    conclusive_phase=phase,
                    pass_history=pass_history,
                    confidence=handler_result.confidence,
                    evidence=accumulated_evidence,
                    source="sieve",
                    resolving_pass_index=pass_index,
                    resolving_pass_handler=invocation.handler,
                    authority=effective_authority,
                    error_class=handler_result.error_class,
                    concluded_by=invocation.handler,
                )

            # Feature 041: a broken measurement is not a finding. Keep the
            # first cause and let later steps try; the pass history keeps
            # every attempt either way.
            if disposition in (StepDisposition.RECORD_ERROR_AND_CONTINUE, StepDisposition.TERMINATE_ERROR):
                if first_error is None:
                    first_error = {
                        "message": handler_result.message,
                        "error_class": handler_result.error_class,
                        "phase": phase,
                        "pass_index": pass_index,
                        "handler": invocation.handler,
                        "authority": effective_authority,
                    }
                continue

            # ATTACH_EVIDENCE_AND_CONTINUE or TERMINATE_INCONCLUSIVE fall
            # through to the LLM-consultation / continue path below.

            # INCONCLUSIVE -- check for LLM consultation. An earlier ERROR
            # takes precedence over waiting for a judgment.
            if (
                phase == VerificationPhase.LLM
                and self.stop_on_llm
                and first_error is None
                and handler_result.details
                and "consultation_request" in handler_result.details
            ):
                return SieveResult(
                    control_id=control_spec.control_id,
                    status="PENDING",
                    message="LLM consultation required",
                    level=control_spec.level,
                    conclusive_phase=phase,
                    pass_history=pass_history,
                    evidence={
                        **accumulated_evidence,
                        "llm_consultation": handler_result.details["consultation_request"],
                    },
                    source="sieve",
                    authority="suggestive",
                    concluded_by="none",
                    pending={"kind": "llm_judgment"},
                )

            # Continue to next handler

        if first_error is not None:
            return SieveResult(
                control_id=control_spec.control_id,
                status="ERROR",
                message=first_error["message"],
                level=control_spec.level,
                conclusive_phase=first_error["phase"],
                pass_history=pass_history,
                evidence=accumulated_evidence,
                source="sieve",
                resolving_pass_index=first_error["pass_index"],
                resolving_pass_handler=first_error["handler"],
                authority=first_error["authority"],
                error_class=first_error["error_class"],
                concluded_by=first_error["handler"],
                error={
                    "class": first_error["error_class"] or "evaluation",
                    "cause": first_error["message"],
                },
            )

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
            # Feature 026 bug fix: a WARN because "all steps were suggestive
            # or inconclusive" IS a suggestive-authority verdict. Not None
            # / unknown -- suggestive. Preserves the safety-provenance
            # signal on the human-facing report.
            authority="suggestive",
            # Feature 036: no pass concluded, so FR-009a's "resolving pass"
            # does not exist here. Fall back to the LAST pass's
            # classification -- with nothing to supersede it, an
            # environmental failure on the final attempt is the best
            # available explanation for why this control could not be
            # verified. Without this, a fully degraded audit (every pass
            # timing out) reports a bare "manual verification required" and
            # the operator never learns their token expired.
            error_class=last_error_class,
            concluded_by="none",
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

        # Step 3: Inject dependency results into context.
        # Issue #485: only the control's declared `depends_on`, not every
        # control evaluated so far. A level-3 run was injecting ~57
        # unrelated status keys into each consultation payload.
        declared_deps = control_spec.metadata.get("depends_on") or []
        for dep_id in declared_deps:
            dep_result = self._dependency_results.get(dep_id)
            if dep_result is not None:
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
            authority="suggestive",
            concluded_by="none",
        )
        self._dependency_results[control_spec.control_id] = sieve_result
        return sieve_result

    def verify_with_llm_response(
        self,
        control_spec: ControlSpec,
        context: CheckContext,
        llm_response: LLMConsultationResponse,
        consultation: dict[str, Any] | None = None,
        source: str = "harness",
    ) -> SieveResult:
        """
        Resolve a control awaiting a model judgment (feature 041, data-model.md).

        A judgment never concludes PASS. A positive judgment whose cited
        excerpts all appear in ``consultation``'s judged content becomes a
        PASS candidate (PENDING, ``pending.kind = "confirmation"``); a
        negative one is a suggestive FAIL; an invalid or inconclusive one
        leaves the control WARN; a model-service failure is ERROR. The
        judgment's confidence is recorded, never used to decide.

        Args:
            control_spec: The control being verified
            context: Original context
            llm_response: Parsed model response
            consultation: The ``llm_consultation`` the control's model step
                produced; citations are checked against its content
            source: Who produced the judgment (``harness`` or ``mcp_agent``)

        Returns:
            SieveResult with final status
        """
        from darnit.trust.judgments import Judgment, assess_judgment, candidate_result

        base_evidence: dict[str, Any] = {
            "llm_reasoning": llm_response.reasoning,
            "llm_evidence": llm_response.evidence_cited,
        }
        if consultation:
            base_evidence["llm_consultation"] = consultation

        if llm_response.status == PassOutcome.ERROR:
            error_class = llm_response.error_class or "unavailable"
            return SieveResult(
                control_id=control_spec.control_id,
                status="ERROR",
                message=f"Model judgment could not be obtained: {llm_response.reasoning}",
                level=control_spec.level,
                conclusive_phase=VerificationPhase.LLM,
                evidence=base_evidence,
                source="sieve",
                resolving_pass_handler="llm_eval",
                authority="suggestive",
                error_class=error_class,
                concluded_by="llm_eval",
                error={"class": error_class, "cause": llm_response.reasoning or "model service failure"},
            )

        verdicts = {PassOutcome.PASS: "pass", PassOutcome.FAIL: "fail"}
        judgment = Judgment(
            verdict=verdicts.get(llm_response.status, "inconclusive"),
            reasoning=llm_response.reasoning,
            cited_evidence=tuple(llm_response.evidence_cited),
            model=llm_response.model,
            model_version=llm_response.model_version,
            confidence=llm_response.confidence,
        )
        assessment = assess_judgment(judgment, consultation, source=source)

        if assessment.kind == "finding":
            return SieveResult(
                control_id=control_spec.control_id,
                status="FAIL",
                message=f"Model finding: {llm_response.reasoning}",
                level=control_spec.level,
                conclusive_phase=VerificationPhase.LLM,
                confidence=llm_response.confidence,
                evidence=base_evidence,
                source="sieve",
                authority="suggestive",
                concluded_by="llm_judgment",
            )

        if assessment.kind == "candidate":
            pending = SieveResult(
                control_id=control_spec.control_id,
                status="PENDING",
                message="",
                level=control_spec.level,
                confidence=llm_response.confidence,
                evidence=base_evidence,
                source="sieve",
                pending={"kind": "llm_judgment"},
            )
            return candidate_result(pending, assessment.candidate or {})

        verification_steps = None
        for inv in control_spec.metadata.get("handler_invocations", []):
            if inv.handler == "manual":
                steps = (inv.model_extra or {}).get("steps")
                if steps:
                    verification_steps = steps
                break

        if assessment.kind == "invalid":
            message = f"Model judgment rejected: {assessment.reason}"
            base_evidence["invalid_judgment"] = {
                "verdict": judgment.verdict,
                "reasoning": judgment.reasoning,
                "cited_evidence": list(judgment.cited_evidence),
                "missing_excerpts": list(assessment.missing_excerpts),
                "model": judgment.model,
            }
        else:
            message = f"Model judgment inconclusive: {llm_response.reasoning}"

        return SieveResult(
            control_id=control_spec.control_id,
            status="WARN",
            message=message,
            level=control_spec.level,
            conclusive_phase=VerificationPhase.MANUAL,
            confidence=llm_response.confidence,
            evidence=base_evidence,
            verification_steps=verification_steps
            or [
                "Review LLM analysis above",
                "Verify findings manually",
                f"Control: {control_spec.control_id} - {control_spec.name}",
            ],
            source="sieve",
            authority="suggestive",
            concluded_by="none",
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

        # Execute in dependency order, collect results. The finally block
        # guarantees the MCP pool (if any was constructed) is torn down on
        # every exit path -- success, exception, or interrupt.
        result_map: dict[str, SieveResult] = {}
        try:
            for spec in ordered:
                context = context_factory(spec.control_id)
                result = self.verify(spec, context)
                result_map[spec.control_id] = result
        finally:
            if self._mcp_pool is not None:
                try:
                    self._mcp_pool.teardown_all()
                except Exception as err:  # noqa: BLE001 - best-effort teardown
                    logger.warning("MCP pool teardown at verify_batch exit raised: %s", err)
                self._mcp_pool = None

        # Return in original order
        return [result_map[spec.control_id] for spec in control_specs if spec.control_id in result_map]

    def _apply_on_pass(
        self,
        control_spec: ControlSpec,
        context: CheckContext,
        evidence: dict[str, Any],
    ) -> None:
        """Record the control's on_pass project_update as a proposal in its evidence.

        An audit never writes to the repository (feature 042, FR-001): the
        resolved update is reported under ``evidence["proposed_project_update"]``
        for a person or an applied remediation to act on.

        Values can reference evidence using $EVIDENCE.<key> syntax.
        """
        on_pass = control_spec.metadata.get("on_pass")
        if not on_pass:
            return

        if hasattr(on_pass, "project_update"):
            updates = on_pass.project_update
        elif isinstance(on_pass, dict):
            updates = on_pass.get("project_update", {})
        else:
            return

        if not updates:
            return

        resolved: dict[str, Any] = {}
        for key, value in updates.items():
            if isinstance(value, str) and value.startswith("$EVIDENCE."):
                evidence_key = value[len("$EVIDENCE.") :]
                resolved[key] = evidence.get(evidence_key, value)
            else:
                resolved[key] = value

        evidence["proposed_project_update"] = resolved


# =============================================================================
# Module-level helpers
# =============================================================================


def _build_mcp_pool(handler_ctx: HandlerContext) -> Any:
    """Construct a per-run :class:`McpPool` seeded from the execution context.

    The execution context (assigned by the audit entrypoint) carries an
    ``mcp_servers`` mapping when the effective configuration declared any.
    An audit run that never encounters an mcp-handler pass never reaches
    this function, so the pool cost stays zero for existing consumers.
    """
    from .mcp_pool import McpPool

    servers: dict[str, Any] = {}
    execution_context = handler_ctx.execution_context
    if execution_context is not None:
        maybe = getattr(execution_context, "mcp_servers", None)
        if isinstance(maybe, dict):
            servers = maybe
    return McpPool(servers=servers)


def _handler_status_to_outcome(status: HandlerResultStatus) -> PassOutcome:
    """Convert HandlerResultStatus to PassOutcome."""
    mapping = {
        HandlerResultStatus.PASS: PassOutcome.PASS,
        HandlerResultStatus.FAIL: PassOutcome.FAIL,
        # Feature 037: explicit, because the fallback below is
        # PassOutcome.INCONCLUSIVE -- omitting this entry would record a pass
        # that concluded as one that reached no conclusion, contradicting the
        # control's own status in pass_history.
        HandlerResultStatus.WARN: PassOutcome.WARN,
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
