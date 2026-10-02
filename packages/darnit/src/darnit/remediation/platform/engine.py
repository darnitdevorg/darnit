"""The platform-change engine: read -> plan -> policy/approval -> apply -> read back (feature 043, R1-R5).

Every platform write darnit makes goes through :func:`apply`. It re-reads
the target and re-plans, so the change written is computed from the current
state; under ``prompt`` it writes only a change set whose digest was
approved, and a digest computed from a different state is stale. The outcome
is derived from reading the settings back, never from response text
(FR-006). Platform remediation exists for GitHub only: for any other host
the outcome is ``manual`` and no platform call is made.
"""

from __future__ import annotations

from collections.abc import Collection, Iterable, Sequence
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, PrivateAttr

from darnit.config.operator.schema import RemediationMode
from darnit.core.logging import get_logger
from darnit.core.utils import gh_api_error_class, gh_api_write
from darnit.remediation.plan import Approval, ErrorInfo
from darnit.remediation.platform.model import (
    ChangeSet,
    FieldChange,
    ObservedState,
    PlatformRequirement,
    PlatformTarget,
    Requirement,
    TargetKind,
    is_not_weaker,
    merge_requirements,
)
from darnit.remediation.platform.policy import Approver, ResolvedPolicy, approval_for, mode_for
from darnit.remediation.platform.targets import (
    ReadError,
    UnknownProtectionField,
    manual_steps,
    plan_change_set,
    read_state,
    resolve_default_branch,
    state_changes,
    unmet,
)

logger = get_logger("remediation.platform.engine")

_FORBID = ConfigDict(extra="forbid")

GITHUB_HOST = "github.com"

ResultKind = Literal["applied", "unchanged", "needs_approval", "manual", "error"]


class TargetPlan(BaseModel):
    """The planned change for one target, or why none could be planned."""

    model_config = _FORBID

    target_kind: TargetKind
    target: PlatformTarget | None = None
    requirements: list[Requirement]
    change_set: ChangeSet | None = None
    error: ErrorInfo | None = None
    supported: bool = True
    steps: list[str] = Field(default_factory=list)
    _state: ObservedState | None = PrivateAttr(default=None)


class TargetResult(BaseModel):
    """What an apply did for one target.

    ``kind``: ``applied`` (written and the read-back satisfies every
    requirement), ``unchanged`` (``reason`` ``already``, ``ruleset``, or
    ``stale_preview``), ``needs_approval``, ``manual`` (``reason``
    ``policy_manual`` or ``unsupported_platform``, with ``steps``), or
    ``error``. ``changed`` lists the settings the read-back shows changed.
    """

    model_config = _FORBID

    target_kind: TargetKind
    target: PlatformTarget | None = None
    requirements: list[Requirement]
    kind: ResultKind
    mode: RemediationMode | None = None
    change_set: ChangeSet | None = None
    reason: str | None = None
    error: ErrorInfo | None = None
    changed: list[FieldChange] = Field(default_factory=list)
    steps: list[str] = Field(default_factory=list)
    approval: Approval | None = None


def is_supported(repository: str) -> bool:
    return repository.split("/", 1)[0] == GITHUB_HOST


def platform_repository(local_path: str, owner: str | None, repo: str | None) -> str | None:
    """The canonical identity whose platform settings a remediation of ``local_path`` changes.

    A checkout whose ``origin`` is on another host is that host's repository
    (no platform call is made for it); otherwise the operator-named or
    detected ``owner``/``repo`` on GitHub.
    """
    from darnit.core.utils import detect_checkout_identity
    from darnit.trust.decision import target_from_owner_repo
    from darnit.trust.identity import canonical_identity

    hint = detect_checkout_identity(local_path)
    if hint is not None and not is_supported(hint.canonical):
        return hint.canonical
    named = target_from_owner_repo(owner, repo)
    if named is not None:
        return canonical_identity(named)
    return hint.canonical if hint is not None else None


