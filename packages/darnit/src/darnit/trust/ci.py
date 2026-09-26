"""CI platform detection and CI trust rules (feature 040, research R4).

Only one rule exists in v1, ``push-default-branch``: a push to the
repository's default branch, where the checked-out commit is the commit the
CI platform reports. Pull requests, merge requests, and every other event are
untrusted, as is any CI platform darnit does not recognize.
"""

from __future__ import annotations

import json
import os
import subprocess
from collections.abc import Iterable, Mapping
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING, Any
from urllib.parse import urlsplit

from darnit.trust.identity import canonical_identity

if TYPE_CHECKING:
    from darnit.config.operator.schema import TrustSettings

PUSH_DEFAULT_BRANCH = "push-default-branch"
REASON_PUSH_DEFAULT_BRANCH = "ci: push to default branch"
REASON_UNKNOWN_EVENT = "ci: unknown event"

# Markers other CI systems set; runs under them are recognized as CI but not
# as a platform whose events darnit can evaluate.
_GENERIC_CI_MARKERS = ("JENKINS_URL", "TF_BUILD", "BUILDKITE", "CIRCLECI", "TRAVIS", "TEAMCITY_VERSION")


def is_recognized_ci() -> bool:
    """True when running under a CI platform darnit recognizes."""
    return os.environ.get("GITHUB_ACTIONS") == "true" or os.environ.get("GITLAB_CI") == "true"


@dataclass(frozen=True)
class CiRun:
    """What the CI platform reports about the current run."""

    platform: str
    event: str | None
    repository: str | None
    commit: str | None
    default_branch_push: bool
    reason: str
    facts: dict[str, Any] = field(default_factory=dict)


def _load_payload(path: str | None) -> dict[str, Any]:
    if not path:
        return {}
    try:
        data = json.loads(Path(path).read_text(encoding="utf-8"))
    except (OSError, UnicodeDecodeError, json.JSONDecodeError):
        return {}
    return data if isinstance(data, dict) else {}


def _get(data: Any, *keys: str) -> Any:
    for key in keys:
        if not isinstance(data, dict):
            return None
        data = data.get(key)
    return data


def _github(env: Mapping[str, str], hosts: Iterable[str]) -> CiRun:
    event = env.get("GITHUB_EVENT_NAME") or None
    payload = _load_payload(env.get("GITHUB_EVENT_PATH"))
    host = urlsplit(env.get("GITHUB_SERVER_URL", "")).hostname
    name = env.get("GITHUB_REPOSITORY")
    repository = canonical_identity(f"{host}/{name}", hosts) if host and name else None
    default_branch = _get(payload, "repository", "default_branch")
    ref = env.get("GITHUB_REF")
    ref_type = env.get("GITHUB_REF_TYPE")
    facts: dict[str, Any] = {
        "platform": "github-actions",
        "event": event,
        "repository": repository,
        "ref": ref,
        "ref_type": ref_type,
        "default_branch": default_branch,
        "commit": env.get("GITHUB_SHA"),
    }

    default_branch_push = False
    if event is None:
        reason = REASON_UNKNOWN_EVENT
    elif event == "push":
        default_branch_push = ref_type == "branch" and bool(default_branch) and ref == f"refs/heads/{default_branch}"
        reason = REASON_PUSH_DEFAULT_BRANCH if default_branch_push else "ci: push to non-default branch"
    elif event in ("pull_request", "pull_request_target"):
        head_repo = _get(payload, "pull_request", "head", "repo")
        base_repo = _get(payload, "pull_request", "base", "repo")
        head_id = _get(head_repo, "id")
        fork = head_id is None or head_id != _get(base_repo, "id")
        facts.update(
            head_repository=_get(head_repo, "full_name"),
            base_repository=_get(base_repo, "full_name"),
            fork=fork,
        )
        reason = "ci: fork pull request" if fork else "ci: pull request"
    else:
        reason = f"ci: untrusted event {event}"

    return CiRun(
        platform="github-actions",
        event=event,
        repository=repository,
        commit=env.get("GITHUB_SHA") or None,
        default_branch_push=default_branch_push,
        reason=reason,
        facts=facts,
    )


