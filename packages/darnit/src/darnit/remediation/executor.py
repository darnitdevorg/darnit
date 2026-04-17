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

from __future__ import annotations

import json
import os
import subprocess
from dataclasses import dataclass
from datetime import datetime
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from jinja2 import Environment

from darnit.config.framework_schema import (
    ProjectUpdateRemediationConfig,
    RemediationConfig,
    TemplateConfig,
)
from darnit.config.when_evaluator import evaluate_when
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
    needs_review: bool = False  # True when safe=false — changes may alter behavior

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
                    # Check for llm_enhance in handler results
                    for item in value:
                        if isinstance(item, dict) and "llm_enhance" in item:
                            enhance = item["llm_enhance"]
                            lines.append("")
                            lines.append(f"**AI Enhancement Available** for `{enhance.get('file_path', '')}`:")
                            lines.append(f"> {enhance.get('prompt', '')}")
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

    Templates use Jinja2 with non-colliding delimiters (<< >> for variables,
    <% %> for blocks) so that GitHub Actions ${{ }}, shell $VAR, and other
    dollar-sign syntaxes pass through untouched.

    Available template variables:
    - << OWNER >> - Repository owner
    - << REPO >> - Repository name
    - << BRANCH >> - Default branch
    - << PATH >> - Local repository path
    - << YEAR >> - Current year
    - << DATE >> - Current date (ISO format)
    - << CONTROL >> - Control ID being remediated
    - << context.KEY >> - Confirmed project context values
    - << project.KEY >> - Values from .project/project.yaml
    - << scan.KEY >> - Repo scanner results
    - << scan.KEY | default('fallback') >> - With Jinja2 default filter
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
        scan_values: dict[str, Any] | None = None,
        framework_path: str | None = None,
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
            scan_values: Repo scan values for ${scan.*} substitution.
                Populated by the implementation's repo scanner with detected
                languages, CI tools, directory structure, etc.
            framework_path: Absolute path to the framework TOML file.
                Template ``file`` references are resolved relative to this
                file's directory.  Falls back to ``local_path`` when None.
        """
        self.local_path = os.path.abspath(local_path)
        self.templates = templates or {}
        self._framework_path = framework_path
        self.default_branch = default_branch
        self._context_values = context_values or {}
        self._project_values = project_values or {}
        self._scan_values = scan_values or {}

        # Auto-detect owner/repo if not provided
        if not owner or not repo:
            detected = detect_repo_from_git(local_path)
            if detected:
                owner = owner or detected.get("owner")
                repo = repo or detected.get("repo")

        self.owner = owner
        self.repo = repo

    def _get_template_context(self, control_id: str) -> dict[str, Any]:
        """Build the Jinja2 template context dictionary.

        Returns a flat dict with all variable namespaces:
        - Top-level: OWNER, REPO, BRANCH, PATH, YEAR, DATE, CONTROL
        - context.*: From confirmed context values
        - project.*: From .project/project.yaml
        - scan.*: From repo scanner results

        Jinja2 templates access these as e.g. ``<< REPO >>`` or
        ``<< context.maintainers >>``.
        """
        now = datetime.now()
        ctx: dict[str, Any] = {
            "OWNER": self.owner or "",
            "REPO": self.repo or "",
            "BRANCH": self.default_branch,
            "PATH": self.local_path,
            "YEAR": str(now.year),
            "DATE": now.strftime("%Y-%m-%d"),
            "CONTROL": control_id,
        }

        # Build nested context/project/scan namespaces
        context_ns: dict[str, str] = {}
        if self._context_values:
            for key, value in self._context_values.items():
                if isinstance(value, str):
                    context_ns[key] = value
                elif isinstance(value, list):
                    context_ns[key] = " ".join(str(v) for v in value)
                elif value is not None:
                    context_ns[key] = str(value)
        ctx["context"] = context_ns

        project_ns: dict[str, str] = {}
        if self._project_values:
            for key, value in self._project_values.items():
                if isinstance(value, str):
                    project_ns[key] = value
                elif value is not None:
                    project_ns[key] = str(value)
        ctx["project"] = project_ns

        scan_ns: dict[str, str] = {}
        if self._scan_values:
            for key, value in self._scan_values.items():
                # Strip "scan." prefix if present — the namespace is implicit
                bare_key = key.removeprefix("scan.")
                if isinstance(value, str) and value:
                    scan_ns[bare_key] = value
        ctx["scan"] = scan_ns

        return ctx

    def _get_jinja_env(self) -> Environment:
        """Create a Jinja2 environment with non-colliding delimiters.

        Uses ``<< >>`` for variables and ``<% %>`` for blocks so that
        GitHub Actions ``${{ }}`` and shell ``$VAR`` pass through untouched.
        """
        import jinja2

        return jinja2.Environment(
            variable_start_string="<<",
            variable_end_string=">>",
            block_start_string="<%",
            block_end_string="%>",
            comment_start_string="<#",
            comment_end_string="#>",
            keep_trailing_newline=True,
            undefined=jinja2.Undefined,  # Missing vars render as empty string
        )

    def _substitute(self, text: str, control_id: str) -> str:
        """Render template text using Jinja2.

        Uses ``<< var >>`` delimiters for variables and ``<% %>`` for blocks,
        avoiding collisions with GitHub Actions ``${{ }}``, shell ``$VAR``,
        and other dollar-sign syntaxes.
        """
        env = self._get_jinja_env()
        template = env.from_string(text)
        ctx = self._get_template_context(control_id)
        return template.render(ctx)

    def _substitute_command(self, command: list[str], control_id: str) -> list[str]:
        """Substitute variables in command list using Jinja2."""
        env = self._get_jinja_env()
        ctx = self._get_template_context(control_id)
        result = []
        for arg in command:
            template = env.from_string(arg)
            result.append(template.render(ctx))
        return result

    # Keep legacy method for backward compatibility with _get_substitutions
    # callers (e.g., orchestrator manual steps)
    def _get_substitutions(self, control_id: str) -> dict[str, str]:
        """Get variable substitutions as a flat $VAR / ${var} dict.

        This is a compatibility shim for code that still uses string
        replacement (e.g., manual remediation steps in the orchestrator).
        New code should use _get_template_context() + Jinja2 instead.
        """
        ctx = self._get_template_context(control_id)
        subs: dict[str, str] = {}

        # Top-level vars as $VAR
        for key in ("OWNER", "REPO", "BRANCH", "PATH", "YEAR", "DATE", "CONTROL"):
            subs[f"${key}"] = ctx.get(key, "")

        # Namespace vars as ${namespace.key}
        for ns in ("context", "project", "scan"):
            ns_dict = ctx.get(ns, {})
            if isinstance(ns_dict, dict):
                for key, value in ns_dict.items():
                    if value:
                        subs[f"${{{ns}.{key}}}"] = value

        return subs

    def _get_template_content(self, template_name: str) -> str | None:
        """Get content from a template by name.

        Resolves template file paths relative to the framework TOML location
        to allow plugins to ship templates alongside their configuration.
        Falls back to local_path (repository root) if framework_path is unavailable.

        Future Enhancement: Remote Template Sources
        -------------------------------------------
        For shared templates across organizations or projects:
        - HTTP/HTTPS URLs with local caching: `file = "https://example.com/security.md"`
          (Requires: `file_sha256 = "..."` for integrity)
        - Template registries (like npm/PyPI for templates): `file = "registry://openssf/policy@1.0"`

        These require careful security consideration (trust, integrity, availability).
        """
        template = self.templates.get(template_name)
        if not template:
            return None

        if template.content:
            return template.content

        if template.file:
            # Resolve relative paths against the framework TOML directory
            # so that implementation packages can ship templates alongside
            # their TOML config.  Falls back to local_path when no
            # framework_path is available.
            from pathlib import Path
            template_path = Path(template.file)

            if template_path.is_absolute():
                raise ValueError(
                    f"Template '{template_name}' specifies absolute path '{template.file}'. "
                    f"Template files must be relative paths within the plugin package."
                )

            if self._framework_path:
                base_dir = Path(self._framework_path).parent.resolve()
            else:
                base_dir = Path(self.local_path).resolve()

            resolved = (base_dir / template_path).resolve()
            try:
                resolved.relative_to(base_dir)
            except ValueError as err:
                raise ValueError(
                    f"Template '{template_name}' resolves to {resolved}, outside framework "
                    f"directory {base_dir}. Template files must live within "
                    f"the plugin package."
                ) from err

            try:
                with open(resolved) as f:
                    return f.read()
            except OSError as e:
                logger.warning(f"Failed to read template file {resolved}: {e}")
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
                apply_project_update(self.local_path, config.project_update, control_id)
                result.details["project_update"] = "applied"
            except (OSError, RuntimeError, ValueError) as e:
                logger.warning(f"Remediation for {control_id} succeeded but project_update failed: {e}")
                result.details["project_update"] = f"failed: {e}"
        elif result.success and dry_run and config.project_update:
            result.details["project_update"] = f"would set: {config.project_update.set}"

        return result

    def _execute_handler_invocations(
        self,
        control_id: str,
        config: RemediationConfig,
        dry_run: bool,
    ) -> RemediationResult:
        """Execute handler-based remediation invocations.

        Iterates config.handlers (flat list) and dispatches each through
        the sieve handler registry. Respects ``when`` clauses on individual
        handlers and the ``strategy`` field on RemediationConfig.
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

        # Assemble flat context for when-clause evaluation
        when_context: dict[str, Any] = dict(self._project_values)
        when_context.update(self._context_values)
        # Include scan values so when-clauses can match on detected CI tools
        # (e.g., scan.ci_sast_tools, scan.ci_sca_tools)
        when_context.update(self._scan_values)

        results: list[dict[str, Any]] = []
        all_success = True
        first_match = config.strategy == "first_match"
        matched_any = False

        for invocation in config.handlers:
            # Evaluate when clause — skip handler if condition not met
            if invocation.when and not evaluate_when(invocation.when, when_context):
                logger.debug(
                    "Control %s: remediation handler '%s' skipped (when clause not met: %s)",
                    control_id,
                    invocation.handler,
                    invocation.when,
                )
                continue

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
                results.append(
                    {
                        "handler": invocation.handler,
                        "status": "dry_run",
                        "message": f"Would execute handler: {invocation.handler}",
                        "config": handler_config,
                    }
                )
                matched_any = True
                if first_match:
                    break
                continue

            handler_info = registry.get(invocation.handler)
            if not handler_info:
                results.append(
                    {
                        "handler": invocation.handler,
                        "status": "error",
                        "message": f"Handler '{invocation.handler}' not found",
                    }
                )
                all_success = False
                matched_any = True
                if first_match:
                    break
                continue

            try:
                handler_result = handler_info.fn(handler_config, handler_ctx)
                result_entry: dict[str, Any] = {
                    "handler": invocation.handler,
                    "status": handler_result.status.value,
                    "message": handler_result.message,
                }
                # Propagate handler evidence — needed for llm_consultation,
                # llm_verification_required, and other handler-to-agent signals.
                if handler_result.evidence:
                    result_entry["evidence"] = handler_result.evidence
                results.append(result_entry)
                # Propagate llm_enhance metadata for AI-assisted file customization
                if handler_result.status == HandlerResultStatus.PASS and "llm_enhance" in handler_config:
                    results[-1]["llm_enhance"] = {
                        "prompt": handler_config["llm_enhance"],
                        "file_path": handler_config.get("path", ""),
                    }
                if handler_result.status in (HandlerResultStatus.FAIL, HandlerResultStatus.ERROR):
                    all_success = False
            except (
                RuntimeError,
                ValueError,
                OSError,
                subprocess.SubprocessError,
            ) as e:
                results.append(
                    {
                        "handler": invocation.handler,
                        "status": "error",
                        "message": str(e),
                    }
                )
                all_success = False

            matched_any = True
            if first_match:
                break

        # Handle first_match with no matching handlers
        if first_match and not matched_any:
            unmatched = [str(inv.when) for inv in config.handlers if inv.when]
            return RemediationResult(
                success=False,
                message=(
                    "No applicable remediation handler matched the project context. "
                    f"Unmatched conditions: {', '.join(unmatched)}"
                    if unmatched
                    else "No remediation handlers configured"
                ),
                control_id=control_id,
                remediation_type="handler_pipeline",
                dry_run=dry_run,
                details={"handlers": results, "strategy": "first_match"},
            )

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
        project_dir = os.path.join(local_path, ".project")
        if os.path.isdir(project_dir):
            # .project/ exists but config failed validation — do NOT overwrite
            # with a blank config as that would destroy existing extension data
            # (context, ci settings, etc. in darnit.yaml)
            logger.warning(f"Skipping project_update for {control_id}: .project/ exists but config failed validation")
            return
        if not project_update.create_if_missing:
            logger.debug(f"No .project/ found for {control_id} and create_if_missing=False")
            return
        config = ProjectConfig(name="unknown")

    # Apply each dotted path update
    for dotted_path, value in project_update.set.items():
        _set_nested_value(config, dotted_path, value)
        logger.debug(f"project_update for {control_id}: set {dotted_path} = {value}")

    # Save
    save_project_config(config, local_path)
    logger.info(f"Applied project_update for {control_id}: set {len(project_update.set)} values")


