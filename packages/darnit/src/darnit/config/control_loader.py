"""Convert TOML configuration to executable ControlSpec objects.

This module bridges the declarative configuration (TOML) with the executable
sieve system (ControlSpec and pass objects).

Example:
    from darnit.config.control_loader import load_controls_from_config
    from darnit.config.merger import load_effective_config_by_name

    # Load and merge configs
    config = load_effective_config_by_name("openssf-baseline", Path("/path/to/repo"))

    # Convert to executable ControlSpec objects
    controls = load_controls_from_config(config)

    # Register with sieve
    for control in controls:
        register_control(control)
"""

from collections.abc import Callable
from pathlib import Path
from typing import Any

from darnit.core.logging import get_logger
from darnit.sieve.models import (
    ControlSpec,
)

from .framework_schema import (
    ControlConfig,
    FrameworkConfig,
    HandlerInvocation,
    OnPassConfig,
    SharedHandlerConfig,
)
from .merger import EffectiveConfig, EffectiveControl

logger = get_logger("config.control_loader")


# =============================================================================
# Handler Invocation Resolution (load-time)
# =============================================================================


def _step_declarations(invocation: HandlerInvocation) -> dict[str, Any]:
    """Declared (non-handler-config) fields to carry across a rebuild."""
    return {
        name: getattr(invocation, name)
        for name in HandlerInvocation.model_fields
        if name not in ("handler", "shared", "use_locator") and name in invocation.model_fields_set
    }


def _resolve_shared_handler(
    invocation: HandlerInvocation,
    shared_handlers: dict[str, SharedHandlerConfig],
) -> HandlerInvocation:
    """Resolve a shared handler reference by merging configs.

    The shared handler provides base config. Per-control overrides take precedence.

    Args:
        invocation: Handler invocation that may reference a shared handler
        shared_handlers: Top-level shared handler definitions

    Returns:
        Resolved HandlerInvocation with merged config
    """
    if not invocation.shared:
        return invocation

    shared = shared_handlers.get(invocation.shared)
    if not shared:
        logger.warning(
            "Shared handler '%s' not found in [shared_handlers]",
            invocation.shared,
        )
        return invocation

    # Start with shared handler's extra fields
    merged = dict(shared.model_extra or {})
    # Per-control fields override shared ones
    merged.update(invocation.model_extra or {})

    # Handler name: invocation overrides if set, else use shared's
    handler = invocation.handler if invocation.handler != invocation.shared else shared.handler

    return HandlerInvocation(
        handler=handler,
        shared=invocation.shared,
        use_locator=invocation.use_locator,
        **{**merged, **_step_declarations(invocation)},
    )


def _resolve_use_locator(
    invocation: HandlerInvocation,
    locator_discover: list[str] | None,
    control_id: str,
) -> HandlerInvocation:
    """Resolve use_locator=true by copying locator.discover into files.

    Args:
        invocation: Handler invocation with use_locator=True
        locator_discover: The discover list from LocatorConfig
        control_id: For logging context

    Returns:
        HandlerInvocation with files populated from locator
    """
    if not invocation.use_locator:
        return invocation

    if not locator_discover:
        logger.warning(
            "Control %s: use_locator=true but locator.discover is empty",
            control_id,
        )
        return invocation

    # Copy discover list into handler's files parameter
    extra = dict(invocation.model_extra or {})
    if "files" not in extra:
        extra["files"] = locator_discover

    return HandlerInvocation(
        handler=invocation.handler,
        shared=invocation.shared,
        use_locator=True,
        **extra,
        **_step_declarations(invocation),
    )


def _resolve_handler_invocations(
    invocations: list[HandlerInvocation],
    shared_handlers: dict[str, SharedHandlerConfig],
    locator_discover: list[str] | None,
    control_id: str,
) -> list[HandlerInvocation]:
    """Resolve all handler invocations at load time.

    Applies shared handler merging and use_locator resolution.
    """
    resolved = []
    for inv in invocations:
        inv = _resolve_shared_handler(inv, shared_handlers)
        inv = _resolve_use_locator(inv, locator_discover, control_id)
        resolved.append(inv)
    return resolved


