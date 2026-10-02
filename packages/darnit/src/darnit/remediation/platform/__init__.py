"""Platform-change engine for remediation (feature 043; framework-design 4.5, 15.1-15.2).

The only path by which darnit changes hosting-platform settings: read the
current state, plan the minimal non-weakening change, apply it under the
operator's remediation policy with digest-bound approval, and read it back.
"""

from darnit.remediation.platform.engine import (
    GITHUB_HOST,
    PlatformSession,
    TargetPlan,
    TargetResult,
    apply,
    is_supported,
    plan,
    platform_repository,
    platform_requests,
)
from darnit.remediation.platform.model import (
    ChangeOperation,
    ChangeSet,
    FieldChange,
    ObservedState,
    PlatformRequirement,
    PlatformTarget,
    Requirement,
)
from darnit.remediation.platform.policy import ResolvedPolicy, TerminalApprover, resolve_policy, terminal_approver

__all__ = [
    "GITHUB_HOST",
    "ChangeOperation",
    "ChangeSet",
    "FieldChange",
    "ObservedState",
    "PlatformRequirement",
    "PlatformSession",
    "PlatformTarget",
    "Requirement",
    "ResolvedPolicy",
    "TargetPlan",
    "TargetResult",
    "TerminalApprover",
    "apply",
    "is_supported",
    "plan",
    "platform_repository",
    "platform_requests",
    "resolve_policy",
    "terminal_approver",
]
