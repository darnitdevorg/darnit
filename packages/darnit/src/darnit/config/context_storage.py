"""Context definitions, the pending-context query, and detection helpers.

Stored context values are read only by :mod:`darnit.config.context_resolve`,
whose usable mapping is the only source of values for consumers (feature 042,
FR-006). Nothing here writes. Context values and confirmation records are
written only by :mod:`darnit.config.context_writes`.
"""

from typing import Any

from darnit.config.context_schema import (
    ContextDefinition,
    ContextPromptRequest,
    ContextSource,
    ContextValue,
)
from darnit.core.logging import get_logger

logger = get_logger("config.context_storage")


# =============================================================================
# Context Definitions
# =============================================================================


def _runtime_definition(defn: Any) -> ContextDefinition:
    """The runtime ContextDefinition for a framework ``ContextDefinitionConfig``."""
    from darnit.config.context_schema import ContextType

    return ContextDefinition(
        type=ContextType(defn.type),
        prompt=defn.prompt,
        hint=defn.hint,
        no_detect_hint=defn.no_detect_hint,
        examples=defn.examples,
        values=defn.values,
        affects=defn.affects,
        store_as=defn.store_as,
        auto_detect=defn.auto_detect,
        auto_detect_method=defn.auto_detect_method,
        required=defn.required,
        detect_filter=defn.detect_filter,
        allow_sieve_hints=defn.allow_sieve_hints,
        hint_sources=defn.hint_sources,
        validity_days=defn.validity_days,
        detect=defn.detect,
    )


def framework_definitions(framework: Any) -> dict[str, ContextDefinition]:
    """The runtime context definitions of a ``FrameworkConfig``."""
    return {key: _runtime_definition(defn) for key, defn in framework.context.definitions.items()}


def get_context_definitions(local_path: str) -> dict[str, ContextDefinition]:
    """Get context definitions from the framework TOML.

    This function loads the declarative context definitions from the
    framework configuration (e.g., openssf-baseline.toml [context] section).

    Args:
        local_path: Path to the repository (the framework is not read from it)

    Returns:
        Dict of context_key -> ContextDefinition
    """
    from darnit.config.merger import load_effective_config_auto

    try:
        effective_config = load_effective_config_auto()
        # Access the underlying framework config
        framework = effective_config._framework_config
        if framework is None:
            return {}

        return framework_definitions(framework)
    except Exception as e:
        logger.warning(f"Could not load context definitions: {e}")
        return {}


def get_context_definitions_with_detect(
    local_path: str,
) -> dict[str, tuple[ContextDefinition, list | None]]:
    """Get context definitions with their handler-based detect pipelines.

    Returns both the ContextDefinition and the raw detect pipeline
    (list of HandlerInvocation) from the TOML framework config.

    Args:
        local_path: Path to the repository (the framework is not read from it)

    Returns:
        Dict of context_key -> (ContextDefinition, detect_pipeline_or_None)
    """
    from darnit.config.merger import load_effective_config_auto

    try:
        effective_config = load_effective_config_auto()
        framework = effective_config._framework_config
        if framework is None:
            return {}

        result: dict[str, tuple[ContextDefinition, list | None]] = {}

        for key, defn in framework.context.definitions.items():
            definition = _runtime_definition(defn)
            result[key] = (definition, definition.detect)

        return result
    except Exception as e:
        logger.warning(f"Could not load context definitions with detect: {e}")
        return {}