def _gitlab(env: Mapping[str, str], hosts: Iterable[str]) -> CiRun:
    source = env.get("CI_PIPELINE_SOURCE") or None
    host = env.get("CI_SERVER_HOST")
    path = env.get("CI_PROJECT_PATH")
    repository = canonical_identity(f"{host}/{path}", hosts) if host and path else None
    branch = env.get("CI_COMMIT_BRANCH")
    default_branch = env.get("CI_DEFAULT_BRANCH")
    merge_request = env.get("CI_MERGE_REQUEST_IID")
    facts: dict[str, Any] = {
        "platform": "gitlab-ci",
        "event": source,
        "repository": repository,
        "ref": branch,
        "default_branch": default_branch,
        "commit": env.get("CI_COMMIT_SHA"),
    }

    default_branch_push = False
    if merge_request or source in ("merge_request_event", "external_pull_request_event"):
        target_project = env.get("CI_MERGE_REQUEST_PROJECT_ID")
        source_project = env.get("CI_MERGE_REQUEST_SOURCE_PROJECT_ID")
        fork = target_project != source_project if target_project and source_project else None
        facts.update(merge_request=merge_request, fork=fork)
        reason = "ci: fork merge request" if fork else "ci: merge request"
    elif source is None:
        reason = REASON_UNKNOWN_EVENT
    elif source == "push":
        default_branch_push = bool(branch) and branch == default_branch
        reason = REASON_PUSH_DEFAULT_BRANCH if default_branch_push else "ci: push to non-default branch"
    else:
        reason = f"ci: untrusted event {source}"

    return CiRun(
        platform="gitlab-ci",
        event=source,
        repository=repository,
        commit=env.get("CI_COMMIT_SHA") or None,
        default_branch_push=default_branch_push,
        reason=reason,
        facts=facts,
    )


def detect_ci_run(env: Mapping[str, str] | None = None, case_insensitive_hosts: Iterable[str] = ()) -> CiRun | None:
    """Describe the CI run, or return None when not running under CI."""
    env = os.environ if env is None else env
    if env.get("GITHUB_ACTIONS") == "true":
        return _github(env, case_insensitive_hosts)
    if env.get("GITLAB_CI") == "true":
        return _gitlab(env, case_insensitive_hosts)
    if env.get("CI", "").lower() in ("true", "1", "yes") or any(env.get(m) for m in _GENERIC_CI_MARKERS):
        return CiRun(
            platform="unknown",
            event=None,
            repository=None,
            commit=None,
            default_branch_push=False,
            reason=REASON_UNKNOWN_EVENT,
            facts={"platform": "unknown"},
        )
    return None


def checkout_head(checkout: str | Path) -> str | None:
    """The commit checked out at ``checkout``, or None when it cannot be read."""
    try:
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=checkout,
            capture_output=True,
            text=True,
            timeout=10,
        )
    except (OSError, subprocess.SubprocessError):
        return None
    if result.returncode != 0:
        return None
    return result.stdout.strip() or None


def apply_ci_rules(
    run: CiRun, trusted_repos: set[str], trust: TrustSettings, checkout: str | Path | None
) -> tuple[bool, str]:
    """Apply the operator's CI trust rules to a run whose repository identity came from CI."""
    if not run.default_branch_push:
        return False, run.reason
    if run.repository is None:
        return False, "ci: repository identity unavailable"
    if run.repository not in trusted_repos:
        return False, "not listed"

    hosts = trust.case_insensitive_hosts
    rule_matches = any(
        rule.event == PUSH_DEFAULT_BRANCH
        and (not rule.repos or run.repository in {canonical_identity(r, hosts) for r in rule.repos})
        for rule in trust.ci
    )
    if not rule_matches:
        return False, "ci: no trust rule for push to default branch"
    head = checkout_head(checkout) if checkout is not None else None
    if head is None or head != run.commit:
        return False, "ci: head does not match CI commit"
    return True, REASON_PUSH_DEFAULT_BRANCH
