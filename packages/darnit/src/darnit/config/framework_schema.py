"""Pydantic models for declarative framework configuration.

This module defines the schema for framework definition files (e.g., openssf-baseline.toml)
that allow compliance frameworks to be defined declaratively instead of in Python code.

Schema Structure:
    - metadata: Framework identification (name, version, spec_version)
    - defaults: Default adapter settings
    - adapters: Adapter definitions (python, command, script, http)
    - controls: Control definitions with passes and remediation

Example:
    ```toml
    [metadata]
    name = "openssf-baseline"
    display_name = "OpenSSF Baseline"
    version = "0.1.0"
    spec_version = "OSPS v2025.10.10"

    [controls."OSPS-AC-03.01"]
    name = "PreventDirectCommits"
    level = 1
    domain = "AC"
    description = "Prevent direct commits to primary branch"

    [controls."OSPS-AC-03.01".passes]
    deterministic = { api_check = "check_branch_protection" }
    ```
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field


# =============================================================================
# Enums
# =============================================================================


class AdapterType(str, Enum):
    """Types of adapters for check/remediation execution."""
    PYTHON = "python"      # Python module + function
    COMMAND = "command"    # External CLI tool
    SCRIPT = "script"      # Shell script
    HTTP = "http"          # REST API endpoint


class PassPhase(str, Enum):
    """Verification pass phases (maps to sieve VerificationPhase)."""
    DETERMINISTIC = "deterministic"
    PATTERN = "pattern"
    LLM = "llm"
    MANUAL = "manual"


# =============================================================================
# Adapter Configuration
# =============================================================================


class PythonAdapterConfig(BaseModel):
    """Configuration for Python module-based adapters."""
    type: AdapterType = AdapterType.PYTHON
    module: str  # e.g., "darnit_baseline.adapters.builtin"
    class_name: Optional[str] = Field(default=None, alias="class")

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class CommandAdapterConfig(BaseModel):
    """Configuration for external command adapters.

    # TODO: Add cache_key and batch_controls for shared execution
    # ```toml
    # [adapters.scorecard]
    # type = "command"
    # command = "scorecard"
    # cache_key = "scorecard"      # Cache results under this key
    # batch_controls = true        # Single run serves multiple controls
    # ```
    """
    type: AdapterType = AdapterType.COMMAND
    command: str  # e.g., "kusari", "trivy"
    output_format: str = "json"  # json, text, sarif
    timeout: int = 300  # seconds
    # TODO: cache_key: Optional[str] = None  # Key for caching in ExecutionContext
    # TODO: batch_controls: bool = False  # Single run serves multiple controls

    model_config = ConfigDict(extra="allow")


class ScriptAdapterConfig(BaseModel):
    """Configuration for shell script adapters."""
    type: AdapterType = AdapterType.SCRIPT
    command: str  # e.g., "./scripts/check.sh"
    output_format: str = "json"
    timeout: int = 300

    model_config = ConfigDict(extra="allow")


class HttpAdapterConfig(BaseModel):
    """Configuration for HTTP API adapters."""
    type: AdapterType = AdapterType.HTTP
    endpoint: str  # e.g., "https://api.example.com/check"
    method: str = "POST"
    auth: Optional[Dict[str, str]] = None  # auth config
    timeout: int = 30

    model_config = ConfigDict(extra="allow")


# Union of all adapter configs
AdapterConfig = Union[
    PythonAdapterConfig,
    CommandAdapterConfig,
    ScriptAdapterConfig,
    HttpAdapterConfig,
    Dict[str, Any],  # Fallback for simple inline definitions
]


# =============================================================================
# Pass Configuration (Verification Phases)
# =============================================================================


class DeterministicPassConfig(BaseModel):
    """Configuration for deterministic verification pass."""
    file_must_exist: Optional[List[str]] = None
    file_must_not_exist: Optional[List[str]] = None
    api_check: Optional[str] = None  # Function name or "module:function"
    config_check: Optional[str] = None  # Function name or "module:function"

    model_config = ConfigDict(extra="allow")


class PatternPassConfig(BaseModel):
    """Configuration for pattern matching verification pass."""
    files: Optional[List[str]] = None  # Files to search
    patterns: Optional[Dict[str, str]] = None  # name -> regex pattern
    pass_if_any_match: bool = Field(default=True, alias="pass_if_any")
    fail_if_no_match: bool = False
    custom_analyzer: Optional[str] = None  # Function reference

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class LLMPassConfig(BaseModel):
    """Configuration for LLM-assisted verification pass."""
    prompt: Optional[str] = None  # Inline prompt template
    prompt_file: Optional[str] = None  # Path to prompt file
    files_to_include: Optional[List[str]] = None
    hints: List[str] = Field(default_factory=list, alias="analysis_hints")
    confidence_threshold: float = 0.8

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class ManualPassConfig(BaseModel):
    """Configuration for manual verification pass."""
    steps: List[str] = Field(default_factory=list, alias="verification_steps")
    docs_url: Optional[str] = Field(default=None, alias="verification_docs_url")

    model_config = ConfigDict(extra="allow", populate_by_name=True)


class ExecPassConfig(BaseModel):
    """Configuration for external command execution pass.

    Executes an external command and evaluates the result. This enables
    integration with external tools like trivy, scorecard, kusari, etc.

    Security: Command arguments are passed as a list, never interpolated
    into a shell string. Variables like $PATH are substituted as whole
    list elements only.

    Example:
        ```toml
        [controls."OSPS-VM-05.02".passes]
        exec = {
            command = ["kusari", "repo", "scan", "$PATH", "HEAD"],
            pass_exit_codes = [0],
            output_format = "json",
        }
        ```
    """
    # Command as list (secure - no shell interpolation)
    # Supports $PATH, $OWNER, $REPO as whole-element substitution
    command: List[str]

    # Exit codes that indicate pass (default: [0])
    pass_exit_codes: List[int] = Field(default_factory=lambda: [0])

    # Exit codes that indicate fail (all others = inconclusive)
    fail_exit_codes: Optional[List[int]] = None

    # Output format for parsing (json, sarif, text)
    output_format: str = "text"

    # JSONPath to extract pass/fail from JSON output
    pass_if_json_path: Optional[str] = None  # e.g., "$.status" == "pass"
    pass_if_json_value: Optional[str] = None

    # Regex pattern to match in output for pass
    pass_if_output_matches: Optional[str] = None

    # Regex pattern to match in output for fail
    fail_if_output_matches: Optional[str] = None

    # Timeout in seconds
    timeout: int = 300

    # Working directory (default: repo path)
    cwd: Optional[str] = None

    # Environment variables to set
    env: Dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")


class PassesConfig(BaseModel):
    """Configuration for all verification passes of a control."""
    deterministic: Optional[DeterministicPassConfig] = None
    exec: Optional[ExecPassConfig] = None  # External command execution
    pattern: Optional[PatternPassConfig] = None
    llm: Optional[LLMPassConfig] = None
    manual: Optional[ManualPassConfig] = None

    model_config = ConfigDict(extra="allow")

    def get_ordered_passes(self) -> List[tuple]:
        """Return passes in execution order: deterministic -> exec -> pattern -> llm -> manual."""
        passes = []
        if self.deterministic:
            passes.append((PassPhase.DETERMINISTIC, self.deterministic))
        if self.exec:
            passes.append((PassPhase.DETERMINISTIC, self.exec))  # exec is deterministic
        if self.pattern:
            passes.append((PassPhase.PATTERN, self.pattern))
        if self.llm:
            passes.append((PassPhase.LLM, self.llm))
        if self.manual:
            passes.append((PassPhase.MANUAL, self.manual))
        return passes


# =============================================================================
# Check and Remediation Routing
# =============================================================================


class CheckConfig(BaseModel):
    """Configuration for how a control is checked.

    # TODO: Add 'extract' field for shared tool result extraction
    # This would allow multiple controls to share a single tool run (e.g., Scorecard):
    #
    # ```toml
    # [adapters.scorecard]
    # type = "command"
    # command = "scorecard"
    # cache_key = "scorecard"  # Results cached under this key
    #
    # [controls."OSPS-AC-03.01"]
    # check = { adapter = "scorecard", extract = "checks.BranchProtection" }
    #
    # [controls."OSPS-QA-02.01"]
    # check = { adapter = "scorecard", extract = "checks.CITests" }
    # ```
    #
    # The 'extract' field would be a JSONPath or dot-notation path to extract
    # the specific result from the cached tool output.
    """
    adapter: str = "builtin"  # Adapter name
    handler: Optional[str] = None  # Specific handler function
    config: Dict[str, Any] = Field(default_factory=dict)  # Adapter-specific config
    # TODO: extract: Optional[str] = None  # JSONPath to extract from cached tool output

    model_config = ConfigDict(extra="allow")


class RemediationConfig(BaseModel):
    """Configuration for how a control is remediated."""
    adapter: str = "builtin"
    handler: Optional[str] = None  # e.g., "create_security_policy"
    template: Optional[str] = None  # e.g., "standard", "minimal"
    safe: bool = True  # Safe to auto-apply without confirmation
    requires_api: bool = False  # Requires API access (GitHub, etc.)
    config: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")


# =============================================================================
# Control Configuration
# =============================================================================


class ControlConfig(BaseModel):
    """Configuration for a single compliance control.

    Example:
        ```toml
        [controls."OSPS-AC-03.01"]
        name = "PreventDirectCommits"
        level = 1
        domain = "AC"
        description = "Prevent direct commits to primary branch"

        [controls."OSPS-AC-03.01".passes]
        deterministic = { api_check = "check_branch_protection" }
        manual = { steps = ["Check branch protection settings"] }

        [controls."OSPS-AC-03.01".remediation]
        handler = "enable_branch_protection"
        requires_api = true
        ```
    """
    # Required fields
    name: str
    level: int  # 1, 2, or 3
    domain: str  # AC, BR, DO, GV, LE, QA, SA, VM
    description: str

    # Verification passes
    passes: Optional[PassesConfig] = None

    # Check routing (which adapter verifies this control)
    check: Optional[CheckConfig] = None

    # Remediation routing
    remediation: Optional[RemediationConfig] = None

    # Metadata
    tags: List[str] = Field(default_factory=list)
    security_severity: Optional[float] = None  # 0.0-10.0 CVSS-like
    help_md: Optional[str] = None  # Inline markdown help
    help_file: Optional[str] = None  # Path to help markdown file
    docs_url: Optional[str] = None  # Link to external docs

    model_config = ConfigDict(extra="allow")


# =============================================================================
# Framework Defaults
# =============================================================================


class FrameworkDefaults(BaseModel):
    """Default settings for the framework."""
    check_adapter: str = "builtin"
    remediation_adapter: str = "builtin"

    model_config = ConfigDict(extra="allow")


# =============================================================================
# Framework Metadata
# =============================================================================


class FrameworkMetadata(BaseModel):
    """Metadata for the compliance framework."""
    name: str  # e.g., "openssf-baseline"
    display_name: str  # e.g., "OpenSSF Baseline"
    version: str  # e.g., "0.1.0"
    spec_version: Optional[str] = None  # e.g., "OSPS v2025.10.10"
    description: Optional[str] = None
    url: Optional[str] = None  # Link to spec

    model_config = ConfigDict(extra="allow")


# =============================================================================
# Main Framework Configuration
# =============================================================================


class FrameworkConfig(BaseModel):
    """Complete framework configuration loaded from TOML.

    This is the root model for framework definition files like openssf-baseline.toml.

    Example:
        ```toml
        [metadata]
        name = "openssf-baseline"
        display_name = "OpenSSF Baseline"
        version = "0.1.0"
        spec_version = "OSPS v2025.10.10"

        [defaults]
        check_adapter = "builtin"

        [adapters.builtin]
        type = "python"
        module = "darnit_baseline.adapters.builtin"

        [controls."OSPS-AC-03.01"]
        name = "PreventDirectCommits"
        level = 1
        domain = "AC"
        description = "Prevent direct commits to primary branch"
        ```
    """
    # Framework identification
    metadata: FrameworkMetadata

    # Default settings
    defaults: FrameworkDefaults = Field(default_factory=FrameworkDefaults)

    # Adapter definitions
    adapters: Dict[str, AdapterConfig] = Field(default_factory=dict)

    # Control definitions
    controls: Dict[str, ControlConfig] = Field(default_factory=dict)

    # Control groups (for batch configuration)
    control_groups: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")

    # =========================================================================
    # Convenience Methods
    # =========================================================================

    def get_controls_by_level(self, level: int) -> Dict[str, ControlConfig]:
        """Get all controls at a specific maturity level."""
        return {
            control_id: control
            for control_id, control in self.controls.items()
            if control.level == level
        }

    def get_controls_by_domain(self, domain: str) -> Dict[str, ControlConfig]:
        """Get all controls in a specific domain."""
        return {
            control_id: control
            for control_id, control in self.controls.items()
            if control.domain == domain
        }

    def get_adapter_config(self, name: str) -> Optional[AdapterConfig]:
        """Get adapter configuration by name."""
        return self.adapters.get(name)

    def get_check_adapter(self, control_id: str) -> str:
        """Get the adapter name for checking a control."""
        control = self.controls.get(control_id)
        if control and control.check:
            return control.check.adapter
        return self.defaults.check_adapter

    def get_remediation_adapter(self, control_id: str) -> str:
        """Get the adapter name for remediating a control."""
        control = self.controls.get(control_id)
        if control and control.remediation:
            return control.remediation.adapter
        return self.defaults.remediation_adapter


# =============================================================================
# Factory Functions
# =============================================================================


def create_framework_config(
    name: str,
    display_name: str,
    version: str = "0.1.0",
    spec_version: Optional[str] = None,
) -> FrameworkConfig:
    """Create a minimal framework configuration.

    Args:
        name: Framework identifier (e.g., "openssf-baseline")
        display_name: Human-readable name
        version: Framework version
        spec_version: Specification version being implemented

    Returns:
        Minimal FrameworkConfig instance
    """
    return FrameworkConfig(
        metadata=FrameworkMetadata(
            name=name,
            display_name=display_name,
            version=version,
            spec_version=spec_version,
        ),
        defaults=FrameworkDefaults(),
        adapters={},
        controls={},
    )