def get_pending_context(
    local_path: str,
    control_ids: list[str] | None = None,
    owner: str | None = None,
    repo: str | None = None,
    *,
    target: str | None = None,
) -> list[ContextPromptRequest]:
    """Context keys that are candidates or unknown and affect a loaded control.

    Pure: nothing is written (feature 042, FR-001). Each request carries the
    key's candidate, if any, with its origin; a candidate is shown to a
    person and never used as the key's value.

    Args:
        local_path: Path to the repository
        control_ids: Optional list of control IDs to check (default: all)
        owner: Repository owner, for detection (auto-detected from git if not provided)
        repo: Repository name, for detection (auto-detected from git if not provided)
        target: Repository identity the operator named, for operator-side confirmations

    Returns:
        List of ContextPromptRequest sorted by priority (highest first)
    """
    from darnit.config.context_resolve import resolve_context

    definitions = get_context_definitions(local_path)
    if not definitions:
        return []

    if owner is None or repo is None:
        from darnit.core.utils import detect_owner_repo

        detected_owner, detected_repo = detect_owner_repo(local_path)
        owner = owner or detected_owner or None
        repo = repo or detected_repo or None

    resolved = resolve_context(local_path, definitions, target=target, owner=owner, repo=repo)

    pending: list[ContextPromptRequest] = []
    for candidate in resolved.pending(control_ids):
        definition = resolved.definitions[candidate.key]
        affected = [c for c in definition.affects if not control_ids or c in control_ids]
        current_value = None
        if candidate.value is not None and candidate.origin is not None:
            current_value = ContextValue(
                source=ContextSource.AUTO_DETECTED,
                value=candidate.value,
                detection_method=f"{candidate.origin.kind.value}:{candidate.origin.method or ''}".rstrip(":"),
                confidence=candidate.origin.confidence if candidate.origin.confidence is not None else 0.0,
            )
        pending.append(
            ContextPromptRequest(
                key=candidate.key,
                definition=definition,
                control_ids=affected,
                current_value=current_value,
                candidate=candidate,
                priority=len(affected),
            )
        )

    pending.sort(key=lambda x: x.priority, reverse=True)
    return pending


def _apply_detect_filter(
    key: str,
    definition: Any,
    detected: ContextValue,
) -> ContextValue | None:
    """Filter a detected candidate through the key's `detect_filter`.

    Returns the surviving value, or None when nothing survives. A key with no
    filter is returned untouched.

    The reporting here is deliberate. A discarded value must be
    distinguishable from "detection found nothing" (FR-008), and a filter that
    could not run must be distinguishable from one that ran and said no -- a
    guard that silently does not run is the defect this feature fixes.
    """
    from darnit.context.detect_filter import FilterDecision, apply_filter

    expression = getattr(definition, "detect_filter", None)
    if not expression:
        return detected

    outcome = apply_filter(expression, detected.value, key)

    if outcome.decision is FilterDecision.KEEP:
        if outcome.discarded:
            logger.info(
                "Context '%s': kept %d detected value(s), discarded %d by detect_filter (%s)",
                key,
                len(outcome.value) if isinstance(outcome.value, list) else 1,
                len(outcome.discarded),
                ", ".join(repr(d) for d in outcome.discarded[:3]),
            )
        detected.value = outcome.value
        return detected

    if outcome.decision is FilterDecision.REJECT:
        logger.info(
            "Context '%s': detected value rejected by detect_filter, leaving the key unset (%s)",
            key,
            ", ".join(repr(d) for d in outcome.discarded[:3]),
        )
    else:
        logger.warning(
            "Context '%s': detect_filter could not be evaluated, so the "
            "detected value is discarded rather than accepted (%s)",
            key,
            outcome.reason,
        )
    return None


