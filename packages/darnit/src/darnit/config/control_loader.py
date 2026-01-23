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

from pathlib import Path
from typing import Any, Callable, Dict, List, Optional

from darnit.core.logging import get_logger
from darnit.sieve.models import (
    CheckContext,
    ControlSpec,
    PassResult,
    VerificationPhase,
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
# Pass Converters
# =============================================================================


def _convert_deterministic_pass(config: DeterministicPassConfig) -> DeterministicPass:
    """Convert DeterministicPassConfig to DeterministicPass.

    Args:
        config: Declarative pass configuration

    Returns:
        Executable DeterministicPass
    """
    # For now, we support file_must_exist and file_must_not_exist directly
    # api_check and config_check require function resolution (advanced)
    return DeterministicPass(
        file_must_exist=config.file_must_exist,
        file_must_not_exist=config.file_must_not_exist,
        # Note: api_check and config_check are function references
        # These would need adapter resolution for full support
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
        except (IOError, OSError) as e:
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


def _convert_passes_config(passes_config: Optional[PassesConfig]) -> List[Any]:
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


def load_controls_from_effective(config: EffectiveConfig) -> List[ControlSpec]:
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


def load_controls_from_framework(config: FrameworkConfig) -> List[ControlSpec]:
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
    repo_path: Optional[Path] = None,
) -> List[ControlSpec]:
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
    repo_path: Optional[Path] = None,
) -> List[ControlSpec]:
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
    registry_func: Optional[Callable[[ControlSpec], None]] = None,
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