def _coerce_to_field_type(obj: object, field_name: str, value: object) -> object:
    """Coerce a value to match the expected Pydantic field type.

    When setting a string value to a field that expects a Pydantic model
    (e.g., PathRef), constructs the model with path=value. This handles
    the common case where on_pass auto-derives set documentation.readme
    to a string like "README.md", but the field expects PathRef(path=...).

    Returns the coerced value, or the original value if coercion isn't needed.
    """
    import types

    from pydantic import BaseModel

    if not isinstance(obj, BaseModel) or not isinstance(value, str):
        return value

    field_info = type(obj).model_fields.get(field_name)
    if not field_info or not field_info.annotation:
        return value

    annotation = field_info.annotation

    # Find BaseModel type from annotation (handles X | None unions)
    model_type = None
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        model_type = annotation
    else:
        args = getattr(annotation, "__args__", ())
        if args and (isinstance(annotation, types.UnionType) or getattr(annotation, "__origin__", None) is not None):
            for arg in args:
                if isinstance(arg, type) and issubclass(arg, BaseModel):
                    model_type = arg
                    break

    if model_type is None:
        return value  # Field doesn't expect a BaseModel — use string as-is

    # Try constructing the model with path=value (PathRef pattern)
    try:
        return model_type(path=value)
    except (TypeError, ValueError):
        pass

    return value