def platform_requests(framework: Any, control_ids: Iterable[str]) -> list[PlatformRequirement]:
    """Every ``platform_setting`` requirement declared by the remediations of ``control_ids``."""
    requests: list[PlatformRequirement] = []
    for control_id in control_ids:
        control = framework.controls.get(control_id)
        remediation = getattr(control, "remediation", None)
        for handler in getattr(remediation, "handlers", None) or []:
            if handler.handler == "platform_setting":
                extra = handler.model_extra or {}
                requests.append(
                    PlatformRequirement(target=extra["target"], require=extra["require"], branch=extra.get("branch"))
                )
    return requests


def _owner_repo(repository: str) -> tuple[str, str]:
    from darnit.trust.decision import owner_repo_from_identity

    return owner_repo_from_identity(repository)


class _Group(BaseModel):
    model_config = _FORBID

    kind: TargetKind
    branch: str | None
    members: list[int]
    error: ErrorInfo | None = None


def _groups(repository: str, requests: Sequence[PlatformRequirement]) -> list[_Group]:
    """Requests grouped by target, with branch requests resolved to the default branch."""
    owner, repo = _owner_repo(repository)
    default: str | None = None
    default_error: ErrorInfo | None = None
    if any(r.target == "branch_protection" and r.branch is None for r in requests):
        try:
            default = resolve_default_branch(owner, repo)
        except ReadError as e:
            default_error = e.info()
    groups: dict[tuple[str, str | None], _Group] = {}
    for index, request in enumerate(requests):
        branch = request.branch if request.target == "branch_protection" else None
        error = None
        if request.target == "branch_protection" and branch is None:
            branch, error = default, default_error
        key = (request.target, branch)
        group = groups.setdefault(key, _Group(kind=request.target, branch=branch, members=[], error=error))
        group.members.append(index)
    return list(groups.values())


def _plan_group(repository: str, group: _Group, requests: Sequence[PlatformRequirement]) -> TargetPlan:
    requirements = merge_requirements(requests[i].require for i in group.members)
    owner, repo = _owner_repo(repository)
    if not is_supported(repository):
        branch = group.branch or "the default branch" if group.kind == "branch_protection" else None
        target = PlatformTarget.for_kind(group.kind, owner, repo, branch)
        return TargetPlan(
            target_kind=group.kind,
            target=target,
            requirements=requirements,
            supported=False,
            steps=[
                f"darnit changes platform settings only on GitHub; {repository} is not on GitHub",
                *manual_steps(target, requirements),
            ],
        )
    if group.error is not None:
        return TargetPlan(target_kind=group.kind, requirements=requirements, error=group.error)
    target = PlatformTarget.for_kind(group.kind, owner, repo, group.branch)
    try:
        state = read_state(target)
    except ReadError as e:
        return TargetPlan(target_kind=group.kind, target=target, requirements=requirements, error=e.info())
    try:
        change_set = plan_change_set(state, requirements)
    except UnknownProtectionField as e:
        return TargetPlan(
            target_kind=group.kind,
            target=target,
            requirements=requirements,
            error=ErrorInfo(error_class="evaluation", cause=str(e)),
        )
    planned = TargetPlan(target_kind=group.kind, target=target, requirements=requirements, change_set=change_set)
    planned._state = state
    return planned


def _plans(repository: str, requests: Sequence[PlatformRequirement]) -> list[tuple[_Group, TargetPlan]]:
    if not is_supported(repository):
        groups = []
        seen: dict[tuple[str, str | None], _Group] = {}
        for index, request in enumerate(requests):
            key = (request.target, request.branch)
            if key not in seen:
                seen[key] = _Group(kind=request.target, branch=request.branch, members=[])
                groups.append(seen[key])
            seen[key].members.append(index)
    else:
        groups = _groups(repository, requests)
    return [(group, _plan_group(repository, group, requests)) for group in groups]