def _auto_derive_on_pass(control_config: ControlConfig) -> OnPassConfig | None:
    """Auto-derive on_pass when conditions are met.

    Conditions:
    - Control has locator.project_path
    - Control has a file_exists handler in its passes list
    - Control has no explicit on_pass

    Returns:
        Generated OnPassConfig, or None if conditions aren't met
    """
    if control_config.on_pass:
        return None  # Explicit on_pass takes precedence

    locator = control_config.locator
    if not locator or not locator.project_path:
        return None

    passes = control_config.passes
    if not passes:
        return None

    # Check for file_exists handler in flat list
    for inv in passes:
        if isinstance(inv, HandlerInvocation) and inv.handler == "file_exists":
            return OnPassConfig(
                project_update={locator.project_path: "$EVIDENCE.relative_path"}
            )

    return None


def _validate_control_references(
    controls: dict[str, ControlConfig],
) -> None:
    """Validate depends_on and inferred_from references at load time.

    Warns on references to unknown control IDs.
    """
    control_ids = set(controls.keys())

    for control_id, config in controls.items():
        if config.depends_on:
            for dep_id in config.depends_on:
                if dep_id not in control_ids:
                    logger.warning(
                        "Control %s: depends_on references unknown control '%s'",
                        control_id,
                        dep_id,
                    )

        if config.inferred_from:
            if config.inferred_from not in control_ids:
                logger.warning(
                    "Control %s: inferred_from references unknown control '%s'",
                    control_id,
                    config.inferred_from,
                )


# =============================================================================
# Control Converter
# =============================================================================


def control_from_effective(
    control_id: str,
    effective: EffectiveControl,
    framework: str | None = None,
    source: str | None = None,
) -> ControlSpec:
    """Convert EffectiveControl to ControlSpec.

    Args:
        control_id: Control identifier
        effective: Merged effective control
        framework: Framework name, for load-time validation errors
        source: Framework file, for load-time validation errors

    Returns:
        Executable ControlSpec
    """
    # Build the tags dict - effective.tags already includes level/domain from merger
    tags = dict(effective.tags) if effective.tags else {}

    # Extract level/domain/security_severity from tags if not present as top-level
    # This supports the new flexible schema where everything can be in tags
    level = effective.level
    if level is None and "level" in tags:
        level = tags["level"]

    domain = effective.domain
    if domain is None and "domain" in tags:
        domain = tags["domain"]

    security_severity = effective.security_severity
    if security_severity is None and "security_severity" in tags:
        security_severity = tags["security_severity"]

    metadata: dict = {
        "security_severity": security_severity,
        "docs_url": effective.docs_url,
        "check_adapter": effective.check_adapter,
        "remediation_adapter": effective.remediation_adapter,
    }

    if effective.when:
        metadata["when"] = effective.when
    if effective.depends_on:
        metadata["depends_on"] = effective.depends_on
    if effective.inferred_from:
        metadata["inferred_from"] = effective.inferred_from
    if effective.on_pass:
        metadata["on_pass"] = effective.on_pass

    # Transfer handler invocations from effective passes_config to metadata
    if effective.passes_config:
        from darnit.config.framework_schema import HandlerInvocation
        metadata["handler_invocations"] = [
            HandlerInvocation(**p) if isinstance(p, dict) else p
            for p in effective.passes_config
        ]
        validate_step_authority(
            framework,
            control_id,
            metadata["handler_invocations"],
            source=None if effective.steps_from_operator else source,
            operator_supplied=effective.steps_from_operator,
        )

    return ControlSpec(
        control_id=control_id,
        level=level,
        domain=domain,
        name=effective.name,
        description=effective.description,
        tags=tags,  # Pass tags directly, ControlSpec.__post_init__ will add level/domain
        metadata=metadata,
    )


