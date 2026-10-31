"""Platform change models (feature 043, data-model.md; framework-design 4.5, 15.2).

A ``platform_setting`` step declares a :class:`Requirement` on a
:class:`PlatformTarget`. The engine reads the target's :class:`ObservedState`
and plans a :class:`ChangeSet`: the minimal :class:`ChangeOperation`s that
satisfy every requirement on the target without weakening anything. Approval
binds to ``ChangeSet.digest``, which covers the target, the observed state,
and the exact operations.
"""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from darnit.remediation.plan import ErrorInfo, digest

_FORBID = ConfigDict(extra="forbid")

TargetKind = Literal["branch_protection", "repository", "vulnerability_reporting"]
Impact = Literal["platform", "high_impact"]

TARGET_IMPACT: dict[str, Impact] = {
    "branch_protection": "platform",
    "repository": "high_impact",
    "vulnerability_reporting": "platform",
}

REQUIREMENT_KEYS: dict[str, frozenset[str]] = {
    "branch_protection": frozenset(
        {
            "require_pull_request",
            "require_approvals",
            "prevent_deletion",
            "prevent_force_push",
            "enforce_admins",
            "require_status_checks",
        }
    ),
    "repository": frozenset({"visibility"}),
    "vulnerability_reporting": frozenset({"enabled"}),
}


def _check_requirement(kind: str, key: str, value: Any) -> Any:
    """``value`` if it is a valid requirement ``key`` for ``kind``, else ValueError.

    A requirement only ever asks for the stricter state: booleans must be
    true, counts at least one, visibility public, contexts non-empty.
    """
    if kind not in REQUIREMENT_KEYS:
        raise ValueError(f"unknown platform target {kind!r}; expected one of {sorted(REQUIREMENT_KEYS)}")
    if key not in REQUIREMENT_KEYS[kind]:
        raise ValueError(
            f"unknown requirement {key!r} for target {kind!r}; expected one of {sorted(REQUIREMENT_KEYS[kind])}"
        )
    if key == "require_approvals":
        if isinstance(value, bool) or not isinstance(value, int) or value < 1:
            raise ValueError("require_approvals must be an integer of at least 1")
        return value
    if key == "require_status_checks":
        if not isinstance(value, list) or not value or not all(isinstance(c, str) and c for c in value):
            raise ValueError("require_status_checks must be a non-empty list of status-check contexts")
        return sorted(set(value))
    if key == "visibility":
        if value != "public":
            raise ValueError('visibility can only be required to be "public"')
        return value
    if value is not True:
        raise ValueError(f"{key} can only be required to be true")
    return value


class PlatformTarget(BaseModel):
    """The repository or branch whose settings a remediation changes."""

    model_config = _FORBID

    kind: TargetKind
    impact: Impact
    owner: str = Field(min_length=1)
    repo: str = Field(min_length=1)
    branch: str | None = None

    @classmethod
    def for_kind(cls, kind: str, owner: str, repo: str, branch: str | None = None) -> PlatformTarget:
        return cls(kind=kind, impact=TARGET_IMPACT[kind], owner=owner, repo=repo, branch=branch)

    @model_validator(mode="after")
    def _fixed_impact(self) -> PlatformTarget:
        if self.impact != TARGET_IMPACT[self.kind]:
            raise ValueError(f"target {self.kind!r} has impact {TARGET_IMPACT[self.kind]!r}")
        if (self.kind == "branch_protection") != (self.branch is not None):
            raise ValueError("a branch is named for branch_protection targets, and only for them")
        return self


class Requirement(BaseModel):
    """One requirement key and the value it asks for."""

    model_config = _FORBID

    key: str
    value: Any


class PlatformRequirement(BaseModel):
    """What one ``platform_setting`` step asks of a target (its TOML fields)."""

    model_config = _FORBID

    target: TargetKind
    require: dict[str, Any]
    branch: str | None = None

    @model_validator(mode="after")
    def _valid(self) -> PlatformRequirement:
        if not self.require:
            raise ValueError("require names at least one requirement")
        self.require = {key: _check_requirement(self.target, key, value) for key, value in self.require.items()}
        if self.branch is not None and self.target != "branch_protection":
            raise ValueError("branch applies only to target branch_protection")
        if self.branch is not None and not self.branch.strip():
            raise ValueError("branch must not be empty")
        return self


