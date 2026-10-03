"""GitHub platform targets: readers, the protection translator, comparators, planners (feature 043, research R2, R3).

Each target kind has a reader that turns platform GET responses into an
:class:`~darnit.remediation.platform.model.ObservedState`, a comparator
that decides which requirements already hold (classic settings or an active
ruleset), and a planner that produces the minimal non-weakening operations.

Branch protection ``fields`` use the PUT shape of
``PUT /repos/{o}/{r}/branches/{b}/protection`` (plus ``required_signatures``,
which has its own endpoint). An unprotected branch is described by its
effective settings: deletions and force pushes allowed, nothing required.
"""

from __future__ import annotations

import copy
from collections.abc import Iterable, Mapping
from typing import Any

from darnit.core.error_class import ErrorClass
from darnit.core.utils import gh_api_error_class, gh_api_with_status
from darnit.remediation.plan import ErrorInfo
from darnit.remediation.platform.model import (
    ChangeOperation,
    ChangeSet,
    FieldChange,
    ObservedState,
    PlatformTarget,
    Requirement,
)


class ReadError(Exception):
    """A target's current settings could not be read (FR-002)."""

    def __init__(self, error_class: ErrorClass, cause: str) -> None:
        super().__init__(cause)
        self.error_class = error_class
        self.cause = cause

    def info(self) -> ErrorInfo:
        return ErrorInfo(error_class=self.error_class, cause=self.cause)


class UnknownProtectionField(ValueError):
    """A protection response holds a setting the translator cannot carry into a PUT."""

    def __init__(self, field: str) -> None:
        super().__init__(f"cannot preserve unknown protection setting {field}")
        self.field = field


def _read(endpoint: str, what: str) -> Any:
    body, status, error = gh_api_with_status(endpoint)
    if 200 <= status < 300:
        return body
    raise ReadError(gh_api_error_class(status, error), f"cannot read {what} ({endpoint}): {error or f'HTTP {status}'}")


def _read_mapping(endpoint: str, what: str) -> dict[str, Any]:
    body = _read(endpoint, what)
    if not isinstance(body, dict):
        raise ReadError("evaluation", f"cannot read {what} ({endpoint}): the response is not an object")
    return body


def resolve_default_branch(owner: str, repo: str) -> str:
    """The repository's default branch as the platform reports it (FR-007)."""
    body = _read_mapping(f"/repos/{owner}/{repo}", "the repository's default branch")
    branch = body.get("default_branch")
    if not isinstance(branch, str) or not branch:
        raise ReadError("evaluation", f"the platform reported no default branch for {owner}/{repo}")
    return branch


# =============================================================================
# Branch protection translator (GET shape <-> PUT shape)
# =============================================================================

_WRAPPED_BOOLEANS = (
    "required_linear_history",
    "allow_force_pushes",
    "allow_deletions",
    "block_creations",
    "required_conversation_resolution",
    "lock_branch",
    "allow_fork_syncing",
)
_TOP_KEYS = frozenset(
    {
        "url",
        "required_status_checks",
        "enforce_admins",
        "required_pull_request_reviews",
        "restrictions",
        "required_signatures",
        *_WRAPPED_BOOLEANS,
    }
)
_ENABLED_KEYS = frozenset({"url", "enabled"})
_STATUS_KEYS = frozenset({"url", "enforcement_level", "strict", "contexts", "contexts_url", "checks"})
_REVIEW_KEYS = frozenset(
    {
        "url",
        "dismissal_restrictions",
        "dismiss_stale_reviews",
        "require_code_owner_reviews",
        "required_approving_review_count",
        "require_last_push_approval",
        "bypass_pull_request_allowances",
    }
)
_REVIEW_BOOLEANS = ("dismiss_stale_reviews", "require_code_owner_reviews", "require_last_push_approval")
_ACTOR_KEYS = frozenset({"url", "users_url", "teams_url", "apps_url", "users", "teams", "apps"})
_ACTOR_IDS = (("users", "login"), ("teams", "slug"), ("apps", "slug"))
MANDATORY_PUT_KEYS = ("required_status_checks", "enforce_admins", "required_pull_request_reviews", "restrictions")


class _Unknown:
    """Collects unknown settings; raises on the first one when strict."""

    def __init__(self, strict: bool) -> None:
        self.strict = strict
        self.found: dict[str, Any] = {}

    def check(self, obj: Mapping[str, Any], known: frozenset[str], path: str) -> None:
        for key in obj:
            if key not in known:
                field = f"{path}.{key}" if path else key
                if self.strict:
                    raise UnknownProtectionField(field)
                self.found[field] = copy.deepcopy(obj[key])


