"""Config merger for combining framework and operator configurations.

The framework TOML provides the controls; operator configuration (which
never comes from the audited repository) replaces passes, adds custom
controls, and overrides MCP servers and stores. Nothing in the audited
repository enters the effective configuration; a repository's legacy
``.baseline.toml`` is not read (framework-design 14.4).

Example:
    Loading and merging configurations::

        from darnit.config.merger import load_effective_config_by_name

        effective = load_effective_config_by_name("openssf-baseline", operator=operator)

See Also:
    - :mod:`darnit.core.registry` for plugin discovery
    - :mod:`darnit.config.framework_schema` for framework config schema
    - :mod:`darnit.config.operator.schema` for operator configuration
"""

from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

from pydantic import ValidationError

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

from darnit.core.logging import get_logger

from .framework_schema import (
    ControlConfig,
    FrameworkConfig,
    McpServerConfig,
    StoresConfig,
)

if TYPE_CHECKING:
    from .operator.schema import OperatorConfig

logger = get_logger("config.merger")

# =============================================================================
# Effective Configuration
# =============================================================================


@dataclass
class EffectiveControl:
    """Merged control configuration: framework definition plus operator overrides.

    Level and domain are optional to support frameworks that don't use
    maturity levels or domain categorization. Use the tags dict for
    flexible key-value metadata that can be filtered uniformly.
    """
    control_id: str
    name: str
    description: str

    # Optional framework-specific fields
    level: int | None = None  # Maturity level - None if framework doesn't use levels
    domain: str | None = None  # Domain code - None if not applicable

    # Source tracking
    from_framework: bool = True

    # Remediation routing
    remediation_handler: str | None = None
    remediation_config: dict[str, Any] = field(default_factory=dict)

    # Framework pass configuration (for sieve) — flat list of handler invocation dicts
    passes_config: list[dict[str, Any]] | None = None
    # Feature 044: the passes come from operator configuration (a custom
    # control or a pass override), so a step type of a plugin that is not
    # installed loads and audits ERROR instead of failing the load.
    steps_from_operator: bool = False

    # Flexible key-value tags for filtering and metadata
    tags: dict[str, Any] = field(default_factory=dict)
    security_severity: float | None = None
    docs_url: str | None = None

    # New fields needed for Sieve metadata
    when: dict[str, Any] | None = None
    depends_on: list[str] | None = None
    inferred_from: str | None = None
    on_pass: dict[str, Any] | None = None


@dataclass
class EffectiveConfig:
    """Merged configuration combining framework and operator configuration.

    This is the runtime configuration used by the audit engine.
    """
    # Framework metadata
    framework_name: str
    framework_version: str
    spec_version: str | None = None

    # Merged controls
    controls: dict[str, EffectiveControl] = field(default_factory=dict)

    # Merged MCP-server allowlist: framework + operator configuration, with
    # per-name replacement (spec FR-016).
    mcp_servers: dict[str, "McpServerConfig"] = field(default_factory=dict)

    # Feature 033: merged per-artifact persistence backend selection.
    # Operator configuration's `[stores.<kind>]` for a given kind fully
    # replaces the framework TOML block for that kind (per-kind
    # replacement, disjoint kinds coexist).
    stores: "StoresConfig | None" = None

    # Source config (for reference)
    _framework_config: FrameworkConfig | None = None

    def get_controls_by_level(self, level: int) -> dict[str, EffectiveControl]:
        """Get all controls at a specific level.

        Note: Controls without a level (level=None) are not included.
        """
        return {cid: ctrl for cid, ctrl in self.controls.items() if ctrl.level == level}

    def get_controls_by_domain(self, domain: str) -> dict[str, EffectiveControl]:
        """Get all controls in a specific domain.

        Note: Controls without a domain (domain=None) are not included.
        """
        return {cid: ctrl for cid, ctrl in self.controls.items() if ctrl.domain == domain}


# =============================================================================
# Merge Functions
# =============================================================================


