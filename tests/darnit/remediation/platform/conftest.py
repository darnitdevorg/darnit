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

from darnit.core.utils import GhApiCall, RecordedGhApi, set_gh_api_responder

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


class SimulatedGitHub(RecordedGhApi):
    """A ``RecordedGhApi`` whose successful writes change what later GETs return (feature 043 US1).

    Platform writes are verified by reading the settings back (FR-006), so a
    test of an apply needs a platform that remembers writes. Writes follow the
    GitHub REST semantics the engine relies on: a protection ``PUT`` replaces
    the whole protection (omitted optional booleans become false, absent
    objects become disabled), the reviews ``PATCH`` merges only the fields it
    sends, ``POST .../enforce_admins`` turns it on, ``POST
    .../required_status_checks/contexts`` adds contexts. A recorded write with
    a non-2xx status is rejected and changes nothing. ``reject`` names writes
    (``"PUT /repos/o/r/branches/main/protection"``) to answer 422 instead.
    """

    def __init__(self, responses: Responses, *, reject: tuple[str, ...] = ()):
        super().__init__(responses)
        self._rejected = {self._key(key) for key in reject}

    def _get(self, path: str) -> Any:
        return self.responses.get(("GET", path), {}).get("body")

    def _set(self, path: str, body: Any, status: int = 200) -> None:
        self.responses[("GET", path)] = {"status": status, "body": body}

    def __call__(self, method: str, endpoint: str | None = None, body: Any = None):
        if endpoint is None:
            method, endpoint = "GET", method
        verb = method.upper()
        key = (verb, self._path(endpoint))
        if verb != "GET" and key in self._rejected:
            self.calls.append(GhApiCall(verb, endpoint, body))
            return None, 422, "HTTP 422: Validation Failed"
        answer = super().__call__(verb, endpoint, body)
        if verb != "GET" and 200 <= answer[1] < 300:
            self._apply(verb, self._path(endpoint), body)
        return answer

    def _apply(self, verb: str, path: str, body: Any) -> None:
        if path == REPO_PATH and verb == "PATCH":
            repo = dict(self._get(path))
            if body.get("visibility") == "public" or body.get("private") is False:
                repo.update(private=False, visibility="public")
            self._set(path, repo)
            return
        if path == f"{REPO_PATH}/private-vulnerability-reporting" and verb == "PUT":
            self._set(path, {"enabled": True})
            return
        branch, _, rest = path.removeprefix(f"{REPO_PATH}/branches/").partition("/protection")
        protection_path = _protection_path(branch)
        current = (
            self._get(protection_path)
            if self.responses.get(("GET", protection_path), {}).get("status", 200) == 200
            else None
        )
        if rest == "" and verb == "PUT":
            self._set(protection_path, _protection_from_put(branch, body, current))
            branch_body = dict(self._get(f"{REPO_PATH}/branches/{branch}"))
            branch_body["protected"] = True
            self._set(f"{REPO_PATH}/branches/{branch}", branch_body)
            return
        assert current is not None, f"{verb} {path} on an unprotected branch"
        updated = dict(current)
        url = f"{API}{protection_path}"
        if rest == "/required_pull_request_reviews" and verb == "PATCH":
            reviews = dict(
                updated.get("required_pull_request_reviews") or {"url": f"{url}/required_pull_request_reviews"}
            )
            reviews.update(body or {})
            updated["required_pull_request_reviews"] = reviews
        elif rest == "/enforce_admins" and verb == "POST":
            updated["enforce_admins"] = {"url": f"{url}/enforce_admins", "enabled": True}
        elif rest == "/required_status_checks/contexts" and verb == "POST":
            checks = dict(updated["required_status_checks"])
            added = [c for c in body["contexts"] if c not in checks["contexts"]]
            checks["contexts"] = checks["contexts"] + added
            checks["checks"] = checks["checks"] + [{"context": c, "app_id": None} for c in added]
            updated["required_status_checks"] = checks
        elif rest == "/required_status_checks" and verb == "PATCH":
            contexts = list(body.get("contexts") or [])
            updated["required_status_checks"] = {
                "url": f"{url}/required_status_checks",
                "strict": bool(body.get("strict", False)),
                "contexts": contexts,
                "contexts_url": f"{url}/required_status_checks/contexts",
                "checks": [{"context": c, "app_id": None} for c in contexts],
            }
        else:
            raise AssertionError(f"SimulatedGitHub does not model {verb} {path}")
        self._set(protection_path, updated)

    def protection(self, branch: str = "main") -> dict[str, Any]:
        return self._get(_protection_path(branch))


