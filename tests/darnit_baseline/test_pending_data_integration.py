"""Pending questions use real audit results and the stored cache."""

import json
import subprocess

import pytest

from darnit.core.utils import RecordedGhApi, set_gh_api_responder
from darnit.tools.audit import _full_audit_cache_location, read_full_audit_cache
from darnit_baseline.tools import audit_openssf_baseline, get_pending_data

TARGET = "github.com/integration/project"
LICENSE_CONTROLS = ["OSPS-LE-02.01", "OSPS-LE-03.01"]


def pending_keys(repo):
    response = get_pending_data(
        local_path=str(repo),
        owner="integration",
        repo="project",
        control_ids=LICENSE_CONTROLS,
        limit=0,
    )
    data = json.loads(response.split("\n---\n", 1)[-1])
    assert data["status"] != "error", data
    return {question["key"] for question in data["questions"]}


@pytest.mark.parametrize("invalidate", [None, "expired", "changed_checkout"])
def test_license_question_after_full_audit(tmp_path, invalidate):
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "LICENSE").write_text(
        "MIT License\n\nPermission is hereby granted, free of charge, to any person obtaining a copy. The software is provided without warranty."
    )
    subprocess.run(["git", "init", "-q", str(repo)], check=True)
    subprocess.run(["git", "-C", str(repo), "add", "LICENSE"], check=True)
    subprocess.run(
        ["git", "-C", str(repo), "-c", "user.name=Integration Test",
         "-c", "user.email=test@example.invalid", "-c", "commit.gpgsign=false",
         "commit", "-qm", "Initial license"],
        check=True,
    )

    assert "license_type" in pending_keys(repo)
    responder = RecordedGhApi({
        "/repos/integration/project": {
            "body": {"owner": {"type": "Organization"}, "license": {"spdx_id": "MIT"}},
        },
    })
    previous = set_gh_api_responder(responder)
    try:
        audit_openssf_baseline(
            owner="integration", repo="project", local_path=str(repo), output_format="json",
        )
        cache = read_full_audit_cache(str(repo), "openssf-baseline", level=3, target=TARGET)
        assert cache is not None
        statuses = {result["id"]: result["status"] for result in cache["results"]}
        assert all(statuses[control] == "PASS" for control in LICENSE_CONTROLS), {control: statuses[control] for control in LICENSE_CONTROLS}
        assert "license_type" not in pending_keys(repo)

        if invalidate == "expired":
            stores, key = _full_audit_cache_location(str(repo), "openssf-baseline", None)
            try:
                cache["timestamp"] = "2000-01-01T00:00:00+00:00"
                stores.cache.write(key, cache)
            finally:
                stores.close_all()
        elif invalidate == "changed_checkout":
            (repo / "LICENSE").write_text("License decision still pending.\n")

        if invalidate:
            assert "license_type" in pending_keys(repo)
        if invalidate == "changed_checkout":
            audit_openssf_baseline(
                owner="integration", repo="project", local_path=str(repo), output_format="json",
            )
            assert "license_type" in pending_keys(repo)
    finally:
        set_gh_api_responder(previous)