def merge_control(
    control_id: str,
    framework_control: ControlConfig,
) -> EffectiveControl:
    """Build a control's effective configuration from its definition.

    Args:
        control_id: Control identifier
        framework_control: The control's definition (framework TOML or an
            operator custom control)

    Returns:
        EffectiveControl
    """
    # Build tags dict - start with explicit tags, then add level/domain if present
    tags = dict(framework_control.tags) if framework_control.tags else {}
    if framework_control.level is not None:
        tags["level"] = framework_control.level
    if framework_control.domain is not None:
        tags["domain"] = framework_control.domain
    if framework_control.security_severity is not None:
        tags["security_severity"] = framework_control.security_severity

    effective = EffectiveControl(
        control_id=control_id,
        name=framework_control.name,
        level=framework_control.level,
        domain=framework_control.domain,
        description=framework_control.description,
        from_framework=True,
        tags=tags,
        security_severity=framework_control.security_severity,
        docs_url=framework_control.docs_url,
        when=framework_control.when,
        depends_on=framework_control.depends_on,
        inferred_from=framework_control.inferred_from,
        on_pass=framework_control.on_pass.model_dump() if framework_control.on_pass else None,
    )

    # Apply framework remediation config
    if framework_control.remediation:
        effective.remediation_config = dict(framework_control.remediation.config)

    # Store passes config for sieve (flat list of handler invocations)
    # Resolve use_locator before dumping so handlers get files lists
    if framework_control.passes:
        from .control_loader import _resolve_handler_invocations

        locator_discover = None
        if framework_control.locator and framework_control.locator.discover:
            locator_discover = framework_control.locator.discover

        resolved = _resolve_handler_invocations(
            framework_control.passes,
            {},  # shared_handlers resolved separately
            locator_discover,
            control_id,
        )
        effective.passes_config = [p.model_dump() for p in resolved]

    return effective


def ensure_framework_allowed(framework_name: str, operator: "OperatorConfig | None") -> None:
    """Refuse a framework the operator's ``plugins.allowed`` list leaves out."""
    if operator is not None and operator.plugins.allowed and framework_name not in operator.plugins.allowed:
        raise ValueError(
            f"Framework '{framework_name}' is not in the operator configuration's "
            f"plugins.allowed list ({', '.join(operator.plugins.allowed)})."
        )


def merge_configs(
    framework: FrameworkConfig,
    operator: "OperatorConfig | None" = None,
) -> EffectiveConfig:
    """Merge framework and operator configuration into effective config.

    Operator configuration is applied last: its pass overrides, custom
    controls, MCP servers, and stores win over the framework's.

    Args:
        framework: Framework configuration
        operator: Operator configuration (optional)

    Returns:
        Merged EffectiveConfig ready for use

    Raises:
        ValueError: The operator's ``plugins.allowed`` list excludes the framework.
    """
    ensure_framework_allowed(framework.metadata.name, operator)

    effective = EffectiveConfig(
        framework_name=framework.metadata.name,
        framework_version=framework.metadata.version,
        spec_version=framework.metadata.spec_version,
        _framework_config=framework,
    )

    # Merge MCP-server allowlist (spec FR-016): each operator entry REPLACES
    # the framework's block for that name entirely; disjoint names coexist.
    effective.mcp_servers = dict(framework.mcp_servers)
    if operator:
        effective.mcp_servers.update(operator.mcp_servers)

    # Merge persistence backend selection (feature 033): per-kind
    # replacement, operator block over framework block.
    from .framework_schema import StoresConfig as _StoresConfig

    merged_stores_data: dict[str, Any] = {}
    for kind in ("project", "attestation", "report", "cache"):
        fw_block = getattr(framework.stores, kind, None)
        operator_block = getattr(operator.stores, kind, None) if operator else None
        block = operator_block if operator_block is not None else fw_block
        if block is not None:
            merged_stores_data[kind] = block
    effective.stores = _StoresConfig.model_construct(**merged_stores_data)

    # Controls in TOML declaration order (issue #428).
    for control_id, framework_control in framework.controls.items():
        effective.controls[control_id] = merge_control(
            control_id=control_id,
            framework_control=framework_control,
        )

    if operator:
        for control_id, control in operator.custom_controls.items():
            effective.controls[control_id] = merge_control(
                control_id=control_id,
                framework_control=control,
            )
            effective.controls[control_id].steps_from_operator = True
        for control_id, override in operator.controls.items():
            if override.passes is not None and control_id in effective.controls:
                effective.controls[control_id].passes_config = [p.model_dump() for p in override.passes]
                effective.controls[control_id].steps_from_operator = True

    return effective


# =============================================================================
# Loading Functions
# =============================================================================


def _unknown_keys(error: ValidationError, loc_prefix: tuple[Any, ...], depth: int) -> list[tuple[Any, ...]]:
    """The location after ``loc_prefix`` of each unknown key ``depth`` levels below it in ``error``."""
    width = len(loc_prefix)
    return [
        tuple(err["loc"][width:])
        for err in error.errors()
        if err["type"] == "extra_forbidden" and len(err["loc"]) == width + depth and tuple(err["loc"][:width]) == loc_prefix
    ]