def merge_requirements(requests: Iterable[Mapping[str, Any]]) -> list[Requirement]:
    """The strictest value of every requirement key across ``requests``, sorted by key."""
    merged: dict[str, Any] = {}
    for require in requests:
        for key, value in require.items():
            if key not in merged:
                merged[key] = value
            elif key == "require_approvals":
                merged[key] = max(merged[key], value)
            elif key == "require_status_checks":
                merged[key] = sorted(set(merged[key]) | set(value))
    return [Requirement(key=key, value=merged[key]) for key in sorted(merged)]


class FieldChange(BaseModel):
    """One setting an operation changes: its value before and after."""

    model_config = _FORBID

    field: str
    before: Any
    after: Any


class ChangeOperation(BaseModel):
    """One platform write, with the exact JSON body sent."""

    model_config = _FORBID

    method: Literal["PUT", "PATCH", "POST"]
    endpoint: str
    body: dict[str, Any] | None = None
    changes: list[FieldChange] = Field(default_factory=list)


class ObservedState(BaseModel):
    """A target's current settings as read from the platform."""

    model_config = _FORBID

    target: PlatformTarget
    exists: bool
    fields: dict[str, Any] = Field(default_factory=dict)
    rules: list[dict[str, Any]] = Field(default_factory=list)
    digest: str = ""
    read_error: ErrorInfo | None = None

    @model_validator(mode="after")
    def _digest(self) -> ObservedState:
        self.digest = digest({"exists": self.exists, "fields": self.fields, "rules": self.rules})
        return self


_TOWARD_TRUE = frozenset(
    {
        "protected",
        "enforce_admins",
        "required_linear_history",
        "required_conversation_resolution",
        "require_code_owner_reviews",
        "dismiss_stale_reviews",
        "require_last_push_approval",
        "block_creations",
        "lock_branch",
        "required_signatures",
        "enabled",
    }
)
_TOWARD_FALSE = frozenset({"allow_deletions", "allow_force_pushes", "allow_fork_syncing"})
_ENABLED_WHEN_SET = frozenset({"required_pull_request_reviews", "required_status_checks", "restrictions"})


def is_not_weaker(field: str, before: Any, after: Any) -> bool:
    """True when ``after`` is equal to or stricter than ``before`` for ``field`` (FR-003)."""
    if before == after:
        return True
    leaf = field.rsplit(".", 1)[-1]
    if leaf in _TOWARD_TRUE:
        return after is True
    if leaf in _TOWARD_FALSE:
        return after is False
    if leaf == "required_approving_review_count":
        return isinstance(after, int) and after >= (before or 0)
    if leaf == "contexts":
        return set(after or []) >= set(before or [])
    if leaf == "visibility":
        return after == "public"
    if field in _ENABLED_WHEN_SET:
        return before is None and after is not None
    return False


ChangeReason = Literal["already", "ruleset"]


class ChangeSet(BaseModel):
    """The minimal operations that satisfy every requirement on one target."""

    model_config = _FORBID

    target: PlatformTarget
    requirements: list[Requirement]
    observed_digest: str
    operations: list[ChangeOperation] = Field(default_factory=list)
    satisfied_by: ChangeReason | None = None
    impact_notes: list[str] = Field(default_factory=list)
    digest: str = ""

    @model_validator(mode="after")
    def _valid(self) -> ChangeSet:
        for operation in self.operations:
            for change in operation.changes:
                if not is_not_weaker(change.field, change.before, change.after):
                    raise ValueError(
                        f"refusing a change that weakens {change.field}: {change.before!r} -> {change.after!r}"
                    )
        if bool(self.operations) == (self.satisfied_by is not None):
            raise ValueError("satisfied_by is set exactly when there is nothing to change")
        expected = change_set_digest(self.target, self.observed_digest, self.operations)
        if not self.digest:
            self.digest = expected
        elif self.digest != expected:
            raise ValueError("digest does not match the change set")
        return self

    @property
    def fields(self) -> list[FieldChange]:
        return [change for operation in self.operations for change in operation.changes]


def change_set_digest(target: PlatformTarget, observed_digest: str, operations: Iterable[ChangeOperation]) -> str:
    return digest(
        {
            "target": target.model_dump(mode="json"),
            "observed_digest": observed_digest,
            "operations": [operation.model_dump(mode="json") for operation in operations],
        }
    )


__all__ = [
    "REQUIREMENT_KEYS",
    "TARGET_IMPACT",
    "ChangeOperation",
    "ChangeSet",
    "FieldChange",
    "Impact",
    "ObservedState",
    "PlatformRequirement",
    "PlatformTarget",
    "Requirement",
    "TargetKind",
    "change_set_digest",
    "is_not_weaker",
    "merge_requirements",
]
