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

import importlib
from collections.abc import Callable
from importlib.metadata import entry_points
from pathlib import Path
from typing import Any

from darnit.core.logging import get_logger
from darnit.sieve.models import (
    ControlSpec,
)
from darnit.sieve.passes import (
    DeterministicPass,
    ExecPass,
    LLMPass,
    ManualPass,
    PatternPass,
)

from .framework_schema import (
    ControlConfig,
    DeterministicPassConfig,
    ExecPassConfig,
    FrameworkConfig,
    HandlerInvocation,
    LLMPassConfig,
    ManualPassConfig,
    OnPassConfig,
    PassesConfig,
    PatternPassConfig,
    SharedHandlerConfig,
)
from .merger import EffectiveConfig, EffectiveControl

logger = get_logger("config.control_loader")


# =============================================================================
# Module Import Security
# =============================================================================

# Base allowlist - always allowed
_BASE_ALLOWED_PREFIXES = (
    "darnit.",
    "darnit_baseline.",
    "darnit_plugins.",
    "darnit_testchecks.",
)

# Cache for dynamically discovered prefixes
_discovered_prefixes: set[str] | None = None


def _get_allowed_module_prefixes() -> tuple[str, ...]:
    """Get allowed module prefixes, including registered plugins.

    Combines the base allowlist with prefixes from all registered
    entry points in darnit.* groups. This allows third-party plugins
    to register their modules as trusted.

    Returns:
        Tuple of allowed module prefixes (e.g., ("darnit.", "darnit_baseline."))
    """
    global _discovered_prefixes

    if _discovered_prefixes is None:
        _discovered_prefixes = set(_BASE_ALLOWED_PREFIXES)

        # Discover prefixes from registered entry points
        for group in (
            "darnit.implementations",
            "darnit.frameworks",
            "darnit.check_adapters",
            "darnit.remediation_adapters",
        ):
            try:
                eps = entry_points(group=group)
                for ep in eps:
                    # Entry point value is "package.module:function"
                    module_path = ep.value.split(":")[0]
                    package_name = module_path.split(".")[0]
                    _discovered_prefixes.add(f"{package_name}.")
            except Exception:
                pass  # Entry point group might not exist

    return tuple(_discovered_prefixes)


def _is_module_allowed(module_path: str) -> bool:
    """Check if a module path is in the allowed allowlist.

    Args:
        module_path: Full module path (e.g., "darnit_baseline.controls.level2")

    Returns:
        True if the module is allowed to be imported
    """
    allowed = _get_allowed_module_prefixes()
    return module_path.startswith(allowed)


# =============================================================================
# Pass Converters
# =============================================================================


def _resolve_check_function(reference: str) -> Callable | None:
    """Resolve a handler reference to a callable.

    Supports three resolution strategies (in order):
    1. Short name lookup: Check the handler registry for registered handlers
       - e.g., "check_branch_protection" → registered handler function
    2. Module:function path: Load from allowlisted module path
       - e.g., "darnit_baseline.controls.level2:_create_changelog_check"
    3. Factory pattern: If the resolved function can be called with no args
       and returns a callable, use the returned callable

    Security: Only allows loading modules from allowlisted prefixes
    to prevent arbitrary code execution from malicious TOML files.
    The allowlist includes base darnit packages plus any packages
    registered via entry points.

    Args:
        reference: Handler short name or "module:function" path

    Returns:
        The resolved function, or None if resolution fails
    """
    if not reference:
        logger.warning("Empty check function reference")
        return None

    # Strategy 1: Check handler registry for short names (no colon) first
    if ":" not in reference:
        from darnit.core.handlers import get_handler

        handler = get_handler(reference)
        if handler is not None:
            logger.debug(f"Resolved handler '{reference}' from registry")
            return handler

    # Strategy 2: Parse as module:function path
    if ":" not in reference:
        logger.warning(
            f"Handler '{reference}' not found in registry and not a module:function path. "
            f"Register it with @register_handler or use full module:function syntax."
        )
        return None

    module_path, func_name = reference.rsplit(":", 1)

    # Security: Validate module path against allowlist
    if not _is_module_allowed(module_path):
        logger.warning(
            f"Blocked import of '{module_path}': not in allowed module prefixes. "
            f"Register your plugin via entry points to allow imports."
        )
        return None

    try:
        module = importlib.import_module(module_path)
        func = getattr(module, func_name)

        if not callable(func):
            logger.warning(f"Reference {reference} is not callable")
            return None

        # Try calling the function to see if it's a factory
        # Factory functions have no required parameters and return a callable
        try:
            import inspect

            sig = inspect.signature(func)
            # Check if all parameters have defaults (i.e., can be called with no args)
            can_call_no_args = all(
                p.default is not inspect.Parameter.empty
                or p.kind in (inspect.Parameter.VAR_POSITIONAL, inspect.Parameter.VAR_KEYWORD)
                for p in sig.parameters.values()
            )

            if can_call_no_args:
                result = func()
                if callable(result):
                    logger.debug(f"Resolved factory function {reference} -> {result}")
                    return result

            # Not a factory, return the function itself
            logger.debug(f"Resolved direct function {reference}")
            return func

        except (TypeError, ValueError):
            # If we can't inspect or call, just return the function
            return func

    except ImportError as e:
        logger.warning(f"Could not import module for check function {reference}: {e}")
        return None
    except AttributeError as e:
        logger.warning(f"Function not found in module for {reference}: {e}")
        return None


