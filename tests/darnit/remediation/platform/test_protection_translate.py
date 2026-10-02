"""GET-to-PUT branch-protection translator is total and lossless (feature 043 T017; R3)."""

from __future__ import annotations

import copy

import pytest

from darnit.remediation.platform.targets import (
    UnknownProtectionField,
    normalize_protection_get,
    protection_get_to_put,
    protection_put_to_get,
)
from tests.darnit.remediation.platform.conftest import API, _protection, _satisfied_protection, _stricter_protection

URL = f"{API}/repos/o/r/branches/main/protection"


def _with_review_allowances() -> dict:
    body = _stricter_protection()
    reviews = body["required_pull_request_reviews"]
    reviews["dismissal_restrictions"] = {
        "url": f"{URL}/dismissal_restrictions",
        "users_url": f"{URL}/dismissal_restrictions/users",
        "teams_url": f"{URL}/dismissal_restrictions/teams",
        "users": [{"login": "hubot", "id": 2}],
        "teams": [{"slug": "maintainers", "id": 3}],
        "apps": [{"slug": "review-bot", "id": 4}],
    }
    reviews["bypass_pull_request_allowances"] = {
        "users": [{"login": "release-bot", "id": 5}],
        "teams": [],
        "apps": [{"slug": "merge-queue", "id": 6}],
    }
    body["required_signatures"]["enabled"] = True
    body["block_creations"] = {"enabled": True}
    body["lock_branch"] = {"enabled": True}
    body["allow_fork_syncing"] = {"enabled": True}
    return body


RECORDED = {
    "stricter": _stricter_protection,
    "satisfied": _satisfied_protection,
    "minimal": _protection,
    "review_allowances": _with_review_allowances,
}


@pytest.mark.unit
@pytest.mark.parametrize("name", sorted(RECORDED))
def test_round_trip_without_loss(name: str) -> None:
    get = RECORDED[name]()

    assert protection_put_to_get(protection_get_to_put(get)) == normalize_protection_get(get)


@pytest.mark.unit
@pytest.mark.parametrize("name", sorted(RECORDED))
def test_put_shape_has_every_mandatory_key(name: str) -> None:
    put = protection_get_to_put(RECORDED[name]())

    assert {"required_status_checks", "enforce_admins", "required_pull_request_reviews", "restrictions"} <= set(put)
    assert isinstance(put["enforce_admins"], bool)


@pytest.mark.unit
def test_shapes_translate_to_put() -> None:
    put = protection_get_to_put(_with_review_allowances())

    assert put["restrictions"] == {"users": ["octocat"], "teams": ["release-managers"], "apps": ["deploy-bot"]}
    assert put["required_status_checks"] == {
        "strict": True,
        "checks": [{"context": "ci/build", "app_id": 15368}, {"context": "ci/test", "app_id": 15368}],
    }
    reviews = put["required_pull_request_reviews"]
    assert reviews["dismissal_restrictions"] == {"users": ["hubot"], "teams": ["maintainers"], "apps": ["review-bot"]}
    assert reviews["bypass_pull_request_allowances"] == {"users": ["release-bot"], "teams": [], "apps": ["merge-queue"]}
    assert put["block_creations"] is True and put["lock_branch"] is True and put["allow_fork_syncing"] is True
    assert "required_signatures" not in put, "required signatures have their own endpoint; PUT does not carry them"


@pytest.mark.unit
def test_disabled_objects_translate_to_null() -> None:
    put = protection_get_to_put(_protection())

    assert put["required_status_checks"] is None
    assert put["restrictions"] is None


@pytest.mark.unit
def test_unknown_top_level_key_raises() -> None:
    get = _stricter_protection()
    get["future_setting"] = {"enabled": True}

    with pytest.raises(UnknownProtectionField) as exc:
        protection_get_to_put(get)

    assert exc.value.field == "future_setting"
    assert "cannot preserve unknown protection setting future_setting" in str(exc.value)


@pytest.mark.unit
@pytest.mark.parametrize(
    ("section", "key"),
    [
        ("required_pull_request_reviews", "require_review_from_ai"),
        ("required_status_checks", "merge_queue_only"),
        ("restrictions", "roles"),
    ],
)
def test_unknown_nested_key_raises(section: str, key: str) -> None:
    get = copy.deepcopy(_stricter_protection())
    get[section][key] = True

    with pytest.raises(UnknownProtectionField) as exc:
        protection_get_to_put(get)

    assert exc.value.field == f"{section}.{key}"