def control_from_framework(
    control_id: str,
    control_config: Any,  # ControlConfig from framework_schema
    shared_handlers: dict[str, SharedHandlerConfig] | None = None,
    framework: str | None = None,
    source: str | None = None,
) -> ControlSpec:
    """Convert ControlConfig from framework to ControlSpec.

    Performs load-time resolution of:
    - Shared handler references (merged with per-control overrides)
    - use_locator=true (copies locator.discover into handler files)
    - Auto-derived on_pass (from locator.project_path + file_exists handler)

    Args:
        control_id: Control identifier
        control_config: Framework control configuration
        shared_handlers: Top-level shared handler definitions for resolution
        framework: Framework name, for load-time validation errors
        source: Framework file, for load-time validation errors

    Returns:
        Executable ControlSpec
    """
    shared_handlers = shared_handlers or {}

    # Resolve handler invocations at load time
    locator_discover = None
    if hasattr(control_config, "locator") and control_config.locator:
        locator_discover = control_config.locator.discover or None

    if control_config.passes:
        control_config.passes = _resolve_handler_invocations(
            control_config.passes, shared_handlers, locator_discover, control_id
        )

    # Build tags dict from config - tags is now Dict[str, Any]
    tags = dict(control_config.tags) if control_config.tags else {}

    # Extract level/domain/security_severity from tags if not present as top-level
    level = control_config.level
    if level is None and "level" in tags:
        level = tags["level"]

    domain = control_config.domain
    if domain is None and "domain" in tags:
        domain = tags["domain"]

    security_severity = control_config.security_severity
    if security_severity is None and "security_severity" in tags:
        security_severity = tags["security_severity"]

    # Build metadata dict
    metadata: dict = {
        "security_severity": security_severity,
        "docs_url": control_config.docs_url,
    }

    # Carry on_pass config through metadata for the orchestrator
    # Auto-derive if conditions are met
    on_pass = getattr(control_config, "on_pass", None)
    if not on_pass:
        on_pass = _auto_derive_on_pass(control_config)
    if on_pass:
        metadata["on_pass"] = on_pass

    # Carry new control fields through metadata for the orchestrator
    if hasattr(control_config, "when") and control_config.when:
        metadata["when"] = control_config.when
    if hasattr(control_config, "depends_on") and control_config.depends_on:
        metadata["depends_on"] = control_config.depends_on
    if hasattr(control_config, "inferred_from") and control_config.inferred_from:
        metadata["inferred_from"] = control_config.inferred_from

    # Carry handler invocations through metadata for orchestrator dispatch
    if control_config.passes:
        validate_step_authority(framework, control_id, control_config.passes, source=source)
        metadata["handler_invocations"] = control_config.passes

    # Carry remediation handler invocations if present
    if hasattr(control_config, "remediation") and control_config.remediation:
        rem = control_config.remediation
        if rem.handlers:
            validate_remediation_steps(framework, control_id, rem.handlers, source=source)
            metadata["remediation_handler_invocations"] = rem.handlers

    return ControlSpec(
        control_id=control_id,
        level=level,
        domain=domain,
        name=control_config.name,
        description=control_config.description,
        tags=tags,
        metadata=metadata,
    )


# =============================================================================
# Main Loading Functions
# =============================================================================


def load_controls_from_effective(config: EffectiveConfig) -> list[ControlSpec]:
    """Load ControlSpec objects from effective configuration.

    This is the main entry point for loading controls from merged
    framework + user configuration.

    Controls a repository claims are not applicable are still loaded: the
    claim is the repository's assertion, which the audit reports alongside
    the control's result (feature 040).

    Args:
        config: Merged effective configuration

    Returns:
        List of executable ControlSpec objects
    """
    controls = []
    framework_config = config._framework_config
    source = framework_config._source_path if framework_config is not None else None

    for control_id, effective in config.controls.items():
        try:
            control = control_from_effective(control_id, effective, framework=config.framework_name, source=source)
            controls.append(control)
        except (TypeError, ValueError, KeyError) as e:
            logger.warning(f"Could not load control {control_id}: {e}")
            continue
        framework_control = framework_config.controls.get(control_id) if framework_config is not None else None
        if effective.from_framework and framework_control is not None and framework_control.remediation:
            validate_remediation_steps(
                config.framework_name, control_id, framework_control.remediation.handlers, source=source
            )

    return controls


