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
from datetime import UTC, datetime
from typing import TYPE_CHECKING, Any, Literal

if TYPE_CHECKING:
    from collections.abc import Callable

    from jinja2 import Environment

    from darnit.remediation.platform import PlatformSession
    from darnit.remediation.platform.policy import ItemApprover
    from darnit.sieve.handler_registry import HandlerContext, SieveHandlerInfo

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
from darnit.remediation.plan import Approval, FileChange, PlanItem, content_digest, normalize_repo_path

logger = get_logger("remediation.executor")

_ExecOutcome = tuple[dict[str, Any], list[FileChange], bool, bool]


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
    # Feature 043 (framework-design 15.3). An apply whose plan holds an item
    # that requires individual approval and was not approved runs no step of
    # the control; the unapproved PlanItem digests are listed here.
    # ``approvals`` are the individual approvals the apply used.
    needs_approval: list[str] = field(default_factory=list)
    approvals: list[Approval] = field(default_factory=list)

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
        approvals: Collection[str] = (),
        item_approver: ItemApprover | None = None,
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
            approvals: ``PlanItem`` digests a person approved individually
                (framework-design 15.3), in addition to the platform
                session's approvals. A plan item that requires individual
                approval runs in an apply only when its own digest is here.
            item_approver: Asks a person to approve a plan item that requires
                individual approval and has no approved digest (``darnit run``
                at a terminal). Every such item of a control must be approved
                before any step of the control runs; asking stops at the first
                refusal. When None, such an item ends as needs approval.
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
        self._approvals = frozenset(approvals)
        self._item_approver = item_approver
        self._granted: dict[str, Approval] = {}
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
            if not dry_run and planned.details.get("missing_handlers"):
                return RemediationResult(
                    success=False,
                    message=f"Handler(s) not found: {planned.details['missing_handlers']}; nothing was run",
                    control_id=control_id,
                    remediation_type="handler_pipeline",
                    dry_run=False,
                    details=planned.details,
                    plan=planned.plan,
                )
            if not dry_run and (unapproved := self._unapproved(planned.plan, config.safe)):
                return RemediationResult(
                    success=False,
                    message=(
                        f"Needs individual approval of {len(unapproved)} plan item digest(s); "
                        "no step of this remediation was run"
                    ),
                    control_id=control_id,
                    remediation_type="handler_pipeline",
                    dry_run=False,
                    details={"needs_approval": unapproved},
                    plan=planned.plan,
                    needs_approval=unapproved,
                )
            result = planned if dry_run else self._run_steps(control_id, config, "apply", planned.plan)
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
            result.approvals = self._used_approvals(planned.plan)

        if result.success and config.project_update and config.project_update.set:
            self._project_update(control_id, config.project_update, result)

        return result

    def _approved_digests(self) -> frozenset[str]:
        platform = self.platform.approvals if self.platform is not None else frozenset()
        return self._approvals | platform | self._granted.keys()

    def _operator(self) -> str:
        from darnit.remediation.platform.policy import ResolvedPolicy

        return (self.platform.policy if self.platform is not None else ResolvedPolicy()).operator

    def _individually_approved(self, item: PlanItem, safe: bool) -> bool:
        """``item``'s own digest is approved (framework-design 15.3).

        An item that needs approval only because it holds a high-impact
        change set under ``prompt`` is approved as well by the digests of its
        change sets, or by the session's approver, which asks a person for
        each change set before the platform engine writes it (15.2).
        """
        approved = self._approved_digests()
        if item.digest in approved:
            return True
        if item.previewable and safe and item.change_sets:
            if self.platform is not None and self.platform.approver is not None:
                return True
            return all(cs["digest"] in approved for cs in item.change_sets if cs.get("operations"))
        return False

    def _unapproved(self, plan: list[PlanItem], safe: bool) -> list[str]:
        """Digests of the items of ``plan`` that need individual approval and lack it, after asking a person."""
        unapproved = [
            item for item in plan if item.requires_individual_approval and not self._individually_approved(item, safe)
        ]
        if self._item_approver is None:
            return [item.digest for item in unapproved]
        granted: dict[str, Approval] = {}
        for index, item in enumerate(unapproved):
            if not self._item_approver(item, _approval_reasons(item, safe)):
                return [i.digest for i in unapproved[index:]]
            granted[item.digest] = Approval(
                digest=item.digest, approved_by=self._operator(), approved_at=datetime.now(UTC)
            )
        self._granted.update(granted)
        return []

    def _used_approvals(self, plan: list[PlanItem]) -> list[Approval]:
        approved = self._approved_digests()
        now = datetime.now(UTC)
        return [
            self._granted.get(item.digest) or Approval(digest=item.digest, approved_by=self._operator(), approved_at=now)
            for item in plan
            if item.requires_individual_approval and item.digest in approved
        ]

    def _project_update(
        self, control_id: str, project_update: ProjectUpdateRemediationConfig, result: RemediationResult
    ) -> None:
        try:
            changes = plan_project_update(
                self.local_path, project_update.set, create=project_update.create_if_missing
            )
            if result.dry_run:
                changes = [self._planned_write(c) for c in changes]
        except (ValueError, WriteRefused) as e:
            if result.dry_run:
                result.details["project_update"] = f"would fail: {e}"
            else:
                logger.warning(f"Remediation for {control_id} succeeded but project_update failed: {e}")
                result.details["project_update"] = f"failed: {e}"
            return

        if result.dry_run:
            result.details["project_update"] = (
                f"would set: {project_update.set}" if any(c.changes for c in changes) else "unchanged"
            )
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

    def _recorded_files(self) -> dict[str, str]:
        """Path to recorded content digest of every file this run wrote, from one read of the run manifest."""
        if self.run_id is None:
            return {}
        repository = manifest.repository_identity(self.local_path, self.owner, self.repo)
        run = manifest.load_run(repository, self.run_id, checkout=self.local_path)
        return {f.path: f.after_digest for f in run.files} if run else {}

    def _written_this_run(self, path: str) -> bool:
        recorded = self._recorded_files().get(path)
        if recorded is None:
            return False
        try:
            with open(os.path.join(self.local_path, path), "rb") as f:
                return content_digest(f.read()) == recorded
        except OSError:
            return False

    def _planned_write(self, change: FileChange) -> FileChange:
        """``change`` as :meth:`_write` would apply it, by the same read-only checks (FR-011, FR-021).

        A target with uncommitted user changes comes back as ``action =
        "none"``, reason ``user_changes_present``; a target the repository
        ignores comes back with ``ignored = True``.

        Raises:
            WriteRefused: the target's git state cannot be read.
        """
        if not change.changes:
            return change
        user_changes, ignored = self._vcs_state(change.path)
        if user_changes:
            return FileChange(path=change.path, action="none", reason="user_changes_present")
        return change.model_copy(update={"ignored": True}) if ignored else change

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

    def amend_created(self, created: FileChange, content: str) -> FileChange:
        """Replace the content of a file this run created, through the single writer (framework-design 4.3).

        Returns ``created`` with the new content; the run manifest records the
        new digest, so the file stays committable.

        Raises:
            WriteRefused: ``created`` is not a create, the file was not created
                in this run, or it changed since this run wrote it.
        """
        if created.action != "create":
            raise WriteRefused(f"{created.path} was not created by this remediation")
        if not self._written_this_run(created.path):
            raise WriteRefused(f"{created.path} was not created in this run, or changed since")
        self._write(
            FileChange(path=created.path, action="modify", content=content, before_digest=created.after_digest)
        )
        return FileChange(
            path=created.path,
            action="create",
            content=content,
            ignored=created.ignored,
            project_reference=created.project_reference,
        )

    def _record_change_set(self, digest: str) -> None:
        repository, run_id = self._ensure_run()
        manifest.record_change_set(repository, run_id, digest, checkout=self.local_path)

    def _reference_changes(self, reference: str, path: str) -> tuple[list[FileChange], str | None]:
        from darnit.config.resolver import render_reference_update

        rendered, kept = render_reference_update(self.local_path, reference, path)
        return _rendered_file_changes(self.local_path, rendered), kept

    def _planned_references(self, changes: list[FileChange], entry: dict[str, Any]) -> list[FileChange]:
        """The ``.project/`` changes that would record each planned create's ``project_reference``."""
        planned: list[FileChange] = []
        for change in changes:
            if change.action != "create" or not change.project_reference:
                continue
            if change.ignored:
                entry["project_reference"] = _reference_note(change, f"{change.path} is ignored by the repository")
                continue
            references, kept = self._reference_changes(change.project_reference, change.path)
            references = [self._planned_write(c) for c in references]
            blocked = [c.path for c in references if not c.changes]
            if kept is None and blocked:
                kept = f"{', '.join(blocked)} has uncommitted changes"
            planned += references
            entry["project_reference"] = _reference_note(change, kept)
        return planned

    def _record_reference(self, created: FileChange, entry: dict[str, Any]) -> list[FileChange]:
        """Record ``created.project_reference`` for a file this run created, into an empty field (FR-015).

        Returns the ``.project/`` changes as applied; ``entry["project_reference"]``
        says whether the reference was recorded, and why not.
        """
        assert created.project_reference is not None
        applied: list[FileChange] = []
        kept: str | None
        if created.ignored:
            kept = f"{created.path} is ignored by the repository"
        elif not self._written_this_run(created.path):
            kept = f"{created.path} was not created in this run"
        else:
            try:
                changes, kept = self._reference_changes(created.project_reference, created.path)
                for change in changes:
                    applied.append(self._write(change))
            except (WriteRefused, OSError, ValueError, LookupError) as e:
                kept = f"the project file was not written: {e}"
            blocked = [c.path for c in applied if not c.changes]
            if kept is None and blocked:
                kept = f"{', '.join(blocked)} has uncommitted changes"
        entry["project_reference"] = _reference_note(created, kept)
        return applied

    def _apply_exec(
        self,
        handler_info: SieveHandlerInfo,
        handler_config: dict[str, Any],
        handler_ctx: HandlerContext,
        planned: PlanItem | None,
    ) -> _ExecOutcome:
        """Run an exec step in the checkout and record what it changed (framework-design 4.4).

        Returns ``(result entry, file changes, success, wrote)``. A previewed
        path with uncommitted user changes stops the step before it runs. A
        file the command changed that had uncommitted user changes before is
        a conflict. The changed files are recorded only when the step
        succeeded cleanly; after a failure, a conflict, a deletion, a
        non-text write, or a difference from the preview, none is recorded
        (so none is ever committed), they are returned as the step's file
        changes and listed in ``entry["not_recorded"]`` for a person to
        review, and a file an earlier step of this run recorded is removed
        from the run manifest (``entry["removed_from_run"]``).
        """
        from darnit.remediation import working_tree
        from darnit.sieve.handler_registry import HandlerResultStatus

        entry: dict[str, Any] = {"handler": handler_config["handler"]}
        previewed = [c for c in planned.file_changes if c.changes] if planned and planned.previewable else []

        def failed(message: str, changes: list[FileChange] | None = None) -> _ExecOutcome:
            entry.update(status="error", message=message)
            return entry, changes or [], False, False

        try:
            before = working_tree.digests(self.local_path, working_tree.visible_files(self.local_path))
            recorded = self._recorded_files()
            dirty = {
                p
                for p in working_tree.user_changed(self.local_path)
                if p not in recorded or before.get(p) != recorded[p]
            }
            conflicts = sorted(c.path for c in previewed if c.path in dirty)
            if conflicts:
                return failed(
                    f"Not run: uncommitted user changes in previewed path(s) {conflicts}",
                    [FileChange(path=p, action="none", reason="user_changes_present") for p in conflicts],
                )
        except (git_state.GitStateError, OSError) as e:
            return failed(f"Not run: cannot read the working tree: {e}")

        passed = False
        try:
            handler_result = handler_info.fn(handler_config, handler_ctx)
        except (RuntimeError, ValueError, OSError, subprocess.SubprocessError) as e:
            entry.update(status="error", message=str(e))
        else:
            passed = handler_result.status == HandlerResultStatus.PASS
            entry.update(status=handler_result.status.value, message=handler_result.message)
            if handler_result.evidence:
                entry["evidence"] = handler_result.evidence

        try:
            found = working_tree.diff(self.local_path, before, working_tree.visible_files(self.local_path))
        except (git_state.GitStateError, OSError) as e:
            return failed(f"{entry['message']}; the changes it made cannot be read: {e}")

        conflicted = [c.path for c in found.changes if c.path in dirty]
        written = [c for c in found.changes if c.path not in dirty]

        problems: list[str] = []
        if not passed:
            problems.append(entry["message"])
        if conflicted:
            problems.append(f"changed files that had uncommitted user changes: {conflicted}")
        if found.deleted:
            problems.append(f"deleted {found.deleted}")
        if found.not_text:
            problems.append(f"wrote non-text files {found.not_text}")
        if planned is not None and planned.previewable:
            expected = {c.path: c.after_digest for c in previewed}
            actual = {c.path: c.after_digest for c in found.changes}
            mismatch = {
                "planned_only": sorted(expected.keys() - actual.keys()),
                "applied_only": sorted(actual.keys() - expected.keys()),
                "different": sorted(p for p in expected.keys() & actual.keys() if expected[p] != actual[p]),
            }
            if any(mismatch.values()):
                entry["preview_mismatch"] = mismatch
                problems.append(f"applied changes differ from the preview: {mismatch}")
        conflicts = [FileChange(path=p, action="none", reason="user_changes_present") for p in conflicted]
        if problems:
            if written:
                entry["not_recorded"] = sorted(c.path for c in written)
                problems.append(
                    f"written but not recorded: {entry['not_recorded']}; they will not be committed, "
                    "review them by hand"
                )
            superseded = sorted(c.path for c in written if c.path in recorded)
            if superseded:
                repository, run_id = self._ensure_run()
                for path in superseded:
                    manifest.forget_file(repository, run_id, path, checkout=self.local_path)
                entry["removed_from_run"] = superseded
                problems.append(
                    f"removed from the run: {superseded}, which an earlier step of this run wrote and this "
                    "step changed; they no longer hold what remediation wrote and will not be committed"
                )
            entry.update(status="error", message="; ".join(problems))
            return entry, written + conflicts, False, False
        for change in written:
            repository, run_id = self._ensure_run()
            manifest.record_file(repository, run_id, change.path, change.after_digest or "", checkout=self.local_path)
        return entry, written, True, bool(written)

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
        planned: list[PlanItem] | None = None,
    ) -> RemediationResult:
        """Run the handler invocations in ``mode``.

        Iterates config.handlers (flat list) and dispatches each through
        the sieve handler registry. Respects ``when`` clauses on individual
        handlers and the ``strategy`` field on RemediationConfig. In apply
        mode, the file changes of a step are written only when the step
        returned PASS; an ``exec`` step writes through its command and is
        compared with its planned item in ``planned``.
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
        missing: list[str] = []

        high_impact_mode = self.platform.policy.settings.high_impact if self.platform else "prompt"

        planned_by_step = {item.step: item for item in planned or []}

        def plan_item(step: str, **fields: Any) -> PlanItem:
            previewable = fields.setdefault("previewable", True)
            high_impact = any(cs["target"]["impact"] == "high_impact" for cs in fields.get("change_sets", []))
            may_act = (
                not previewable
                or bool(fields.get("commands"))
                or any(c.changes for c in fields.get("file_changes", []))
                or any(cs.get("operations") for cs in fields.get("change_sets", []))
            )
            item = PlanItem(
                control_id=control_id,
                step=step,
                requires_individual_approval=may_act
                and (not previewable or not config.safe or (high_impact and high_impact_mode == "prompt")),
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
                missing.append(invocation.handler)
                all_success = False
                if first_match:
                    break
                continue

            previewable = _step_previewable(handler_info, handler_config)
            if mode == "plan" and not previewable:
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

            if mode == "apply" and _is_exec(handler_info):
                entry, changes, ok, step_wrote = self._apply_exec(
                    handler_info, handler_config, handler_ctx, planned_by_step.get(step)
                )
                results.append(entry)
                file_changes.extend(changes)
                all_success = all_success and ok
                wrote = wrote or step_wrote
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
                plan_item(step, commands=commands, previewable=previewable and not _is_exec(handler_info))
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
            reference = handler_config.get("project_reference") if invocation.handler == "file_create" else None
            if reference:
                changes = [
                    c.model_copy(update={"project_reference": reference}) if c.action == "create" else c
                    for c in changes
                ]

            if mode == "apply":
                for digest in handler_result.evidence.get("applied_change_sets") or []:
                    self._record_change_set(digest)
                    wrote = True

            if mode == "plan":
                try:
                    if not _is_exec(handler_info):
                        changes = [self._planned_write(c) for c in changes]
                    changes = changes + self._planned_references(changes, result_entry)
                except WriteRefused as e:
                    result_entry["status"] = "error"
                    result_entry["message"] = f"Not written: {e}"
                    all_success = False
                    changes = []
                previewed = not _is_exec(handler_info) or handler_result.status == HandlerResultStatus.PASS
                plan_item(
                    step,
                    file_changes=changes,
                    change_sets=list(handler_result.evidence.get("change_sets") or []),
                    commands=commands,
                    previewable=previewable and previewed,
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
                    if applied.action == "create" and applied.project_reference:
                        recorded = self._record_reference(applied, result_entry)
                        file_changes.extend(recorded)
                        wrote = wrote or any(c.changes for c in recorded)
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
        missing_details = {"missing_handlers": missing} if missing else {}

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
                details={"handlers": results, "strategy": "first_match", **missing_details},
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
            details={"handlers": results, **missing_details},
            plan=plan_items,
            file_changes=file_changes,
            changed=all_success and wrote,
            run_id=run_id,
        )


def _approval_reasons(item: PlanItem, safe: bool) -> list[str]:
    """Why ``item`` requires individual approval (framework-design 15.3)."""
    reasons = []
    if not safe:
        reasons.append("its remediation is marked safe = false")
    if not item.previewable:
        reasons.append("it cannot be previewed exactly")
    if any(cs["target"]["impact"] == "high_impact" for cs in item.change_sets if cs.get("operations")):
        reasons.append("it holds a high-impact platform change")
    return reasons


def _is_exec(handler_info: SieveHandlerInfo) -> bool:
    from darnit.sieve.builtin_handlers import exec_handler

    return handler_info.fn is exec_handler


def _step_previewable(handler_info: SieveHandlerInfo, handler_config: Mapping[str, Any]) -> bool:
    """The step can be previewed exactly: its handler registered plan support, or it is a declared exec (4.4)."""
    from darnit.sieve.builtin_handlers import exec_previewable

    if _is_exec(handler_info):
        return exec_previewable(dict(handler_config))
    return handler_info.supports_plan


def _file_changes(evidence: Mapping[str, Any]) -> list[FileChange]:
    """The ``FileChange`` entries a handler returned in ``evidence["file_changes"]``."""
    raw = evidence.get("file_changes") or []
    if not isinstance(raw, list):
        raise ValueError("file_changes must be a list")
    return [item if isinstance(item, FileChange) else FileChange.model_validate(item) for item in raw]


def _reference_note(change: FileChange, kept: str | None) -> dict[str, Any]:
    note: dict[str, Any] = {"reference": change.project_reference, "path": change.path, "recorded": kept is None}
    if kept is not None:
        note["reason"] = kept
    return note


def _rendered_file_changes(local_path: str, rendered: Mapping[str, str]) -> list[FileChange]:
    """``FileChange`` entries for ``.project/`` files rendered by the round-trip writer (feature 042)."""
    root = os.path.abspath(local_path)
    changes = []
    for path, text in rendered.items():
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
    return _rendered_file_changes(root, render_project_config_update(root, list(updates), mutate, create=create))


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
    "plan_project_update",
]