def _unknown_control_keys_message(source: str, unknown: list[tuple[Any, Any]]) -> str:
    keys = "; ".join(f"control {control!r} has unknown key {key!r}" for control, key in unknown)
    return f"{source}: {keys} (framework-design 2.3)"


def _parse_framework_only(path: Path) -> FrameworkConfig:
    """Parse + template-validate a framework TOML — WITHOUT resolving composition.

    This is the helper that the composition resolver's default
    ``source_loader`` routes through, so recursive source loads do NOT
    re-enter composition with a fresh ``_resolution_stack``. Cycle
    detection (FR-012) and recursive composition (FR-018) depend on this
    split — see ``specs/013-plugin-composition/research.md`` §R-002 for
    the full rationale.

    Callers OUTSIDE the composition resolver should generally call
    :func:`load_framework_config` instead; this helper produces a
    parsed-but-not-composition-resolved ``FrameworkConfig`` that is NOT
    safe to hand to the audit pipeline if it has composition state.

    Args:
        path: Path to framework TOML file

    Returns:
        Parsed FrameworkConfig (composition state still present if any)

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file is invalid
    """
    if not path.exists():
        raise FileNotFoundError(f"Framework config not found: {path}")

    with open(path, "rb") as f:
        data = tomllib.load(f)

    # Convert to schema model
    try:
        config = FrameworkConfig(**data)
    except ValidationError as e:
        unknown = _unknown_keys(e, ("controls",), 2)
        if not unknown:
            raise
        raise ValueError(_unknown_control_keys_message(f"Framework file {path}", unknown)) from e
    config._source_path = str(path)

    # Validate template file paths at load time
    # Check if file templates exist relative to the framework config location
    # and prevent path traversal outside the plugin packages
    base_dir = path.parent.resolve()
    for name, template in config.templates.items():
        if template.file:
            template_path = Path(template.file)

            if template_path.is_absolute():
                raise ValueError(
                    f"Template '{name}' specifies absolute path '{template.file}'. "
                    f"Template files must be relative paths within the plugin package."
                )

            resolved = (base_dir / template_path).resolve()
            try:
                resolved.relative_to(base_dir)
            except ValueError as err:
                raise ValueError(
                    f"Template '{name}' resolves to {resolved}, outside framework "
                    f"directory {base_dir}. Template files must live within "
                    f"the plugin package."
                ) from err

            if not resolved.exists():
                raise FileNotFoundError(
                    f"Template file '{template.file}' for template '{name}' "
                    f"not found relative to framework config '{path}'"
                )

    return config


# Parsed framework configs are large (the baseline TOML is 4000+ lines) and
# were previously re-parsed several times per audit. Keyed by resolved path,
# invalidated on mtime change so .toml edits are picked up even in a
# long-running MCP server. Composed frameworks are keyed on the top-level
# file's mtime only; editing a composition *source* without touching the
# top file serves stale until the next mtime change.
_framework_config_cache: dict[Path, tuple[int, FrameworkConfig]] = {}


def load_framework_config(path: Path) -> FrameworkConfig:
    """Load framework configuration from TOML file.

    Results are cached per resolved path and invalidated when the file's
    mtime changes. Callers MUST treat the returned config as read-only.

    If the parsed config has any ``[[compose]]`` blocks or
    ``[overrides."…"]`` blocks, this function resolves composition exactly
    once before returning, so callers receive a flat ``FrameworkConfig``
    that is shape-identical to a non-composite's. The resolver itself uses
    :func:`_parse_framework_only` (NOT this function) to load source
    frameworks recursively; that split is load-bearing for cycle
    detection — see ``specs/013-plugin-composition/contracts/resolver-api.md``
    §Integration contract.

    Args:
        path: Path to framework TOML file

    Returns:
        Fully-resolved FrameworkConfig (composition state cleared if any)

    Raises:
        FileNotFoundError: If file doesn't exist
        ValueError: If file is invalid
        CompositionError: Any composition-resolution failure (missing
            source, cycle, conflict, orphan override, etc.).
    """
    resolved = path.resolve()
    try:
        mtime_ns = resolved.stat().st_mtime_ns
    except FileNotFoundError:
        raise FileNotFoundError(f"Framework config not found: {path}") from None

    cached = _framework_config_cache.get(resolved)
    if cached is not None and cached[0] == mtime_ns:
        return cached[1]

    config = _parse_framework_only(path)

    # Composition resolution runs EXACTLY ONCE at the top of this call chain.
    # The resolver's `source_loader` calls `_parse_framework_only` (not this
    # function) for recursive source loads, so the resolver's per-call
    # `_resolution_stack` is the single source of truth for cycle detection.
    if config.compose or config.overrides:
        from darnit.core.composition import resolve_composition

        config = resolve_composition(config)
        config._source_path = str(path)

    _framework_config_cache[resolved] = (mtime_ns, config)
    return config