def _enabled(value: Any) -> dict[str, bool]:
    return {"enabled": bool(value)}


def _protection_from_put(branch: str, body: dict[str, Any], current: dict[str, Any] | None) -> dict[str, Any]:
    url = f"{API}{_protection_path(branch)}"
    result: dict[str, Any] = {
        "url": url,
        "required_signatures": (current or {}).get(
            "required_signatures", {"url": f"{url}/required_signatures", "enabled": False}
        ),
        "enforce_admins": {"url": f"{url}/enforce_admins", "enabled": bool(body["enforce_admins"])},
    }
    for name in (
        "required_linear_history",
        "allow_force_pushes",
        "allow_deletions",
        "block_creations",
        "required_conversation_resolution",
        "lock_branch",
        "allow_fork_syncing",
    ):
        result[name] = _enabled(body.get(name, False))
    reviews = body["required_pull_request_reviews"]
    if reviews is not None:
        result["required_pull_request_reviews"] = {
            "url": f"{url}/required_pull_request_reviews",
            "dismiss_stale_reviews": reviews.get("dismiss_stale_reviews", False),
            "require_code_owner_reviews": reviews.get("require_code_owner_reviews", False),
            "required_approving_review_count": reviews.get("required_approving_review_count", 0),
            "require_last_push_approval": reviews.get("require_last_push_approval", False),
        }
        for optional in ("dismissal_restrictions", "bypass_pull_request_allowances"):
            if optional in reviews:
                result["required_pull_request_reviews"][optional] = reviews[optional]
    checks = body["required_status_checks"]
    if checks is not None:
        entries = checks.get("checks") or [{"context": c, "app_id": None} for c in checks.get("contexts", [])]
        result["required_status_checks"] = {
            "url": f"{url}/required_status_checks",
            "strict": checks["strict"],
            "contexts": [c["context"] for c in entries],
            "contexts_url": f"{url}/required_status_checks/contexts",
            "checks": [dict(c) for c in entries],
        }
    restrictions = body["restrictions"]
    if restrictions is not None:
        previous = (current or {}).get("restrictions") or {}
        result["restrictions"] = {
            "url": f"{url}/restrictions",
            "users_url": f"{url}/restrictions/users",
            "teams_url": f"{url}/restrictions/teams",
            "apps_url": f"{url}/restrictions/apps",
            "users": [u for u in previous.get("users", []) if u["login"] in restrictions["users"]]
            + [
                {"login": login}
                for login in restrictions["users"]
                if login not in {u["login"] for u in previous.get("users", [])}
            ],
            "teams": [t for t in previous.get("teams", []) if t["slug"] in restrictions["teams"]]
            + [
                {"slug": slug}
                for slug in restrictions["teams"]
                if slug not in {t["slug"] for t in previous.get("teams", [])}
            ],
            "apps": [a for a in previous.get("apps", []) if a["slug"] in restrictions.get("apps", [])]
            + [
                {"slug": slug}
                for slug in restrictions.get("apps", [])
                if slug not in {a["slug"] for a in previous.get("apps", [])}
            ],
        }
    return result


@pytest.fixture()
def simulated_gh() -> Iterator[Callable[..., SimulatedGitHub]]:
    """Install a :class:`SimulatedGitHub` built from a fixture name or response set; restore afterwards."""
    previous = set_gh_api_responder(None)

    def install(responses: str | Responses, **kwargs: Any) -> SimulatedGitHub:
        if isinstance(responses, str):
            responses = PLATFORM_FIXTURES[responses]()
        responder = SimulatedGitHub(responses, **kwargs)
        set_gh_api_responder(responder)
        return responder

    yield install
    set_gh_api_responder(previous)
