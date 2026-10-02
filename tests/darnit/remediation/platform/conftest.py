"""Recorded GitHub platform states for remediation tests (feature 043 T003; research R12, quickstart V1).

Each builder returns a fresh ``RecordedGhApi`` response set for repository
``o/r``. GET bodies follow the GitHub REST GET shapes (``enforce_admins``
as ``{url, enabled}``, ``allow_*`` as ``{enabled}``, restrictions as arrays
of user/team/app objects, status checks with ``checks[{context, app_id}]``),
which differ from the PUT shapes a remediation sends. Writes a fixture
expects to succeed are recorded; any other write answers status 0.
"""

from __future__ import annotations

from collections.abc import Callable, Iterator
from contextlib import contextmanager
from typing import Any

import pytest

from darnit.core.utils import RecordedGhApi, set_gh_api_responder

OWNER = "o"
REPO = "r"
API = "https://api.github.com"
REPO_PATH = f"/repos/{OWNER}/{REPO}"
CHECKS_APP_ID = 15368

Responses = dict[str, dict[str, Any]]


def _ok(body: Any, status: int = 200) -> dict[str, Any]:
    return {"status": status, "body": body}


def _err(status: int, message: str) -> dict[str, Any]:
    return {"status": status, "error": f"HTTP {status}: {message}"}


def _protection_path(branch: str) -> str:
    return f"{REPO_PATH}/branches/{branch}/protection"


def _repository(default_branch: str = "main", *, private: bool = False) -> dict[str, Any]:
    return {
        "id": 1296269,
        "node_id": "MDEwOlJlcG9zaXRvcnkxMjk2MjY5",
        "name": REPO,
        "full_name": f"{OWNER}/{REPO}",
        "owner": {"login": OWNER, "id": 1, "type": "Organization"},
        "private": private,
        "visibility": "private" if private else "public",
        "default_branch": default_branch,
        "archived": False,
        "url": f"{API}{REPO_PATH}",
        "permissions": {"admin": True, "maintain": True, "push": True, "triage": True, "pull": True},
    }


def _branch(name: str, *, protected: bool, contexts: list[str] | None = None) -> dict[str, Any]:
    contexts = contexts or []
    return {
        "name": name,
        "commit": {"sha": "7fd1a60b01f91b314f59955a4e4d4e80d8edf11d", "url": f"{API}{REPO_PATH}/commits/7fd1a60"},
        "protected": protected,
        "protection": {
            "enabled": protected,
            "required_status_checks": {
                "enforcement_level": "non_admins" if contexts else "off",
                "contexts": list(contexts),
                "checks": [{"context": c, "app_id": CHECKS_APP_ID} for c in contexts],
            },
        },
        "protection_url": f"{API}{_protection_path(name)}",
    }


def _protection(
    branch: str = "main",
    *,
    approvals: int = 1,
    code_owner_reviews: bool = False,
    dismiss_stale_reviews: bool = False,
    contexts: list[str] | None = None,
    restricted: bool = False,
    enforce_admins: bool = True,
    linear_history: bool = False,
    conversation_resolution: bool = False,
    allow_force_pushes: bool = False,
    allow_deletions: bool = False,
) -> dict[str, Any]:
    url = f"{API}{_protection_path(branch)}"
    body: dict[str, Any] = {
        "url": url,
        "required_pull_request_reviews": {
            "url": f"{url}/required_pull_request_reviews",
            "dismiss_stale_reviews": dismiss_stale_reviews,
            "require_code_owner_reviews": code_owner_reviews,
            "required_approving_review_count": approvals,
            "require_last_push_approval": False,
        },
        "required_signatures": {"url": f"{url}/required_signatures", "enabled": False},
        "enforce_admins": {"url": f"{url}/enforce_admins", "enabled": enforce_admins},
        "required_linear_history": {"enabled": linear_history},
        "allow_force_pushes": {"enabled": allow_force_pushes},
        "allow_deletions": {"enabled": allow_deletions},
        "block_creations": {"enabled": False},
        "required_conversation_resolution": {"enabled": conversation_resolution},
        "lock_branch": {"enabled": False},
        "allow_fork_syncing": {"enabled": False},
    }
    if contexts:
        body["required_status_checks"] = {
            "url": f"{url}/required_status_checks",
            "strict": True,
            "contexts": list(contexts),
            "contexts_url": f"{url}/required_status_checks/contexts",
            "checks": [{"context": c, "app_id": CHECKS_APP_ID} for c in contexts],
        }
    if restricted:
        body["restrictions"] = {
            "url": f"{url}/restrictions",
            "users_url": f"{url}/restrictions/users",
            "teams_url": f"{url}/restrictions/teams",
            "apps_url": f"{url}/restrictions/apps",
            "users": [{"login": "octocat", "id": 583231, "type": "User", "site_admin": False}],
            "teams": [
                {
                    "id": 1,
                    "slug": "release-managers",
                    "name": "Release Managers",
                    "permission": "admin",
                    "url": f"{API}/teams/1",
                }
            ],
            "apps": [
                {
                    "id": 1,
                    "slug": "deploy-bot",
                    "name": "Deploy Bot",
                    "owner": {"login": OWNER, "id": 1, "type": "Organization"},
                }
            ],
        }
    return body


