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

# =============================================================================
# TODO: Future Schema Enhancements (Roadmap)
# =============================================================================
#
# This schema is versioned at 0.1.0-alpha. The following enhancements are
# planned for future versions. See docs/declarative-configuration.md for details.
#
# -----------------------------------------------------------------------------
# HIGH PRIORITY
# -----------------------------------------------------------------------------
#
# 1. Policy Language Support for Check Output Evaluation
#    - Add `policy` field to ExecPassConfig for CEL/Rego expressions
#    - Support complex boolean conditions: `score >= 7.0 && checks.*.pass`
#    - Candidates: CEL (Google), Rego (OPA), CUE, JSONPath extensions
#    - See: passes.py _extract_json_path() for implementation location
#
# 2. External Template Files
#    - Primary: Resolve file paths relative to framework TOML location
#      Example: `file = "templates/security.md"` (relative to TOML)
#    - Template inheritance/composition: `extends = "base_template"`
#    - Future: Remote sources (https://, git://) with integrity checks
#    - See: remediation/executor.py _get_template_content() for implementation
#
# 3. Schema Migration Tooling
#    - CLI command: `darnit migrate-config old.toml`
#    - Automatic schema version detection and upgrade
#    - Validation warnings for deprecated fields
#    - Generate migration diff before applying
#
# -----------------------------------------------------------------------------
# MEDIUM PRIORITY
# -----------------------------------------------------------------------------
#
# 4. Control Dependencies
#    - Run control B only if control A passes
#    - Example: `depends_on = ["OSPS-AC-01.01"]`
#    - Skip dependent controls if prerequisite fails
#    - Useful for: "has CI" before "CI runs tests"
#
# 5. Conditional Controls
#    - Enable/disable controls based on project context
#    - Example: `when = { has_releases = true }` or `when = { language = "python" }`
#    - Auto-detect project type and apply relevant controls
#
# 6. Async/Parallel Check Execution
#    - Run independent checks in parallel
#    - Configurable concurrency limits
#    - Progress reporting during long audits
#    - Example in defaults: `parallel_checks = true, max_concurrency = 5`
#
# 7. Shared Execution Context (Batch Tool Runs)
#    - Single tool run (e.g., Scorecard) serves multiple controls
#    - Cache results with `cache_key` in adapter config
#    - Extract per-control results with JSONPath
#    - Already has TODOs in CheckConfig and CommandAdapterConfig
#
# -----------------------------------------------------------------------------
# LOWER PRIORITY
# -----------------------------------------------------------------------------
#
# 8. Rich Output Formats
#    - HTML report generation with charts
#    - PDF export for compliance documentation
#    - GitHub Actions annotations format
#    - GitLab CI report format
#    - OSCAL (Open Security Controls Assessment Language) export
#
# 9. Control Versioning
#    - Track control changes over time
#    - Deprecation notices with migration guidance
#    - Example: `deprecated = true, deprecated_by = "OSPS-AC-03.02"`
#    - Sunset dates for removed controls
#
# 10. Custom Validation Functions
#     - Register Python validators for complex checks
#     - Example: `validator = "my_module:validate_sbom_completeness"`
#     - Safer than full adapter, scoped to single control
#
# 11. Inheritance Between Frameworks
#     - Extend base frameworks with custom controls
#     - Example: `extends = "openssf-baseline"` at framework level
#     - Override specific controls while inheriting others
#
# 12. Localization/i18n
#     - Translatable control descriptions and messages
#     - Example: `description.en = "...", description.es = "..."`
#     - Or external translation files
#
# 13. Severity/Priority Scoring Improvements
#     - Custom scoring algorithms
#     - Risk-based prioritization
#     - Business impact weighting
#     - Example: `risk_score = { base = 7.0, exploitability = 0.8 }`
#
# =============================================================================
"""

from enum import Enum
from typing import Any, Dict, List, Optional, Union

from pydantic import BaseModel, ConfigDict, Field, field_validator


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
# Locator Configuration (Evidence Location)
# =============================================================================


class LocatorLLMHints(BaseModel):
    """LLM hints for investigation fallback when file not found by discovery.

    When deterministic discovery fails, these hints guide LLM investigation
    to find the evidence in non-standard locations or formats.

    Example:
        ```toml
        [controls."OSPS-VM-01.01".locator.llm_hints]
        search_for = "security policy, vulnerability reporting, security contact"
        check_files = ["README.md", "docs/index.md"]
        look_for_urls = true
        ```
    """
    # Keywords to search for in the codebase
    search_for: Optional[str] = None

    # Files to search within for references
    check_files: List[str] = Field(default_factory=list)

    # Whether to look for external URLs (e.g., docs.example.com/security)
    look_for_urls: bool = False

    model_config = ConfigDict(extra="allow")


class LocatorConfig(BaseModel):
    """Configuration for locating evidence for a control.

    The locator defines how to find the artifact that satisfies a control:
    1. First check .project/ reference (project_path)
    2. Fall back to pattern discovery (discover)
    3. If still not found, use LLM hints for investigation

    Example:
        ```toml
        [controls."OSPS-VM-01.01".locator]
        project_path = "security.policy"
        discover = ["SECURITY.md", ".github/SECURITY.md", "docs/SECURITY.md"]
        kind = "file"

        [controls."OSPS-VM-01.01".locator.llm_hints]
        search_for = "security policy, vulnerability reporting"
        check_files = ["README.md"]
        look_for_urls = true
        ```
    """
    # .project/ field reference (e.g., "security.policy", "governance.contributing")
    # Uses dot notation: section.field
    project_path: Optional[str] = None

    # Discovery patterns (fallback if not in .project/)
    # Order matters: first match wins
    discover: List[str] = Field(default_factory=list)

    # Kind of evidence being located
    # - file: Local file in repository
    # - url: External URL (e.g., external docs site)
    # - api: API endpoint or runtime configuration (e.g., branch protection)
    # - config: Configuration in a config file
    kind: str = "file"  # file | url | api | config

    # LLM hints for investigation fallback
    llm_hints: Optional[LocatorLLMHints] = None

    model_config = ConfigDict(extra="allow")


class OutputMapping(BaseModel):
    """Map external tool output to standardized CheckOutput contract.

    When using external tools that produce their own output format,
    this mapping extracts the relevant fields using JSONPath expressions.

    Example:
        ```toml
        [controls."OSPS-AC-03.01".check.output_mapping]
        status_path = "$.checks.BranchProtection.pass"
        score_path = "$.checks.BranchProtection.score"
        pass_threshold = 8
        message_path = "$.checks.BranchProtection.reason"
        found_path = "$.checks.BranchProtection.details.url"
        ```
    """
    # JSONPath to extract pass/fail status (bool or "pass"/"fail" string)
    status_path: Optional[str] = None

    # JSONPath to extract numeric score (0-10 scale)
    score_path: Optional[str] = None

    # Score threshold for pass (when using score_path)
    # If score >= pass_threshold, status = "pass"
    pass_threshold: Optional[float] = None

    # JSONPath to extract message/reason
    message_path: Optional[str] = None

    # JSONPath to extract found evidence location (file path or URL)
    found_path: Optional[str] = None

    # JSONPath to extract evidence kind (file, url, api, config)
    found_kind_path: Optional[str] = None

    # Default kind if not extractable
    found_kind_default: str = "file"

    model_config = ConfigDict(extra="allow")


# =============================================================================
# Check and Remediation Routing
# =============================================================================


class CheckConfig(BaseModel):
    """Configuration for how a control is checked.

    Supports both builtin adapters and external tools with output mapping.

    Example with builtin:
        ```toml
        [controls."OSPS-VM-01.01".check]
        adapter = "builtin"
        handler = "check_security_policy"
        ```

    Example with external tool and output mapping:
        ```toml
        [controls."OSPS-AC-03.01".check]
        adapter = "scorecard"

        [controls."OSPS-AC-03.01".check.output_mapping]
        status_path = "$.checks.BranchProtection.pass"
        score_path = "$.checks.BranchProtection.score"
        pass_threshold = 8
        ```

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

    # Output mapping for external tools
    # Maps tool output to standardized CheckOutput contract
    output_mapping: Optional[OutputMapping] = None

    # TODO: extract: Optional[str] = None  # JSONPath to extract from cached tool output

    model_config = ConfigDict(extra="allow")