def _enabled(obj: Any, path: str, unknown: _Unknown) -> bool:
    if obj is None:
        return False
    if isinstance(obj, bool):
        return obj
    if not isinstance(obj, Mapping):
        raise UnknownProtectionField(path)
    unknown.check(obj, _ENABLED_KEYS, path)
    return obj.get("enabled") is True


def _actors(obj: Any, path: str, unknown: _Unknown, *, known: frozenset[str] = _ACTOR_KEYS) -> dict[str, list[str]]:
    if not isinstance(obj, Mapping):
        raise UnknownProtectionField(path)
    unknown.check(obj, known, path)
    result: dict[str, list[str]] = {}
    for group, identifier in _ACTOR_IDS:
        entries = obj.get(group) or []
        names = []
        for entry in entries:
            name = entry.get(identifier) if isinstance(entry, Mapping) else None
            if not isinstance(name, str):
                raise UnknownProtectionField(f"{path}.{group}")
            names.append(name)
        result[group] = names
    return result


def _status_checks(obj: Any, unknown: _Unknown) -> dict[str, Any] | None:
    if obj is None:
        return None
    if not isinstance(obj, Mapping):
        raise UnknownProtectionField("required_status_checks")
    unknown.check(obj, _STATUS_KEYS, "required_status_checks")
    if obj.get("checks") is not None:
        checks = []
        for check in obj["checks"]:
            if not isinstance(check, Mapping) or not isinstance(check.get("context"), str):
                raise UnknownProtectionField("required_status_checks.checks")
            entry = {"context": check["context"]}
            if check.get("app_id") is not None:
                entry["app_id"] = check["app_id"]
            checks.append(entry)
    else:
        checks = [{"context": context} for context in obj.get("contexts") or []]
    return {"strict": obj.get("strict") is True, "checks": checks}


def _reviews(obj: Any, unknown: _Unknown) -> dict[str, Any] | None:
    if obj is None:
        return None
    if not isinstance(obj, Mapping):
        raise UnknownProtectionField("required_pull_request_reviews")
    path = "required_pull_request_reviews"
    unknown.check(obj, _REVIEW_KEYS, path)
    result: dict[str, Any] = {name: obj.get(name) is True for name in _REVIEW_BOOLEANS}
    count = obj.get("required_approving_review_count", 0)
    result["required_approving_review_count"] = count if isinstance(count, int) else 0
    for name in ("dismissal_restrictions", "bypass_pull_request_allowances"):
        if obj.get(name) is not None:
            result[name] = _actors(obj[name], f"{path}.{name}", unknown)
    return result


def _translate(get: Mapping[str, Any], unknown: _Unknown) -> dict[str, Any]:
    unknown.check(get, _TOP_KEYS, "")
    put: dict[str, Any] = {
        "required_status_checks": _status_checks(get.get("required_status_checks"), unknown),
        "enforce_admins": _enabled(get.get("enforce_admins"), "enforce_admins", unknown),
        "required_pull_request_reviews": _reviews(get.get("required_pull_request_reviews"), unknown),
        "restrictions": (
            _actors(get["restrictions"], "restrictions", unknown) if get.get("restrictions") is not None else None
        ),
    }
    for name in _WRAPPED_BOOLEANS:
        put[name] = _enabled(get.get(name), name, unknown)
    return put


def protection_get_to_put(get: Mapping[str, Any]) -> dict[str, Any]:
    """Translate a protection GET response into the PUT body that preserves every setting.

    Total over the known field list; any other key raises
    :class:`UnknownProtectionField` rather than risk dropping it.
    ``required_signatures`` is read but not part of the PUT body.
    """
    return _translate(get, _Unknown(strict=True))


def _actors_as_get(actors: Mapping[str, list[str]]) -> dict[str, list[dict[str, str]]]:
    return {group: [{identifier: name} for name in actors.get(group, [])] for group, identifier in _ACTOR_IDS}


