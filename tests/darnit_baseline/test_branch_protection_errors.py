"""Branch-protection controls report broken measurements as ERROR (feature 041 US2, FR-007).

Recorded platform responses are served through the ``gh_api_with_status``
responder hook, the same path the adversarial corpus uses, and the four
Baseline branch-protection controls run end-to-end from the shipped TOML.
"""

from __future__ import annotations

import pytest

from darnit.config.control_loader import load_controls_from_framework
from darnit.config.merger import load_framework_by_name
from darnit.core.utils import RecordedGhApi, set_gh_api_responder
from darnit.sieve.handler_registry import reset_sieve_handler_registry
from darnit.sieve.models import CheckContext
from darnit.sieve.orchestrator import SieveOrchestrator
from darnit.tools.audit import calculate_compliance

PROTECTION = "/repos/octo/hello/branches/main/protection"
RULESETS = "/repos/octo/hello/rulesets"
CONTROLS = ["OSPS-AC-03.01", "OSPS-AC-03.02", "OSPS-QA-03.01", "OSPS-QA-07.01"]


@pytest.fixture(autouse=True)
def _baseline_handlers():
    reset_sieve_handler_registry()
    from darnit.core.discovery import get_implementation

    impl = get_implementation("openssf-baseline")
    assert impl is not None
    impl.register_handlers()
    yield


@pytest.fixture()
def specs():
    fw = load_framework_by_name("openssf-baseline")
    return {s.control_id: s for s in load_controls_from_framework(fw)}


@pytest.fixture()
def platform():
    previous = set_gh_api_responder(None)

    def install(responses=None, **kwargs) -> RecordedGhApi:
        responder = RecordedGhApi(responses, **kwargs)
        set_gh_api_responder(responder)
        return responder

    yield install
    set_gh_api_responder(previous)


def _verify(spec):
    ctx = CheckContext(owner="octo", repo="hello", local_path="/tmp", default_branch="main", control_id=spec.control_id)
    return SieveOrchestrator(stop_on_llm=False).verify(spec, ctx)


@pytest.mark.parametrize("control_id", CONTROLS)
@pytest.mark.parametrize(
    ("responses", "expected_class"),
    [
        ({PROTECTION: {"status": 401, "error": "HTTP 401: Bad credentials"}}, "auth"),
        ({PROTECTION: {"status": 403, "error": "HTTP 403: Resource not accessible by integration"}}, "auth"),
        ({PROTECTION: {"status": 429, "error": "HTTP 429: Too Many Requests"}}, "rate_limit"),
        ({PROTECTION: {"status": 403, "error": "HTTP 403: API rate limit exceeded for installation"}}, "rate_limit"),
        (
            {
                PROTECTION: {"status": 404, "error": "HTTP 404: Branch not protected"},
                RULESETS: {"status": 403, "error": "HTTP 403: Forbidden"},
            },
            "auth",
        ),
        (
            {
                PROTECTION: {"status": 404, "error": "HTTP 404: Branch not protected"},
                RULESETS: {"status": 429, "error": "HTTP 429: Too Many Requests"},
            },
            "rate_limit",
        ),
    ],
)
def test_platform_error_is_error_with_class(platform, specs, control_id, responses, expected_class) -> None:
    platform(responses)
    result = _verify(specs[control_id])
    assert result.status == "ERROR"
    assert result.error["class"] == expected_class
    assert result.error["cause"]
    assert result.concluded_by == "github_branch_protection"


@pytest.mark.parametrize("control_id", CONTROLS)
def test_gh_missing_is_error_missing_tool(platform, specs, control_id) -> None:
    platform(gh_missing=True)
    result = _verify(specs[control_id])
    assert result.status == "ERROR"
    assert result.error["class"] == "missing_tool"


@pytest.mark.parametrize("control_id", CONTROLS)
def test_no_protection_is_still_fail(platform, specs, control_id) -> None:
    platform(
        {
            PROTECTION: {"status": 404, "error": "HTTP 404: Branch not protected"},
            RULESETS: {"status": 200, "body": []},
        }
    )
    result = _verify(specs[control_id])
    assert result.status == "FAIL"
    assert result.error is None


def test_errored_level_is_not_compliant(platform, specs) -> None:
    platform({PROTECTION: {"status": 403, "error": "HTTP 403: Forbidden"}})
    results = [_verify(specs[cid]).to_legacy_dict() for cid in CONTROLS]
    by_level = {r["level"] for r in results}
    compliance = calculate_compliance(results, level=max(by_level))
    assert not any(compliance[lvl] for lvl in by_level)
