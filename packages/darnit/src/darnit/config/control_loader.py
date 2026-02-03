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
    DeterministicPassConfig,
    ExecPassConfig,
    FrameworkConfig,
    LLMPassConfig,
    ManualPassConfig,
    PassesConfig,
    PatternPassConfig,
)
from .merger import EffectiveConfig, EffectiveControl

logger = get_logger("config.control_loader")


# =============================================================================
# Module Import Security
# =============================================================================

# Base whitelist - always allowed
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

    Combines the base whitelist with prefixes from all registered
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
    """Check if a module path is in the allowed whitelist.

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
    """Resolve a 'module:function' reference to a callable.

    Supports two patterns:
    1. Factory functions that return a callable: module:factory_func
       - The factory is called, and its return value is used as the check
    2. Direct check functions: module:check_func
       - The function itself is used as the check

    Security: Only allows loading modules from whitelisted prefixes
    to prevent arbitrary code execution from malicious TOML files.
    The whitelist includes base darnit packages plus any packages
    registered via entry points.

    Args:
        reference: String like "darnit_baseline.controls.level2:_create_changelog_check"

    Returns:
        The resolved function, or None if resolution fails
    """
    if not reference or ":" not in reference:
        logger.warning(f"Invalid check function reference (missing ':'): {reference}")
        return None

    module_path, func_name = reference.rsplit(":", 1)

    # Security: Validate module path against whitelist
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
# Control Converter
# =============================================================================


def _convert_passes_config(passes_config: PassesConfig | None) -> list[Any]:
    """Convert PassesConfig to list of executable pass objects.

    Args:
        passes_config: Declarative passes configuration

    Returns:
        List of pass objects in execution order
    """
    if not passes_config:
        return []

    passes = []

    # Order: deterministic -> exec -> pattern -> llm -> manual
    if passes_config.deterministic:
        passes.append(_convert_deterministic_pass(passes_config.deterministic))

    if passes_config.exec:
        passes.append(_convert_exec_pass(passes_config.exec))

    if passes_config.pattern:
        passes.append(_convert_pattern_pass(passes_config.pattern))

    if passes_config.llm:
        passes.append(_convert_llm_pass(passes_config.llm))

    if passes_config.manual:
        passes.append(_convert_manual_pass(passes_config.manual))

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
) -> ControlSpec:
    """Convert ControlConfig from framework to ControlSpec.

    Args:
        control_id: Control identifier
        control_config: Framework control configuration

    Returns:
        Executable ControlSpec
    """
    passes = _convert_passes_config(control_config.passes) if control_config.passes else []

    # Build tags dict from config - tags is now Dict[str, Any]
    tags = dict(control_config.tags) if control_config.tags else {}

    # Extract level/domain/security_severity from tags if not present as top-level
    # This supports the new flexible schema where everything can be in tags
    level = control_config.level
    if level is None and "level" in tags:
        level = tags["level"]

    domain = control_config.domain
    if domain is None and "domain" in tags:
        domain = tags["domain"]

    security_severity = control_config.security_severity
    if security_severity is None and "security_severity" in tags:
        security_severity = tags["security_severity"]

    return ControlSpec(
        control_id=control_id,
        level=level,
        domain=domain,
        name=control_config.name,
        description=control_config.description,
        passes=passes,
        tags=tags,  # Pass tags directly, ControlSpec.__post_init__ will add level/domain
        metadata={
            "security_severity": security_severity,
            "docs_url": control_config.docs_url,
        },
    )


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

    Args:
        config: Framework configuration

    Returns:
        List of executable ControlSpec objects
    """
    controls = []

    for control_id, control_config in config.controls.items():
        try:
            control = control_from_framework(control_id, control_config)
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
