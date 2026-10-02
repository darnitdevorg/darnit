"""Remediation plan, outcome, and run models (feature 043, data-model.md).

Remediation handlers describe what they would change as :class:`FileChange`
entries; the executor is the only writer and applies exactly those changes
(research R6). A preview is a list of :class:`PlanItem` entries; an apply
produces one :class:`RemediationOutcome` per control (FR-017).

Every digest is ``"sha256:" + hex(sha256(canonical_json(x)))`` via
:func:`digest`; file contents are hashed by :func:`content_digest`.
"""

from __future__ import annotations

import hashlib
import json
import posixpath
from datetime import datetime
from typing import Any, Literal

from pydantic import BaseModel, ConfigDict, Field, field_validator, model_serializer, model_validator

from darnit.config.operator.schema import RemediationSettings
from darnit.core.error_class import ErrorClass

_FORBID = ConfigDict(extra="forbid")

DIGEST_PREFIX = "sha256:"

FileChangeAction = Literal["create", "modify", "none"]
FileChangeReason = Literal["already_exists", "user_changes_present", "when_not_met"]
OutcomeKind = Literal[
    "fixed",
    "changed_not_passing",
    "changed_not_verified",
    "unchanged",
    "needs_approval",
    "needs_confirmation",
    "manual",
    "error",
]
OUTCOME_KINDS: tuple[str, ...] = (
    "fixed",
    "changed_not_passing",
    "changed_not_verified",
    "unchanged",
    "needs_approval",
    "needs_confirmation",
    "manual",
    "error",
)


def canonical_json(value: Any) -> str:
    return json.dumps(value, sort_keys=True, separators=(",", ":"))


def digest(value: Any) -> str:
    """Digest of a JSON-compatible value; stable under dict key order."""
    return DIGEST_PREFIX + hashlib.sha256(canonical_json(value).encode("utf-8")).hexdigest()


def content_digest(content: str | bytes) -> str:
    """Digest of file content (UTF-8 for text), comparable with a file read from disk."""
    data = content.encode("utf-8") if isinstance(content, str) else content
    return DIGEST_PREFIX + hashlib.sha256(data).hexdigest()


def normalize_repo_path(path: str) -> str:
    """``path`` as a normalized repository-relative POSIX path; ValueError if it leaves the repository."""
    if not path or "\\" in path or "\x00" in path:
        raise ValueError(f"not a repository-relative path: {path!r}")
    if posixpath.isabs(path):
        raise ValueError(f"path must be relative to the repository: {path!r}")
    normalized = posixpath.normpath(path)
    if normalized == "." or normalized == ".." or normalized.startswith("../"):
        raise ValueError(f"path leaves the repository: {path!r}")
    if normalized.split("/", 1)[0] == ".git":
        raise ValueError(f"path is inside .git: {path!r}")
    return normalized


class FileChange(BaseModel):
    """One file a remediation step would create or modify, or leaves alone with a reason."""

    model_config = _FORBID

    path: str
    action: FileChangeAction
    reason: FileChangeReason | None = None
    ignored: bool = False
    content: str | None = None
    before_digest: str | None = None
    after_digest: str | None = None
    project_reference: str | None = None

    @field_validator("path")
    @classmethod
    def _relative_path(cls, value: str) -> str:
        return normalize_repo_path(value)

    @model_validator(mode="after")
    def _consistent(self) -> FileChange:
        if self.action == "none":
            if self.reason is None:
                raise ValueError("a FileChange with action 'none' needs a reason")
            if self.content is not None or self.after_digest is not None:
                raise ValueError("a FileChange with action 'none' has no resulting content")
            return self
        if self.reason is not None:
            raise ValueError(f"a FileChange with action {self.action!r} has no reason")
        if self.content is None:
            raise ValueError(f"a FileChange with action {self.action!r} needs its resulting content")
        if self.action == "create" and self.before_digest is not None:
            raise ValueError("a created file has no before_digest")
        if self.action == "modify" and self.before_digest is None:
            raise ValueError("a modified file needs the before_digest it was planned against")
        expected = content_digest(self.content)
        if self.after_digest is None:
            self.after_digest = expected
        elif self.after_digest != expected:
            raise ValueError("after_digest does not match content")
        return self

    @property
    def changes(self) -> bool:
        return self.action != "none"