def _run_detect_pipeline(
    key: str,
    detect_pipeline: list,
    local_path: str,
    owner: str | None,
    repo: str | None,
) -> ContextValue | None:
    """Run handler-based context detection pipeline.

    Processes the `detect` list from a TOML [context.key] definition through
    the sieve handler registry, following the confidence gradient:
    deterministic handlers first, then pattern, then llm, then manual/confirm.

    Stops at the first handler that produces a usable result. A step's
    ``value_if_fail`` applies only when that step ran to completion and
    answered negatively (FAIL, or a CEL ``expr`` that evaluated false) and no
    earlier step failed to run; a step that errored or could not decide
    produces no value (feature 042, FR-016, FR-017).

    Args:
        key: Context key being detected (e.g., "maintainers")
        detect_pipeline: List of HandlerInvocation objects from TOML
        local_path: Path to the repository
        owner: GitHub owner (optional)
        repo: GitHub repo name (optional)

    Returns:
        ContextValue with auto-detected value if found, None otherwise
    """
    incomplete = False
    try:
        from darnit.sieve.handler_registry import (
            HandlerContext,
            HandlerResultStatus,
            get_sieve_handler_registry,
        )

        registry = get_sieve_handler_registry()

        # Build handler context for detection
        handler_ctx = HandlerContext(
            local_path=local_path,
            owner=owner or "",
            repo=repo or "",
            default_branch="main",
            control_id=f"context.{key}",
            project_context={},
            gathered_evidence={},
            shared_cache={},
            dependency_results={},
        )

        for invocation in detect_pipeline:
            handler_info = registry.get(invocation.handler)
            if not handler_info:
                logger.debug(
                    "Context detect: handler '%s' not found for key '%s'",
                    invocation.handler,
                    key,
                )
                incomplete = True
                continue

            # Build handler config from invocation's extra fields
            handler_config = dict(invocation.model_extra or {})
            handler_config["handler"] = invocation.handler

            try:
                result = handler_info.fn(handler_config, handler_ctx)
            except Exception as e:
                logger.debug(
                    "Context detect handler '%s' error for '%s': %s",
                    invocation.handler,
                    key,
                    e,
                )
                incomplete = True
                continue

            # Apply CEL expr if present (same as orchestrator does for controls)
            if handler_config.get("expr"):
                try:
                    from darnit.sieve.orchestrator import _apply_cel_expr

                    result = _apply_cel_expr(handler_config, result)
                except ImportError:
                    pass

            if result.status == HandlerResultStatus.PASS and result.evidence:
                # First check handler config for value_if_pass
                value_if_pass = handler_config.get("value_if_pass")
                if value_if_pass is not None:
                    return ContextValue.auto_detected(
                        value=value_if_pass,
                        method=f"detect_pipeline:{invocation.handler}",
                        confidence=result.confidence,
                    )
                # Fallback: extract value from evidence
                detected_value = result.evidence.get("value") or result.evidence.get(key)
                if detected_value is not None:
                    return ContextValue.auto_detected(
                        value=detected_value,
                        method=f"detect_pipeline:{invocation.handler}",
                        confidence=result.confidence,
                    )

            if result.status in (
                HandlerResultStatus.FAIL,
                HandlerResultStatus.INCONCLUSIVE,
                HandlerResultStatus.ERROR,
            ):
                concluded = result.status == HandlerResultStatus.FAIL or (
                    result.status == HandlerResultStatus.INCONCLUSIVE and "expr" in (result.evidence or {})
                )
                if not concluded:
                    incomplete = True
                    continue
                value_if_fail = handler_config.get("value_if_fail")
                if value_if_fail is not None:
                    if incomplete:
                        return None
                    return ContextValue.auto_detected(
                        value=value_if_fail,
                        method=f"detect_pipeline:{invocation.handler}:fail_fallback",
                        # A concluded negative frequently leaves confidence
                        # unset (None); fall back to auto_detected's own
                        # default rather than passing None into a numeric
                        # comparison.
                        confidence=result.confidence if result.confidence is not None else 0.8,
                    )

            # No value_if_fail -- try next handler in pipeline

    except ImportError:
        logger.debug("Sieve handler registry not available for context detection")
    except Exception as e:
        logger.warning(f"Context detect pipeline failed for '{key}': {e}")

    return None


def _try_sieve_detection(
    key: str,
    local_path: str,
    owner: str | None,
    repo: str | None,
) -> ContextValue | None:
    """Try to auto-detect context using the context sieve.

    Uses progressive detection: deterministic → heuristic → API.

    Args:
        key: Context key to detect (e.g., "maintainers")
        local_path: Path to the repository
        owner: GitHub owner (optional)
        repo: GitHub repo name (optional)

    Returns:
        ContextValue with auto-detected value if found, None otherwise
    """
    try:
        from darnit.context import get_context_sieve

        sieve = get_context_sieve()
        result = sieve.detect(key, local_path, owner, repo)

        if result.is_usable:
            return ContextValue.auto_detected(
                value=result.value,
                method=f"context_sieve ({len(result.signals)} signals)",
                confidence=result.confidence,
            )
    except ImportError:
        logger.debug("Context sieve not available, skipping auto-detection")
    except Exception as e:
        logger.warning(f"Context sieve detection failed for '{key}': {e}")

    return None