def protection_put_to_get(put: Mapping[str, Any]) -> dict[str, Any]:
    """The normalized GET shape (see :func:`normalize_protection_get`) a PUT body describes."""
    result: dict[str, Any] = {"enforce_admins": {"enabled": bool(put["enforce_admins"])}}
    for name in _WRAPPED_BOOLEANS:
        result[name] = {"enabled": bool(put.get(name, False))}
    checks = put.get("required_status_checks")
    if checks is not None:
        entries = [{"context": c["context"], "app_id": c.get("app_id")} for c in checks.get("checks", [])]
        result["required_status_checks"] = {
            "strict": bool(checks.get("strict")),
            "contexts": [c["context"] for c in entries],
            "checks": entries,
        }
    else:
        result["required_status_checks"] = None
    reviews = put.get("required_pull_request_reviews")
    if reviews is not None:
        shown: dict[str, Any] = {name: bool(reviews.get(name, False)) for name in _REVIEW_BOOLEANS}
        shown["required_approving_review_count"] = reviews.get("required_approving_review_count", 0)
        for name in ("dismissal_restrictions", "bypass_pull_request_allowances"):
            if name in reviews:
                shown[name] = _actors_as_get(reviews[name])
        result["required_pull_request_reviews"] = shown
    else:
        result["required_pull_request_reviews"] = None
    restrictions = put.get("restrictions")
    result["restrictions"] = _actors_as_get(restrictions) if restrictions is not None else None
    return result


def normalize_protection_get(get: Mapping[str, Any]) -> dict[str, Any]:
    """A protection GET response without URLs, with users, teams, and apps reduced to their identifiers.

    ``required_signatures`` is left out: it is not part of a PUT body.
    """
    unknown = _Unknown(strict=True)
    unknown.check(get, _TOP_KEYS, "")
    result: dict[str, Any] = {
        "enforce_admins": {"enabled": _enabled(get.get("enforce_admins"), "enforce_admins", unknown)}
    }
    for name in _WRAPPED_BOOLEANS:
        result[name] = {"enabled": _enabled(get.get(name), name, unknown)}
    checks = get.get("required_status_checks")
    if checks is not None:
        unknown.check(checks, _STATUS_KEYS, "required_status_checks")
        entries = (
            [{"context": c["context"], "app_id": c.get("app_id")} for c in checks["checks"]]
            if checks.get("checks") is not None
            else [{"context": c, "app_id": None} for c in checks.get("contexts") or []]
        )
        result["required_status_checks"] = {
            "strict": checks.get("strict") is True,
            "contexts": [c["context"] for c in entries],
            "checks": entries,
        }
    else:
        result["required_status_checks"] = None
    reviews = get.get("required_pull_request_reviews")
    if reviews is not None:
        unknown.check(reviews, _REVIEW_KEYS, "required_pull_request_reviews")
        shown: dict[str, Any] = {name: reviews.get(name) is True for name in _REVIEW_BOOLEANS}
        shown["required_approving_review_count"] = reviews.get("required_approving_review_count", 0)
        for name in ("dismissal_restrictions", "bypass_pull_request_allowances"):
            if reviews.get(name) is not None:
                shown[name] = _actors_as_get(_actors(reviews[name], name, unknown))
        result["required_pull_request_reviews"] = shown
    else:
        result["required_pull_request_reviews"] = None
    restrictions = get.get("restrictions")
    result["restrictions"] = (
        _actors_as_get(_actors(restrictions, "restrictions", unknown)) if restrictions is not None else None
    )
    return result


UNPROTECTED_FIELDS: dict[str, Any] = {
    "required_status_checks": None,
    "enforce_admins": False,
    "required_pull_request_reviews": None,
    "restrictions": None,
    "required_linear_history": False,
    "allow_force_pushes": True,
    "allow_deletions": True,
    "block_creations": False,
    "required_conversation_resolution": False,
    "lock_branch": False,
    "allow_fork_syncing": False,
    "required_signatures": False,
}


# =============================================================================
# Readers
# =============================================================================


def read_state(target: PlatformTarget) -> ObservedState:
    """Read the target's current settings. Raises :class:`ReadError` when any read fails."""
    if target.kind == "branch_protection":
        return _read_branch(target)
    if target.kind == "repository":
        body = _read_mapping(f"/repos/{target.owner}/{target.repo}", "repository settings")
        visibility = body.get("visibility")
        if visibility not in ("public", "private", "internal"):
            private = body.get("private")
            if not isinstance(private, bool):
                raise ReadError("evaluation", "the platform reported no repository visibility")
            visibility = "private" if private else "public"
        return ObservedState(target=target, exists=True, fields={"visibility": visibility})
    endpoint = f"/repos/{target.owner}/{target.repo}/private-vulnerability-reporting"
    body = _read_mapping(endpoint, "private vulnerability reporting")
    if not isinstance(body.get("enabled"), bool):
        raise ReadError("evaluation", f"cannot read private vulnerability reporting ({endpoint}): no enabled flag")
    return ObservedState(target=target, exists=True, fields={"enabled": body["enabled"]})


