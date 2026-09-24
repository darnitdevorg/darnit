"""Context storage abstraction layer for interactive context collection.

This module provides a unified interface for loading and saving context values
with provenance tracking. It supports multiple storage formats:

1. Legacy: .project.yaml x-openssf-baseline.context section
2. CNCF: .project/project.yaml extensions.openssf-baseline.config.context section

The abstraction layer isolates the rest of the codebase from storage format changes
as the CNCF .project/ specification evolves.

Note: The CNCF .project/ specification is still under development (PR #131).
This module may need updates as the upstream spec evolves.
"""

from pathlib import Path
from typing import Any

from darnit.config.context_schema import (
    ContextByCategory,
    ContextDefinition,
    ContextPromptRequest,
    ContextSource,
    ContextValue,
)
from darnit.config.loader import (
    init_project_config,
    load_project_config,
    save_project_config,
)
from darnit.config.schema import (
    BaselineExtension,
    ProjectContext,
)
from darnit.core.logging import get_logger

logger = get_logger("config.context_storage")


# =============================================================================
# Context Loading
# =============================================================================


def _parse_context_value(val: Any) -> ContextValue | None:
    """Helper to reconstruct ContextValue from a raw dictionary or wrap a native value."""
    if val is None:
        return None
    if isinstance(val, dict) and "value" in val and "source" in val:
        try:
            return ContextValue.model_validate(val)
        except Exception:
            pass
    if isinstance(val, ContextValue):
        return val
    # Wrap primitive in a USER_CONFIRMED context value
    # primitives found natively or untracked are considered user-confirmed overrides
    return ContextValue(
        source=ContextSource.USER_CONFIRMED,
        value=val,
        confidence=1.0,
    )


def load_context(local_path: str) -> ContextByCategory:
    """Load usable context values: stored values re-checked against detect_filter.

    Every consumer of context -- audit, remediation, auto-detect, the harness,
    and pending-key calculation -- reads through here, so a stored value that
    fails its key's filter is dropped for all of them at once (FR-014). Use
    load_stored_context only when the raw on-disk contents are needed.
    """
    return _filter_context(local_path, load_stored_context(local_path))


def load_stored_context(local_path: str) -> ContextByCategory:
    """Load all context values with provenance from project config, unfiltered.

    This function abstracts the storage format and returns context values
    organized by category with full provenance tracking.

    Priority order:
    1. CNCF format: .project/project.yaml native fields + extensions.openssf-baseline.config.context
    2. Legacy format: .project.yaml x-openssf-baseline.context

    Args:
        local_path: Path to the repository

    Returns:
        Dict of category -> {key -> ContextValue}
        Categories include: governance, security, build, project, ci, custom
    """
    config = load_project_config(local_path)
    if not config:
        return {}

    context_by_category: ContextByCategory = {}

    def _add_context(category: str, key: str, value: Any) -> None:
        ctx_val = _parse_context_value(value)
        if ctx_val is not None:
            if category not in context_by_category:
                context_by_category[category] = {}
            context_by_category[category][key] = ctx_val

    # 1. Native CNCF Fields Mapping
    if contact := config.get_security_contact():
        _add_context("security", "security_contact", contact)

    # Note: Other native mappings (like governance_model native equivalent) would go here
    # once they are merged upstream into the CNCF spec.

    # 2. Extensions / Legacy Mapping (x_openssf_baseline.context)
    if config.x_openssf_baseline and config.x_openssf_baseline.context:
        ctx = config.x_openssf_baseline.context

        # Build category
        _add_context("build", "has_releases", ctx.has_releases)
        _add_context("build", "has_compiled_assets", ctx.has_compiled_assets)

        # Project category
        _add_context("project", "has_subprojects", ctx.has_subprojects)
        _add_context("project", "is_library", ctx.is_library)

        # CI category
        _add_context("ci", "provider", ctx.ci_provider)

        # Platform category
        _add_context("platform", "platform", ctx.platform)
        _add_context("platform", "primary_language", ctx.primary_language)
        _add_context("platform", "languages", ctx.languages)

        # Governance category
        _add_context("governance", "maintainers", ctx.maintainers)
        _add_context("governance", "governance_model", ctx.governance_model)

        # Security category (fallback if native not found)
        if ctx.security_contact is not None and "security_contact" not in context_by_category.get("security", {}):
            _add_context("security", "security_contact", ctx.security_contact)

        # Dynamically load unmapped arbitrary fields into 'custom' category
        known_keys = {
            "has_releases",
            "has_compiled_assets",
            "has_subprojects",
            "is_library",
            "ci_provider",
            "platform",
            "primary_language",
            "languages",
            "maintainers",
            "governance_model",
            "security_contact",
        }
        for key, val in ctx.model_dump(exclude_unset=True).items():
            if key not in known_keys and val is not None:
                _add_context("custom", key, val)

    return context_by_category