class RemediationConfig(BaseModel):
    """Configuration for how a control is remediated.

    Supports multiple remediation strategies that can be mixed:
    - handler: Python function reference (legacy)
    - file_create: Create a file from template
    - exec: Execute external command
    - api_call: Make GitHub API call
    """
    # Legacy Python handler reference
    adapter: str = "builtin"
    handler: Optional[str] = None  # e.g., "create_security_policy"

    # Declarative remediation types
    file_create: Optional["FileCreateRemediationConfig"] = None
    exec: Optional["ExecRemediationConfig"] = None
    api_call: Optional["ApiCallRemediationConfig"] = None

    # Common settings
    template: Optional[str] = None  # Template name reference
    safe: bool = True  # Safe to auto-apply without confirmation
    requires_api: bool = False  # Requires API access (GitHub, etc.)
    requires_confirmation: bool = False  # Require user confirmation
    dry_run_supported: bool = True  # Supports dry-run mode
    config: Dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")


class FileCreateRemediationConfig(BaseModel):
    """Configuration for file creation remediation.

    Creates a file from a template with variable substitution.

    Example:
        ```toml
        [controls."OSPS-VM-01.01".remediation.file_create]
        path = "SECURITY.md"
        template = "security_policy_standard"
        overwrite = false
        ```
    """
    # Target file path (relative to repo root)
    path: str

    # Template to use (references templates section)
    template: Optional[str] = None

    # Inline content (alternative to template)
    content: Optional[str] = None

    # Whether to overwrite existing files
    overwrite: bool = False

    # Create parent directories if needed
    create_dirs: bool = True

    model_config = ConfigDict(extra="allow")