def _read_branch(target: PlatformTarget) -> ObservedState:
    base = f"/repos/{target.owner}/{target.repo}"
    branch = target.branch
    branch_body = _read_mapping(f"{base}/branches/{branch}", f"branch {branch}")
    protected = branch_body.get("protected")
    if not isinstance(protected, bool):
        raise ReadError("evaluation", f"the platform did not report whether branch {branch} is protected")
    if protected:
        get = _read_mapping(f"{base}/branches/{branch}/protection", f"branch protection for {branch}")
        unknown = _Unknown(strict=False)
        fields = _translate(get, unknown)
        fields["required_signatures"] = _enabled(get.get("required_signatures"), "required_signatures", unknown)
        if unknown.found:
            fields["unrecognized"] = unknown.found
    else:
        fields = dict(UNPROTECTED_FIELDS)
    rules = _read(f"{base}/rules/branches/{branch}", f"active rules for branch {branch}")
    if not isinstance(rules, list):
        raise ReadError("evaluation", f"cannot read active rules for branch {branch}: the response is not a list")
    return ObservedState(target=target, exists=protected, fields=fields, rules=rules)


# =============================================================================
# Comparators
# =============================================================================


def _contexts(fields: Mapping[str, Any]) -> list[str]:
    checks = fields.get("required_status_checks")
    if not checks:
        return []
    return sorted({c["context"] for c in checks.get("checks", [])})


def _review_count(fields: Mapping[str, Any]) -> int:
    reviews = fields.get("required_pull_request_reviews") or {}
    return int(reviews.get("required_approving_review_count") or 0)


def _met_classic(state: ObservedState, requirement: Requirement) -> bool:
    fields = state.fields
    key, value = requirement.key, requirement.value
    if key == "require_pull_request":
        return fields.get("required_pull_request_reviews") is not None
    if key == "require_approvals":
        return fields.get("required_pull_request_reviews") is not None and _review_count(fields) >= value
    if key == "prevent_deletion":
        return fields.get("allow_deletions") is False
    if key == "prevent_force_push":
        return fields.get("allow_force_pushes") is False
    if key == "enforce_admins":
        return fields.get("enforce_admins") is True
    if key == "require_status_checks":
        return set(value) <= set(_contexts(fields))
    if key == "visibility":
        return fields.get("visibility") == value
    if key == "enabled":
        return fields.get("enabled") is True
    return False


def _met_rules(rules: Iterable[Mapping[str, Any]], requirement: Requirement) -> bool:
    key, value = requirement.key, requirement.value
    for rule in rules:
        kind = rule.get("type")
        params = rule.get("parameters") or {}
        if key == "require_pull_request" and kind == "pull_request":
            return True
        if key == "require_approvals" and kind == "pull_request":
            count = params.get("required_approving_review_count", 0)
            if isinstance(count, int) and count >= value:
                return True
        if key == "prevent_deletion" and kind == "deletion":
            return True
        if key == "prevent_force_push" and kind == "non_fast_forward":
            return True
        if key == "require_status_checks" and kind == "required_status_checks":
            contexts = {c.get("context") for c in params.get("required_status_checks") or []}
            if set(value) <= contexts:
                return True
    return False


def unmet(state: ObservedState, requirements: Iterable[Requirement]) -> list[Requirement]:
    """The requirements neither the classic settings nor an active rule satisfy."""
    return [r for r in requirements if not _met_classic(state, r) and not _met_rules(state.rules, r)]


def _satisfied_by(state: ObservedState, requirements: list[Requirement]) -> str:
    return "already" if all(_met_classic(state, r) for r in requirements) else "ruleset"


# =============================================================================
# Planners
# =============================================================================