def flatten_user_context(context_by_category: ContextByCategory) -> dict[str, Any]:
    """Flatten categorized context into bare keys for ``when`` clause evaluation.

    The ``when`` clause system uses bare keys like ``ci_provider``, ``has_releases``,
    ``platform``, etc.  But :func:`load_context` returns categories like
    ``{"ci": {"provider": ContextValue(...)}, "build": {"has_releases": ...}}``.

    This helper resolves the mismatch by mapping ``category.key`` → bare key:
    - ``ci.provider`` → ``ci_provider``
    - Everything else keeps its stored key as-is (already bare)

    Returns:
        Flat dict mapping bare key → raw value.
    """
    flat: dict[str, Any] = {}
    # Mapping of (category, stored_key) → bare key used in when clauses
    remap = {
        ("ci", "provider"): "ci_provider",
    }
    for category_name, category_values in context_by_category.items():
        for stored_key, ctx_value in category_values.items():
            bare_key = remap.get((category_name, stored_key), stored_key)
            flat[bare_key] = ctx_value.value
    return flat


def get_context_value(
    local_path: str,
    key: str,
    category: str | None = None,
) -> ContextValue | None:
    """Get a specific context value with provenance.

    Args:
        local_path: Path to the repository
        key: Context key to retrieve (e.g., "has_releases", "maintainers")
        category: Optional category to search in (e.g., "build", "governance")
                 If not specified, searches all categories

    Returns:
        ContextValue if found, None otherwise
    """
    context = load_context(local_path)

    stored: ContextValue | None = None
    if category:
        # Search specific category
        cat_context = context.get(category, {})
        stored = cat_context.get(key)
    else:
        # Search all categories
        for cat_context in context.values():
            if key in cat_context:
                stored = cat_context[key]
                break

    return stored


def get_raw_value(
    local_path: str,
    key: str,
    default: Any = None,
) -> Any:
    """Get a context value without provenance (just the raw value).

    This is a convenience function for when you only need the value,
    not the full ContextValue with provenance.

    Args:
        local_path: Path to the repository
        key: Context key to retrieve
        default: Default value if not found

    Returns:
        The raw value, or default if not found
    """
    ctx_value = get_context_value(local_path, key)
    if ctx_value:
        return ctx_value.value
    return default


def _filter_context(local_path: str, context: ContextByCategory) -> ContextByCategory:
    if not context:
        return context
    try:
        definitions = get_context_definitions(local_path)
    except Exception as exc:  # noqa: BLE001 - a read must not fail on config
        logger.debug("Could not load context definitions to filter stored context: %s", exc)
        return context

    filtered: ContextByCategory = {}
    for category, values in context.items():
        for key, stored in values.items():
            kept = _filter_stored_value(definitions, key, stored)
            if kept is not None:
                filtered.setdefault(category, {})[key] = kept
    return filtered