class ExecRemediationConfig(BaseModel):
    """Configuration for command execution remediation.

    Executes an external command for remediation. Supports variable
    substitution ($OWNER, $REPO, $BRANCH, $PATH).

    Example:
        ```toml
        [controls."OSPS-AC-03.01".remediation.exec]
        command = ["gh", "api", "-X", "PUT", "/repos/$OWNER/$REPO/branches/$BRANCH/protection"]
        stdin_template = "branch_protection_payload"
        success_exit_codes = [0]
        ```
    """
    # Command as list (secure - no shell interpolation)
    command: List[str]

    # Template for stdin input (for API payloads)
    stdin_template: Optional[str] = None

    # Inline stdin content
    stdin: Optional[str] = None

    # Exit codes that indicate success
    success_exit_codes: List[int] = Field(default_factory=lambda: [0])

    # Timeout in seconds
    timeout: int = 300

    # Environment variables
    env: Dict[str, str] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")


class ApiCallRemediationConfig(BaseModel):
    """Configuration for GitHub API call remediation.

    Makes a GitHub API call using gh cli. This is a convenience wrapper
    around ExecRemediationConfig specifically for GitHub API operations.

    Example:
        ```toml
        [controls."OSPS-AC-03.01".remediation.api_call]
        method = "PUT"
        endpoint = "/repos/$OWNER/$REPO/branches/$BRANCH/protection"
        payload_template = "branch_protection"
        ```
    """
    # HTTP method
    method: str = "PUT"

    # API endpoint (supports variable substitution)
    endpoint: str

    # JSON payload template name
    payload_template: Optional[str] = None

    # Inline JSON payload
    payload: Optional[Dict[str, Any]] = None

    # JQ filter for response
    jq_filter: Optional[str] = None

    model_config = ConfigDict(extra="allow")


# =============================================================================
# Template Configuration
# =============================================================================


class TemplateConfig(BaseModel):
    """Configuration for a reusable template.

    Templates support variable substitution:
    - $OWNER - Repository owner
    - $REPO - Repository name
    - $BRANCH - Default branch
    - $YEAR - Current year
    - $DATE - Current date (ISO format)
    - $MAINTAINERS - List of maintainers (if detectable)

    Example:
        ```toml
        [templates.security_policy_standard]
        content = '''
        # Security Policy

        ## Reporting a Vulnerability

        Please report security vulnerabilities to security@$OWNER.github.io
        '''
        ```
    """
    # Template content (inline)
    content: Optional[str] = None

    # Path to template file (alternative to inline)
    file: Optional[str] = None

    # Description of this template
    description: Optional[str] = None

    model_config = ConfigDict(extra="allow")


