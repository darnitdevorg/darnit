"""Integration tests for the four branch-protection controls.

Verifies:
- 404 from classic AND empty rulesets list -> FAIL (feature 019 semantic
  preserved under feature 032's two-surface check for the true-negative
  case).
- Healthy 200 from classic -> PASS via classic surface (no ruleset
  consultation).

The controls: OSPS-AC-03.01, OSPS-AC-03.02, OSPS-QA-03.01, OSPS-QA-07.01.

Tests patch `darnit_baseline.branch_protection.gh_api_with_status`
(function-level substitution) so the tests do not require `gh` on PATH or
network access.
"""

from __future__ import annotations

import pytest

from darnit.config.merger import load_framework_by_name
from darnit.core.plugin import ControlSpec
from darnit.sieve.handler_registry import reset_sieve_handler_registry
from darnit.sieve.models import CheckContext
from darnit.sieve.orchestrator import SieveOrchestrator
from darnit_baseline import branch_protection as bp

NAMED_CONTROLS = (
    "OSPS-AC-03.01",
    "OSPS-AC-03.02",
    "OSPS-QA-03.01",
    "OSPS-QA-07.01",
)

HEALTHY_PROTECTION_BODY = {
    "required_pull_request_reviews": {
        "required_approving_review_count": 1,
        "dismiss_stale_reviews": True,
    },
    "required_status_checks": {
        "strict": True,
        "contexts": ["ci/build"],
    },
    "enforce_admins": {"enabled": True},
    "allow_deletions": {"enabled": False},
    "allow_force_pushes": {"enabled": False},
    "restrictions": None,
    "url": "https://api.github.com/repos/testorg/testrepo/branches/main/protection",
}


@pytest.fixture(autouse=True)
def _register_baseline_handlers():
    reset_sieve_handler_registry()
    from darnit.core.discovery import get_implementation

    impl = get_implementation("openssf-baseline")
    assert impl is not None, "openssf-baseline implementation not discovered"
    impl.register_handlers()
    yield


def _load_control(control_id: str) -> ControlSpec:
    """Load a real ControlSpec from openssf-baseline.toml."""
    config = load_framework_by_name(control_id.split("-", 1)[0].lower() if False else "openssf-baseline")
    control = config.controls[control_id]
    tags = control.tags or {}
    level = control.level if control.level is not None else tags.get("level", 1)
    domain = control.domain if control.domain is not None else tags.get("domain", "UNKNOWN")
    return ControlSpec(
        control_id=control_id,
        name=control.name,
        description=control.description or "",
        level=level,
        domain=domain,
        metadata={"handler_invocations": control.passes, "when": control.when},
    )


def _make_context(control_id: str) -> CheckContext:
    return CheckContext(
        owner="testorg",
        repo="testrepo",
        local_path="/tmp/test-branch-protection",
        default_branch="main",
        control_id=control_id,
        project_context={"platform": "github", "ci_provider": "github"},
    )


def _install_gh_mock(monkeypatch, responses):
    """Substitute a canned response sequence into the handler's gh helper."""
    queue = list(responses)

    def _fake(endpoint, *, paginate=False):
        for i, (pat, body, status, msg) in enumerate(queue):
            if pat in endpoint or endpoint.endswith(pat):
                queue.pop(i)
                return body, status, msg
        raise AssertionError(
            f"unexpected gh_api_with_status call to {endpoint!r} "
            f"(paginate={paginate}); remaining={[p for p, *_ in queue]}"
        )

    monkeypatch.setattr(bp, "gh_api_with_status", _fake)


# ---------------------------------------------------------------------------
# Definitive negative: classic 404 + empty rulesets -> FAIL
# ---------------------------------------------------------------------------


class TestNoProtectionReportsFail:
    """The four named branch-protection controls MUST report FAIL when
    both surfaces respond definitively and neither confirms protection.
    Feature 019 established this invariant for the classic-only case;
    feature 032 preserves it under the two-surface check."""

    @pytest.mark.unit
    @pytest.mark.parametrize("control_id", NAMED_CONTROLS)
    def test_control_resolves_fail_on_branch_not_protected(self, control_id, monkeypatch):
        _install_gh_mock(monkeypatch, [
            ("/branches/main/protection", None, 404, "HTTP 404: Not Found"),
            ("/rulesets", [], 200, ""),
        ])

        spec = _load_control(control_id)
        context = _make_context(control_id)
        orchestrator = SieveOrchestrator(stop_on_llm=True)
        result = orchestrator.verify(spec, context)
        legacy = result.to_legacy_dict()

        assert legacy["status"] == "FAIL", (
            f"{control_id}: expected FAIL on 404 + no rulesets, got "
            f"{legacy['status']!r}. Message: {legacy.get('message')!r}"
        )


# ---------------------------------------------------------------------------
# Healthy positive: 200 with all fields -> PASS via classic surface
# ---------------------------------------------------------------------------


class TestHealthyResponsePasses:
    """Regression guard: a healthy classic branch-protection body still
    produces PASS across the four controls without consulting rulesets.
    Feature 032's cross-surface change must not affect this path."""

    @pytest.mark.unit
    @pytest.mark.parametrize("control_id", NAMED_CONTROLS)
    def test_control_resolves_pass_on_healthy_body(self, control_id, monkeypatch):
        # Only the classic call is expected -- rulesets are never consulted.
        _install_gh_mock(monkeypatch, [
            ("/branches/main/protection", HEALTHY_PROTECTION_BODY, 200, ""),
        ])

        spec = _load_control(control_id)
        context = _make_context(control_id)
        orchestrator = SieveOrchestrator(stop_on_llm=True)
        result = orchestrator.verify(spec, context)
        legacy = result.to_legacy_dict()

        assert legacy["status"] == "PASS", (
            f"{control_id}: expected PASS on healthy body, got "
            f"{legacy['status']!r}. Message: {legacy.get('message')!r}"
        )