def plan(repository: str, requests: Iterable[PlatformRequirement]) -> list[TargetPlan]:
    """Read every target ``requests`` name and plan one change set per target; writes nothing."""
    return [target_plan for _group, target_plan in _plans(repository, list(requests))]


def _unmatched(approvals: Collection[str], plans: Iterable[TargetPlan], known: Collection[str]) -> bool:
    current = {p.change_set.digest for p in plans if p.change_set is not None}
    return any(a not in current and a not in known for a in approvals)


def _write(target_plan: TargetPlan, base: TargetResult) -> TargetResult:
    change_set = target_plan.change_set
    before = target_plan._state
    assert change_set is not None and target_plan.target is not None and before is not None
    failure: tuple[str, int, str] | None = None
    for operation in change_set.operations:
        _body, status, error = gh_api_write(operation.method, operation.endpoint, operation.body)
        if not 200 <= status < 300:
            failure = (f"{operation.method} {operation.endpoint}", status, error or f"HTTP {status}")
            break
    try:
        after = read_state(target_plan.target)
    except ReadError as e:
        cause = "the change was sent but the settings could not be read back"
        if failure:
            cause = f"{failure[0]} was rejected ({failure[2]}); {cause}"
        return base.model_copy(
            update={"kind": "error", "error": ErrorInfo(error_class=e.error_class, cause=f"{cause}: {e.cause}")}
        )
    changed = state_changes(before, after)
    shown = ", ".join(c.field for c in changed) or "nothing"
    if failure:
        error_class = gh_api_error_class(failure[1], failure[2])
        cause = f"{failure[0]} was rejected ({failure[2]}); the read-back shows changed: {shown}"
        return base.model_copy(
            update={"kind": "error", "changed": changed, "error": ErrorInfo(error_class=error_class, cause=cause)}
        )
    weakened = [c for c in changed if not is_not_weaker(c.field, c.before, c.after)]
    if weakened:
        names = ", ".join(c.field for c in weakened)
        cause = f"the read-back shows settings weakened or changed unexpectedly: {names}"
        return base.model_copy(
            update={"kind": "error", "changed": changed, "error": ErrorInfo(error_class="evaluation", cause=cause)}
        )
    missing = unmet(after, target_plan.requirements)
    if missing:
        names = ", ".join(r.key for r in missing)
        cause = f"the read-back does not satisfy: {names}; changed: {shown}"
        return base.model_copy(
            update={"kind": "error", "changed": changed, "error": ErrorInfo(error_class="evaluation", cause=cause)}
        )
    return base.model_copy(update={"kind": "applied", "changed": changed})


def _apply_plan(
    target_plan: TargetPlan,
    *,
    policy: ResolvedPolicy,
    approvals: Collection[str],
    approver: Approver | None,
    stale: bool,
) -> TargetResult:
    base = TargetResult(
        target_kind=target_plan.target_kind,
        target=target_plan.target,
        requirements=target_plan.requirements,
        kind="error",
        change_set=target_plan.change_set,
    )
    if not target_plan.supported:
        return base.model_copy(update={"kind": "manual", "reason": "unsupported_platform", "steps": target_plan.steps})
    if target_plan.error is not None or target_plan.change_set is None:
        return base.model_copy(update={"error": target_plan.error})
    change_set = target_plan.change_set
    assert target_plan.target is not None
    mode = mode_for(policy.settings, target_plan.target)
    base = base.model_copy(update={"mode": mode})
    if not change_set.operations:
        return base.model_copy(update={"kind": "unchanged", "reason": change_set.satisfied_by})
    if mode == "manual":
        steps = manual_steps(target_plan.target, target_plan.requirements, change_set)
        return base.model_copy(update={"kind": "manual", "reason": "policy_manual", "steps": steps})
    approval = None
    if mode == "prompt":
        approval = approval_for(change_set, policy=policy, approvals=approvals, approver=approver)
        if approval is None:
            if stale:
                return base.model_copy(update={"kind": "unchanged", "reason": "stale_preview"})
            return base.model_copy(update={"kind": "needs_approval"})
    try:
        result = _write(target_plan, base.model_copy(update={"approval": approval}))
    except ReadError as e:
        return base.model_copy(update={"error": e.info()})
    logger.info(
        "Platform change %s on %s/%s: %s",
        change_set.digest,
        target_plan.target.owner,
        target_plan.target.repo,
        result.kind,
    )
    return result


