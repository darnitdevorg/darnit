"""Declarative remediation executor.

This module executes remediations defined in the framework TOML files.
Remediations use a flat ordered list of handler invocations dispatched
through the sieve handler registry.

Example:
    ```python
    from darnit.remediation.executor import RemediationExecutor
    from darnit.config.framework_schema import RemediationConfig

    executor = RemediationExecutor(
        local_path="/path/to/repo",
        owner="myorg",
        repo="myrepo",
        templates=framework.templates,
    )

    result = executor.execute(control_id, remediation_config, dry_run=True)
    ```
"""

import json
import os
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from darnit.config.framework_schema import (
    ProjectUpdateRemediationConfig,
    RemediationConfig,
    TemplateConfig,
)
from darnit.core.logging import get_logger
from darnit.remediation.helpers import (
    detect_repo_from_git,
)

logger = get_logger("remediation.executor")


@dataclass
class RemediationResult:
    """Result of a remediation execution."""

    success: bool
    message: str
    control_id: str
    remediation_type: str  # "file_create", "exec", "api_call", "handler"
    dry_run: bool
    details: dict[str, Any]

    def to_markdown(self) -> str:
        """Format result as markdown."""
        if self.dry_run:
            prefix = "🔍 **DRY RUN**"
        elif self.success:
            prefix = "✅"
        else:
            prefix = "❌"

        lines = [f"{prefix} {self.message}"]

        if self.details:
            lines.append("")
            for key, value in self.details.items():
                if isinstance(value, list):
                    lines.append(f"**{key}:**")
                    for item in value:
                        lines.append(f"  - {item}")
                elif isinstance(value, dict):
                    lines.append(f"**{key}:**")
                    lines.append(f"```json\n{json.dumps(value, indent=2)}\n```")
                else:
                    lines.append(f"**{key}:** {value}")

        return "\n".join(lines)


