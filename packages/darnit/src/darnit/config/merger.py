"""Config merger for combining framework and user configurations.

This module provides functionality to merge framework configurations with
user customizations, applying proper override semantics.

Merge Rules:
    1. Scalar values: User overrides framework
    2. Objects/dicts: Deep merge (user keys override, framework keys preserved)
    3. Arrays/lists: User replaces framework entirely
    4. Special keys:
        - status = "n/a" → Marks control as not applicable
        - check = {...} → Replaces entire check config
        - extends = "..." → Specifies base framework

Framework Resolution:
    The ``extends`` field in user config can reference frameworks by name.
    Resolution order:

    1. Explicit path (if ``extends`` contains "/" or ends in ".toml"); only
       honored when the operator trusts the repository's config (see
       :func:`load_user_config`)
    2. Entry point lookup via :class:`~darnit.core.registry.PluginRegistry`

    Example::

        # .baseline.toml
        extends = "openssf-baseline"  # Resolved via entry points

Example:
    Loading and merging configurations::

        from darnit.config.merger import (
            load_framework_config,
            load_framework_by_name,
            load_user_config,
            load_effective_config,
        )

        # Load by path
        framework = load_framework_config(Path("openssf-baseline.toml"))

        # Load by name (via entry points)
        framework = load_framework_by_name("openssf-baseline")

        # Load user config and merge
        effective = load_effective_config(
            framework_path=Path("openssf-baseline.toml"),
            repo_path=Path("/path/to/repo"),
        )

        # Or load by framework name
        effective = load_effective_config_by_name(
            framework_name="openssf-baseline",
            repo_path=Path("/path/to/repo"),
        )

See Also:
    - :mod:`darnit.core.registry` for plugin discovery
    - :mod:`darnit.config.framework_schema` for framework config schema
    - :mod:`darnit.config.user_schema` for user config schema
"""

import copy
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any

try:
    import tomllib
except ImportError:
    import tomli as tomllib  # type: ignore

from darnit.core.logging import get_logger

from .framework_schema import (
    AdapterConfig,
    ControlConfig,
    FrameworkConfig,
    FrameworkDefaults,
    McpServerConfig,
    StoresConfig,
)
from .user_schema import (
    ControlOverride,
    ControlStatus,
    UserConfig,
)

if TYPE_CHECKING:
    from .operator.schema import OperatorConfig

logger = get_logger("config.merger")

# =============================================================================
# Effective Configuration
# =============================================================================