def load_controls_from_framework(config: FrameworkConfig) -> list[ControlSpec]:
    """Load ControlSpec objects directly from framework configuration.

    Use this when you want framework controls without user customization.
    Performs load-time validation and resolution of shared handlers,
    use_locator, on_pass auto-derivation, and reference validation.

    Args:
        config: Framework configuration

    Returns:
        List of executable ControlSpec objects
    """
    # Validate depends_on and inferred_from references
    _validate_control_references(config.controls)

    shared_handlers = config.shared_handlers or {}
    controls = []

    for control_id, control_config in config.controls.items():
        try:
            control = control_from_framework(
                control_id,
                control_config,
                shared_handlers=shared_handlers,
                framework=config.metadata.name,
                source=config._source_path,
            )
            controls.append(control)
        except (TypeError, ValueError, KeyError) as e:
            logger.warning(f"Could not load control {control_id}: {e}")

    return controls


def load_controls_from_toml(
    framework_path: Path,
    repo_path: Path | None = None,
) -> list[ControlSpec]:
    """Load controls from TOML files.

    Convenience function that loads framework TOML, optionally merges
    with user .baseline.toml, and returns executable controls.

    Args:
        framework_path: Path to framework TOML file
        repo_path: Path to repository (for .baseline.toml)

    Returns:
        List of executable ControlSpec objects
    """
    from .merger import load_effective_config

    config = load_effective_config(framework_path, repo_path)
    return load_controls_from_effective(config)


def load_controls_by_name(
    framework_name: str,
    repo_path: Path | None = None,
) -> list[ControlSpec]:
    """Load controls by framework name.

    Resolves framework via entry points, merges with user config,
    and returns executable controls.

    Args:
        framework_name: Framework identifier (e.g., "openssf-baseline")
        repo_path: Path to repository (for .baseline.toml)

    Returns:
        List of executable ControlSpec objects

    Raises:
        ValueError: If framework not found
    """
    from .merger import load_effective_config_by_name

    config = load_effective_config_by_name(framework_name, repo_path)
    return load_controls_from_effective(config)


# =============================================================================
# Registration Helper
# =============================================================================


def register_controls_from_config(
    config: EffectiveConfig,
    registry_func: Callable[[ControlSpec], None] | None = None,
) -> int:
    """Load controls from config and register them.

    Args:
        config: Effective configuration
        registry_func: Function to register each control
            (defaults to sieve.registry.register_control)

    Returns:
        Number of controls registered
    """
    if registry_func is None:
        from darnit.sieve.registry import register_control

        registry_func = register_control

    controls = load_controls_from_effective(config)

    for control in controls:
        registry_func(control)

    return len(controls)


# =============================================================================
# Feature 041: step authority validation (contracts/step-declarations.md)
# =============================================================================

_LEGACY_AUTHORITIES = frozenset(("dispositive", "suggestive", "asserted"))

# Feature 044 (framework-design 3.0.3): accepted on every step, whatever its
# step type declares.
COMMON_STEP_FIELDS = frozenset(HandlerInvocation.model_fields) | {"description", "expr"}

# Plugin step types already reported as not declaring their settings, so
# each is reported once per process.
_UNCHECKED_SETTINGS_WARNED: set[str] = set()


def _registered_step_type(registry: Any, handler: str, framework: str | None) -> Any:
    """The registered step type, registering ``framework``'s own plugin step types first if it is missing.

    Validation runs after plugin step types register (framework-design
    3.0.3); a caller that loads a framework before registering its plugin
    must not see that plugin's step types reported as unregistered.
    """
    info = registry.get(handler)
    if info is None and framework:
        from darnit.core.discovery import register_implementation_handlers

        if register_implementation_handlers(framework):
            info = registry.get(handler)
    return info