def _create_field_default(obj: object, field_name: str) -> object:
    """Create a default instance for a Pydantic model field.

    When a Pydantic model field is None and we need to set a nested value,
    this creates the correct type (e.g., SecurityConfig, PathRef) instead
    of a raw dict, which would corrupt the config on serialization.

    Returns:
        An instance of the expected field type, or {} as fallback.
    """
    import types

    from pydantic import BaseModel

    if isinstance(obj, BaseModel):
        field_info = type(obj).model_fields.get(field_name)
        if field_info and field_info.annotation:
            annotation = field_info.annotation

            # Direct model type (e.g., SecurityConfig)
            if isinstance(annotation, type) and issubclass(annotation, BaseModel):
                try:
                    return annotation()
                except (TypeError, ValueError):
                    pass

            # Union type (X | Y or Optional[X]) — find a BaseModel subclass
            args = getattr(annotation, "__args__", ())
            if args and (
                isinstance(annotation, types.UnionType) or getattr(annotation, "__origin__", None) is not None
            ):
                for arg in args:
                    if isinstance(arg, type) and issubclass(arg, BaseModel):
                        try:
                            return arg()
                        except (TypeError, ValueError):
                            break
    return {}


def _set_nested_value(obj: object, dotted_path: str, value: object) -> None:
    """Set a nested attribute/dict value using a dotted path.

    Supports both attribute access (for Pydantic models) and dict access.
    Creates intermediate Pydantic models as needed, constructing them with
    the correct field values to avoid schema corruption.

    For example, setting "documentation.readme.path" = "README.md" on a
    ProjectConfig creates DocumentationConfig(readme=PathRef(path="README.md"))
    rather than raw dicts.

    Args:
        obj: Root object to update
        dotted_path: Dot-separated path (e.g., "security.policy.path")
        value: Value to set
    """
    parts = dotted_path.split(".")
    current = obj

    for i, part in enumerate(parts[:-1]):
        if isinstance(current, dict):
            if part not in current:
                current[part] = {}
            current = current[part]
        elif hasattr(current, part):
            next_val = getattr(current, part)
            if next_val is None:
                # Create the expected Pydantic model type
                default = _create_field_default(current, part)
                if isinstance(default, dict):
                    # Fallback dict — but check if the remaining path can be
                    # constructed as a Pydantic model with the leaf value
                    remaining = parts[i + 1 :]
                    model = _try_construct_nested(current, part, remaining, value)
                    if model is not None:
                        try:
                            setattr(current, part, model)
                        except (AttributeError, TypeError, ValueError):
                            pass
                        return  # Fully constructed, done
                    next_val = default
                else:
                    next_val = default
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
        # If the field expects a Pydantic model (e.g., PathRef) and we have
        # a plain string, try constructing the model with the value
        coerced = _coerce_to_field_type(current, final_key, value)
        try:
            setattr(current, final_key, coerced)
        except (AttributeError, TypeError, ValueError) as e:
            logger.warning(f"Could not set {dotted_path} = {value}: {e}")