def _change_set_changes(change_set: dict[str, Any]) -> bool:
    return bool(change_set.get("operations"))


class PlanItem(BaseModel):
    """One remediation step in a preview."""

    model_config = _FORBID

    control_id: str
    step: str
    file_changes: list[FileChange] = Field(default_factory=list)
    change_sets: list[dict[str, Any]] = Field(default_factory=list)
    commands: list[list[str]] = Field(default_factory=list)
    previewable: bool
    requires_individual_approval: bool = False
    digest: str = ""

    @model_validator(mode="after")
    def _digest(self) -> PlanItem:
        expected = digest(self.model_dump(mode="json", exclude={"digest"}))
        if not self.digest:
            self.digest = expected
        elif self.digest != expected:
            raise ValueError("digest does not match the plan item")
        return self

    @property
    def changes(self) -> bool:
        return any(c.changes for c in self.file_changes) or any(_change_set_changes(c) for c in self.change_sets)


class ErrorInfo(BaseModel):
    """Feature 041 error block: an environmental ``class`` and its ``cause``."""

    model_config = ConfigDict(extra="forbid", populate_by_name=True)

    error_class: ErrorClass = Field(alias="class")
    cause: str = Field(min_length=1)

    @model_serializer
    def _as_041_block(self) -> dict[str, str]:
        return {"class": self.error_class, "cause": self.cause}


class Approval(BaseModel):
    """A person's approval of one previewed change set or plan item."""

    model_config = _FORBID

    digest: str
    approved_by: str
    approved_at: datetime


class RemediationOutcome(BaseModel):
    """What remediation did for one control, and whether it now passes (FR-017)."""

    model_config = _FORBID

    control_id: str
    kind: OutcomeKind
    file_changes: list[FileChange] = Field(default_factory=list)
    change_sets: list[dict[str, Any]] = Field(default_factory=list)
    recheck: dict[str, Any] | None = None
    reason: str | None = None
    error: ErrorInfo | None = None

    @property
    def changed(self) -> bool:
        return any(c.changes for c in self.file_changes) or any(_change_set_changes(c) for c in self.change_sets)

    @model_validator(mode="after")
    def _kind_matches_evidence(self) -> RemediationOutcome:
        recheck_status = (self.recheck or {}).get("status")
        if self.kind in ("fixed", "changed_not_passing", "changed_not_verified") and not self.changed:
            raise ValueError(f"outcome {self.kind!r} needs a non-empty change")
        if self.kind == "fixed" and recheck_status != "PASS":
            raise ValueError("outcome 'fixed' needs a passing re-check")
        if self.kind == "changed_not_passing" and (recheck_status is None or recheck_status == "PASS"):
            raise ValueError("outcome 'changed_not_passing' needs a re-check that did not pass")
        if self.kind == "error" and self.error is None:
            raise ValueError("outcome 'error' needs an error class and cause")
        return self


def summarize(outcomes: list[RemediationOutcome]) -> dict[str, int]:
    counts = dict.fromkeys(OUTCOME_KINDS, 0)
    for outcome in outcomes:
        counts[outcome.kind] += 1
    return counts


class RemediationRun(BaseModel):
    """One preview or apply of remediation for a repository."""

    model_config = _FORBID

    run_id: str
    repository: str
    mode: Literal["preview", "apply"]
    policy: RemediationSettings
    operator_config_digest: str | None
    approvals: list[Approval] = Field(default_factory=list)
    plan: list[PlanItem] = Field(default_factory=list)
    outcomes: list[RemediationOutcome] = Field(default_factory=list)
    summary: dict[str, int] = Field(default_factory=dict)

    @model_validator(mode="after")
    def _derived_summary(self) -> RemediationRun:
        if self.mode == "preview" and self.outcomes:
            raise ValueError("a preview has no outcomes")
        computed = summarize(self.outcomes)
        if self.summary and self.summary != computed:
            raise ValueError("summary must be derived from outcomes")
        self.summary = computed
        return self


__all__ = [
    "DIGEST_PREFIX",
    "OUTCOME_KINDS",
    "Approval",
    "ErrorInfo",
    "FileChange",
    "FileChangeAction",
    "FileChangeReason",
    "OutcomeKind",
    "PlanItem",
    "RemediationOutcome",
    "RemediationRun",
    "canonical_json",
    "content_digest",
    "digest",
    "normalize_repo_path",
    "summarize",
]