def _filter_stored_value(
    definitions: dict[str, ContextDefinition], key: str, stored: ContextValue
) -> ContextValue | None:
    """Re-evaluate a stored value against its key's detect_filter (FR-014).

    The read path performed no validation before feature 039, so a value
    auto-accepted while the filter was not running persists indefinitely -- and
    the repositories most likely to hold one are exactly those audited while
    the guard was off. Without this, the fix protects only repositories that
    have never been audited.

    This runs inside load_context rather than being opted into by callers. An
    opt-in would mean any future caller silently skips the guard, which is the
    defect class this feature exists to close.

    Nothing is written (FR-015). A stored value may carry a human confirmation,
    and Principle IV makes confirmation the transition that grants usability --
    the framework reports that a stored value now fails its filter; it does not
    silently revoke what a person put there.
    """
    from darnit.context.detect_filter import FilterDecision, apply_filter

    definition = definitions.get(key)
    expression = getattr(definition, "detect_filter", None) if definition else None
    if not expression:
        return stored

    outcome = apply_filter(expression, stored.value, key)
    if outcome.decision is FilterDecision.KEEP:
        if outcome.discarded:
            logger.info(
                "Context '%s': stored value had %d element(s) removed by "
                "detect_filter on read; stored context is unchanged",
                key,
                len(outcome.discarded),
            )
            stored.value = outcome.value
        return stored

    logger.warning(
        "Context '%s': the stored value fails this key's detect_filter and is "
        "treated as unset (%s). Stored context is NOT modified; correct or "
        "remove it in .project/ if it is wrong.",
        key,
        outcome.reason,
    )
    return None


def is_context_confirmed(local_path: str, key: str) -> bool:
    """Check if a context key has been confirmed by the user.

    Args:
        local_path: Path to the repository
        key: Context key to check

    Returns:
        True if the context value has been set
    """
    return get_context_value(local_path, key) is not None


# =============================================================================
# Context Saving
# =============================================================================


def save_context_value(
    local_path: str,
    key: str,
    value: Any,
    source: ContextSource = ContextSource.USER_CONFIRMED,
    category: str | None = None,
    detection_method: str | None = None,
    confidence: float = 1.0,
) -> str:
    """Save a context value with provenance tracking.

    This function saves the value to the appropriate storage format
    and tracks how the value was obtained.

    Args:
        local_path: Path to the repository
        key: Context key to save (e.g., "has_releases", "maintainers")
        value: The value to save
        source: How the value was obtained
        category: Category for organization (e.g., "build", "governance")
        detection_method: How auto-detected values were found
        confidence: Confidence score (0.0-1.0)

    Returns:
        Path to the saved config file

    Raises:
        ValueError: If the key is not a known context key
    """
    resolved_path = Path(local_path).resolve()

    # Load existing config or create new one
    config = load_project_config(str(resolved_path))
    if config is None:
        config = init_project_config(str(resolved_path))

    # Ensure baseline extension exists
    if config.x_openssf_baseline is None:
        config.x_openssf_baseline = BaselineExtension()

    # Ensure context exists
    if config.x_openssf_baseline.context is None:
        config.x_openssf_baseline.context = ProjectContext()

    ctx = config.x_openssf_baseline.context

    # Normalize key (e.g. provider -> ci_provider)
    if key == "provider" and category == "ci":
        key = "ci_provider"

    # 1. Native CNCF Fields mapping (value is saved without provenance in native fields)
    if key == "security_contact":
        from darnit.config.schema import SecurityConfig

        if config.security is None:
            config.security = SecurityConfig()
        config.security.contact = value  # Unwrapped primitive

    # 2. Extensions Framework mapping (with provenance)
    from datetime import datetime

    kwargs = {
        "source": source,
        "value": value,
        "confidence": confidence,
    }
    if source == ContextSource.AUTO_DETECTED:
        kwargs["detected_at"] = datetime.now()
        kwargs["detection_method"] = detection_method
    elif source == ContextSource.USER_CONFIRMED:
        kwargs["confirmed_at"] = datetime.now()

    ctx_val = ContextValue(**kwargs)

    # Store complete provenance struct under baseline context for dynamic fields,
    # and just the raw primitive for strictly typed fields.
    if key in ctx.__class__.model_fields:
        setattr(ctx, key, value)
    else:
        setattr(ctx, key, ctx_val.model_dump(exclude_none=True))

    # Log provenance (even though we can't store it in legacy format)
    logger.info(f"Saved context {key}={value} (source={source.value}, confidence={confidence})")

    # Save config
    config_path = save_project_config(config, str(resolved_path))
    return config_path


