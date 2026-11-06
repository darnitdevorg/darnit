import pytest

from darnit.config.control_loader import load_controls_from_framework
from darnit.config.merger import load_framework_by_name
from darnit.core.utils import RecordedGhApi, set_gh_api_responder
from darnit.sieve.models import CheckContext
from darnit.sieve.orchestrator import SieveOrchestrator

ORG_ENDPOINT = "/orgs/octo"
WORKFLOW_ENDPOINT = "/repos/octo/hello/actions/permissions/workflow"


def run_check(tmp_path, control_id, endpoint, response):
    framework = load_framework_by_name("openssf-baseline")
    control = next(c for c in load_controls_from_framework(framework) if c.control_id == control_id)
    context = CheckContext(
        owner="octo", repo="hello", local_path=str(tmp_path), default_branch="main", control_id=control_id
    )
    previous = set_gh_api_responder(RecordedGhApi({endpoint: response}))
    try:
        return SieveOrchestrator().verify(control, context)
    finally:
        set_gh_api_responder(previous)


@pytest.mark.parametrize("permission", ["none", "read", "write", "admin"])
def test_collaborator_permissions_need_manual_review(tmp_path, permission):
    body = {"default_repository_permission": permission}
    result = run_check(tmp_path, "OSPS-AC-02.01", ORG_ENDPOINT, {"body": body})

    assert result.status == "WARN"
    assert result.evidence["response"]["body"] == body
    assert any("outside collaborators" in step for step in result.evidence["verification_steps"])


@pytest.mark.parametrize(("permission", "expected"), [("read", "PASS"), ("write", "FAIL")])
def test_workflow_default_decides_the_result(tmp_path, permission, expected):
    body = {"default_workflow_permissions": permission}
    result = run_check(tmp_path, "OSPS-AC-04.01", WORKFLOW_ENDPOINT, {"body": body})

    assert result.status == expected
    assert result.concluded_by == "gh_api"


@pytest.mark.parametrize(
    ("control_id", "endpoint", "response"),
    [
        ("OSPS-AC-02.01", ORG_ENDPOINT, {"body": {}}),
        ("OSPS-AC-02.01", ORG_ENDPOINT, {"status": 404}),
        ("OSPS-AC-04.01", WORKFLOW_ENDPOINT, {"body": {}}),
        ("OSPS-AC-04.01", WORKFLOW_ENDPOINT, {"body": {"default_workflow_permissions": "unknown"}}),
        ("OSPS-AC-04.01", WORKFLOW_ENDPOINT, {"status": 403}),
    ],
)
def test_unreadable_permissions_report_an_error(tmp_path, control_id, endpoint, response):
    result = run_check(tmp_path, control_id, endpoint, response)

    assert result.status == "ERROR"