class RemediationExecutor:
    """Executes declarative remediations from framework TOML configs.

    Dispatches handler invocations from RemediationConfig.handlers through
    the sieve handler registry (file_create, exec, api_call, manual_steps, etc.).

    Variable substitution is supported in templates and commands:
    - $OWNER - Repository owner
    - $REPO - Repository name
    - $BRANCH - Default branch
    - $PATH - Local repository path
    - $YEAR - Current year
    - $DATE - Current date (ISO format)
    - $CONTROL - Control ID being remediated
    """

    def __init__(
        self,
        local_path: str = ".",
        owner: str | None = None,
        repo: str | None = None,
        default_branch: str = "main",
        templates: dict[str, TemplateConfig] | None = None,
        context_values: dict[str, Any] | None = None,
        project_values: dict[str, Any] | None = None,
    ):
        """Initialize the executor.

        Args:
            local_path: Path to the repository
            owner: Repository owner (auto-detected if not provided)
            repo: Repository name (auto-detected if not provided)
            default_branch: Default branch name
            templates: Template definitions from framework config
            context_values: Confirmed context values for ${context.*} substitution
            project_values: Flattened .project/project.yaml for ${project.*} substitution
        """
        self.local_path = os.path.abspath(local_path)
        self.templates = templates or {}
        self.default_branch = default_branch
        self._context_values = context_values or {}
        self._project_values = project_values or {}

        # Auto-detect owner/repo if not provided
        if not owner or not repo:
            detected = detect_repo_from_git(local_path)
            if detected:
                owner = owner or detected.get("owner")
                repo = repo or detected.get("repo")

        self.owner = owner
        self.repo = repo

    def _get_substitutions(self, control_id: str) -> dict[str, str]:
        """Get variable substitutions for templates and commands.

        Includes standard $VAR substitutions and ${context.*} / ${project.*}
        references resolved from confirmed context and project config.
        """
        now = datetime.now()
        subs = {
            "$OWNER": self.owner or "",
            "$REPO": self.repo or "",
            "$BRANCH": self.default_branch,
            "$PATH": self.local_path,
            "$YEAR": str(now.year),
            "$DATE": now.strftime("%Y-%m-%d"),
            "$CONTROL": control_id,
        }

        # Add ${context.*} from confirmed context values
        if self._context_values:
            for key, value in self._context_values.items():
                if isinstance(value, str):
                    subs[f"${{context.{key}}}"] = value
                elif isinstance(value, list):
                    subs[f"${{context.{key}}}"] = ", ".join(str(v) for v in value)
                elif value is not None:
                    subs[f"${{context.{key}}}"] = str(value)

        # Add ${project.*} from .project/project.yaml
        if self._project_values:
            for key, value in self._project_values.items():
                if isinstance(value, str):
                    subs[f"${{project.{key}}}"] = value
                elif value is not None:
                    subs[f"${{project.{key}}}"] = str(value)

        return subs

    def _substitute(self, text: str, control_id: str) -> str:
        """Substitute variables in text.

        Handles both $VAR and ${...} patterns.
        Unresolved ${...} references are replaced with empty string.
        """
        import re

        substitutions = self._get_substitutions(control_id)
        result = text

        # First: resolve ${...} patterns (more specific, match first)
        for var, value in substitutions.items():
            if var.startswith("${") and value:
                result = result.replace(var, value)

        # Replace any remaining unresolved ${...} with empty string
        result = re.sub(r"\$\{[^}]+\}", "", result)

        # Then: resolve standard $VAR patterns
        for var, value in substitutions.items():
            if not var.startswith("${") and value:
                result = result.replace(var, value)

        return result

    def _substitute_command(self, command: list[str], control_id: str) -> list[str]:
        """Substitute variables in command list."""
        substitutions = self._get_substitutions(control_id)
        result = []
        for arg in command:
            modified = arg
            for var, value in substitutions.items():
                if var in modified and value:
                    modified = modified.replace(var, value)
            result.append(modified)
        return result

    def _get_template_content(self, template_name: str) -> str | None:
        """Get content from a template by name.

        # TODO: Enhanced Template File Loading (Future Enhancement)
        # =========================================================
        # Current implementation only supports:
        # - Inline content in TOML
        # - File paths relative to the audited repository (local_path)
        #
        # Primary enhancement: Relative paths from framework TOML location
        # ----------------------------------------------------------------
        # Templates should be resolved relative to the framework TOML file,
        # not the repository being audited. This allows frameworks to bundle
        # templates alongside their TOML definition.
        #
        # Example directory structure:
        #   darnit-baseline/
        #   ├── openssf-baseline.toml
        #   └── templates/
        #       ├── security_policy.md
        #       └── contributing.md
        #
        # Example TOML usage:
        #   [templates.security_policy]
        #   file = "templates/security_policy.md"  # Relative to TOML location
        #
        # Implementation requirements:
        # - Pass framework_path (TOML file location) to executor
        # - Resolve template.file relative to framework_path directory
        # - Fall back to local_path for backward compatibility
        # - Add validation for template existence at config load time
        #
        # Future: Remote template sources (to explore later)
        # ---------------------------------------------------
        # For shared templates across organizations or projects:
        #
        # - HTTP/HTTPS URLs with local caching
        #   Example: `file = "https://example.com/templates/security.md"`
        #   Requires: `file_sha256 = "abc123..."` for integrity
        #
        # - Git repository references
        #   Example: `file = "git://github.com/org/templates#security.md"`
        #
        # - Template registries (like npm/PyPI for templates)
        #   Example: `file = "registry://openssf/security-policy@1.0"`
        #
        # These require careful security consideration (trust, integrity,
        # availability) and should be explored after local file support
        # is solid.
        #
        # Other enhancements:
        # - Template inheritance: `extends = "security_policy_base"`
        # - Template directories: `[metadata] templates_dir = "templates/"`
        # - Caching for performance
        """
        template = self.templates.get(template_name)
        if not template:
            return None

        if template.content:
            return template.content

        if template.file:
            # Template file path is relative to framework package
            # For now, we'll support absolute paths or paths relative to local_path
            template_path = template.file
            if not os.path.isabs(template_path):
                template_path = os.path.join(self.local_path, template_path)

            try:
                with open(template_path) as f:
                    return f.read()
            except OSError as e:
                logger.warning(f"Failed to read template file {template_path}: {e}")
                return None

        return None

    def execute(
        self,
        control_id: str,
        config: RemediationConfig,
        dry_run: bool = True,
    ) -> RemediationResult:
        """Execute a remediation based on its configuration.

        Dispatches handler invocations from config.handlers in order.
        After a successful remediation, applies any project_update
        to keep .project/project.yaml in sync.

        Args:
            control_id: The control ID being remediated
            config: Remediation configuration from TOML
            dry_run: If True, show what would be done without making changes

        Returns:
            RemediationResult with execution outcome
        """
        if not config.handlers:
            return RemediationResult(
                success=False,
                message="No remediation handlers configured",
                control_id=control_id,
                remediation_type="none",
                dry_run=dry_run,
                details={},
            )

        result = self._execute_handler_invocations(control_id, config, dry_run)

        # Apply project_update if the primary remediation succeeded
        if result.success and not dry_run and config.project_update:
            try:
                apply_project_update(
                    self.local_path, config.project_update, control_id
                )
                result.details["project_update"] = "applied"
            except Exception as e:
                logger.warning(
                    f"Remediation for {control_id} succeeded but "
                    f"project_update failed: {e}"
                )
                result.details["project_update"] = f"failed: {e}"
        elif result.success and dry_run and config.project_update:
            result.details["project_update"] = (
                f"would set: {config.project_update.set}"
            )

        return result

    def _execute_handler_invocations(
        self,
        control_id: str,
        config: RemediationConfig,
        dry_run: bool,
    ) -> RemediationResult:
        """Execute handler-based remediation invocations.

        Iterates config.handlers (flat list) and dispatches each through
        the sieve handler registry.
        """
        from darnit.sieve.handler_registry import (
            HandlerContext,
            HandlerResultStatus,
            get_sieve_handler_registry,
        )

        registry = get_sieve_handler_registry()
        handler_ctx = HandlerContext(
            local_path=self.local_path,
            owner=self.owner or "",
            repo=self.repo or "",
            default_branch=self.default_branch,
            control_id=control_id,
            project_context=dict(self._project_values),
        )

        results: list[dict[str, Any]] = []
        all_success = True

        for invocation in config.handlers:
            handler_config = dict(invocation.model_extra or {})
            handler_config["handler"] = invocation.handler

            # Resolve template references to content
            if "template" in handler_config and "content" not in handler_config:
                template_name = handler_config["template"]
                content = self._get_template_content(template_name)
                if content:
                    content = self._substitute(content, control_id)
                    handler_config["content"] = content

            if dry_run:
                results.append({
                    "handler": invocation.handler,
                    "status": "dry_run",
                    "message": f"Would execute handler: {invocation.handler}",
                    "config": handler_config,
                })
                continue

            handler_info = registry.get(invocation.handler)
            if not handler_info:
                results.append({
                    "handler": invocation.handler,
                    "status": "error",
                    "message": f"Handler '{invocation.handler}' not found",
                })
                all_success = False
                continue

            try:
                handler_result = handler_info.fn(handler_config, handler_ctx)
                results.append({
                    "handler": invocation.handler,
                    "status": handler_result.status.value,
                    "message": handler_result.message,
                })
                if handler_result.status != HandlerResultStatus.PASS:
                    all_success = False
            except Exception as e:
                results.append({
                    "handler": invocation.handler,
                    "status": "error",
                    "message": str(e),
                })
                all_success = False

        return RemediationResult(
            success=all_success,
            message=(
                f"Executed {len(results)} remediation handler(s)"
                if not dry_run
                else f"Would execute {len(results)} remediation handler(s)"
            ),
            control_id=control_id,
            remediation_type="handler_pipeline",
            dry_run=dry_run,
            details={"handlers": results},
        )

