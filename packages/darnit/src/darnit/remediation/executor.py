"""Declarative remediation executor.

This module executes remediations defined in the framework TOML files.
Remediations use a flat ordered list of handler invocations dispatched
through the sieve handler registry.

Feature 043 (research R6): the executor is the single writer. Remediation
handlers registered with ``supports_plan`` return the files they would change
as :class:`~darnit.remediation.plan.FileChange` entries and never write. A
preview (``dry_run=True``, plan mode) runs them with ``mode="plan"`` and
returns :class:`~darnit.remediation.plan.PlanItem` entries; handlers without
plan support are listed as not previewable and are not invoked. An apply runs
the plan first (so a key that needs confirmation stops it before any write,
feature 042), then runs every handler with ``mode="apply"``, writes the
returned changes atomically, and records each in the operator-side run
manifest.

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
import stat
import subprocess
import tempfile
from collections.abc import Collection, Iterator, Mapping
from dataclasses import dataclass, field
from datetime import datetime
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Callable

    from jinja2 import Environment

    from darnit.remediation.platform import PlatformSession

from darnit.config.framework_schema import (
    ProjectUpdateRemediationConfig,
    RemediationConfig,
    TemplateConfig,
)
from darnit.config.when_evaluator import evaluate_when
from darnit.core.logging import get_logger
from darnit.remediation import git_state, manifest
from darnit.remediation.helpers import (
    detect_repo_from_git,
)
from darnit.remediation.plan import FileChange, PlanItem, content_digest, normalize_repo_path

logger = get_logger("remediation.executor")


class ConfirmationRequired(Exception):
    """A remediation read a context key that has no usable value (feature 042, FR-007)."""

    def __init__(self, key: str) -> None:
        super().__init__(f"confirmation required: {key}")
        self.key = key


class WriteRefused(Exception):
    """The executor did not write a planned change; nothing was written for it."""


class GuardedContext(Mapping[str, Any]):
    """Context values for templates and ``when`` clauses.

    Reading a key in ``unconfirmed`` that has no value raises
    :class:`ConfirmationRequired`. It is not a ``LookupError``, so Jinja does
    not turn it into an undefined value, and a template's ``default()`` or
    membership test cannot stand in for the missing value.
    """

    def __init__(self, values: Mapping[str, Any], unconfirmed: Collection[str]) -> None:
        self._values = dict(values)
        self._unconfirmed = frozenset(unconfirmed) - self._values.keys()

    def __getitem__(self, key: str) -> Any:
        if key in self._unconfirmed:
            raise ConfirmationRequired(key)
        return self._values[key]

    def __contains__(self, key: object) -> bool:
        if key in self._unconfirmed:
            raise ConfirmationRequired(str(key))
        return key in self._values

    def __iter__(self) -> Iterator[str]:
        return iter(self._values)

    def __len__(self) -> int:
        return len(self._values)


@dataclass
class RemediationResult:
    """Result of a remediation execution."""

    success: bool
    message: str
    control_id: str
    remediation_type: str  # "file_create", "exec", "platform_setting", "handler"
    dry_run: bool
    details: dict[str, Any]
    needs_review: bool = False  # True when safe=false — changes may alter behavior
    confirmation_required: str | None = None  # Context key that needs a person's confirmation
    # Feature 043. ``plan``: one item per evaluated step. ``file_changes``: the
    # planned changes in a preview, the applied ones (and the reasons for
    # unchanged files) in an apply. ``changed`` is True only for an apply in
    # which every step succeeded and at least one file was written.
    plan: list[PlanItem] = field(default_factory=list)
    file_changes: list[FileChange] = field(default_factory=list)
    changed: bool = False
    run_id: str | None = None

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
    the sieve handler registry (file_create, exec, platform_setting, manual_steps, etc.).

    Templates use Jinja2 with non-colliding delimiters (<< >> for variables,
    <% %> for blocks) so that GitHub Actions ${{ }}, shell $VAR, and other
    dollar-sign syntaxes pass through untouched.

    Available template variables:
    - << OWNER >> - Repository owner
    - << REPO >> - Repository name
    - << BRANCH >> - Default branch
    - << PATH >> - Local repository path
    - << YEAR >> - Current year (used by LICENSE templates; year-per-year
      cadence is slow enough that PR diffs stay stable within a calendar
      year -- see Determinism Tier 1 note in _get_template_context)
    - << CONTROL >> - Control ID being remediated
    - << context.KEY >> - Usable project context values; reading a key in
      ``unconfirmed_keys`` stops the remediation with "confirmation required"
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
        now_provider: Callable[[], datetime] | None = None,
        unconfirmed_keys: Collection[str] = (),
        run_id: str | None = None,
        platform: PlatformSession | None = None,
    ):
        """Initialize the executor.

        Args:
            local_path: Path to the repository
            owner: Repository owner (auto-detected if not provided)
            repo: Repository name (auto-detected if not provided)
            default_branch: Default branch name
            templates: Template definitions from framework config
            context_values: Usable context values for ${context.*} substitution
                and ``when`` clauses
            project_values: Flattened .project/project.yaml for ${project.*} substitution
            scan_values: Repo scan values for ${scan.*} substitution.
                Populated by the implementation's repo scanner with detected
                languages, CI tools, directory structure, etc.
            framework_path: Absolute path to the framework TOML file.
                Template ``file`` references are resolved relative to this
                file's directory.  Falls back to ``local_path`` when None.
            now_provider: Optional callable returning the "current" datetime,
                used to derive ``<< YEAR >>`` in template output. Defaults
                to :func:`datetime.now`. Parameterized so tests can inject
                a fixed clock (Determinism Tier 1, #418).
            unconfirmed_keys: Context keys without a usable value
                (``ResolvedContext.unusable_keys()``). A template or ``when``
                clause that reads one stops the remediation with
                "confirmation required" (feature 042, FR-007).
            run_id: Remediation run whose manifest records this executor's
                writes (feature 043). When None, the first write starts a new
                run; every later write by this executor joins it.
            platform: The run's platform session (feature 043): the operator
                policy, the approved digests, and the run's platform
                requirements. ``platform_setting`` steps plan and apply
                through it; when None, each such step plans alone under the
                operator policy with no approvals.
        """
        self.local_path = os.path.abspath(local_path)
        self.templates = templates or {}
        self._framework_path = framework_path
        self.default_branch = default_branch
        self._context_values = context_values or {}
        self._project_values = project_values or {}
        self._scan_values = scan_values or {}
        self._now_provider = now_provider or datetime.now
        self._unconfirmed_keys = frozenset(unconfirmed_keys)
        self.run_id = run_id
        self._run_ready = False
        self.platform = platform
        self._in_git: bool | None = None

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
        # YEAR is derived from now_provider (test-injectable). DATE was
        # dropped: no template referenced it, and its day-per-day drift
        # was cluttering PR diffs for identical inputs run on different
        # days. Determinism Tier 1 (#418).
        now = self._now_provider()
        ctx: dict[str, Any] = {
            "OWNER": self.owner or "",
            "REPO": self.repo or "",
            "BRANCH": self.default_branch,
            "PATH": self.local_path,
            "YEAR": str(now.year),
            "CONTROL": control_id,
        }

        # Build nested context/project/scan namespaces. List values are
        # sorted before joining so upstream ordering (dict iteration,
        # API-response order) does not drift the rendered output across
        # runs. Determinism Tier 1 (#418).
        context_ns: dict[str, str] = {}
        if self._context_values:
            for key, value in self._context_values.items():
                if isinstance(value, str):
                    context_ns[key] = value
                elif isinstance(value, list):
                    context_ns[key] = " ".join(sorted(str(v) for v in value))
                elif value is not None:
                    context_ns[key] = str(value)
        ctx["context"] = GuardedContext(context_ns, self._unconfirmed_keys)

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
            if isinstance(ns_dict, Mapping):
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
                with open(resolved, encoding="utf-8") as f:
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
        """Preview (``dry_run=True``) or apply a remediation.

        A preview runs every plan-capable handler in plan mode and changes
        nothing. An apply first computes the same plan, so a key that needs
        confirmation stops it before any write (feature 042, FR-007), then
        runs the handlers in apply mode and writes their file changes. After
        a successful apply, ``config.project_update`` is written the same way.

        Args:
            control_id: The control ID being remediated
            config: Remediation configuration from TOML
            dry_run: True for plan mode, False for apply mode

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

        try:
            planned = self._run_steps(control_id, config, "plan")
            result = planned if dry_run else self._run_steps(control_id, config, "apply")
        except ConfirmationRequired as needed:
            return RemediationResult(
                success=False,
                message=str(needed),
                control_id=control_id,
                remediation_type="handler_pipeline",
                dry_run=dry_run,
                details={},
                confirmation_required=needed.key,
            )
        if not dry_run:
            result.plan = planned.plan

        if result.success and config.project_update and config.project_update.set:
            self._project_update(control_id, config.project_update, result)

        return result

    def _project_update(
        self, control_id: str, project_update: ProjectUpdateRemediationConfig, result: RemediationResult
    ) -> None:
        try:
            changes = plan_project_update(
                self.local_path, project_update.set, create=project_update.create_if_missing
            )
        except ValueError as e:
            if result.dry_run:
                result.details["project_update"] = f"would fail: {e}"
            else:
                logger.warning(f"Remediation for {control_id} succeeded but project_update failed: {e}")
                result.details["project_update"] = f"failed: {e}"
            return

        if result.dry_run:
            result.details["project_update"] = f"would set: {project_update.set}"
            result.plan.append(
                PlanItem(control_id=control_id, step="project_update", file_changes=changes, previewable=True)
            )
            result.file_changes.extend(changes)
            return

        written = False
        for change in changes:
            try:
                applied = self._write(change)
            except (WriteRefused, OSError, ValueError, LookupError) as e:
                logger.warning(f"Remediation for {control_id} succeeded but project_update failed: {e}")
                result.details["project_update"] = f"failed: {e}"
                return
            result.file_changes.append(applied)
            written = written or applied.changes
        result.details["project_update"] = "applied" if written else "unchanged"
        if written:
            result.changed = True
            result.run_id = self.run_id

    def _ensure_run(self) -> tuple[str, str]:
        repository = manifest.repository_identity(self.local_path, self.owner, self.repo)
        if not self._run_ready:
            if self.run_id is None:
                self.run_id = manifest.start_run(repository, checkout=self.local_path).run_id
            elif manifest.load_run(repository, self.run_id, checkout=self.local_path) is None:
                manifest.start_run(repository, checkout=self.local_path, run_id=self.run_id)
            self._run_ready = True
        assert self.run_id is not None
        return repository, self.run_id

    def _vcs_state(self, path: str) -> tuple[bool, bool]:
        """``(user_changes, ignored)`` for ``path`` in a git checkout; ``(False, False)`` outside one.

        A file this run wrote, unchanged since, is not a user change.
        """
        if self._in_git is None:
            self._in_git = git_state.is_work_tree(self.local_path)
        if not self._in_git:
            return False, False
        try:
            if git_state.is_ignored(self.local_path, path):
                return False, True
            if not git_state.has_uncommitted_changes(self.local_path, path):
                return False, False
        except git_state.GitStateError as e:
            raise WriteRefused(f"{path}: {e}") from e
        return not self._written_this_run(path), False

    def _written_this_run(self, path: str) -> bool:
        if self.run_id is None:
            return False
        repository = manifest.repository_identity(self.local_path, self.owner, self.repo)
        run = manifest.load_run(repository, self.run_id, checkout=self.local_path)
        entry = next((f for f in run.files if f.path == path), None) if run else None
        if entry is None:
            return False
        try:
            with open(os.path.join(self.local_path, path), "rb") as f:
                return content_digest(f.read()) == entry.after_digest
        except OSError:
            return False

    def _write(self, change: FileChange) -> FileChange:
        """Write one planned change atomically and record it in the run manifest.

        Returns the change as applied. A target with uncommitted user changes
        is not written and comes back as ``action = "none"``, reason
        ``user_changes_present`` (FR-011); a target the repository ignores is
        written and comes back with ``ignored = True``, so it is never staged
        (FR-014).

        Raises:
            WriteRefused: the target is outside the repository, its git state
                cannot be read, or it is no longer in the state the change
                was planned against.
        """
        if not change.changes:
            return change
        assert change.content is not None
        root = os.path.realpath(self.local_path)
        full_path = os.path.join(root, change.path)
        if os.path.commonpath([root, os.path.realpath(full_path)]) != root:
            raise WriteRefused(f"{change.path} resolves outside the repository")
        user_changes, ignored = self._vcs_state(change.path)
        if user_changes:
            return FileChange(path=change.path, action="none", reason="user_changes_present")
        if change.action == "create" and os.path.lexists(full_path):
            raise WriteRefused(f"{change.path} exists; it was planned as a new file")
        if change.action == "modify":
            try:
                with open(full_path, "rb") as f:
                    current = f.read()
            except OSError as e:
                raise WriteRefused(f"{change.path} cannot be read: {e}") from e
            if content_digest(current) != change.before_digest:
                raise WriteRefused(f"{change.path} changed since it was planned")

        repository, run_id = self._ensure_run()
        os.makedirs(os.path.dirname(full_path), exist_ok=True)
        _write_bytes_atomic(full_path, change.content.encode("utf-8"))
        manifest.record_file(repository, run_id, change.path, change.after_digest or "", checkout=self.local_path)
        return change.model_copy(update={"ignored": True}) if ignored else change

    def _record_change_set(self, digest: str) -> None:
        repository, run_id = self._ensure_run()
        manifest.record_change_set(repository, run_id, digest, checkout=self.local_path)

    def _when_not_met(self, handler_config: dict[str, Any]) -> list[FileChange]:
        path = handler_config.get("path")
        if not isinstance(path, str):
            return []
        try:
            return [FileChange(path=normalize_repo_path(path), action="none", reason="when_not_met")]
        except ValueError:
            return []

    def _run_steps(
        self,
        control_id: str,
        config: RemediationConfig,
        mode: Literal["plan", "apply"],
    ) -> RemediationResult:
        """Run the handler invocations in ``mode``.

        Iterates config.handlers (flat list) and dispatches each through
        the sieve handler registry. Respects ``when`` clauses on individual
        handlers and the ``strategy`` field on RemediationConfig. In apply
        mode, the file changes of a step are written only when the step
        returned PASS.
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
            mode=mode,
            platform=self.platform,
        )

        # Assemble flat context for when-clause evaluation. Scan values let
        # when-clauses match on detected CI tools (e.g., scan.ci_sast_tools).
        when_values: dict[str, Any] = dict(self._project_values)
        when_values.update(self._context_values)
        when_values.update(self._scan_values)
        when_context = GuardedContext(when_values, self._unconfirmed_keys)

        results: list[dict[str, Any]] = []
        plan_items: list[PlanItem] = []
        file_changes: list[FileChange] = []
        all_success = True
        wrote = False
        first_match = config.strategy == "first_match"
        matched_any = False

        high_impact_mode = self.platform.policy.settings.high_impact if self.platform else "prompt"

        def plan_item(step: str, **fields: Any) -> PlanItem:
            previewable = fields.setdefault("previewable", True)
            high_impact = any(cs["target"]["impact"] == "high_impact" for cs in fields.get("change_sets", []))
            item = PlanItem(
                control_id=control_id,
                step=step,
                requires_individual_approval=(
                    not previewable or not config.safe or (high_impact and high_impact_mode == "prompt")
                ),
                **fields,
            )
            plan_items.append(item)
            if self.platform is not None:
                self.platform.note_known(item.digest)
            return item

        for index, invocation in enumerate(config.handlers):
            step = f"{invocation.handler}[{index}]"
            handler_config = dict(invocation.model_extra or {})
            handler_config["handler"] = invocation.handler

            # Evaluate when clause — skip handler if condition not met
            if invocation.when and not evaluate_when(invocation.when, when_context):
                logger.debug(
                    "Control %s: remediation handler '%s' skipped (when clause not met: %s)",
                    control_id,
                    invocation.handler,
                    invocation.when,
                )
                skipped = self._when_not_met(handler_config)
                plan_item(step, file_changes=skipped)
                file_changes.extend(skipped)
                continue

            # Resolve template references to content
            if "template" in handler_config and "content" not in handler_config:
                template_name = handler_config["template"]
                content = self._get_template_content(template_name)
                if content:
                    content = self._substitute(content, control_id)
                    handler_config["content"] = content

            matched_any = True
            command = handler_config.get("command")
            commands = [[str(arg) for arg in command]] if isinstance(command, list) else []

            handler_info = registry.get(invocation.handler)
            if not handler_info:
                results.append(
                    {
                        "handler": invocation.handler,
                        "status": "error",
                        "message": f"Handler '{invocation.handler}' not found",
                    }
                )
                plan_item(step, commands=commands, previewable=False)
                all_success = False
                if first_match:
                    break
                continue

            if mode == "plan" and not handler_info.supports_plan:
                results.append(
                    {
                        "handler": invocation.handler,
                        "status": "not_previewable",
                        "message": (
                            f"Cannot be previewed exactly: handler '{invocation.handler}' does not support plan mode"
                        ),
                        "config": handler_config,
                    }
                )
                plan_item(step, commands=commands, previewable=False)
                if first_match:
                    break
                continue

            try:
                handler_result = handler_info.fn(handler_config, handler_ctx)
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
                plan_item(step, commands=commands, previewable=handler_info.supports_plan)
                all_success = False
                if first_match:
                    break
                continue

            result_entry: dict[str, Any] = {
                "handler": invocation.handler,
                "status": handler_result.status.value,
                "message": handler_result.message,
            }
            # Propagate handler evidence -- needed for llm_consultation,
            # llm_verification_required, and other handler-to-agent signals.
            if handler_result.evidence:
                result_entry["evidence"] = handler_result.evidence
            results.append(result_entry)
            if handler_result.status in (HandlerResultStatus.FAIL, HandlerResultStatus.ERROR):
                all_success = False

            try:
                changes = _file_changes(handler_result.evidence)
            except ValueError as e:
                result_entry["status"] = "error"
                result_entry["message"] = f"Invalid file changes from handler '{invocation.handler}': {e}"
                all_success = False
                changes = []

            if mode == "apply":
                for digest in handler_result.evidence.get("applied_change_sets") or []:
                    self._record_change_set(digest)
                    wrote = True

            if mode == "plan":
                plan_item(
                    step,
                    file_changes=changes,
                    change_sets=list(handler_result.evidence.get("change_sets") or []),
                    commands=[] if handler_info.supports_plan else commands,
                    previewable=handler_info.supports_plan,
                )
                file_changes.extend(changes)
            elif handler_result.status == HandlerResultStatus.PASS and result_entry["status"] != "error":
                for change in changes:
                    try:
                        applied = self._write(change)
                    except (WriteRefused, OSError, ValueError, LookupError) as e:
                        result_entry["status"] = "error"
                        result_entry["message"] = f"Not written: {e}"
                        all_success = False
                        break
                    file_changes.append(applied)
                    wrote = wrote or applied.changes
                # Propagate llm_enhance metadata for AI-assisted file customization
                if result_entry["status"] != "error" and "llm_enhance" in handler_config:
                    results[-1]["llm_enhance"] = {
                        "prompt": handler_config["llm_enhance"],
                        "file_path": handler_config.get("path", ""),
                    }

            if first_match:
                break

        dry_run = mode == "plan"
        run_id = self.run_id if wrote else None

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
                plan=plan_items,
                file_changes=file_changes,
            )

        return RemediationResult(
            success=all_success,
            message=(
                f"Would execute {len(results)} remediation handler(s)"
                if dry_run
                else f"Executed {len(results)} remediation handler(s)"
            ),
            control_id=control_id,
            remediation_type="handler_pipeline",
            dry_run=dry_run,
            details={"handlers": results},
            plan=plan_items,
            file_changes=file_changes,
            changed=all_success and wrote,
            run_id=run_id,
        )


def _file_changes(evidence: Mapping[str, Any]) -> list[FileChange]:
    """The ``FileChange`` entries a handler returned in ``evidence["file_changes"]``."""
    raw = evidence.get("file_changes") or []
    if not isinstance(raw, list):
        raise ValueError("file_changes must be a list")
    return [item if isinstance(item, FileChange) else FileChange.model_validate(item) for item in raw]


def _write_bytes_atomic(path: str, data: bytes) -> None:
    """Replace ``path`` with ``data`` via a tempfile in the same directory.

    A modified file keeps its permission bits (git tracks the executable
    bit); a new file gets the default mode for the process umask.
    """
    try:
        mode = stat.S_IMODE(os.stat(path).st_mode)
    except FileNotFoundError:
        umask = os.umask(0)
        os.umask(umask)
        mode = 0o666 & ~umask
    directory = os.path.dirname(path) or "."
    fd, tmp = tempfile.mkstemp(dir=directory, prefix=".darnit-write-", suffix=".tmp")
    try:
        with os.fdopen(fd, "wb") as f:
            f.write(data)
        os.chmod(tmp, mode)
        os.replace(tmp, path)
    except BaseException:
        try:
            os.unlink(tmp)
        except OSError:
            pass
        raise


def plan_project_update(local_path: str, updates: Mapping[str, Any], *, create: bool = True) -> list[FileChange]:
    """The ``.project/`` file changes that setting ``updates`` would make; writes nothing.

    Uses the feature 042 round-trip rendering, so comments, ordering, and
    fields darnit does not own are preserved (FR-020).

    Raises:
        ValueError: A ``.project/`` file is present but unreadable or invalid.
    """
    from darnit.config.loader import render_project_config_update

    def mutate(config: object) -> None:
        for dotted_path, value in updates.items():
            _set_nested_value(config, dotted_path, value)

    root = os.path.abspath(local_path)
    changes = []
    for path, text in render_project_config_update(root, list(updates), mutate, create=create).items():
        relative = os.path.relpath(path, root).replace(os.sep, "/")
        try:
            with open(path, "rb") as f:
                current: bytes | None = f.read()
        except FileNotFoundError:
            current = None
        if current is None:
            changes.append(FileChange(path=relative, action="create", content=text))
        elif current != text.encode("utf-8"):
            changes.append(FileChange(path=relative, action="modify", content=text, before_digest=content_digest(current)))
    return changes


def apply_project_update(
    local_path: str,
    project_update: ProjectUpdateRemediationConfig,
    control_id: str,
) -> None:
    """Apply a project_update to the ``.project/`` files.

    Sets each dotted path from ``project_update.set`` and nothing else:
    comments, ordering, and fields darnit does not own are preserved
    (feature 042, FR-020). CNCF fields are written to
    ``.project/project.yaml``, other fields to ``.project/darnit.yaml``.

    Args:
        local_path: Path to the repository root
        project_update: Configuration specifying what to update
        control_id: Control ID for logging context

    Raises:
        ValueError: A ``.project/`` file is present but unreadable or
            invalid; nothing is written and the errors are in the message
            (FR-019).

    Example:
        Given project_update.set = {"security.policy.path": "SECURITY.md"},
        this updates .project/project.yaml:

            security:
              policy:
                path: SECURITY.md
    """
    if not project_update.set:
        return

    from darnit.config.loader import update_project_config

    def mutate(config: object) -> None:
        for dotted_path, value in project_update.set.items():
            _set_nested_value(config, dotted_path, value)
            logger.debug(f"project_update for {control_id}: set {dotted_path} = {value}")

    written = update_project_config(
        local_path, list(project_update.set), mutate, create=project_update.create_if_missing
    )
    if written:
        logger.info(f"Applied project_update for {control_id}: set {len(project_update.set)} values")
    else:
        logger.debug(f"project_update for {control_id}: nothing to change")


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
    "ConfirmationRequired",
    "GuardedContext",
    "RemediationExecutor",
    "RemediationResult",
    "WriteRefused",
    "apply_project_update",
    "plan_project_update",
]