def _convert_deterministic_pass(config: DeterministicPassConfig) -> DeterministicPass:
    """Convert DeterministicPassConfig to DeterministicPass.

    Args:
        config: Declarative pass configuration

    Returns:
        Executable DeterministicPass
    """
    # Resolve function references for api_check and config_check
    api_check = _resolve_check_function(config.api_check) if config.api_check else None
    config_check = _resolve_check_function(config.config_check) if config.config_check else None

    return DeterministicPass(
        file_must_exist=config.file_must_exist,
        file_must_not_exist=config.file_must_not_exist,
        api_check=api_check,
        config_check=config_check,
    )


def _convert_exec_pass(config: ExecPassConfig) -> ExecPass:
    """Convert ExecPassConfig to ExecPass.

    Args:
        config: Declarative pass configuration

    Returns:
        Executable ExecPass
    """
    return ExecPass(
        command=list(config.command),
        pass_exit_codes=list(config.pass_exit_codes),
        fail_exit_codes=list(config.fail_exit_codes) if config.fail_exit_codes else None,
        output_format=config.output_format,
        pass_if_output_matches=config.pass_if_output_matches,
        fail_if_output_matches=config.fail_if_output_matches,
        pass_if_json_path=config.pass_if_json_path,
        pass_if_json_value=config.pass_if_json_value,
        timeout=config.timeout,
        cwd=config.cwd,
        env=dict(config.env) if config.env else {},
    )


def _convert_pattern_pass(config: PatternPassConfig) -> PatternPass:
    """Convert PatternPassConfig to PatternPass.

    Args:
        config: Declarative pass configuration

    Returns:
        Executable PatternPass
    """
    return PatternPass(
        file_patterns=config.files,
        content_patterns=dict(config.patterns) if config.patterns else None,
        pass_if_any_match=config.pass_if_any_match,
        fail_if_no_match=config.fail_if_no_match,
        # Note: custom_analyzer requires function resolution
    )


def _convert_llm_pass(config: LLMPassConfig) -> LLMPass:
    """Convert LLMPassConfig to LLMPass.

    Args:
        config: Declarative pass configuration

    Returns:
        Executable LLMPass
    """
    prompt = config.prompt or ""
    if config.prompt_file:
        # Load prompt from file if specified
        try:
            prompt_path = Path(config.prompt_file)
            if prompt_path.exists():
                prompt = prompt_path.read_text()
        except OSError as e:
            logger.warning(f"Could not load prompt file {config.prompt_file}: {e}")

    return LLMPass(
        prompt_template=prompt,
        files_to_include=config.files_to_include,
        analysis_hints=list(config.hints),
        confidence_threshold=config.confidence_threshold,
    )


def _convert_manual_pass(config: ManualPassConfig) -> ManualPass:
    """Convert ManualPassConfig to ManualPass.

    Args:
        config: Declarative pass configuration

    Returns:
        Executable ManualPass
    """
    return ManualPass(
        verification_steps=list(config.steps),
        verification_docs_url=config.docs_url,
    )


# =============================================================================
# Handler Invocation Resolution (load-time)
# =============================================================================


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
        **merged,
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
    - Control has a deterministic file_exists handler (new format)
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

    # Check for file_exists handler in new format
    det = passes.deterministic
    if isinstance(det, list):
        for inv in det:
            if isinstance(inv, HandlerInvocation) and inv.handler == "file_exists":
                return OnPassConfig(
                    project_update={locator.project_path: "$EVIDENCE.relative_path"}
                )

    # Check for file_must_exist in legacy format
    if isinstance(det, DeterministicPassConfig) and det.file_must_exist:
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