def save_context_values(
    local_path: str,
    values: dict[str, Any],
    source: ContextSource = ContextSource.USER_CONFIRMED,
) -> str:
    """Save multiple context values at once.

    Args:
        local_path: Path to the repository
        values: Dict of key -> value to save

    Returns:
        Path to the saved config file
    """
    config_path = None
    for key, value in values.items():
        if value is not None:
            config_path = save_context_value(local_path, key, value, source)
    return config_path or str(Path(local_path) / ".project.yaml")


# =============================================================================
# Context Definitions
# =============================================================================


def get_context_definitions(local_path: str) -> dict[str, ContextDefinition]:
    """Get context definitions from the framework TOML.

    This function loads the declarative context definitions from the
    framework configuration (e.g., openssf-baseline.toml [context] section).

    Args:
        local_path: Path to the repository

    Returns:
        Dict of context_key -> ContextDefinition
    """
    from darnit.config.context_schema import ContextDefinition, ContextType
    from darnit.config.merger import load_effective_config_auto

    try:
        effective_config = load_effective_config_auto(local_path)
        # Access the underlying framework config
        framework = effective_config._framework_config
        if framework is None:
            return {}

        definitions: dict[str, ContextDefinition] = {}

        for key, defn in framework.context.definitions.items():
            # Convert ContextDefinitionConfig to ContextDefinition
            definitions[key] = ContextDefinition(
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
            )

        return definitions
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
        local_path: Path to the repository

    Returns:
        Dict of context_key -> (ContextDefinition, detect_pipeline_or_None)
    """
    from darnit.config.context_schema import ContextDefinition, ContextType
    from darnit.config.merger import load_effective_config_auto

    try:
        effective_config = load_effective_config_auto(local_path)
        framework = effective_config._framework_config
        if framework is None:
            return {}

        result: dict[str, tuple[ContextDefinition, list | None]] = {}

        for key, defn in framework.context.definitions.items():
            definition = ContextDefinition(
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
            )
            detect_pipeline = defn.detect if hasattr(defn, "detect") else None
            result[key] = (definition, detect_pipeline)

        return result
    except Exception as e:
        logger.warning(f"Could not load context definitions with detect: {e}")
        return {}


def get_pending_context(
    local_path: str,
    control_ids: list[str] | None = None,
    level: int = 3,
    owner: str | None = None,
    repo: str | None = None,
) -> list[ContextPromptRequest]:
    """Get list of context values that would improve audit accuracy.

    Returns context prompt requests sorted by priority (number of controls affected).
    For context keys with auto_detect=true, attempts to auto-detect values
    and includes them in the response for user confirmation.

    Detection priority:
    1. Handler-based detect pipeline (if defined in TOML [context.key].detect)
    2. Context sieve (hardcoded Python detectors)
    3. No detection (prompt user directly)

    Args:
        local_path: Path to the repository
        control_ids: Optional list of control IDs to check (default: all applicable)
        level: Maximum level to consider (1, 2, or 3)
        owner: GitHub owner (auto-detected from git if not provided)
        repo: GitHub repo name (auto-detected from git if not provided)

    Returns:
        List of ContextPromptRequest sorted by priority (highest first)
    """
    # Get context definitions with detect pipelines from framework
    definitions_with_detect = get_context_definitions_with_detect(local_path)
    if not definitions_with_detect:
        # Fallback to definitions without detect info
        definitions = get_context_definitions(local_path)
        if not definitions:
            return []
        definitions_with_detect = {k: (v, None) for k, v in definitions.items()}

    # Get current context values
    current_context = load_context(local_path)

    # Flatten current context keys (both stored keys and definition keys)
    confirmed_keys: set = set()
    for category_name, category_values in current_context.items():
        for stored_key in category_values:
            confirmed_keys.add(stored_key)
            # Also add "category.stored_key" for store_as reverse lookup
            confirmed_keys.add(f"{category_name}.{stored_key}")

    # Auto-detect owner/repo if not provided
    if owner is None or repo is None:
        from darnit.core.utils import detect_owner_repo

        detected_owner, detected_repo = detect_owner_repo(local_path)
        owner = owner or detected_owner or None
        repo = repo or detected_repo or None

    # Load auto_accept_confidence threshold from framework config
    auto_accept_threshold = 0.8
    try:
        from darnit.config.merger import load_effective_config_auto

        effective_config = load_effective_config_auto(Path(local_path))
        framework = effective_config._framework_config
        if framework is not None:
            auto_accept_threshold = framework.context.auto_accept_confidence
    except Exception:
        pass  # Use default threshold

    pending: list[ContextPromptRequest] = []
    auto_accepted_keys: list[str] = []

    for key, (definition, detect_pipeline) in definitions_with_detect.items():
        # Skip if already confirmed (check both definition key and store_as target)
        if key in confirmed_keys:
            continue
        if definition.store_as and definition.store_as in confirmed_keys:
            continue

        # Determine affected controls
        affected = definition.affects
        if control_ids:
            # Filter to only specified controls
            affected = [c for c in affected if c in control_ids]

        if not affected:
            continue

        # Auto-detect value using handler pipeline or context sieve
        current_value = None
        if detect_pipeline:
            # Primary: handler-based detection from TOML detect pipeline
            current_value = _run_detect_pipeline(key, detect_pipeline, local_path, owner, repo)
        if current_value is None and definition.auto_detect:
            # Fallback: context sieve (hardcoded Python detectors)
            current_value = _try_sieve_detection(key, local_path, owner, repo)

        # Feature 039 (#165, #150): apply the key's detect_filter here, where
        # both detection routes have converged, and BEFORE the auto-accept
        # threshold below. Filtering inside each route separately would be two
        # call sites to keep in step, and the sieve fallback is the older path
        # most likely to be forgotten. Filtering after the threshold would
        # already have written the rejected value.
        if current_value is not None:
            current_value = _apply_detect_filter(key, definition, current_value)

        # Auto-accept high-confidence detections without user prompting
        if current_value is not None and current_value.confidence >= auto_accept_threshold:
            current_value.auto_accepted = True
            auto_accepted_keys.append(key)
            logger.debug(
                "Auto-accepted context '%s' (confidence: %.0f%%, threshold: %.0f%%)",
                key,
                current_value.confidence * 100,
                auto_accept_threshold * 100,
            )
            # Save auto-accepted value directly
            try:
                save_context_value(
                    local_path,
                    key,
                    current_value.value,
                    source=ContextSource.AUTO_DETECTED,
                    detection_method=current_value.detection_method,
                    confidence=current_value.confidence,
                )
            except Exception as e:
                logger.debug("Failed to save auto-accepted '%s': %s", key, e)
                # Fall through to pending if save fails
                current_value.auto_accepted = False
                auto_accepted_keys.pop()

        if key not in auto_accepted_keys:
            pending.append(
                ContextPromptRequest(
                    key=key,
                    definition=definition,
                    control_ids=affected,
                    current_value=current_value,
                    priority=len(affected),  # Priority = number of controls affected
                )
            )

    if auto_accepted_keys:
        logger.info(
            "Auto-accepted %d context field(s): %s",
            len(auto_accepted_keys),
            ", ".join(auto_accepted_keys),
        )

    # Sort by priority (highest first)
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

    Stops at the first handler that produces a usable result.

    Args:
        key: Context key being detected (e.g., "maintainers")
        detect_pipeline: List of HandlerInvocation objects from TOML
        local_path: Path to the repository
        owner: GitHub owner (optional)
        repo: GitHub repo name (optional)

    Returns:
        ContextValue with auto-detected value if found, None otherwise
    """
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

            # Non-PASS: apply value_if_fail as a stable fallback if the TOML
            # author set one. Short-circuits the chain -- subsequent handlers
            # are not tried. This is the mechanism that makes flaky network
            # detectors (e.g., `gh release list`) produce a deterministic
            # false rather than a missing key when they can't conclude.
            if result.status in (
                HandlerResultStatus.FAIL,
                HandlerResultStatus.INCONCLUSIVE,
                HandlerResultStatus.ERROR,
            ):
                value_if_fail = handler_config.get("value_if_fail")
                if value_if_fail is not None:
                    return ContextValue.auto_detected(
                        value=value_if_fail,
                        method=f"detect_pipeline:{invocation.handler}:fail_fallback",
                        # Handlers that FAIL / ERROR / INCONCLUSIVE frequently
                        # leave confidence unset (None); fall back to
                        # auto_detected's own default rather than passing None
                        # into a numeric comparison.
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