def _rule(rule_type: str, parameters: dict[str, Any] | None = None) -> dict[str, Any]:
    rule: dict[str, Any] = {
        "type": rule_type,
        "ruleset_source_type": "Repository",
        "ruleset_source": f"{OWNER}/{REPO}",
        "ruleset_id": 42,
    }
    if parameters is not None:
        rule["parameters"] = parameters
    return rule


def _branch_writes(branch: str) -> Responses:
    path = _protection_path(branch)
    url = f"{API}{path}"
    return {
        f"PUT {path}": _ok({"url": url}),
        f"PATCH {path}/required_pull_request_reviews": _ok({"url": f"{url}/required_pull_request_reviews"}),
        f"POST {path}/enforce_admins": _ok({"url": f"{url}/enforce_admins", "enabled": True}),
        f"POST {path}/required_status_checks/contexts": _ok([]),
        f"PATCH {path}/required_status_checks": _ok({"url": f"{url}/required_status_checks"}),
    }


def _repository_writes() -> Responses:
    return {
        f"PATCH {REPO_PATH}": _ok(_repository()),
        f"PUT {REPO_PATH}/private-vulnerability-reporting": _ok(None, 204),
    }


def _base(
    *,
    protection: dict[str, Any] | None,
    branch: str = "main",
    private: bool = False,
    pvr_enabled: bool = True,
    rules: list[dict[str, Any]] | None = None,
    rulesets: list[dict[str, Any]] | None = None,
    writes: bool = True,
) -> Responses:
    contexts = (protection or {}).get("required_status_checks", {}).get("contexts", [])
    responses: Responses = {
        REPO_PATH: _ok(_repository(branch, private=private)),
        f"{REPO_PATH}/branches/{branch}": _ok(_branch(branch, protected=protection is not None, contexts=contexts)),
        _protection_path(branch): _ok(protection) if protection is not None else _err(404, "Branch not protected"),
        f"{REPO_PATH}/rules/branches/{branch}": _ok(rules or []),
        f"{REPO_PATH}/rulesets": _ok(rulesets or []),
        f"{REPO_PATH}/private-vulnerability-reporting": _ok({"enabled": pvr_enabled}),
    }
    if writes:
        responses.update(_branch_writes(branch))
        responses.update(_repository_writes())
    return responses


def _stricter_protection() -> dict[str, Any]:
    return _protection(
        approvals=2,
        code_owner_reviews=True,
        dismiss_stale_reviews=True,
        contexts=["ci/build", "ci/test"],
        restricted=True,
        enforce_admins=True,
        linear_history=True,
        conversation_resolution=True,
        allow_force_pushes=False,
        allow_deletions=True,
    )


def _satisfied_protection(branch: str = "main") -> dict[str, Any]:
    return _protection(branch, approvals=1, contexts=["ci/build"], enforce_admins=True)


def unprotected() -> Responses:
    return _base(protection=None)


def stricter() -> Responses:
    return _base(protection=_stricter_protection())


def satisfied() -> Responses:
    return _base(protection=_satisfied_protection())


