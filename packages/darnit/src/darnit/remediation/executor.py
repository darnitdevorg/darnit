"""Declarative remediation executor.

This module executes remediations defined in the framework TOML files.
It supports four remediation types:
- FileCreate: Create files from templates
- Exec: Execute external commands
- ApiCall: Make GitHub API calls
- Manual: Return structured guidance for non-automatable controls

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
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import Any

from darnit.config.framework_schema import (
    ApiCallRemediationConfig,
    ExecRemediationConfig,
    FileCreateRemediationConfig,
    ProjectUpdateRemediationConfig,
    RemediationConfig,
    TemplateConfig,
)
from darnit.core.logging import get_logger
from darnit.remediation.helpers import (
    detect_repo_from_git,
    ensure_directory,
    write_file_safe,
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

    This executor handles three types of remediations:
    1. FileCreate: Create files from templates with variable substitution
    2. Exec: Execute external commands
    3. ApiCall: Make GitHub API calls using gh CLI

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

        After a successful remediation action, also applies any project_update
        to keep .project/project.yaml in sync with the actual project state.

        Args:
            control_id: The control ID being remediated
            config: Remediation configuration from TOML
            dry_run: If True, show what would be done without making changes

        Returns:
            RemediationResult with execution outcome
        """
        # Try handler-based dispatch first (new format)
        if hasattr(config, "has_handler_invocations") and config.has_handler_invocations():
            return self._execute_handler_invocations(control_id, config, dry_run)

        # Determine which remediation type to use (legacy)
        result = None
        if config.file_create:
            result = self._execute_file_create(control_id, config.file_create, dry_run)
        elif config.exec:
            result = self._execute_exec(control_id, config.exec, dry_run)
        elif config.api_call:
            result = self._execute_api_call(control_id, config.api_call, dry_run)
        elif config.manual:
            details: dict[str, Any] = {"steps": config.manual.steps}
            if config.manual.docs_url:
                details["docs_url"] = config.manual.docs_url
            if config.manual.context_hints:
                details["context_hints"] = config.manual.context_hints
            return RemediationResult(
                success=True,
                message="Manual remediation guidance",
                control_id=control_id,
                remediation_type="manual",
                dry_run=dry_run,
                details=details,
            )
        elif config.handler:
            # Legacy handler reference - return info about it
            return RemediationResult(
                success=False,
                message=f"Legacy handler '{config.handler}' requires Python execution",
                control_id=control_id,
                remediation_type="handler",
                dry_run=dry_run,
                details={
                    "handler": config.handler,
                    "adapter": config.adapter,
                    "note": "Use the implementation package's remediation function",
                },
            )
        else:
            return RemediationResult(
                success=False,
                message="No remediation action configured",
                control_id=control_id,
                remediation_type="none",
                dry_run=dry_run,
                details={},
            )

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

        Dispatches handler invocations through the sieve handler registry.
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

        for phase_name, invocations in config.get_handler_invocations():
            for invocation in invocations:
                handler_info = registry.get(invocation.handler)
                if not handler_info:
                    results.append({
                        "handler": invocation.handler,
                        "status": "error",
                        "message": f"Handler '{invocation.handler}' not found",
                    })
                    all_success = False
                    continue

                handler_config = dict(invocation.model_extra or {})
                handler_config["handler"] = invocation.handler

                if dry_run:
                    results.append({
                        "handler": invocation.handler,
                        "phase": phase_name,
                        "status": "dry_run",
                        "message": f"Would execute handler: {invocation.handler}",
                        "config": handler_config,
                    })
                    continue

                try:
                    handler_result = handler_info.fn(handler_config, handler_ctx)
                    results.append({
                        "handler": invocation.handler,
                        "phase": phase_name,
                        "status": handler_result.status.value,
                        "message": handler_result.message,
                    })
                    if handler_result.status != HandlerResultStatus.PASS:
                        all_success = False
                except Exception as e:
                    results.append({
                        "handler": invocation.handler,
                        "phase": phase_name,
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

    def _execute_file_create(
        self,
        control_id: str,
        config: FileCreateRemediationConfig,
        dry_run: bool,
    ) -> RemediationResult:
        """Execute a file creation remediation."""
        target_path = os.path.join(self.local_path, config.path)

        # Get content from template or inline
        content = None
        template_name = None

        if config.template:
            template_name = config.template
            content = self._get_template_content(config.template)
            if not content:
                return RemediationResult(
                    success=False,
                    message=f"Template '{config.template}' not found",
                    control_id=control_id,
                    remediation_type="file_create",
                    dry_run=dry_run,
                    details={"template": config.template, "path": config.path},
                )
        elif config.content:
            content = config.content
        else:
            return RemediationResult(
                success=False,
                message="No content or template specified",
                control_id=control_id,
                remediation_type="file_create",
                dry_run=dry_run,
                details={"path": config.path},
            )

        # Apply variable substitution
        content = self._substitute(content, control_id)

        # Check if file exists
        file_exists = os.path.exists(target_path)
        if file_exists and not config.overwrite:
            return RemediationResult(
                success=True,
                message=f"File already exists — control may already be satisfied: {config.path}",
                control_id=control_id,
                remediation_type="file_create_skipped",
                dry_run=dry_run,
                details={
                    "path": config.path,
                    "overwrite": config.overwrite,
                    "note": "File exists; set overwrite=true to replace",
                },
            )

        details = {
            "path": config.path,
            "template": template_name,
            "overwrite": config.overwrite,
            "content_preview": content[:200] + "..." if len(content) > 200 else content,
        }

        if dry_run:
            return RemediationResult(
                success=True,
                message=f"Would create file: {config.path}",
                control_id=control_id,
                remediation_type="file_create",
                dry_run=True,
                details=details,
            )

        # Create parent directories if needed
        if config.create_dirs:
            parent_dir = os.path.dirname(target_path)
            if parent_dir:
                error = ensure_directory(parent_dir)
                if error:
                    return RemediationResult(
                        success=False,
                        message=error,
                        control_id=control_id,
                        remediation_type="file_create",
                        dry_run=False,
                        details=details,
                    )

        # Write the file
        success, message = write_file_safe(target_path, content)
        return RemediationResult(
            success=success,
            message=f"Created file: {config.path}" if success else message,
            control_id=control_id,
            remediation_type="file_create",
            dry_run=False,
            details=details,
        )

    def _execute_exec(
        self,
        control_id: str,
        config: ExecRemediationConfig,
        dry_run: bool,
    ) -> RemediationResult:
        """Execute a command remediation."""
        # Substitute variables in command
        command = self._substitute_command(config.command, control_id)

        # Get stdin content if specified
        stdin_content = None
        if config.stdin_template:
            stdin_content = self._get_template_content(config.stdin_template)
            if stdin_content:
                stdin_content = self._substitute(stdin_content, control_id)
        elif config.stdin:
            stdin_content = self._substitute(config.stdin, control_id)

        details = {
            "command": " ".join(command),
            "timeout": config.timeout,
            "success_exit_codes": config.success_exit_codes,
        }
        if stdin_content:
            details["stdin_preview"] = (
                stdin_content[:100] + "..."
                if len(stdin_content) > 100
                else stdin_content
            )

        if dry_run:
            return RemediationResult(
                success=True,
                message=f"Would execute: {' '.join(command)}",
                control_id=control_id,
                remediation_type="exec",
                dry_run=True,
                details=details,
            )

        # Execute the command
        try:
            env = os.environ.copy()
            env.update(config.env)

            result = subprocess.run(
                command,
                input=stdin_content,
                capture_output=True,
                text=True,
                timeout=config.timeout,
                cwd=self.local_path,
                env=env,
            )

            success = result.returncode in config.success_exit_codes
            details["exit_code"] = result.returncode
            details["stdout"] = result.stdout[:500] if result.stdout else ""
            details["stderr"] = result.stderr[:500] if result.stderr else ""

            return RemediationResult(
                success=success,
                message=(
                    "Command succeeded"
                    if success
                    else f"Command failed with exit code {result.returncode}"
                ),
                control_id=control_id,
                remediation_type="exec",
                dry_run=False,
                details=details,
            )

        except subprocess.TimeoutExpired:
            return RemediationResult(
                success=False,
                message=f"Command timed out after {config.timeout}s",
                control_id=control_id,
                remediation_type="exec",
                dry_run=False,
                details=details,
            )
        except FileNotFoundError:
            return RemediationResult(
                success=False,
                message=f"Command not found: {command[0]}",
                control_id=control_id,
                remediation_type="exec",
                dry_run=False,
                details=details,
            )
        except subprocess.SubprocessError as e:
            return RemediationResult(
                success=False,
                message=f"Command error: {str(e)}",
                control_id=control_id,
                remediation_type="exec",
                dry_run=False,
                details=details,
            )

    def _execute_api_call(
        self,
        control_id: str,
        config: ApiCallRemediationConfig,
        dry_run: bool,
    ) -> RemediationResult:
        """Execute a GitHub API call remediation."""
        # Substitute variables in endpoint
        endpoint = self._substitute(config.endpoint, control_id)

        # Get payload
        payload = None
        if config.payload_template:
            payload_content = self._get_template_content(config.payload_template)
            if payload_content:
                payload_content = self._substitute(payload_content, control_id)
                try:
                    payload = json.loads(payload_content)
                except json.JSONDecodeError as e:
                    return RemediationResult(
                        success=False,
                        message=f"Invalid JSON in payload template: {e}",
                        control_id=control_id,
                        remediation_type="api_call",
                        dry_run=dry_run,
                        details={"template": config.payload_template},
                    )
        elif config.payload:
            payload = config.payload

        details = {
            "method": config.method,
            "endpoint": endpoint,
        }
        if payload:
            details["payload"] = payload

        if dry_run:
            return RemediationResult(
                success=True,
                message=f"Would call GitHub API: {config.method} {endpoint}",
                control_id=control_id,
                remediation_type="api_call",
                dry_run=True,
                details=details,
            )

        # Build gh api command
        command = ["gh", "api", "-X", config.method, endpoint]

        if config.jq_filter:
            command.extend(["--jq", config.jq_filter])

        # Execute with payload via stdin
        try:
            result = subprocess.run(
                command + (["--input", "-"] if payload else []),
                input=json.dumps(payload) if payload else None,
                capture_output=True,
                text=True,
                timeout=30,
            )

            success = result.returncode == 0
            details["exit_code"] = result.returncode

            if result.stdout:
                try:
                    details["response"] = json.loads(result.stdout)
                except json.JSONDecodeError:
                    details["response"] = result.stdout[:500]

            if result.stderr:
                details["error"] = result.stderr[:500]

            return RemediationResult(
                success=success,
                message=(
                    "API call succeeded"
                    if success
                    else f"API call failed: {result.stderr[:100]}"
                ),
                control_id=control_id,
                remediation_type="api_call",
                dry_run=False,
                details=details,
            )

        except FileNotFoundError:
            return RemediationResult(
                success=False,
                message="gh CLI not found. Install from https://cli.github.com/",
                control_id=control_id,
                remediation_type="api_call",
                dry_run=False,
                details=details,
            )
        except subprocess.TimeoutExpired:
            return RemediationResult(
                success=False,
                message="API call timed out",
                control_id=control_id,
                remediation_type="api_call",
                dry_run=False,
                details=details,
            )
        except subprocess.SubprocessError as e:
            return RemediationResult(
                success=False,
                message=f"API call error: {str(e)}",
                control_id=control_id,
                remediation_type="api_call",
                dry_run=False,
                details=details,
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