def apply_project_update(
    local_path: str,
    project_update: ProjectUpdateRemediationConfig,
    control_id: str,
) -> None:
    """Apply a project_update to .project/project.yaml.

    Updates the project configuration with values specified in the
    project_update config. Uses dotted paths to set nested values.

    Args:
        local_path: Path to the repository root
        project_update: Configuration specifying what to update
        control_id: Control ID for logging context

    Raises:
        RuntimeError: If .project/ cannot be created or updated

    Example:
        Given project_update.set = {"security.policy.path": "SECURITY.md"},
        this updates .project/project.yaml:

            security:
              policy:
                path: SECURITY.md
    """
    if not project_update.set:
        return

    try:
        from darnit.config.loader import load_project_config, save_project_config
        from darnit.config.schema import ProjectConfig
    except ImportError as e:
        logger.warning(f"Config loader not available for project_update: {e}")
        return

    # Load or create project config
    config = load_project_config(local_path)
    if config is None:
        if not project_update.create_if_missing:
            logger.debug(
                f"No .project/ found for {control_id} and create_if_missing=False"
            )
            return
        config = ProjectConfig(name="unknown")

    # Apply each dotted path update
    for dotted_path, value in project_update.set.items():
        _set_nested_value(config, dotted_path, value)
        logger.debug(f"project_update for {control_id}: set {dotted_path} = {value}")

    # Save
    save_project_config(config, local_path)
    logger.info(
        f"Applied project_update for {control_id}: "
        f"set {len(project_update.set)} values"
    )


def _set_nested_value(obj: object, dotted_path: str, value: object) -> None:
    """Set a nested attribute/dict value using a dotted path.

    Supports both attribute access (for Pydantic models) and dict access.
    Creates intermediate dicts as needed.

    Args:
        obj: Root object to update
        dotted_path: Dot-separated path (e.g., "security.policy.path")
        value: Value to set
    """
    parts = dotted_path.split(".")
    current = obj

    for part in parts[:-1]:
        if isinstance(current, dict):
            if part not in current:
                current[part] = {}
            current = current[part]
        elif hasattr(current, part):
            next_val = getattr(current, part)
            if next_val is None:
                # Try to create the expected type
                next_val = {}
                try:
                    setattr(current, part, next_val)
                except (AttributeError, TypeError, ValueError):
                    pass
            current = next_val
        else:
            # Create as dict
            new_dict: dict = {}
            try:
                setattr(current, part, new_dict)
            except (AttributeError, TypeError, ValueError):
                pass
            current = new_dict

    # Set the final value
    final_key = parts[-1]
    if isinstance(current, dict):
        current[final_key] = value
    else:
        try:
            setattr(current, final_key, value)
        except (AttributeError, TypeError, ValueError) as e:
            logger.warning(
                f"Could not set {dotted_path} = {value}: {e}"
            )


__all__ = [
    "RemediationExecutor",
    "RemediationResult",
    "apply_project_update",
]
