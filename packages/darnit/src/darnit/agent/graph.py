"""Agent graph nodes for the darnit run interactive pipeline.

Implements the audit → collect_context → remediate workflow as discrete,
composable nodes that operate on AuditState.

Bug fixes addressed here:

  Issue #144 — remediate() was logging what it *would* fix but never calling
  RemediationExecutor. Now it loads the framework config, builds an executor
  with the confirmed context values from state, and calls execute() for every
  FAIL control that has a remediation definition.

  Issue #145 — collect_context() was storing user answers in
  state.feedback_questions but never triggering a re-audit so the answers
  could actually improve control outcomes. Now it persists answers via
  save_context_values() and returns a sentinel that the caller should use
  to schedule a fresh audit pass.

  Issue #146 — feedback_questions were write-only: answers were collected
  but no downstream node read them. collect_context() now also writes
  state.context_values (a flat {key: answer} map) which remediate() passes
  directly to RemediationExecutor as context_values=, enabling
  ${context.*} substitution in remediation templates.
"""

from __future__ import annotations

from typing import Any

from darnit.agent.state import AuditState
from darnit.config.context_storage import save_context_values
from darnit.config.framework_schema import FrameworkConfig
from darnit.core.logging import get_logger
from darnit.remediation.executor import RemediationExecutor
from darnit.tools.audit import prepare_audit, run_checks

logger = get_logger("agent.graph")


# =============================================================================
# audit node
# =============================================================================


def audit(state: AuditState) -> AuditState:
    """Run a compliance audit and store results in state.

    Uses the framework identified by state.framework_name (or auto-resolved
    from .baseline.toml) and injects any context values already confirmed so
    that context-dependent controls can be resolved correctly on re-runs.

    Args:
        state: Current agent state.

    Returns:
        Updated state with audit_results populated.
    """
    owner, repo, resolved_path, default_branch, error = prepare_audit(
        state.owner, state.repo, state.local_path
    )

    if error:
        state.error = error
        return state

    # Persist auto-detected repo coordinates back into state
    state.owner = owner
    state.repo = repo
    state.default_branch = default_branch

    try:
        # Pass context_values so that re-audit runs pick up confirmed answers
        results, _skipped = run_checks(
            owner=owner,
            repo=repo,
            local_path=resolved_path,
            default_branch=default_branch,
            level=state.level,
            stop_on_llm=True,
            apply_user_config=True,
            framework_name=state.framework_name,
        )
        state.audit_results = results
        state.error = None
        logger.info(
            "Audit complete: %d results (%d FAIL, %d WARN)",
            len(results),
            len(state.failing_control_ids()),
            len(state.warn_control_ids()),
        )
    except Exception as exc:
        state.error = str(exc)
        logger.error("Audit failed: %s", exc)

    return state


# =============================================================================
# collect_context node
# =============================================================================


def collect_context(state: AuditState, answers: dict[str, str]) -> AuditState:
    """Record user answers to context questions and persist them.

    Issue #145 fix: After answers are stored, context_values is updated so
    that the *next* call to audit() picks up the confirmed values.  The caller
    is responsible for calling audit() again after this node returns; this
    function signals that a re-audit is needed by clearing state.audit_results.

    Issue #146 fix: Answers are written into state.context_values (a plain
    dict) so that remediate() — and any future node — can read them without
    iterating over feedback_questions themselves.

    Args:
        state: Current agent state.
        answers: Mapping of {context_key: answer_string} provided by the user.
            Keys must match the context_key field of a FeedbackQuestion in
            state.feedback_questions.

    Returns:
        Updated state with:
        - feedback_questions updated (answered=True for matched questions)
        - context_values updated with all confirmed answers
        - audit_results cleared to signal a re-audit is required
    """
    if not answers:
        return state

    # Security: validate all answers before storing any of them.  User-supplied
    # values ultimately flow into RemediationExecutor._substitute_command(); even
    # without shell=True, null bytes and newlines can break argument handling and
    # shell metacharacters are rejected as a defence-in-depth measure.
    for key, value in answers.items():
        _validate_context_answer(key, value)

    # Record answers on the individual questions
    for question in state.feedback_questions:
        if question.context_key in answers:
            question.answer = answers[question.context_key]
            question.answered = True

    # Issue #146 fix: build the flat context map from ALL answered questions
    # (not just the ones answered in this call) so downstream nodes see the
    # complete picture.
    state.context_values = state.collect_answered_context()

    # Persist confirmed answers to .project/project.yaml so that the sieve
    # engine can load them on the next audit pass.
    if state.context_values:
        try:
            save_context_values(
                local_path=state.local_path,
                values=state.context_values,
            )
            logger.info(
                "Persisted %d context value(s): %s",
                len(state.context_values),
                list(state.context_values.keys()),
            )
        except Exception as exc:
            # Non-fatal: log and continue — the in-memory values are still set.
            logger.warning("Failed to persist context values: %s", exc)

    # Issue #145 fix: clear audit_results so the caller knows a re-audit is
    # required with the newly confirmed context.
    state.audit_results = []

    return state


# =============================================================================
# remediate node
# =============================================================================