def _where(framework: str | None, source: str | None) -> str:
    where = f"framework {framework or '<unknown>'!r}"
    return f"{where} (file {source})" if source else where


def _validate_step_keys(inv: HandlerInvocation, info: Any, reject: Callable[[str], None]) -> None:
    """A step key must be a common step field or one its step type declares (feature 044, FR-008)."""
    if info.settings is None:
        if info.name not in _UNCHECKED_SETTINGS_WARNED:
            _UNCHECKED_SETTINGS_WARNED.add(info.name)
            logger.warning(
                "Settings for step type %r (plugin %r) are not checked: it does not declare them",
                info.name,
                info.plugin or "core",
            )
        return
    unknown = sorted(set(inv.model_extra or {}) - COMMON_STEP_FIELDS - info.settings)
    if unknown:
        accepted = ", ".join(sorted(info.settings)) or "none"
        reject(
            f"unknown step key {', '.join(repr(k) for k in unknown)} for step type {inv.handler!r}; "
            f"correct or remove it (its settings: {accepted}; plus the common step fields)"
        )


def validate_remediation_steps(
    framework: str | None, control_id: str, handlers: list, *, source: str | None = None
) -> None:
    """Remediation steps name a registered step type and only keys it accepts (feature 044, framework-design 3.0.3)."""
    from darnit.core.errors import AuthorityViolation
    from darnit.sieve.handler_registry import get_sieve_handler_registry

    registry = get_sieve_handler_registry()
    where = _where(framework, source)
    for idx, inv in enumerate(handlers):
        step_id = f"remediation[{idx}]:{inv.handler}"

        def reject(message: str, _step_id: str = step_id) -> None:
            raise AuthorityViolation(control_id=control_id, step_id=_step_id, message=f"{where}: {message}")

        info = _registered_step_type(registry, inv.handler, framework)
        if info is None:
            reject(f"step type {inv.handler!r} is not registered")
        _validate_step_keys(inv, info, reject)


def validate_step_authority(
    framework: str | None,
    control_id: str,
    invocations: list,
    *,
    source: str | None = None,
    operator_supplied: bool = False,
) -> None:
    """Reject step declarations that break the per-claim authority rules.

    Called from every control-loading path (``control_from_framework`` and
    ``control_from_effective``) after plugin handlers register. Raises
    ``AuthorityViolation`` naming the framework (and ``source`` file),
    control, step index, and outcome.

    Feature 044 (framework-design 3.0.3): it also rejects a step type that
    is not registered, a step key outside the common step fields and the
    step type's declared settings, and an ``expr`` its step type cannot
    take. For ``operator_supplied`` steps (operator custom controls and
    pass overrides) an unregistered step type loads instead: the
    orchestrator reports it ERROR, class ``missing_tool``, at dispatch.
    """
    from darnit.core.errors import AuthorityViolation
    from darnit.sieve.handler_registry import HandlerPhase, effective_outcomes, get_sieve_handler_registry

    registry = get_sieve_handler_registry()
    where = _where(framework, source)

    for idx, inv in enumerate(invocations):
        step_id = f"pass[{idx}]:{inv.handler}"

        def reject(message: str, _step_id: str = step_id) -> None:
            raise AuthorityViolation(control_id=control_id, step_id=_step_id, message=f"{where}: {message}")

        info = _registered_step_type(registry, inv.handler, framework)
        if info is None:
            if operator_supplied:
                continue
            reject(f"step type {inv.handler!r} is not registered")
        _validate_step_keys(inv, info, reject)

        existence = bool(getattr(inv, "existence", False))
        if existence and info.existence_ceiling is None:
            reject(f"existence = true is only for presence and pattern steps; {inv.handler!r} has no existence ceiling")
        ceiling = info.existence_ceiling if existence else info.ceiling

        legacy = getattr(inv, "authority", None)
        if legacy is not None:
            if legacy not in _LEGACY_AUTHORITIES:
                reject(f"step declares authority={legacy!r} which is not one of {sorted(_LEGACY_AUTHORITIES)!r}")
            if legacy == "asserted":
                reject("step declares authority='asserted'; asserted is a person's confirmation, not a step type")
            if legacy == "dispositive" and not ceiling:
                reject(f"step declares authority='dispositive' but {inv.handler!r} may not conclude any outcome")

        promotion = getattr(inv, "promotion", None)
        if promotion is not None and info.phase == HandlerPhase.LLM:
            reject(f"outcome {promotion.outcome!r}: a model judgment is never promoted to conclude it")
        promoted = {promotion.outcome} if promotion is not None else set()
        for outcome in getattr(inv, "concludes", None) or []:
            if outcome not in ceiling and outcome not in promoted:
                reject(
                    f"outcome {outcome!r} is outside the {inv.handler!r} ceiling {sorted(ceiling)} "
                    "and the step records no promotion for it"
                )

        if getattr(inv, "fail_on_miss", False):
            if inv.handler not in ("regex", "pattern"):
                reject(f"fail_on_miss is only for pattern steps, not {inv.handler!r}")
            if "fail" not in effective_outcomes(info, inv):
                reject("fail_on_miss requires outcome 'fail' in the step's effective set")

        if getattr(inv, "fail_on_status", None) is not None:
            if inv.handler != "gh_api":
                reject(f"fail_on_status is only for gh_api steps, not {inv.handler!r}")
            if "fail" not in effective_outcomes(info, inv):
                reject("fail_on_status requires outcome 'fail' in the step's effective set")

        expr = (getattr(inv, "model_extra", None) or {}).get("expr")
        if expr is not None:
            _validate_expression_references(inv.handler, str(expr), info.expression_names, reject)

        if getattr(inv, "expr_decides", False):
            _validate_expr_decides(inv.handler, expr, info.expression_names, reject)

        if inv.handler == "gh_api":
            _validate_evidence_fields(inv.model_extra or {}, reject)