OPERATOR_CONFIGURATION_HOME = "operator configuration"
PROJECT_ASSERTIONS_HOME = ".project/darnit.yaml"
# A repository's legacy configuration file. darnit never reads it for an
# audit; `darnit config migrate` reads it to move its contents
# (framework-design 14.4).
BASELINE_TOML = ".baseline.toml"

# Files shaped like operator configuration that darnit never reads from an
# audited repository; they are reported so their authors know where the
# settings belong.
_OPERATOR_SHAPED_FILES = (".darnit/config.toml", ".darnit.toml", "darnit.toml", ".config/darnit/config.toml")
_PROJECT_EXTENSION_FILE = ".project/darnit.yaml"
_PROJECT_TOOL_KEYS = frozenset(
    {"operator", "plugins", "mcp_servers", "custom_controls", "stores", "llm", "trust", "policy", "adapters", "passes"}
)
_CLAIM_KEYS = frozenset({"status", "reason"})


@dataclass(frozen=True)
class IgnoredSetting:
    """A setting found in the audited repository that darnit did not apply."""

    file: str
    key: str
    new_home: str


def baseline_toml_warnings(repo_path: Path) -> list[str]:
    """The notice for a ``.baseline.toml`` in the audited repository (FR-023).

    darnit does not read the file; when it exists, the audit reports this one
    notice, whatever the file contains.
    """
    if not (Path(repo_path) / BASELINE_TOML).is_file():
        return []
    return [
        f"{BASELINE_TOML} is no longer read and was ignored; run `darnit config migrate` to move its "
        f"claims to {PROJECT_ASSERTIONS_HOME} and get an {OPERATOR_CONFIGURATION_HOME} fragment for "
        "its tool settings."
    ]


def _operator_shaped_settings(repo_path: Path) -> list[IgnoredSetting]:
    settings: list[IgnoredSetting] = []
    for rel in _OPERATOR_SHAPED_FILES:
        path = repo_path / rel
        if not path.is_file():
            continue
        try:
            keys = list(tomllib.loads(path.read_text(encoding="utf-8")))
        except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
            keys = ["*"]
        settings.extend(IgnoredSetting(rel, key, OPERATOR_CONFIGURATION_HOME) for key in keys)
    return settings


def _project_extension_settings(repo_path: Path) -> list[IgnoredSetting]:
    path = repo_path / _PROJECT_EXTENSION_FILE
    if not path.is_file():
        return []
    import yaml

    try:
        data = yaml.safe_load(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, yaml.YAMLError):
        return []
    if not isinstance(data, dict):
        return []

    keys = [key for key in data if key in _PROJECT_TOOL_KEYS]
    controls = data.get("controls")
    if isinstance(controls, dict):
        for control_id, override in controls.items():
            if isinstance(override, dict):
                keys.extend(
                    f"controls.{control_id}.{field}" for field in override if field not in _CLAIM_KEYS
                )
    return [IgnoredSetting(_PROJECT_EXTENSION_FILE, key, OPERATOR_CONFIGURATION_HOME) for key in keys]


def find_ignored_repository_settings(repo_path: Path) -> list[IgnoredSetting]:
    """List every tool setting the audited repository tries to supply.

    None of these are applied; they are reported with the place the setting
    now belongs so the report can show what was ignored (feature 040).
    """
    repo_path = Path(repo_path)
    return [*_operator_shaped_settings(repo_path), *_project_extension_settings(repo_path)]


def load_effective_config(
    framework_path: Path,
    *,
    operator: "OperatorConfig | None" = None,
) -> EffectiveConfig:
    """Load a framework TOML and merge operator configuration into it.

    Args:
        framework_path: Path to framework TOML file
        operator: Operator configuration to apply (optional)

    Returns:
        Merged EffectiveConfig
    """
    return merge_configs(load_framework_config(framework_path), operator)


# =============================================================================
# Framework Name Resolution (via PluginRegistry)
# =============================================================================