def plan_change_set(state: ObservedState, requirements: list[Requirement]) -> ChangeSet:
    """The minimal non-weakening change satisfying ``requirements`` from ``state``.

    Raises:
        UnknownProtectionField: the plan needs a full protection PUT and the
            current protection holds a setting the translator does not know.
    """
    missing = unmet(state, requirements)
    target = state.target
    if not missing:
        return ChangeSet(
            target=target,
            requirements=requirements,
            observed_digest=state.digest,
            satisfied_by=_satisfied_by(state, requirements),
        )
    if target.kind == "branch_protection":
        operations = _plan_branch(state, {r.key: r.value for r in missing})
    elif target.kind == "repository":
        operations = [
            ChangeOperation(
                method="PATCH",
                endpoint=f"/repos/{target.owner}/{target.repo}",
                body={"visibility": "public"},
                changes=[FieldChange(field="visibility", before=state.fields.get("visibility"), after="public")],
            )
        ]
    else:
        operations = [
            ChangeOperation(
                method="PUT",
                endpoint=f"/repos/{target.owner}/{target.repo}/private-vulnerability-reporting",
                changes=[FieldChange(field="enabled", before=state.fields.get("enabled"), after=True)],
            )
        ]
    return ChangeSet(
        target=target,
        requirements=requirements,
        observed_digest=state.digest,
        operations=operations,
        impact_notes=impact_notes(state),
    )


def impact_notes(state: ObservedState) -> list[str]:
    """Consequences of changing the target that a person approving it must see (R14)."""
    if state.target.kind == "repository":
        return [
            "All code, commit history, issues, and Actions logs become publicly readable.",
            "Existing private forks are detached from the repository.",
        ]
    if state.target.kind == "branch_protection" and state.rules:
        return [
            f"An active ruleset also applies to branch {state.target.branch}; "
            "this change adds classic branch protection alongside it."
        ]
    return []


def _plan_branch(state: ObservedState, missing: dict[str, Any]) -> list[ChangeOperation]:
    target = state.target
    endpoint = f"/repos/{target.owner}/{target.repo}/branches/{target.branch}/protection"
    fields = state.fields
    approvals = missing.get("require_approvals", 0)
    needs_reviews = "require_pull_request" in missing or "require_approvals" in missing
    contexts = missing.get("require_status_checks")

    if not state.exists:
        body: dict[str, Any] = dict.fromkeys(MANDATORY_PUT_KEYS)
        body["enforce_admins"] = "enforce_admins" in missing
        changes = [
            FieldChange(field="protected", before=False, after=True),
            FieldChange(field="allow_deletions", before=True, after=False),
            FieldChange(field="allow_force_pushes", before=True, after=False),
        ]
        if needs_reviews:
            body["required_pull_request_reviews"] = {"required_approving_review_count": approvals}
            changes.append(
                FieldChange(
                    field="required_pull_request_reviews", before=None, after=body["required_pull_request_reviews"]
                )
            )
        if body["enforce_admins"]:
            changes.append(FieldChange(field="enforce_admins", before=False, after=True))
        if contexts:
            body["required_status_checks"] = {"strict": False, "contexts": list(contexts)}
            changes.append(
                FieldChange(field="required_status_checks", before=None, after=body["required_status_checks"])
            )
        return [ChangeOperation(method="PUT", endpoint=endpoint, body=body, changes=changes)]

    operations: list[ChangeOperation] = []
    reviews = fields.get("required_pull_request_reviews")
    target_count = max(approvals, _review_count(fields))
    fold_reviews = needs_reviews and reviews is None
    fold_checks = bool(contexts) and fields.get("required_status_checks") is None
    put_changes: list[FieldChange] = []
    if needs_reviews:
        patch = {"required_approving_review_count": target_count}
        if fold_reviews:
            put_changes.append(FieldChange(field="required_pull_request_reviews", before=None, after=patch))
        else:
            change = FieldChange(
                field="required_pull_request_reviews.required_approving_review_count",
                before=_review_count(fields),
                after=target_count,
            )
            operations.append(
                ChangeOperation(
                    method="PATCH", endpoint=f"{endpoint}/required_pull_request_reviews", body=patch, changes=[change]
                )
            )
    if "enforce_admins" in missing:
        operations.append(
            ChangeOperation(
                method="POST",
                endpoint=f"{endpoint}/enforce_admins",
                changes=[FieldChange(field="enforce_admins", before=False, after=True)],
            )
        )
    if contexts:
        current = _contexts(fields)
        added = [c for c in contexts if c not in current]
        if fold_checks:
            put_changes.append(FieldChange(field="required_status_checks", before=None, after={"contexts": added}))
        else:
            operations.append(
                ChangeOperation(
                    method="POST",
                    endpoint=f"{endpoint}/required_status_checks/contexts",
                    body={"contexts": added},
                    changes=[
                        FieldChange(
                            field="required_status_checks.contexts", before=current, after=sorted({*current, *added})
                        )
                    ],
                )
            )

    toggles = [
        name
        for key, name in (("prevent_deletion", "allow_deletions"), ("prevent_force_push", "allow_force_pushes"))
        if key in missing
    ]
    put_changes += [FieldChange(field=name, before=fields.get(name), after=False) for name in toggles]
    if put_changes:
        if fields.get("unrecognized"):
            raise UnknownProtectionField(sorted(fields["unrecognized"])[0])
        body = {key: copy.deepcopy(value) for key, value in fields.items() if key != "required_signatures"}
        if needs_reviews:
            current_reviews = body["required_pull_request_reviews"] or {}
            body["required_pull_request_reviews"] = {**current_reviews, "required_approving_review_count": target_count}
        if "enforce_admins" in missing:
            body["enforce_admins"] = True
        if contexts:
            checks = body["required_status_checks"] or {"strict": False, "checks": []}
            known = {c["context"] for c in checks["checks"]}
            checks["checks"] = checks["checks"] + [{"context": c} for c in contexts if c not in known]
            body["required_status_checks"] = checks
        for name in toggles:
            body[name] = False
        operations.append(ChangeOperation(method="PUT", endpoint=endpoint, body=body, changes=put_changes))
    return operations