@dataclass
class EffectiveControl:
    """Merged control configuration with framework + user overrides.

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
    from_user: bool = False

    # Status
    status: ControlStatus | None = None
    status_reason: str | None = None

    # Check routing
    check_adapter: str = "builtin"
    check_handler: str | None = None
    check_config: dict[str, Any] = field(default_factory=dict)

    # Remediation routing
    remediation_adapter: str = "builtin"
    remediation_handler: str | None = None
    remediation_config: dict[str, Any] = field(default_factory=dict)

    # Framework pass configuration (for sieve) — flat list of handler invocation dicts
    passes_config: list[dict[str, Any]] | None = None

    # Flexible key-value tags for filtering and metadata
    tags: dict[str, Any] = field(default_factory=dict)
    security_severity: float | None = None
    docs_url: str | None = None

    # New fields needed for Sieve metadata
    when: dict[str, Any] | None = None
    depends_on: list[str] | None = None
    inferred_from: str | None = None
    on_pass: dict[str, Any] | None = None

    def is_applicable(self) -> bool:
        """Check if control should be evaluated."""
        return self.status not in (ControlStatus.NA, ControlStatus.DISABLED)


@dataclass
class EffectiveConfig:
    """Merged configuration combining framework and user configs.

    This is the runtime configuration used by the audit engine.
    """
    # Framework metadata
    framework_name: str
    framework_version: str
    spec_version: str | None = None

    # Merged adapters (framework + user)
    adapters: dict[str, AdapterConfig] = field(default_factory=dict)

    # Merged controls
    controls: dict[str, EffectiveControl] = field(default_factory=dict)

    # Settings from user config
    cache_results: bool = True
    cache_ttl: int = 300
    timeout: int = 300

    # Merged MCP-server allowlist: framework + .baseline.toml, with
    # per-name replacement (spec FR-016). Empty dict is the pre-feature
    # default and preserves backward compatibility.
    mcp_servers: dict[str, "McpServerConfig"] = field(default_factory=dict)

    # Feature 033: merged per-artifact persistence backend selection.
    # `.baseline.toml`'s `[stores.<kind>]` for a given kind fully
    # replaces the framework TOML block for that kind (per-kind
    # replacement, disjoint kinds coexist).
    stores: "StoresConfig | None" = None

    # Source configs (for reference)
    _framework_config: FrameworkConfig | None = None
    _user_config: UserConfig | None = None

    def get_controls_by_level(self, level: int) -> dict[str, EffectiveControl]:
        """Get all applicable controls at a specific level.

        Note: Controls without a level (level=None) are not included.
        """
        return {
            cid: ctrl for cid, ctrl in self.controls.items()
            if ctrl.level == level and ctrl.is_applicable()
        }

    def get_controls_by_domain(self, domain: str) -> dict[str, EffectiveControl]:
        """Get all applicable controls in a specific domain.

        Note: Controls without a domain (domain=None) are not included.
        """
        return {
            cid: ctrl for cid, ctrl in self.controls.items()
            if ctrl.domain == domain and ctrl.is_applicable()
        }

    def get_excluded_controls(self) -> dict[str, str]:
        """Get all non-applicable controls with reasons."""
        return {
            cid: ctrl.status_reason or "No reason provided"
            for cid, ctrl in self.controls.items()
            if not ctrl.is_applicable()
        }

    def get_adapter(self, name: str) -> AdapterConfig | None:
        """Get adapter configuration by name."""
        return self.adapters.get(name)


# =============================================================================
# Merge Functions
# =============================================================================


def deep_merge(base: dict[str, Any], override: dict[str, Any]) -> dict[str, Any]:
    """Deep merge two dictionaries.

    Rules:
    - Scalar values: override replaces base
    - Dicts: recursive merge
    - Lists: override replaces base entirely

    Args:
        base: Base dictionary (from framework)
        override: Override dictionary (from user)

    Returns:
        Merged dictionary
    """
    result = copy.deepcopy(base)

    for key, value in override.items():
        if key in result and isinstance(result[key], dict) and isinstance(value, dict):
            # Recursive merge for nested dicts
            result[key] = deep_merge(result[key], value)
        else:
            # Override scalar or list values
            result[key] = copy.deepcopy(value)

    return result


def merge_control(
    control_id: str,
    framework_control: ControlConfig | None,
    user_override: ControlOverride | None,
    defaults: FrameworkDefaults,
) -> EffectiveControl:
    """Merge a single control's framework config with user override.

    Args:
        control_id: Control identifier
        framework_control: Framework definition (may be None for custom controls)
        user_override: User override (may be None)
        defaults: Framework defaults

    Returns:
        Merged EffectiveControl
    """
    # Start with framework config or create minimal for custom control
    if framework_control:
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
            check_adapter=defaults.check_adapter,
            remediation_adapter=defaults.remediation_adapter,
            tags=tags,
            security_severity=framework_control.security_severity,
            docs_url=framework_control.docs_url,
            when=framework_control.when,
            depends_on=framework_control.depends_on,
            inferred_from=framework_control.inferred_from,
            on_pass=framework_control.on_pass.model_dump() if framework_control.on_pass else None,
        )

        # Apply framework check config
        if framework_control.check:
            effective.check_adapter = framework_control.check.adapter
            effective.check_handler = framework_control.check.handler
            effective.check_config = dict(framework_control.check.config)

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

    else:
        # Custom control from user - name and description required, level/domain optional
        effective = EffectiveControl(
            control_id=control_id,
            name=control_id,
            description="User-defined control",
            from_framework=False,
            from_user=True,
        )

    # Apply user overrides
    if user_override:
        effective.from_user = True

        # Status override
        if user_override.status:
            effective.status = user_override.status
            effective.status_reason = user_override.reason

        # Check override
        if user_override.check:
            effective.check_adapter = user_override.check.adapter
            if user_override.check.handler:
                effective.check_handler = user_override.check.handler
            if user_override.check.config:
                effective.check_config = deep_merge(
                    effective.check_config,
                    user_override.check.config,
                )

        # Remediation override
        if user_override.remediation:
            if user_override.remediation.config:
                effective.remediation_config = deep_merge(
                    effective.remediation_config,
                    user_override.remediation.config,
                )

        # Passes override (advanced) — flat list of handler invocations
        if user_override.passes:
            effective.passes_config = [p.model_dump() for p in user_override.passes]

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
    user: UserConfig | None = None,
    operator: "OperatorConfig | None" = None,
) -> EffectiveConfig:
    """Merge framework, user, and operator configurations into effective config.

    Operator configuration is applied last: its pass overrides, custom
    controls, MCP servers, and stores win over the framework's.

    Args:
        framework: Framework configuration
        user: User configuration (optional)
        operator: Operator configuration (optional)

    Returns:
        Merged EffectiveConfig ready for use

    Raises:
        ValueError: The operator's ``plugins.allowed`` list excludes the framework.
    """
    ensure_framework_allowed(framework.metadata.name, operator)

    # Start with framework metadata
    effective = EffectiveConfig(
        framework_name=framework.metadata.name,
        framework_version=framework.metadata.version,
        spec_version=framework.metadata.spec_version,
        _framework_config=framework,
        _user_config=user,
    )

    # Merge adapters (framework first, then user overrides)
    effective.adapters = dict(framework.adapters)
    if user:
        for name, adapter in user.adapters.items():
            effective.adapters[name] = adapter

    # Merge MCP-server allowlist (spec FR-016).
    # Precedence: framework provides the base; each key present in
    # `.baseline.toml` REPLACES the framework's block for that name
    # entirely (no deep merge within a block; the operator's entry is
    # authoritative). Disjoint names coexist.
    effective.mcp_servers = dict(framework.mcp_servers)
    if user:
        for name, srv in user.mcp_servers.items():
            effective.mcp_servers[name] = srv
    if operator:
        effective.mcp_servers.update(operator.mcp_servers)

    # Merge persistence backend selection (feature 033).
    # Per-kind replacement: `.baseline.toml`'s [stores.<kind>] block for
    # a given kind fully replaces the framework TOML block for that
    # kind. Disjoint kinds coexist.
    from .framework_schema import StoresConfig as _StoresConfig

    merged_stores_data: dict[str, Any] = {}
    for kind in ("project", "attestation", "report", "cache"):
        fw_block = getattr(framework.stores, kind, None)
        user_block = getattr(user.stores, kind, None) if user else None
        operator_block = getattr(operator.stores, kind, None) if operator else None
        block = next((b for b in (operator_block, user_block, fw_block) if b is not None), None)
        if block is not None:
            merged_stores_data[kind] = block
    effective.stores = _StoresConfig.model_construct(**merged_stores_data)

    # Apply user settings
    if user:
        effective.cache_results = user.settings.cache_results
        effective.cache_ttl = user.settings.cache_ttl
        effective.timeout = user.settings.timeout

    # Collect all control IDs, preserving declaration order (issue #428).
    # A `set` here randomized iteration order per PYTHONHASHSEED, so the
    # same repo audited twice listed its controls differently. `dict` keys
    # already carry TOML declaration order, which groups controls by domain
    # the way the framework author wrote them -- so dedup through
    # `dict.fromkeys` rather than sorting, which would discard that grouping.
    # Framework controls first, then any user-only additions.
    all_control_ids: list[str] = list(
        dict.fromkeys([*framework.controls, *(user.controls if user else [])])
    )

    # Merge each control
    for control_id in all_control_ids:
        framework_control = framework.controls.get(control_id)
        user_override = user.get_control_override(control_id) if user else None

        # Handle custom controls (user-defined, not in framework)
        if not framework_control and user:
            user_control = user.controls.get(control_id)
            if isinstance(user_control, dict):
                # Check if this is a custom control definition
                if all(k in user_control for k in ("name", "level", "domain")):
                    # Create a ControlConfig from user definition
                    framework_control = ControlConfig(**user_control)

        effective.controls[control_id] = merge_control(
            control_id=control_id,
            framework_control=framework_control,
            user_override=user_override,
            defaults=framework.defaults,
        )

    if operator:
        for control_id, control in operator.custom_controls.items():
            effective.controls[control_id] = merge_control(
                control_id=control_id,
                framework_control=control,
                user_override=None,
                defaults=framework.defaults,
            )
        for control_id, override in operator.controls.items():
            if override.passes is not None and control_id in effective.controls:
                effective.controls[control_id].passes_config = [p.model_dump() for p in override.passes]

    return effective


# =============================================================================
# Loading Functions
# =============================================================================


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
    config = FrameworkConfig(**data)

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

    _framework_config_cache[resolved] = (mtime_ns, config)
    return config


OPERATOR_CONFIGURATION_HOME = "operator configuration"
PROJECT_ASSERTIONS_HOME = ".project/darnit.yaml"
FRAMEWORK_OPTION_HOME = "the --framework option"
USER_CONFIG_FILENAME = ".baseline.toml"

# True for the .baseline.toml deprecation release (FR-021): per-control
# status/reason are still read as claims and every setting is warned about.
# Set to False in the following minor release to ignore the file (FR-023).
BASELINE_TOML_DEPRECATION_ACTIVE = True

# Files shaped like operator configuration that darnit never reads from an
# audited repository; they are reported so their authors know where the
# settings belong.
_OPERATOR_SHAPED_FILES = (".darnit/config.toml", ".darnit.toml", "darnit.toml", ".config/darnit/config.toml")
_PROJECT_EXTENSION_FILE = ".project/darnit.yaml"
_PROJECT_TOOL_KEYS = frozenset(
    {"operator", "plugins", "mcp_servers", "custom_controls", "stores", "llm", "trust", "policy", "adapters", "passes"}
)


@dataclass(frozen=True)
class IgnoredSetting:
    """A setting found in the audited repository that darnit did not apply."""

    file: str
    key: str
    new_home: str


def _new_home(key: str) -> str:
    if key.startswith("controls.") and key.rsplit(".", 1)[-1] in ("status", "reason"):
        return PROJECT_ASSERTIONS_HOME
    return OPERATOR_CONFIGURATION_HOME


# Keys a repository's own .baseline.toml may set.
# Everything else can change what darnit executes, which servers, adapters,
# or stores it trusts, which framework definition it loads, or which controls
# count toward compliance.
_UNTRUSTED_TOP_LEVEL_KEYS = frozenset({"version", "extends", "settings"})


def _restrict_untrusted_user_config(data: dict[str, Any]) -> tuple[dict[str, Any], list[str]]:
    """Reduce a repository-supplied config to scope declarations only.

    The audited repository is controlled by whoever can write to it, not by
    the operator running darnit. Its .baseline.toml may pick a framework by
    registered name and tune settings. It may not supply per-control overrides
    of any kind (including ``status = "n/a"`` exclusions, which would let the
    audited party remove controls from its own compliance result), passes,
    checks, adapters, remediation, custom controls, control groups, MCP
    servers, stores, plugin trust settings, or a framework file by path.
    """
    ignored: list[str] = []
    restricted: dict[str, Any] = {}

    for key, value in data.items():
        if key == "controls" and isinstance(value, dict):
            for control_id, override in value.items():
                fields = override if isinstance(override, dict) else {}
                ignored.extend(f"controls.{control_id}.{field}" for field in fields)
                if not fields:
                    ignored.append(f"controls.{control_id}")
            continue
        if key not in _UNTRUSTED_TOP_LEVEL_KEYS:
            ignored.append(key)
            continue
        restricted[key] = value

    extends = restricted.get("extends")
    if isinstance(extends, str) and ("/" in extends or "\\" in extends or extends.endswith(".toml")):
        ignored.append("extends (path)")
        del restricted["extends"]

    return restricted, ignored


def load_user_config_with_report(repo_path: Path) -> tuple[UserConfig | None, list[IgnoredSetting]]:
    """Load a repository's .baseline.toml as untrusted input and list what was ignored.

    Returns:
        The restricted UserConfig (or None when there is no file) and one
        IgnoredSetting per key that was not applied.
    """
    config_path = Path(repo_path) / USER_CONFIG_FILENAME
    if not BASELINE_TOML_DEPRECATION_ACTIVE or not config_path.exists():
        return None, []

    with open(config_path, "rb") as f:
        data = tomllib.load(f)

    restricted, ignored = _restrict_untrusted_user_config(data)
    report = [IgnoredSetting(USER_CONFIG_FILENAME, key, _new_home(key)) for key in dict.fromkeys(ignored)]
    return UserConfig(**restricted), report


def load_user_config(repo_path: Path, *, trusted: bool = False) -> UserConfig | None:
    """Load user configuration from repository.

    Searches for .baseline.toml in the repository root.

    The file lives in the audited repository, so by default it is treated as
    untrusted input: only ``version``, ``settings``, and ``extends`` naming a
    registered framework are honored, and anything else (including per-control
    ``status``/``reason``) is ignored with a warning. Settings that change what
    darnit executes or trusts belong in operator configuration, which lives
    outside the audited repository.

    Args:
        repo_path: Path to repository
        trusted: Honor the full file. Only for callers whose trust decision
            comes from operator configuration, never from the repository.

    Returns:
        Parsed UserConfig or None if not found
    """
    config_path = Path(repo_path) / USER_CONFIG_FILENAME

    if not BASELINE_TOML_DEPRECATION_ACTIVE or not config_path.exists():
        return None

    if trusted:
        with open(config_path, "rb") as f:
            return UserConfig(**tomllib.load(f))

    user, ignored = load_user_config_with_report(repo_path)
    if ignored:
        logger.warning(
            "Ignoring settings in %s that can change what darnit executes or trusts: %s. "
            "A repository's own configuration is untrusted input; settings like these "
            "belong in operator configuration outside the audited repository.",
            config_path,
            ", ".join(sorted(s.key for s in ignored)),
        )
    return user


def _baseline_toml_settings(data: dict[str, Any]) -> list[str]:
    settings: list[str] = []
    for key, value in data.items():
        if key == "version":
            continue
        if key != "controls" or not isinstance(value, dict):
            settings.append(key)
            continue
        for control_id, override in value.items():
            if not isinstance(override, dict):
                settings.append(f"controls.{control_id}")
                continue
            custom = all(k in override for k in ("name", "level", "domain"))
            fields = [f for f in override if not custom or f in _UNTRUSTED_CONTROL_KEYS]
            settings.extend(f"controls.{control_id}.{field}" for field in fields)
            if custom:
                settings.append(f"controls.{control_id}")
    return settings


def baseline_toml_warnings(repo_path: Path) -> list[str]:
    """Deprecation warnings for the audited repository's .baseline.toml (FR-021, FR-023).

    During the deprecation release, one warning per setting naming where the
    setting now belongs; afterwards, a single notice that the file was ignored.
    """
    path = Path(repo_path) / USER_CONFIG_FILENAME
    if not path.is_file():
        return []
    migrate = "run `darnit config migrate` to move per-control status and reason to " + PROJECT_ASSERTIONS_HOME
    if not BASELINE_TOML_DEPRECATION_ACTIVE:
        return [
            f"{USER_CONFIG_FILENAME} is no longer read and was ignored; {migrate}. "
            f"Tool settings belong in {OPERATOR_CONFIGURATION_HOME}."
        ]
    try:
        data = tomllib.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, tomllib.TOMLDecodeError):
        return [f"{USER_CONFIG_FILENAME} is deprecated and could not be read; {migrate}."]

    warnings = []
    for setting in _baseline_toml_settings(data):
        home = FRAMEWORK_OPTION_HOME if setting.startswith("extends") else _new_home(setting)
        hint = " (run `darnit config migrate`)" if home == PROJECT_ASSERTIONS_HOME else ""
        warnings.append(f"{USER_CONFIG_FILENAME} is deprecated: `{setting}` belongs in {home}{hint}.")
    return warnings


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
                    f"controls.{control_id}.{field}" for field in override if field not in _UNTRUSTED_CONTROL_KEYS
                )
    return [IgnoredSetting(_PROJECT_EXTENSION_FILE, key, OPERATOR_CONFIGURATION_HOME) for key in keys]


def find_ignored_repository_settings(repo_path: Path) -> list[IgnoredSetting]:
    """List every tool setting the audited repository tries to supply.

    None of these are applied; they are reported with the place the setting
    now belongs so the report can show what was ignored (feature 040).
    """
    repo_path = Path(repo_path)
    try:
        _user, ignored = load_user_config_with_report(repo_path)
    except (OSError, tomllib.TOMLDecodeError, ValueError):
        ignored = [IgnoredSetting(USER_CONFIG_FILENAME, "*", OPERATOR_CONFIGURATION_HOME)]
    return [*ignored, *_operator_shaped_settings(repo_path), *_project_extension_settings(repo_path)]


def load_effective_config(
    framework_path: Path,
    repo_path: Path | None = None,
    *,
    operator: "OperatorConfig | None" = None,
) -> EffectiveConfig:
    """Load and merge framework and user configurations.

    Args:
        framework_path: Path to framework TOML file
        repo_path: Path to repository (for .baseline.toml)
        operator: Operator configuration to apply (optional)

    Returns:
        Merged EffectiveConfig
    """
    framework = load_framework_config(framework_path)

    user = None
    if repo_path:
        user = load_user_config(repo_path)

    return merge_configs(framework, user, operator)


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
    repo_path: Path | None = None,
    *,
    operator: "OperatorConfig | None" = None,
) -> EffectiveConfig:
    """Load and merge framework (by name) and user configurations.

    This is a convenience function that combines framework name resolution
    with config loading and merging.

    Args:
        framework_name: Framework identifier (e.g., "openssf-baseline")
        repo_path: Path to repository (for .baseline.toml)
        operator: Operator configuration to apply (optional)

    Returns:
        Merged EffectiveConfig

    Raises:
        ValueError: If framework not found

    Example:
        >>> effective = load_effective_config_by_name(
        ...     "openssf-baseline",
        ...     Path("/path/to/repo"),
        ... )
        >>> print(f"Loaded {len(effective.controls)} controls")
    """
    framework = load_framework_by_name(framework_name)

    user = None
    if repo_path:
        user = load_user_config(repo_path)

    return merge_configs(framework, user, operator)


def load_effective_config_auto(
    repo_path: Path,
    framework_path: Path | None = None,
    framework_name: str | None = None,
    *,
    operator: "OperatorConfig | None" = None,
) -> EffectiveConfig:
    """Load effective config with automatic framework resolution.

    Resolution order:
    1. Explicit framework_path if provided
    2. Explicit framework_name if provided
    3. ``extends`` field from user's .baseline.toml
    4. Default to "openssf-baseline"

    Args:
        repo_path: Path to repository
        framework_path: Explicit path to framework TOML (optional)
        framework_name: Explicit framework name (optional)
        operator: Operator configuration to apply (optional)

    Returns:
        Merged EffectiveConfig

    Raises:
        ValueError: If framework cannot be resolved

    Example:
        >>> # Uses framework specified in .baseline.toml
        >>> effective = load_effective_config_auto(Path("/path/to/repo"))

        >>> # Override with specific framework
        >>> effective = load_effective_config_auto(
        ...     Path("/path/to/repo"),
        ...     framework_name="testchecks",
        ... )
    """
    # Load user config first to check for extends
    user = load_user_config(repo_path)

    # Determine framework
    if framework_path:
        framework = load_framework_config(framework_path)
    elif framework_name:
        framework = load_framework_by_name(framework_name)
    elif user and user.extends:
        # Resolve from user config's extends field
        path = resolve_framework_path(user.extends)
        if path is None:
            raise ValueError(
                f"Framework '{user.extends}' specified in .baseline.toml "
                f"not found. Ensure the framework package is installed."
            )
        framework = load_framework_config(path)
    else:
        # Default to openssf-baseline
        try:
            framework = load_framework_by_name("openssf-baseline")
        except ValueError:
            raise ValueError(
                "No framework specified and 'openssf-baseline' not found. "
                "Please install darnit-baseline or specify a framework."
            ) from None

    return merge_configs(framework, user, operator)


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

        # Check adapter references exist
        if control.check and control.check.adapter != "builtin":
            if control.check.adapter not in config.adapters:
                errors.append(
                    f"Control {control_id} references unknown adapter: "
                    f"{control.check.adapter}"
                )

    return errors


def validate_user_config(
    user: UserConfig,
    framework: FrameworkConfig | None = None,
) -> list[str]:
    """Validate user configuration for common issues.

    Args:
        user: User configuration to validate
        framework: Framework to validate against (optional)

    Returns:
        List of validation errors (empty if valid)
    """
    errors = []

    # Check adapter references
    for control_id, override in user.controls.items():
        if isinstance(override, dict):
            check = override.get("check", {})
            adapter = check.get("adapter") if isinstance(check, dict) else None
        elif isinstance(override, ControlOverride) and override.check:
            adapter = override.check.adapter
        else:
            adapter = None

        if adapter and adapter != "builtin":
            if adapter not in user.adapters:
                # Check framework adapters too
                if not framework or adapter not in framework.adapters:
                    errors.append(
                        f"Control {control_id} references unknown adapter: {adapter}"
                    )

    # Check control groups reference valid controls
    if framework:
        framework_controls = set(framework.controls.keys())
        for _group_name, group in user.control_groups.items():
            for control_id in group.controls:
                if control_id not in framework_controls:
                    # Could be a custom control, so just warn
                    pass

    return errors
