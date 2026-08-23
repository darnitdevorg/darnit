"""Integration tests for the github_branch_protection handler through the sieve orchestrator.

Loads the actual openssf-baseline TOML, patches
`darnit_baseline.branch_protection.gh_api_with_status`, and runs the four
affected controls end-to-end. Locks (a) the four TOML edits at the
orchestrator level and (b) SC-004's exact API-call budget.
"""

from __future__ import annotations

from typing import Any

import pytest

from darnit.config.control_loader import load_controls_from_framework
from darnit.config.merger import load_framework_by_name
from darnit.sieve.handler_registry import reset_sieve_handler_registry
from darnit.sieve.models import CheckContext
from darnit.sieve.orchestrator import SieveOrchestrator
from darnit_baseline import branch_protection as bp


@pytest.fixture(autouse=True)
def _register_baseline_handlers():
    """Ensure the baseline plugin's handlers are registered for each test."""
    reset_sieve_handler_registry()
    from darnit.core.discovery import get_implementation

    impl = get_implementation("openssf-baseline")
    assert impl is not None, "openssf-baseline implementation not discovered"
    impl.register_handlers()
    yield


@pytest.fixture()
def control_specs():
    fw = load_framework_by_name("openssf-baseline")
    specs = {s.control_id: s for s in load_controls_from_framework(fw)}
    return specs


def _make_context(control_id: str) -> CheckContext:
    return CheckContext(
        owner="octo",
        repo="hello",
        local_path="/tmp",
        default_branch="main",
        control_id=control_id,
    )


class _Sequencer:
    def __init__(self, responses):
        self._queue = list(responses)
        self.calls: list[tuple[str, bool]] = []

    def __call__(self, endpoint, *, paginate=False):
        self.calls.append((endpoint, paginate))
        for i, (pat, body, status, msg) in enumerate(self._queue):
            if pat in endpoint or endpoint.endswith(pat):
                self._queue.pop(i)
                return body, status, msg
        raise AssertionError(f"unexpected call to {endpoint} paginate={paginate}; remaining={[p for p,*_ in self._queue]}")


def _ruleset_detail(rule_type: str, review_count: int = 1) -> dict[str, Any]:
    return {
        "id": 1, "name": "Protect main", "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [
            {"type": rule_type, "parameters": {"required_approving_review_count": review_count}}
            if rule_type == "pull_request"
            else {"type": rule_type}
        ],
    }


# ---------------------------------------------------------------------------
# US1 -- four TOML controls resolve PASS via ruleset (T051-T054)
# ---------------------------------------------------------------------------


@pytest.mark.parametrize("control_id, rule_type", [
    ("OSPS-AC-03.01", "pull_request"),
    ("OSPS-AC-03.02", "deletion"),
    ("OSPS-QA-03.01", "required_status_checks"),
    ("OSPS-QA-07.01", "pull_request"),
])
def test_pass_via_ruleset(monkeypatch, control_specs, control_id, rule_type):
    seq = _Sequencer([
        ("/branches/main/protection", None, 404, "HTTP 404: Not Found"),
        ("/rulesets", [{"id": 1, "name": "Protect main", "target": "branch", "enforcement": "active"}], 200, ""),
        ("/rulesets/1", _ruleset_detail(rule_type), 200, ""),
    ])
    monkeypatch.setattr(bp, "gh_api_with_status", seq)

    spec = control_specs[control_id]
    ctx = _make_context(control_id)
    orch = SieveOrchestrator(stop_on_llm=False)
    result = orch.verify(spec, ctx)

    assert result.status == "PASS", f"{control_id}: {result.status} -- {result.message}"
    assert result.evidence["source"] == "ruleset"


# ---------------------------------------------------------------------------
# US2 -- FAIL when neither surface protects (T055) + SC-004 exact budget (T057a)
# ---------------------------------------------------------------------------


def test_fail_when_no_protection(monkeypatch, control_specs):
    seq = _Sequencer([
        ("/branches/main/protection", None, 404, "HTTP 404: Not Found"),
        ("/rulesets", [], 200, ""),
    ])
    monkeypatch.setattr(bp, "gh_api_with_status", seq)

    spec = control_specs["OSPS-AC-03.01"]
    ctx = _make_context("OSPS-AC-03.01")
    orch = SieveOrchestrator(stop_on_llm=False)
    result = orch.verify(spec, ctx)

    assert result.status == "FAIL"
    assert result.evidence["source"] == "neither-surface-provided-protection"


def test_api_call_budget_matches_sc_004(monkeypatch, control_specs):
    """Locks SC-004: 1 classic call + 1 list call + N detail calls + 0 to /repos/{owner}/{repo}."""
    summaries = [
        {"id": i, "name": f"R{i}", "target": "branch", "enforcement": "active"}
        for i in range(1, 4)
    ]
    details = [
        (f"/rulesets/{i}", {
            "id": i, "name": f"R{i}", "enforcement": "active",
            "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
            "rules": [{"type": "deletion"}],  # wrong type for require_pull_request
        }, 200, "")
        for i in range(1, 4)
    ]
    seq = _Sequencer([
        ("/branches/main/protection", None, 404, "HTTP 404: Not Found"),
        ("/rulesets", summaries, 200, ""),
        *details,
    ])
    monkeypatch.setattr(bp, "gh_api_with_status", seq)

    spec = control_specs["OSPS-AC-03.01"]
    orch = SieveOrchestrator(stop_on_llm=False)
    result = orch.verify(spec, _make_context("OSPS-AC-03.01"))

    assert result.status == "FAIL"
    # Exact call profile:
    # 1 classic + 1 rulesets-list + 3 rulesets-detail = 5 calls
    assert len(seq.calls) == 5
    endpoints = [c[0] for c in seq.calls]
    assert endpoints[0].endswith("/branches/main/protection")
    assert endpoints[1].endswith("/rulesets")
    assert seq.calls[1][1] is True  # paginate=True on the list call
    for i, expected in enumerate((1, 2, 3), start=2):
        assert endpoints[i].endswith(f"/rulesets/{expected}"), endpoints[i]
        assert seq.calls[i][1] is False  # detail calls are not paginated
    # Critically: no call to /repos/{owner}/{repo} for default-branch resolution.
    assert not any(
        e.endswith("/repos/octo/hello") or e == "/repos/octo/hello"
        for e in endpoints
    )


# ---------------------------------------------------------------------------
# US3 -- WARN falls through to manual pass (T056)
# ---------------------------------------------------------------------------


def test_warn_when_403_falls_through_to_manual(monkeypatch, control_specs):
    seq = _Sequencer([
        ("/branches/main/protection", None, 403, "HTTP 403: Forbidden"),
    ])
    monkeypatch.setattr(bp, "gh_api_with_status", seq)

    spec = control_specs["OSPS-AC-03.01"]
    orch = SieveOrchestrator(stop_on_llm=False)
    result = orch.verify(spec, _make_context("OSPS-AC-03.01"))

    # Handler is INCONCLUSIVE -> orchestrator falls through to the trailing
    # manual pass, which resolves the control as WARN with verification steps.
    assert result.status == "WARN"