def _convert_passes_config(passes_config: PassesConfig | None) -> list[Any]:
    """Convert PassesConfig to list of executable pass objects.

    Handles both legacy typed configs (converted to pass objects) and
    new handler invocation lists (passed through as-is for orchestrator dispatch).

    Args:
        passes_config: Declarative passes configuration

    Returns:
        List of pass objects in execution order
    """
    if not passes_config:
        return []

    passes = []

    # Order: deterministic -> exec -> pattern -> llm -> manual
    det = passes_config.deterministic
    if det is not None:
        if isinstance(det, DeterministicPassConfig):
            passes.append(_convert_deterministic_pass(det))
        # Handler invocation lists are dispatched by the orchestrator directly

    if passes_config.exec:
        passes.append(_convert_exec_pass(passes_config.exec))

    pat = passes_config.pattern
    if pat is not None:
        if isinstance(pat, PatternPassConfig):
            passes.append(_convert_pattern_pass(pat))

    llm_val = passes_config.llm
    if llm_val is not None:
        if isinstance(llm_val, LLMPassConfig):
            passes.append(_convert_llm_pass(llm_val))

    man = passes_config.manual
    if man is not None:
        if isinstance(man, ManualPassConfig):
            passes.append(_convert_manual_pass(man))

    return passes


def control_from_effective(
    control_id: str,
    effective: EffectiveControl,
) -> ControlSpec:
    """Convert EffectiveControl to ControlSpec.

    Args:
        control_id: Control identifier
        effective: Merged effective control

    Returns:
        Executable ControlSpec
    """
    # Convert passes_config back to PassesConfig if it's a dict
    passes = []
    if effective.passes_config:
        try:
            passes_config = PassesConfig(**effective.passes_config)
            passes = _convert_passes_config(passes_config)
        except (TypeError, ValueError) as e:
            logger.warning(f"Could not convert passes for {control_id}: {e}")

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

    return ControlSpec(
        control_id=control_id,
        level=level,
        domain=domain,
        name=effective.name,
        description=effective.description,
        passes=passes,
        tags=tags,  # Pass tags directly, ControlSpec.__post_init__ will add level/domain
        metadata={
            "security_severity": security_severity,
            "docs_url": effective.docs_url,
            "check_adapter": effective.check_adapter,
            "remediation_adapter": effective.remediation_adapter,
        },
    )


def control_from_framework(
    control_id: str,
    control_config: Any,  # ControlConfig from framework_schema
    shared_handlers: dict[str, SharedHandlerConfig] | None = None,
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

    Returns:
        Executable ControlSpec
    """
    shared_handlers = shared_handlers or {}

    # Resolve handler invocations at load time
    locator_discover = None
    if hasattr(control_config, "locator") and control_config.locator:
        locator_discover = control_config.locator.discover or None

    if control_config.passes:
        _resolve_passes_invocations(
            control_config.passes, shared_handlers, locator_discover, control_id
        )

    passes = _convert_passes_config(control_config.passes) if control_config.passes else []

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
        handler_invocations = control_config.passes.get_handler_invocations()
        if handler_invocations:
            metadata["handler_invocations"] = handler_invocations

    # Carry remediation handler invocations if present
    if hasattr(control_config, "remediation") and control_config.remediation:
        rem = control_config.remediation
        if hasattr(rem, "get_handler_invocations"):
            rem_invocations = rem.get_handler_invocations()
            if rem_invocations:
                metadata["remediation_handler_invocations"] = rem_invocations

    return ControlSpec(
        control_id=control_id,
        level=level,
        domain=domain,
        name=control_config.name,
        description=control_config.description,
        passes=passes,
        tags=tags,
        metadata=metadata,
    )


def _resolve_passes_invocations(
    passes_config: PassesConfig,
    shared_handlers: dict[str, SharedHandlerConfig],
    locator_discover: list[str] | None,
    control_id: str,
) -> None:
    """Resolve handler invocations in passes config in-place.

    Mutates the passes_config to resolve shared and use_locator references.
    """
    for phase_name in ("deterministic", "pattern", "llm", "manual"):
        value = getattr(passes_config, phase_name, None)
        if isinstance(value, list) and value:
            resolved = _resolve_handler_invocations(
                value, shared_handlers, locator_discover, control_id
            )
            setattr(passes_config, phase_name, resolved)


# =============================================================================
# Main Loading Functions
# =============================================================================


def load_controls_from_effective(config: EffectiveConfig) -> list[ControlSpec]:
    """Load ControlSpec objects from effective configuration.

    This is the main entry point for loading controls from merged
    framework + user configuration.

    Args:
        config: Merged effective configuration

    Returns:
        List of executable ControlSpec objects
    """
    controls = []

    for control_id, effective in config.controls.items():
        # Skip non-applicable controls
        if not effective.is_applicable():
            logger.debug(f"Skipping {control_id}: {effective.status_reason}")
            continue

        try:
            control = control_from_effective(control_id, effective)
            controls.append(control)
        except (TypeError, ValueError, KeyError) as e:
            logger.warning(f"Could not load control {control_id}: {e}")

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
                control_id, control_config, shared_handlers=shared_handlers
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