def apply(
    repository: str,
    requests: Iterable[PlatformRequirement],
    *,
    policy: ResolvedPolicy,
    approvals: Collection[str] = (),
    approver: Approver | None = None,
) -> list[TargetResult]:
    """Re-read, re-plan, and write each target's change set as the policy allows; read back."""
    plans = plan(repository, requests)
    stale = _unmatched(approvals, plans, ())
    return [_apply_plan(p, policy=policy, approvals=approvals, approver=approver, stale=stale) for p in plans]


class PlatformSession:
    """The platform targets of one remediation run, shared by all its controls.

    Every ``platform_setting`` step of the run registers its requirement, so
    requirements of several controls on one target are planned as one change
    set and applied once (framework-design 4.5 rule 4). A plan is cached for
    the run; an apply is made once per target and its result is returned to
    every control that asked for it.
    """

    def __init__(
        self,
        repository: str,
        requests: Iterable[PlatformRequirement] = (),
        *,
        policy: ResolvedPolicy,
        approvals: Iterable[str] = (),
        approver: Approver | None = None,
    ) -> None:
        self.repository = repository
        self.policy = policy
        self.approvals = frozenset(approvals)
        self.approver = approver
        self._requests: list[PlatformRequirement] = []
        self._plans: list[tuple[_Group, TargetPlan]] | None = None
        self._results: dict[tuple[str, str | None], TargetResult] = {}
        self._known: set[str] = set()
        for request in requests:
            self.add(request)

    @property
    def requests(self) -> list[PlatformRequirement]:
        return list(self._requests)

    def add(self, request: PlatformRequirement) -> None:
        if request not in self._requests:
            self._requests.append(request)
            self._plans = None

    def note_known(self, digest: str) -> None:
        """Record a digest of this run that is not a change set (a plan item), so approving it is not stale."""
        self._known.add(digest)

    def _all(self) -> list[tuple[_Group, TargetPlan]]:
        if self._plans is None:
            self._plans = _plans(self.repository, self._requests)
        return self._plans

    def _find(self, request: PlatformRequirement) -> tuple[_Group, TargetPlan]:
        self.add(request)
        index = self._requests.index(request)
        for group, target_plan in self._all():
            if index in group.members:
                return group, target_plan
        raise LookupError(request)

    def plan_for(self, request: PlatformRequirement) -> TargetPlan:
        return self._find(request)[1]

    def apply_for(self, request: PlatformRequirement) -> TargetResult:
        group, _ = self._find(request)
        key = (group.kind, group.branch)
        if key not in self._results:
            target_plan = _plan_group(self.repository, group, self._requests)
            plans = [target_plan, *(p for g, p in self._all() if g is not group)]
            stale = _unmatched(self.approvals, plans, self._known)
            self._results[key] = _apply_plan(
                target_plan, policy=self.policy, approvals=self.approvals, approver=self.approver, stale=stale
            )
        return self._results[key]

    @property
    def results(self) -> list[TargetResult]:
        return list(self._results.values())

    @property
    def used_approvals(self) -> list[Approval]:
        return [r.approval for r in self._results.values() if r.approval is not None]


__all__ = [
    "GITHUB_HOST",
    "PlatformSession",
    "ResultKind",
    "TargetPlan",
    "TargetResult",
    "apply",
    "is_supported",
    "plan",
    "platform_repository",
    "platform_requests",
]