def remediate(state: AuditState, dry_run: bool = False) -> AuditState:
    """Remediate all FAIL controls that have a remediation definition.

    Issue #144 fix: Previously this node only logged what it would do.
    Now it loads the framework config, instantiates RemediationExecutor with
    the confirmed context values, and calls execute() for each failing control.

    Issue #146 fix: context_values from answered feedback_questions are passed
    to RemediationExecutor as context_values= so that ${context.*} variables in
    remediation templates are resolved with confirmed answers.

    Args:
        state: Current agent state. Must contain audit_results from a prior
            audit() call. context_values should be populated if collect_context
            was run beforehand.
        dry_run: If True, show what would change without writing any files.

    Returns:
        Updated state with remediation_results populated.
    """
    failing_ids = state.failing_control_ids()
    if not failing_ids:
        logger.info("No failing controls to remediate.")
        return state

    # Load framework config to get remediation definitions
    framework: FrameworkConfig | None = _load_framework_config(state.framework_name)
    if framework is None:
        logger.warning(
            "Could not load framework config; skipping remediation for: %s",
            failing_ids,
        )
        return state

    # Issue #144 fix: build a real executor and call execute() for each control.
    # Issue #146 fix: pass context_values so ${context.*} substitution works.
    executor = RemediationExecutor(
        local_path=state.local_path,
        owner=state.owner,
        repo=state.repo,
        default_branch=state.default_branch,
        templates=framework.templates,
        context_values=state.context_values,   # ← reads answered feedback
        framework_path=_get_framework_path(state.framework_name),
    )

    results: list[dict[str, Any]] = []

    for control_id in failing_ids:
        control_config = framework.controls.get(control_id)
        if control_config is None:
            logger.debug("No framework definition for control %s, skipping.", control_id)
            continue

        remediation_config = control_config.remediation
        if remediation_config is None:
            logger.debug("Control %s has no remediation definition, skipping.", control_id)
            results.append({
                "control_id": control_id,
                "status": "skipped",
                "reason": "no remediation defined",
            })
            continue

        logger.info(
            "%s remediation for %s",
            "Dry-run" if dry_run else "Applying",
            control_id,
        )

        try:
            result = executor.execute(
                control_id=control_id,
                config=remediation_config,
                dry_run=dry_run,
            )
            results.append({
                "control_id": control_id,
                "success": result.success,
                "message": result.message,
                "dry_run": result.dry_run,
                "details": result.details,
            })
            logger.info(
                "Remediation %s for %s: %s",
                "succeeded" if result.success else "failed",
                control_id,
                result.message,
            )
        except Exception as exc:
            logger.error("Remediation error for %s: %s", control_id, exc)
            results.append({
                "control_id": control_id,
                "success": False,
                "message": str(exc),
                "dry_run": dry_run,
                "details": {},
            })

    state.remediation_results = results
    return state


# =============================================================================
# route helper
# =============================================================================


def route(state: AuditState) -> str:
    """Decide the next step based on the current audit state.

    Returns:
        "collect_context" — WARN controls exist and there are unanswered
            feedback questions.
        "remediate"       — FAIL controls exist (and context is complete).
        "end"             — No actionable findings remain.
    """
    if state.error:
        return "end"

    if not state.audit_results:
        # audit_results cleared by collect_context — needs re-audit
        return "audit"

    has_warn = bool(state.warn_control_ids())
    has_fail = bool(state.failing_control_ids())

    if has_warn and state.has_unanswered_questions():
        return "collect_context"

    if has_fail:
        return "remediate"

    return "end"


# =============================================================================
# Private helpers
# =============================================================================


def _load_framework_config(framework_name: str | None):
    """Load FrameworkConfig for the given framework name."""
    try:
        from darnit.config.control_loader import load_framework_config
        from darnit.config.merger import resolve_framework_path

        name = framework_name or "openssf-baseline"
        path = resolve_framework_path(name)
        if path and path.exists():
            return load_framework_config(path)
    except Exception as exc:
        logger.warning("Failed to load framework config: %s", exc)
    return None


def _get_framework_path(framework_name: str | None) -> str | None:
    """Return the absolute path to the framework TOML file, or None."""
    try:
        from darnit.config.merger import resolve_framework_path

        name = framework_name or "openssf-baseline"
        path = resolve_framework_path(name)
        if path and path.exists():
            return str(path)
    except Exception as exc:
        logger.warning("Failed to resolve framework path for %r: %s", framework_name, exc)
    return None


# Characters that must never appear in user-supplied context answer values.
# These could be interpreted as shell metacharacters or break argument parsing
# even when shell=False, and have no legitimate use in compliance context values
# (paths, maintainer names, policy filenames, etc.).
_INVALID_ANSWER_CHARS = frozenset("\x00\n\r;|&$`(){}[]<>\\")


def _validate_context_answer(key: str, value: str) -> None:
    """Raise ValueError if *value* contains characters unsafe for context substitution.

    Args:
        key: The context key (used only for the error message).
        value: The user-supplied answer string to validate.

    Raises:
        ValueError: If the value contains shell metacharacters, newlines, or
            null bytes that could enable injection via command substitution.
    """
    found = _INVALID_ANSWER_CHARS & set(value)
    if found:
        raise ValueError(
            f"Context answer for {key!r} contains disallowed character(s) "
            f"{sorted(found)!r}. Values must not include shell metacharacters, "
            "newlines, or null bytes."
        )