def resolve_framework_path(name_or_path: str) -> Path | None:
    """Resolve a framework name or path to an actual path.

    Resolution order:
    1. If contains "/" or ends with ".toml", treat as path
    2. Otherwise, look up via PluginRegistry entry points

    Args:
        name_or_path: Framework name (e.g., "openssf-baseline") or path

    Returns:
        Resolved Path or None if not found

    Example:
        >>> path = resolve_framework_path("openssf-baseline")
        >>> if path:
        ...     config = load_framework_config(path)

        >>> path = resolve_framework_path("./custom.toml")
        >>> # Returns Path("./custom.toml")
    """
    # Check if it looks like a path
    if "/" in name_or_path or name_or_path.endswith(".toml"):
        return Path(name_or_path)

    # Try to resolve via PluginRegistry
    try:
        from darnit.core.registry import get_plugin_registry

        registry = get_plugin_registry()
        return registry.get_framework_path(name_or_path)
    except ImportError:
        return None


def load_framework_by_name(name: str) -> FrameworkConfig:
    """Load a framework configuration by name.

    Resolves the framework name via PluginRegistry entry points.

    Args:
        name: Framework identifier (e.g., "openssf-baseline")

    Returns:
        Parsed FrameworkConfig

    Raises:
        ValueError: If framework not found

    Example:
        >>> framework = load_framework_by_name("openssf-baseline")
        >>> print(f"Loaded {len(framework.controls)} controls")
    """
    path = resolve_framework_path(name)

    if path is None:
        raise ValueError(
            f"Framework '{name}' not found. "
            f"Ensure the framework package is installed and registers "
            f"a 'darnit.frameworks' entry point."
        )

    if not path.exists():
        raise FileNotFoundError(
            f"Framework '{name}' resolved to {path}, but file not found"
        )

    return load_framework_config(path)


def list_available_frameworks() -> list[str]:
    """List all available framework names.

    Discovers frameworks via PluginRegistry entry points.

    Returns:
        Sorted list of framework names

    Example:
        >>> for name in list_available_frameworks():
        ...     print(f"Available: {name}")
    """
    try:
        from darnit.core.registry import get_plugin_registry

        registry = get_plugin_registry()
        return registry.list_frameworks()
    except ImportError:
        return []


def load_effective_config_by_name(
    framework_name: str,
    *,
    operator: "OperatorConfig | None" = None,
) -> EffectiveConfig:
    """Load a framework by name and merge operator configuration into it.

    Args:
        framework_name: Framework identifier (e.g., "openssf-baseline")
        operator: Operator configuration to apply (optional)

    Returns:
        Merged EffectiveConfig

    Raises:
        ValueError: If framework not found
    """
    return merge_configs(load_framework_by_name(framework_name), operator)


def load_effective_config_auto(
    framework_path: Path | None = None,
    framework_name: str | None = None,
    *,
    operator: "OperatorConfig | None" = None,
) -> EffectiveConfig:
    """Load effective config, resolving the framework.

    Resolution order (nothing in the audited repository selects it):
    1. Explicit framework_path if provided
    2. Explicit framework_name if provided
    3. Default to "openssf-baseline"

    Args:
        framework_path: Explicit path to framework TOML (optional)
        framework_name: Explicit framework name (optional)
        operator: Operator configuration to apply (optional)

    Returns:
        Merged EffectiveConfig

    Raises:
        ValueError: If framework cannot be resolved
    """
    if framework_path:
        framework = load_framework_config(framework_path)
    elif framework_name:
        framework = load_framework_by_name(framework_name)
    else:
        try:
            framework = load_framework_by_name("openssf-baseline")
        except ValueError:
            raise ValueError(
                "No framework specified and 'openssf-baseline' not found. "
                "Please install darnit-baseline or specify a framework."
            ) from None

    return merge_configs(framework, operator)


# =============================================================================
# Validation Functions
# =============================================================================


def validate_framework_config(config: FrameworkConfig) -> list[str]:
    """Validate framework configuration for common issues.

    Args:
        config: Framework configuration to validate

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    # Check metadata
    if not config.metadata.name:
        errors.append("Framework name is required")
    if not config.metadata.display_name:
        errors.append("Framework display_name is required")

    # Check controls
    for control_id, control in config.controls.items():
        if not control.name:
            errors.append(f"Control {control_id} missing name")
        # Level and domain are optional - only validate if present
        if control.level is not None and control.level not in (1, 2, 3):
            errors.append(f"Control {control_id} has invalid level: {control.level}")

    return errors