def _validate_expr_decides(
    handler: str, expr: Any, provided: frozenset[str], reject: Callable[[str], None]
) -> None:
    """``expr_decides`` needs an expression the orchestrator evaluates (feature 044, FR-015, framework-design 3.7)."""
    from darnit.sieve.orchestrator import STEP_TYPES_EVALUATING_OWN_EXPR

    if not provided:
        reject(f"expr_decides is set but step type {handler!r} does not accept expr")
    if handler in STEP_TYPES_EVALUATING_OWN_EXPR:
        reject(f"expr_decides is not needed on {handler!r}: its expr already decides; remove it")
    if expr is None:
        reject("expr_decides is set but the step has no expr")


def _validate_evidence_fields(step: dict[str, Any], reject: Callable[[str], None]) -> None:
    """A gh_api step reading a person's account keeps only declared fields (feature 044, framework-design 3.8)."""
    fields = step.get("evidence_fields")
    if fields is not None and not (isinstance(fields, list) and all(isinstance(f, str) for f in fields)):
        reject(f"evidence_fields must be a list of response body keys, not {fields!r}")
    endpoint = "/" + str(step.get("endpoint", "")).split("?", 1)[0].lstrip("/")
    if fields is None and (endpoint == "/user" or endpoint.startswith(("/user/", "/users/"))):
        reject(
            f"endpoint {endpoint!r} reads a person's account; declare evidence_fields listing only "
            "the response fields the check needs"
        )


def _validate_expression_references(
    handler: str, expr: str, provided: frozenset[str], reject: Callable[[str], None]
) -> None:
    """An ``expr`` may use only the names its step type provides (feature 044, framework-design 3.7)."""
    from darnit.sieve.cel_evaluator import CELCompilationError, expression_free_names

    if not provided:
        reject(f"step type {handler!r} does not accept expr")
    try:
        names = expression_free_names(expr)
    except CELCompilationError as e:
        reject(f"expr {expr!r} does not compile: {e}")
        return
    undeclared = sorted(names - provided)
    if undeclared:
        reject(
            f"expr references {', '.join(repr(n) for n in undeclared)}, which step type {handler!r} "
            f"does not provide (it provides {', '.join(sorted(provided))})"
        )