def _try_construct_nested(parent: object, field_name: str, remaining_parts: list[str], value: object) -> object | None:
    """Try to construct a Pydantic model from a field with nested path values.

    For example, if parent has field 'readme' of type PathRef and remaining
    parts are ['path'] with value 'README.md', constructs PathRef(path='README.md').

    Returns the constructed model, or None if construction isn't possible.
    """
    import types

    from pydantic import BaseModel

    if not isinstance(parent, BaseModel):
        return None

    field_info = type(parent).model_fields.get(field_name)
    if not field_info or not field_info.annotation:
        return None

    annotation = field_info.annotation

    # Find the concrete BaseModel type from the annotation
    model_type = None
    if isinstance(annotation, type) and issubclass(annotation, BaseModel):
        model_type = annotation
    else:
        args = getattr(annotation, "__args__", ())
        if args and (isinstance(annotation, types.UnionType) or getattr(annotation, "__origin__", None) is not None):
            for arg in args:
                if isinstance(arg, type) and issubclass(arg, BaseModel):
                    model_type = arg
                    break

    if model_type is None:
        return None

    # Build nested kwargs from remaining_parts
    # e.g., remaining=['path'], value='README.md' → {'path': 'README.md'}
    # e.g., remaining=['sub', 'key'], value='v' → {'sub': {'key': 'v'}}
    kwargs: dict = {}
    current_dict = kwargs
    for part in remaining_parts[:-1]:
        current_dict[part] = {}
        current_dict = current_dict[part]
    current_dict[remaining_parts[-1]] = value

    try:
        return model_type(**kwargs)
    except (TypeError, ValueError):
        return None


__all__ = [
    "RemediationExecutor",
    "RemediationResult",
    "apply_project_update",
]
