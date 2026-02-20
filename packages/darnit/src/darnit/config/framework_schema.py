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

    [[controls."OSPS-AC-03.01".passes]]
    handler = "exec"
    command = ["gh", "api", "/repos/$OWNER/$REPO/branches/$BRANCH/protection"]
    ```

# =============================================================================
# TODO: Future Schema Enhancements (Roadmap)
# =============================================================================
#
# This schema is versioned at 0.1.0-alpha. The following enhancements are
# planned for future versions. See docs/IMPLEMENTATION_GUIDE.md for details.
#
# -----------------------------------------------------------------------------
# HIGH PRIORITY
# -----------------------------------------------------------------------------
#
# 1. Policy Language Support for Check Output Evaluation
#    - Add `policy` field for CEL/Rego expressions on exec handler output
#    - Support complex boolean conditions: `score >= 7.0 && checks.*.pass`
#    - Candidates: CEL (Google), Rego (OPA), CUE, JSONPath extensions
#    - See: builtin_handlers.py exec_handler() for implementation location
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
from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_validator

# =============================================================================
# Enums
# =============================================================================


class AdapterType(str, Enum):
    """Types of adapters for check/remediation execution."""
    PYTHON = "python"      # Python module + function
    COMMAND = "command"    # External CLI tool
    SCRIPT = "script"      # Shell script
    HTTP = "http"          # REST API endpoint


# =============================================================================
# Adapter Configuration
# =============================================================================


class PythonAdapterConfig(BaseModel):
    """Configuration for Python module-based adapters."""
    type: AdapterType = AdapterType.PYTHON
    module: str  # e.g., "darnit_baseline.tools"
    class_name: str | None = Field(default=None, alias="class")

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
    auth: dict[str, str] | None = None  # auth config
    timeout: int = 30

    model_config = ConfigDict(extra="allow")


# Union of all adapter configs
AdapterConfig = (
    PythonAdapterConfig
    | CommandAdapterConfig
    | ScriptAdapterConfig
    | HttpAdapterConfig
    | dict[str, Any]  # Fallback for simple inline definitions
)


# =============================================================================
# Pass Configuration (Verification Phases)
# =============================================================================



class HandlerInvocation(BaseModel):
    """A single handler call within a pipeline phase.

    Names a registered handler and provides handler-specific configuration
    via pass-through fields. The framework schema doesn't need to know about
    every handler's parameters — extra fields are passed to the handler at
    execution time.

    Example TOML:
        ```toml
        [[controls."OSPS-XX-01".passes]]
        handler = "file_exists"
        files = ["README.md", "README.rst"]

        [[controls."OSPS-XX-01".passes]]
        handler = "exec"
        command = ["gh", "api", "..."]
        expr = "..."
        ```
    """
    # Handler name (registered in the sieve handler registry)
    handler: str

    # Reference to a shared handler definition (from [shared_handlers] section)
    shared: str | None = None

    # Convenience: populate files from locator.discover at load time
    use_locator: bool = False

    # Conditional dispatch — handler is skipped when condition evaluates to false
    # Keys are context keys, values are expected values (same semantics as control-level when)
    # Consumed by orchestrator/executor before dispatch; NOT passed to the handler
    when: dict[str, Any] | None = None

    # All other fields pass through to the handler
    model_config = ConfigDict(extra="allow")


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
    search_for: str | None = None

    # Files to search within for references
    check_files: list[str] = Field(default_factory=list)

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
    project_path: str | None = None

    # Discovery patterns (fallback if not in .project/)
    # Order matters: first match wins
    discover: list[str] = Field(default_factory=list)

    # Kind of evidence being located
    # - file: Local file in repository
    # - url: External URL (e.g., external docs site)
    # - api: API endpoint or runtime configuration (e.g., branch protection)
    # - config: Configuration in a config file
    kind: str = "file"  # file | url | api | config

    # LLM hints for investigation fallback
    llm_hints: LocatorLLMHints | None = None

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
    status_path: str | None = None

    # JSONPath to extract numeric score (0-10 scale)
    score_path: str | None = None

    # Score threshold for pass (when using score_path)
    # If score >= pass_threshold, status = "pass"
    pass_threshold: float | None = None

    # JSONPath to extract message/reason
    message_path: str | None = None

    # JSONPath to extract found evidence location (file path or URL)
    found_path: str | None = None

    # JSONPath to extract evidence kind (file, url, api, config)
    found_kind_path: str | None = None

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
    handler: str | None = None  # Specific handler function
    config: dict[str, Any] = Field(default_factory=dict)  # Adapter-specific config

    # Output mapping for external tools
    # Maps tool output to standardized CheckOutput contract
    output_mapping: OutputMapping | None = None

    # TODO: extract: Optional[str] = None  # JSONPath to extract from cached tool output

    model_config = ConfigDict(extra="allow")


class RemediationConfig(BaseModel):
    """Configuration for how a control is remediated.

    Remediation handlers are a flat ordered list of HandlerInvocation entries.
    The executor iterates the list in order.

    Metadata fields (requires_context, project_update) remain as separate fields.

    Example:
        ```toml
        [controls."OSPS-VM-01.01".remediation]
        requires_context = [{ key = "maintainers", required = true }]

        [[controls."OSPS-VM-01.01".remediation.handlers]]
        handler = "file_create"
        path = "SECURITY.md"
        template = "security_policy"
        ```
    """
    # Flat ordered list of remediation handler invocations
    handlers: list[HandlerInvocation] = Field(default_factory=list)

    # Handler selection strategy:
    # - "all" (default): run all handlers whose `when` matches (existing behavior)
    # - "first_match": stop after the first handler whose `when` matches
    strategy: Literal["all", "first_match"] = "all"

    # Post-remediation .project/ update (applied via on_pass, not a handler)
    project_update: Optional["ProjectUpdateRemediationConfig"] = None

    # Common settings
    template: str | None = None  # Template name reference
    safe: bool = True  # Safe to auto-apply without confirmation
    requires_api: bool = False  # Requires API access (GitHub, etc.)
    requires_confirmation: bool = False  # Require user confirmation
    dry_run_supported: bool = True  # Supports dry-run mode
    config: dict[str, Any] = Field(default_factory=dict)

    # Context requirements - checked by orchestrator before running remediation
    # If any required context is missing or unconfirmed, user is prompted
    requires_context: list["ContextRequirement"] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")



class ProjectUpdateRemediationConfig(BaseModel):
    """Configuration for .project/ file update remediation.

    Updates .project/project.yaml with new values after remediation actions.
    This keeps .project/ in sync with the actual project state.

    Example:
        ```toml
        [controls."OSPS-VM-02.01".remediation.project_update]
        set = { "security.policy.path" = "SECURITY.md" }
        ```

    The `set` dictionary uses dotted paths to specify nested YAML updates:
    - "security.policy.path" -> updates security.policy.path in project.yaml
    - "governance.codeowners.path" -> updates governance.codeowners.path
    """
    # Values to set in .project/project.yaml
    # Keys are dotted paths, values are the new values
    set: dict[str, Any] = Field(default_factory=dict)

    # Whether to create .project/ directory if it doesn't exist
    create_if_missing: bool = True

    model_config = ConfigDict(extra="allow")



# =============================================================================
# Shared Handler Configuration
# =============================================================================


class SharedHandlerConfig(BaseModel):
    """Configuration for a shared handler that can be referenced by multiple controls.

    Shared handlers allow expensive operations (e.g., GitHub API calls) to be
    defined once and reused across controls. When a control references a shared
    handler via ``HandlerInvocation.shared``, the shared handler's config is
    merged with the per-control overrides (control takes precedence).

    Results are cached per audit run — the handler executes once, and all
    controls referencing the same shared handler get the cached result.

    Example:
        ```toml
        [shared_handlers.branch_protection]
        handler = "exec"
        command = ["gh", "api", "/repos/$OWNER/$REPO/branches/$BRANCH/protection"]
        output_format = "json"

        [[controls."OSPS-AC-03.01".passes]]
        shared = "branch_protection"
        expr = "json.required_pull_request_reviews != null"
        ```
    """
    # Handler name (registered in the sieve handler registry)
    handler: str

    # All other fields pass through to the handler
    model_config = ConfigDict(extra="allow")


# =============================================================================
# Post-Check Context Update
# =============================================================================


class OnPassConfig(BaseModel):
    """Configuration for actions to take when a control passes.

    When a check passes, the sieve has found evidence (e.g., "SECURITY.md
    exists at path X"). This config feeds that finding back into .project/
    so subsequent checks can use it.

    The `project_update` field uses the same dotted-path format as
    ``ProjectUpdateRemediationConfig.set``. Values can reference evidence
    from the sieve result using ``$EVIDENCE.<key>`` syntax.

    Example:
        ```toml
        [controls."PH-SEC-01".on_pass]
        project_update = { "security.policy.path" = "SECURITY.md" }
        ```
    """
    # Values to set in .project/project.yaml on pass
    # Keys are dotted paths, values are literals or $EVIDENCE references
    project_update: dict[str, Any] = Field(default_factory=dict)

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
    content: str | None = None

    # Path to template file (alternative to inline)
    file: str | None = None

    # Description of this template
    description: str | None = None

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

        [[controls."OSPS-AC-03.01".passes]]
        handler = "exec"
        command = ["gh", "api", "/repos/$OWNER/$REPO/branches/$BRANCH/protection"]
        expr = "json.required_pull_request_reviews != null"

        [[controls."OSPS-AC-03.01".passes]]
        handler = "manual_steps"
        steps = ["Check branch protection settings"]

        [[controls."OSPS-AC-03.01".remediation.handlers]]
        handler = "manual_steps"
        steps = ["Enable branch protection for the default branch"]
        ```
    """
    # Required fields
    name: str
    description: str

    # Optional framework-specific fields (for backward compatibility)
    # These are also copied into tags dict for uniform filtering
    level: int | None = None  # Maturity level (1, 2, 3) - None if framework doesn't use levels
    domain: str | None = None  # Domain code (e.g., "AC", "VM") - None if not applicable
    security_severity: float | None = None  # 0.0-10.0 CVSS-like - None if not applicable

    # Conditional applicability — control is N/A when condition is false
    # Keys are context keys, values are the expected values
    # Example: when = { has_releases = true }  →  skip if project has no releases
    # Missing context keys → control runs normally (conservative)
    when: dict[str, Any] | None = None

    # Control dependencies
    # depends_on: ordering only — this control runs after listed controls
    # inferred_from: if referenced control PASSES, this control auto-PASSes
    depends_on: list[str] | None = None
    inferred_from: str | None = None

    # Evidence location configuration
    # Defines where to find the artifact that satisfies this control
    locator: LocatorConfig | None = None

    # Verification passes — flat ordered list of handler invocations
    passes: list[HandlerInvocation] | None = None

    @field_validator("passes", mode="before")
    @classmethod
    def validate_passes_format(cls, v: Any) -> list[HandlerInvocation] | None:
        """Reject legacy phase-bucketed passes format with a helpful error."""
        if v is None:
            return None
        if isinstance(v, dict):
            legacy_keys = {"deterministic", "pattern", "llm", "manual", "exec"}
            found = [k for k in legacy_keys if k in v]
            if found:
                raise ValueError(
                    f"Legacy phase-bucketed passes format detected (keys: {found}). "
                    f"Use a flat list of handler invocations instead: "
                    f'passes = [{{ handler = "exec", command = [...] }}]'
                )
        return v

    # Check routing (which adapter verifies this control)
    check: CheckConfig | None = None

    # Remediation routing
    remediation: RemediationConfig | None = None

    # Post-check context update (applied when this control passes)
    on_pass: OnPassConfig | None = None

    # Flexible key-value tags for filtering and metadata
    # Can include any attributes: level, domain, severity, category, priority, etc.
    # For backward compatibility, also accepts List[str] which converts to Dict[str, bool]
    tags: dict[str, Any] = Field(default_factory=dict)
    help_md: str | None = None  # Inline markdown help
    help_file: str | None = None  # Path to help markdown file
    docs_url: str | None = None  # Link to external docs

    model_config = ConfigDict(extra="allow")

    @field_validator("tags", mode="before")
    @classmethod
    def convert_tags_list_to_dict(cls, v: Any) -> dict[str, Any]:
        """Convert List[str] tags to Dict[str, bool] for backward compatibility.

        Allows both formats:
            tags = ["access-control", "auth"]  # Old format -> {"access-control": True, "auth": True}
            tags = { level = 1, category = "auth" }  # New format (preferred)
        """
        if isinstance(v, list):
            return dict.fromkeys(v, True)
        if v is None:
            return {}
        return v


# =============================================================================
# Context Configuration (Interactive Context Collection)
# =============================================================================


class ContextDefinitionConfig(BaseModel):
    """Configuration for a context key from TOML [context.key] section.

    Defines how a context key should be prompted, validated, and stored.
    This enables declarative context prompts instead of hardcoded Python dicts.

    Example:
        ```toml
        [context.maintainers]
        type = "list_or_path"
        prompt = "Who are the project maintainers?"
        hint = "Provide GitHub usernames or path to MAINTAINERS.md"
        examples = ["@user1, @user2", "MAINTAINERS.md"]
        affects = ["OSPS-GV-01.01", "OSPS-GV-01.02", "OSPS-GV-04.01"]
        store_as = "governance.maintainers"
        auto_detect = false
        required = false
        hint_sources = ["CODEOWNERS", ".github/CODEOWNERS", "MAINTAINERS.md"]
        allow_sieve_hints = true
        ```
    """
    # Type of the context value (for validation)
    type: str  # boolean, string, enum, list, path, list_or_path, email, url

    # The question to ask the user
    prompt: str

    # Additional hint to help the user
    hint: str | None = None

    # Example values to show the user
    examples: list[str] = Field(default_factory=list)

    # For enum type - the allowed values
    values: list[str] | None = None

    # Control IDs that are affected by this context
    affects: list[str] = Field(default_factory=list)

    # Where to store in .project/ (e.g., "governance.maintainers")
    store_as: str | None = None

    # Whether this can be auto-detected from repo structure
    auto_detect: bool = False

    # Method to use for auto-detection (e.g., "github_collaborators")
    auto_detect_method: str | None = None

    # Whether this context is required for accurate audit
    required: bool = False

    # Files to check for authoritative values (e.g., CODEOWNERS, MAINTAINERS.md)
    # If any of these files exist, they can be referenced instead of providing values directly
    hint_sources: list[str] = Field(default_factory=list)

    # Whether to show sieve-detected values as hints when no authoritative file exists
    # If True, sieve results (git history, manifests, API) are shown for user confirmation
    # If False, only ask user directly without showing guesses
    allow_sieve_hints: bool = False

    # Handler-based auto-detection pipeline
    # Each entry is a handler invocation processed through the confidence gradient:
    # deterministic handlers first, then pattern, then llm, then manual/confirm
    # Example:
    #   detect = [
    #       { handler = "exec", command = ["gh", "api", "/repos/$OWNER/$REPO/collaborators"], phase = "deterministic" },
    #       { handler = "regex", file = "MAINTAINERS.md", pattern = "@(\\w+)", phase = "pattern" },
    #   ]
    detect: list[HandlerInvocation] | None = None

    model_config = ConfigDict(extra="allow")


class ContextRequirement(BaseModel):
    """Defines when context needs user confirmation before remediation.

    This model enables TOML-driven context requirements for remediations.
    Instead of hardcoding confirmation logic in each remediation function,
    requirements are declared in TOML and the orchestrator handles prompting.

    Example TOML:
        ```toml
        [controls."OSPS-GV-04.01".remediation]
        handler = "create_codeowners"

        [[controls."OSPS-GV-04.01".remediation.requires_context]]
        key = "maintainers"
        required = true
        confidence_threshold = 0.9
        prompt_if_auto_detected = true
        warning = "GitHub collaborators are not necessarily project maintainers"
        ```

    The orchestrator checks these requirements before running the remediation:
    1. If context is missing → prompt user
    2. If context is AUTO_DETECTED and prompt_if_auto_detected → prompt user
    3. If context confidence < threshold → prompt user
    4. Otherwise → proceed with remediation
    """
    # Context key name (e.g., "maintainers", "has_releases")
    key: str

    # Whether this context MUST be confirmed to proceed
    # If False, remediation can proceed without but may use defaults
    required: bool = True

    # Confidence threshold (0.0-1.0)
    # Values with confidence below this trigger a prompt
    confidence_threshold: float = 0.9

    # Whether to prompt even if value was auto-detected
    # True = always ask user to confirm auto-detected values
    # False = trust auto-detection if confidence >= threshold
    prompt_if_auto_detected: bool = True

    # Warning message shown when prompting
    # Explains why confirmation is needed
    warning: str | None = None

    model_config = ConfigDict(extra="allow")


class FrameworkContextConfig(BaseModel):
    """Container for all context definitions from [context] section.

    Groups all context key definitions together. Each key in the context
    section becomes a ContextDefinitionConfig.

    Example TOML:
        ```toml
        [context]
        # Context definitions follow

        [context.has_releases]
        type = "boolean"
        prompt = "Does this project make releases?"
        affects = ["OSPS-BR-02.01"]

        [context.maintainers]
        type = "list_or_path"
        prompt = "Who are the maintainers?"
        affects = ["OSPS-GV-01.01"]
        ```
    """
    # Dictionary of context key -> definition
    # This is populated by the TOML loader from [context.key] sections
    definitions: dict[str, ContextDefinitionConfig] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def transform_toml_structure(cls, data: Any) -> Any:
        """Transform TOML [context.key] structure to {definitions: {key: ...}}.

        TOML structure:
            [context.maintainers]
            type = "list_or_path"
            ...

        Gets parsed as:
            {"maintainers": {"type": "list_or_path", ...}}

        We transform to:
            {"definitions": {"maintainers": {"type": "list_or_path", ...}}}
        """
        if isinstance(data, dict):
            # If 'definitions' already exists, pass through as-is
            if "definitions" in data:
                return data

            # Otherwise, treat all keys as context definitions
            # (except known metadata keys if any)
            definitions = {}
            for key, value in data.items():
                # Each context key should have a 'type' field
                if isinstance(value, dict) and "type" in value:
                    definitions[key] = value
            if definitions:
                return {"definitions": definitions}
        return data

    def get_definition(self, key: str) -> ContextDefinitionConfig | None:
        """Get the definition for a context key."""
        return self.definitions.get(key)

    def get_definitions_for_control(self, control_id: str) -> dict[str, ContextDefinitionConfig]:
        """Get all context definitions that affect a specific control."""
        return {
            key: defn
            for key, defn in self.definitions.items()
            if control_id in defn.affects
        }

    def get_all_affected_controls(self) -> set:
        """Get all control IDs that are affected by context."""
        controls: set = set()
        for defn in self.definitions.values():
            controls.update(defn.affects)
        return controls


# =============================================================================
# Plugin Configuration
# =============================================================================


class PluginConfig(BaseModel):
    """Configuration for a plugin/extension.

    Plugins extend the framework with additional handlers, passes, and templates.
    Each plugin can be configured with version constraints and security settings.

    Example:
        ```toml
        [plugins."darnit-baseline"]
        version = ">=1.0.0"
        allow_unsigned = false
        trusted_publishers = ["kusari-oss"]

        [plugins."my-custom-plugin"]
        version = ">=0.5.0,<2.0.0"
        allow_unsigned = true
        ```

    Security:
        By default, plugins must be signed via Sigstore. Set allow_unsigned=true
        to allow unsigned plugins (NOT recommended for production). The
        trusted_publishers list specifies GitHub organizations/users whose
        signatures are trusted.
    """
    # Version constraint (pip-style specifier)
    # Examples: ">=1.0.0", ">=1.0.0,<2.0.0", "==1.2.3"
    version: str | None = None

    # Whether to allow unsigned packages (default: False for security)
    # If False, plugin must be signed via Sigstore
    allow_unsigned: bool = False

    # List of trusted Sigstore publishers (GitHub orgs or users)
    # If empty and allow_unsigned=False, any valid Sigstore signature is accepted
    # If non-empty, only signatures from these publishers are accepted
    trusted_publishers: list[str] = Field(default_factory=list)

    # Whether this plugin is required (fail audit if not installed)
    required: bool = False

    # Plugin-specific configuration passed to plugin initialization
    config: dict[str, Any] = Field(default_factory=dict)

    model_config = ConfigDict(extra="allow")


class PluginsConfig(BaseModel):
    """Container for plugin configurations.

    Groups all plugin definitions together. Each key in the plugins
    section is the plugin package name.

    Example TOML:
        ```toml
        [plugins]
        # Plugin definitions follow

        [plugins."darnit-baseline"]
        version = ">=1.0.0"

        [plugins."darnit-custom"]
        version = ">=0.1.0"
        allow_unsigned = true
        ```
    """
    # Dictionary of plugin name -> configuration
    plugins: dict[str, PluginConfig] = Field(default_factory=dict)

    # Global settings for plugin loading
    # If True, allow any unsigned plugin (overrides per-plugin setting)
    global_allow_unsigned: bool = False

    # Global list of trusted publishers (merged with per-plugin lists)
    global_trusted_publishers: list[str] = Field(default_factory=list)

    model_config = ConfigDict(extra="allow")

    @model_validator(mode="before")
    @classmethod
    def transform_toml_structure(cls, data: Any) -> Any:
        """Transform TOML [plugins.name] structure to {plugins: {name: ...}}.

        TOML structure:
            [plugins."darnit-baseline"]
            version = ">=1.0.0"
            ...

        Gets parsed as:
            {"darnit-baseline": {"version": ">=1.0.0", ...}}

        We transform to:
            {"plugins": {"darnit-baseline": {"version": ">=1.0.0", ...}}}
        """
        if isinstance(data, dict):
            # If 'plugins' already exists, pass through as-is
            if "plugins" in data:
                return data

            # Check for global settings
            global_allow_unsigned = data.pop("global_allow_unsigned", False)
            global_trusted_publishers = data.pop("global_trusted_publishers", [])

            # Treat remaining keys as plugin names
            plugins = {}
            for key, value in list(data.items()):
                if isinstance(value, dict):
                    plugins[key] = value

            return {
                "plugins": plugins,
                "global_allow_unsigned": global_allow_unsigned,
                "global_trusted_publishers": global_trusted_publishers,
            }
        return data

    def get_plugin_config(self, name: str) -> PluginConfig | None:
        """Get configuration for a specific plugin."""
        return self.plugins.get(name)

    def is_plugin_trusted(self, name: str, publisher: str | None = None) -> bool:
        """Check if a plugin/publisher combination is trusted.

        Args:
            name: Plugin package name
            publisher: Sigstore publisher identity (optional)

        Returns:
            True if the plugin is allowed to run
        """
        plugin_config = self.plugins.get(name)

        # Check global unsigned allowance
        if self.global_allow_unsigned:
            return True

        # Check per-plugin unsigned allowance
        if plugin_config and plugin_config.allow_unsigned:
            return True

        # If no publisher, unsigned is not allowed
        if publisher is None:
            return False

        # Check trusted publishers (global + per-plugin)
        trusted = set(self.global_trusted_publishers)
        if plugin_config:
            trusted.update(plugin_config.trusted_publishers)

        # Empty trusted list means any valid signature is accepted
        if not trusted:
            return True

        return publisher in trusted


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
    spec_version: str | None = None  # e.g., "OSPS v2025.10.10"
    description: str | None = None
    url: str | None = None  # Link to spec

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
        module = "darnit_baseline.tools"

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
    adapters: dict[str, AdapterConfig] = Field(default_factory=dict)

    # Template definitions for remediation
    templates: dict[str, TemplateConfig] = Field(default_factory=dict)

    # Shared handler definitions (cached per audit run)
    shared_handlers: dict[str, SharedHandlerConfig] = Field(default_factory=dict)

    # Control definitions
    controls: dict[str, ControlConfig] = Field(default_factory=dict)

    # Control groups (for batch configuration)
    control_groups: dict[str, dict[str, Any]] = Field(default_factory=dict)

    # Context definitions (for interactive context collection)
    context: FrameworkContextConfig = Field(default_factory=FrameworkContextConfig)

    # Plugin configurations (for extending framework with additional handlers)
    plugins: PluginsConfig = Field(default_factory=PluginsConfig)

    model_config = ConfigDict(extra="allow")

    # =========================================================================
    # Convenience Methods
    # =========================================================================

    def get_controls_by_level(self, level: int) -> dict[str, ControlConfig]:
        """Get all controls at a specific maturity level.

        Note: Controls without a level (level=None) are not included.
        """
        return {
            control_id: control
            for control_id, control in self.controls.items()
            if control.level == level
        }

    def get_controls_by_domain(self, domain: str) -> dict[str, ControlConfig]:
        """Get all controls in a specific domain.

        Note: Controls without a domain (domain=None) are not included.
        """
        return {
            control_id: control
            for control_id, control in self.controls.items()
            if control.domain == domain
        }

    def get_adapter_config(self, name: str) -> AdapterConfig | None:
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
        return self.defaults.remediation_adapter


# =============================================================================
# Factory Functions
# =============================================================================


def create_framework_config(
    name: str,
    display_name: str,
    version: str = "0.1.0",
    spec_version: str | None = None,
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