def ruleset_only() -> Responses:
    rules = [
        _rule(
            "pull_request",
            {
                "required_approving_review_count": 1,
                "dismiss_stale_reviews_on_push": False,
                "require_code_owner_review": False,
                "require_last_push_approval": False,
                "required_review_thread_resolution": False,
                "allowed_merge_methods": ["merge", "squash", "rebase"],
            },
        ),
        _rule("deletion"),
    ]
    rulesets = [
        {
            "id": 42,
            "name": "main protection",
            "target": "branch",
            "source_type": "Repository",
            "source": f"{OWNER}/{REPO}",
            "enforcement": "active",
            "node_id": "RRS_lACkVXNlcgQB",
            "_links": {"self": {"href": f"{API}{REPO_PATH}/rulesets/42"}},
        }
    ]
    return _base(protection=None, rules=rules, rulesets=rulesets)


def read_only_token() -> Responses:
    responses = _base(protection=_stricter_protection(), writes=False)
    forbidden = _err(403, "Resource not accessible by personal access token")
    for key in [*_branch_writes("main"), *_repository_writes()]:
        responses[key] = dict(forbidden)
    return responses


def read_failure() -> Responses:
    return {
        REPO_PATH: _ok(_repository()),
        f"{REPO_PATH}/branches/main": _ok(_branch("main", protected=True)),
        _protection_path("main"): _err(502, "Bad Gateway"),
        f"{REPO_PATH}/rulesets": _err(502, "Bad Gateway"),
        f"{REPO_PATH}/private-vulnerability-reporting": _err(502, "Bad Gateway"),
    }


def unknown_field() -> Responses:
    protection = _stricter_protection()
    protection["future_setting"] = {"enabled": True}
    return _base(protection=protection)


def default_branch_release() -> Responses:
    responses = _base(protection=None, branch="release")
    responses[f"{REPO_PATH}/branches/main"] = _ok(_branch("main", protected=True, contexts=["ci/build"]))
    responses[_protection_path("main")] = _ok(_satisfied_protection("main"))
    responses[f"{REPO_PATH}/rules/branches/main"] = _ok([])
    return responses


def private_repo() -> Responses:
    return _base(protection=_satisfied_protection(), private=True)


def pvr_disabled() -> Responses:
    return _base(protection=_satisfied_protection(), pvr_enabled=False)


PLATFORM_FIXTURES: dict[str, Callable[[], Responses]] = {
    "unprotected": unprotected,
    "stricter": stricter,
    "satisfied": satisfied,
    "ruleset_only": ruleset_only,
    "read_only_token": read_only_token,
    "read_failure": read_failure,
    "unknown_field": unknown_field,
    "default_branch_release": default_branch_release,
    "private_repo": private_repo,
    "pvr_disabled": pvr_disabled,
}


@contextmanager
def recorded_gh(responses: Responses | None = None, **kwargs: Any) -> Iterator[RecordedGhApi]:
    """Serve ``responses`` for the duration of the block, then restore the previous responder."""
    responder = RecordedGhApi(responses, **kwargs)
    previous = set_gh_api_responder(responder)
    try:
        yield responder
    finally:
        set_gh_api_responder(previous)


@pytest.fixture()
def gh_platform() -> Iterator[Callable[..., RecordedGhApi]]:
    """Install a ``RecordedGhApi`` for the test (by fixture name or response set); restore afterwards."""
    previous = set_gh_api_responder(None)

    def install(responses: str | Responses | None = None, **kwargs: Any) -> RecordedGhApi:
        if isinstance(responses, str):
            responses = PLATFORM_FIXTURES[responses]()
        responder = RecordedGhApi(responses, **kwargs)
        set_gh_api_responder(responder)
        return responder

    yield install
    set_gh_api_responder(previous)


@pytest.fixture(name="unprotected")
def _unprotected() -> Responses:
    return unprotected()


@pytest.fixture(name="stricter")
def _stricter() -> Responses:
    return stricter()


@pytest.fixture(name="satisfied")
def _satisfied() -> Responses:
    return satisfied()


@pytest.fixture(name="ruleset_only")
def _ruleset_only() -> Responses:
    return ruleset_only()


@pytest.fixture(name="read_only_token")
def _read_only_token() -> Responses:
    return read_only_token()


@pytest.fixture(name="read_failure")
def _read_failure() -> Responses:
    return read_failure()


@pytest.fixture(name="unknown_field")
def _unknown_field() -> Responses:
    return unknown_field()


@pytest.fixture(name="default_branch_release")
def _default_branch_release() -> Responses:
    return default_branch_release()


@pytest.fixture(name="private_repo")
def _private_repo() -> Responses:
    return private_repo()


@pytest.fixture(name="pvr_disabled")
def _pvr_disabled() -> Responses:
    return pvr_disabled()