# =============================================================================
# Control Configuration
# =============================================================================


class ControlConfig(BaseModel):
    """Configuration for a single compliance control.

    Level, domain, and security_severity are optional to support frameworks
    that don't use maturity levels or severity scoring. Use the tags dict
    for flexible key-value metadata that can be filtered uniformly.

    Example:
        ```toml
        [controls."OSPS-AC-03.01"]
        name = "PreventDirectCommits"
        description = "Prevent direct commits to primary branch"
        tags = { level = 1, domain = "AC", severity = 8.0 }

        [controls."OSPS-AC-03.01".locator]
        project_path = "ci.branch_protection"
        kind = "api"

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
    description: str

    # Optional framework-specific fields (for backward compatibility)
    # These are also copied into tags dict for uniform filtering
    level: Optional[int] = None  # Maturity level (1, 2, 3) - None if framework doesn't use levels
    domain: Optional[str] = None  # Domain code (e.g., "AC", "VM") - None if not applicable
    security_severity: Optional[float] = None  # 0.0-10.0 CVSS-like - None if not applicable

    # Evidence location configuration
    # Defines where to find the artifact that satisfies this control
    locator: Optional[LocatorConfig] = None

    # Verification passes
    passes: Optional[PassesConfig] = None

    # Check routing (which adapter verifies this control)
    check: Optional[CheckConfig] = None

    # Remediation routing
    remediation: Optional[RemediationConfig] = None

    # Flexible key-value tags for filtering and metadata
    # Can include any attributes: level, domain, severity, category, priority, etc.
    # For backward compatibility, also accepts List[str] which converts to Dict[str, bool]
    tags: Dict[str, Any] = Field(default_factory=dict)
    help_md: Optional[str] = None  # Inline markdown help
    help_file: Optional[str] = None  # Path to help markdown file
    docs_url: Optional[str] = None  # Link to external docs

    model_config = ConfigDict(extra="allow")

    @field_validator("tags", mode="before")
    @classmethod
    def convert_tags_list_to_dict(cls, v: Any) -> Dict[str, Any]:
        """Convert List[str] tags to Dict[str, bool] for backward compatibility.

        Allows both formats:
            tags = ["access-control", "auth"]  # Old format -> {"access-control": True, "auth": True}
            tags = { level = 1, category = "auth" }  # New format (preferred)
        """
        if isinstance(v, list):
            return {tag: True for tag in v}
        if v is None:
            return {}
        return v


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
    """Metadata for the compliance framework.

    The schema_version field indicates the TOML configuration format version,
    separate from the framework's own version. This allows the darnit system
    to handle schema migrations and provide appropriate warnings when the
    configuration format is evolving.

    Current schema version: 0.1.0-alpha
    - This indicates the TOML schema is in early development
    - Breaking changes may occur between minor versions
    - Framework authors should expect to update their TOML files
    """
    name: str  # e.g., "openssf-baseline"
    display_name: str  # e.g., "OpenSSF Baseline"
    version: str  # e.g., "0.1.0"
    schema_version: str = "0.1.0-alpha"  # TOML config format version
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

        [templates.security_policy]
        content = '''
        # Security Policy
        ...
        '''

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

    # Template definitions for remediation
    templates: Dict[str, TemplateConfig] = Field(default_factory=dict)

    # Control definitions
    controls: Dict[str, ControlConfig] = Field(default_factory=dict)

    # Control groups (for batch configuration)
    control_groups: Dict[str, Dict[str, Any]] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")

    # =========================================================================
    # Convenience Methods
    # =========================================================================

    def get_controls_by_level(self, level: int) -> Dict[str, ControlConfig]:
        """Get all controls at a specific maturity level.

        Note: Controls without a level (level=None) are not included.
        """
        return {
            control_id: control
            for control_id, control in self.controls.items()
            if control.level == level
        }

    def get_controls_by_domain(self, domain: str) -> Dict[str, ControlConfig]:
        """Get all controls in a specific domain.

        Note: Controls without a domain (domain=None) are not included.
        """
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