# =============================================================================
# Read-back comparison and manual steps
# =============================================================================


def diff_fields(before: Any, after: Any, prefix: str = "") -> list[FieldChange]:
    """Every setting that differs between two observed ``fields`` mappings."""
    if isinstance(before, Mapping) and isinstance(after, Mapping):
        changes: list[FieldChange] = []
        for key in sorted(set(before) | set(after)):
            changes += diff_fields(before.get(key), after.get(key), f"{prefix}.{key}" if prefix else key)
        return changes
    if before != after:
        return [FieldChange(field=prefix, before=before, after=after)]
    return []


def state_changes(before: ObservedState, after: ObservedState) -> list[FieldChange]:
    changes = diff_fields(before.fields, after.fields)
    if before.exists != after.exists and before.target.kind == "branch_protection":
        changes.insert(0, FieldChange(field="protected", before=before.exists, after=after.exists))
    return changes


def _requirement_step(target: PlatformTarget, requirement: Requirement) -> str:
    branch = target.branch
    key, value = requirement.key, requirement.value
    if key == "require_pull_request":
        return f"Require a pull request before merging into {branch}"
    if key == "require_approvals":
        return f"Require at least {value} approving review(s) before merging into {branch}"
    if key == "prevent_deletion":
        return f"Do not allow deletions of {branch}"
    if key == "prevent_force_push":
        return f"Do not allow force pushes to {branch}"
    if key == "enforce_admins":
        return f"Apply the {branch} protection rules to administrators too"
    if key == "require_status_checks":
        return f"Require these status checks to pass before merging into {branch}: {', '.join(value)}"
    if key == "visibility":
        return "Change the repository visibility to public"
    return "Enable private vulnerability reporting"


_SETTINGS_PAGE = {
    "branch_protection": "Settings -> Branches (or Settings -> Rules -> Rulesets)",
    "repository": "Settings -> General -> Danger Zone -> Change repository visibility",
    "vulnerability_reporting": "Settings -> Code security -> Private vulnerability reporting",
}


def manual_steps(
    target: PlatformTarget, requirements: list[Requirement], change_set: ChangeSet | None = None
) -> list[str]:
    """Steps for a person to make the change darnit did not make."""
    steps = [f"Open {target.owner}/{target.repo} {_SETTINGS_PAGE[target.kind]}"]
    steps += [_requirement_step(target, r) for r in requirements]
    if change_set is not None:
        steps += [f"Expected change: {c.field}: {_show(c.before)} -> {_show(c.after)}" for c in change_set.fields]
        steps += [f"Impact: {note}" for note in change_set.impact_notes]
    steps.append("Leave every other existing setting as it is")
    return steps


def _show(value: Any) -> str:
    if value is None:
        return "off"
    if isinstance(value, bool):
        return "true" if value else "false"
    if isinstance(value, list):
        return "[" + ", ".join(str(v) for v in value) + "]"
    return str(value)


def show_value(value: Any) -> str:
    """A field value as a person reads it in a preview."""
    return _show(value)


__all__ = [
    "MANDATORY_PUT_KEYS",
    "UNPROTECTED_FIELDS",
    "ReadError",
    "UnknownProtectionField",
    "diff_fields",
    "impact_notes",
    "manual_steps",
    "normalize_protection_get",
    "plan_change_set",
    "protection_get_to_put",
    "protection_put_to_get",
    "read_state",
    "resolve_default_branch",
    "show_value",
    "state_changes",
    "unmet",
]
