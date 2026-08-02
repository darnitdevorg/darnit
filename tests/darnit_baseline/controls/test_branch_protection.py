"""Integration tests for the four branch-protection controls (feature 020, issue #343).

Verifies that when the GitHub API returns a definitive 404 "Branch not
protected" response, each of the following controls resolves to FAIL
(not WARN, not INCONCLUSIVE):

- OSPS-AC-03.01 (PreventDirectCommits)
- OSPS-AC-03.02 (PreventBranchDeletion)
- OSPS-QA-03.01 (RequiredStatusChecks)
- OSPS-QA-07.01 (RequiredApprovals)

Also verifies the happy path (200 with healthy branch-protection body ->
PASS) does not regress.

Tests patch `subprocess.run` in the exec handler's module so the test
does not require `gh` on PATH or network access.
"""

from __future__ import annotations

import json
from unittest.mock import patch

import pytest

from darnit.config.merger import load_framework_by_name
from darnit.core.plugin import ControlSpec
from darnit.sieve.handler_registry import HandlerContext  # noqa: F401 (documentation)
from darnit.sieve.models import CheckContext
from darnit.sieve.orchestrator import SieveOrchestrator

NAMED_CONTROLS = (
    "OSPS-AC-03.01",
    "OSPS-AC-03.02",
    "OSPS-QA-03.01",
    "OSPS-QA-07.01",
)

BRANCH_NOT_PROTECTED_BODY = json.dumps({
    "message": "Branch not protected",
    "documentation_url": "https://docs.github.com/rest/branches/branch-protection#get-branch-protection",
    "status": "404",
})

HEALTHY_PROTECTION_BODY = json.dumps({
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
})


def _load_control(control_id: str) -> ControlSpec:
    """Load a real ControlSpec from openssf-baseline.toml.

    Uses the framework's own loader so we exercise the exact metadata
    (passes, handler_invocations, etc.) that ships in the TOML.
    """
    config = load_framework_by_name("openssf-baseline")
    control = config.controls[control_id]

    # Build a ControlSpec that carries the handler_invocations metadata
    # the orchestrator expects. This mirrors how darnit-baseline's
    # implementation.get_all_controls() constructs its ControlSpecs.
    tags = control.tags or {}
    level = control.level if control.level is not None else tags.get("level", 1)
    domain = control.domain if control.domain is not None else tags.get("domain", "UNKNOWN")

    return ControlSpec(
        control_id=control_id,
        name=control.name,
        description=control.description or "",
        level=level,
        domain=domain,
        metadata={
            "handler_invocations": control.passes,
            "when": control.when,
        },
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


class _FakeSubprocessResult:
    """Minimal stand-in for subprocess.CompletedProcess."""

    def __init__(self, returncode: int, stdout: str = "", stderr: str = ""):
        self.returncode = returncode
        self.stdout = stdout
        self.stderr = stderr


@pytest.fixture()
def patched_gh_404():
    """Patch subprocess.run so `gh api` returns HTTP 404 'Branch not protected'."""
    def _fake_run(*args, **kwargs):
        return _FakeSubprocessResult(
            returncode=1,
            stdout=BRANCH_NOT_PROTECTED_BODY,
            stderr="",
        )

    with patch("darnit.sieve.builtin_handlers.subprocess.run", side_effect=_fake_run):
        yield


@pytest.fixture()
def patched_gh_200_healthy():
    """Patch subprocess.run so `gh api` returns HTTP 200 with a healthy protection body.

    For OSPS-QA-07.01 the command adds `--jq
    '.required_pull_request_reviews.required_approving_review_count >= 1'`,
    so its stdout should be the string `true`. Other three controls receive
    the full JSON.
    """
    def _fake_run(*args, **kwargs):
        cmd = args[0] if args else kwargs.get("args", [])
        if any("--jq" in str(a) for a in cmd):
            return _FakeSubprocessResult(returncode=0, stdout="true\n", stderr="")
        return _FakeSubprocessResult(
            returncode=0,
            stdout=HEALTHY_PROTECTION_BODY,
            stderr="",
        )

    with patch("darnit.sieve.builtin_handlers.subprocess.run", side_effect=_fake_run):
        yield


# ---------------------------------------------------------------------------
# FR-007 acceptance: definitive 404 -> FAIL
# ---------------------------------------------------------------------------


class TestDefinitive404ReportsFail:
    """The four named branch-protection controls MUST report FAIL on 404
    'Branch not protected' after feature 020 lands."""

    @pytest.mark.unit
    @pytest.mark.parametrize("control_id", NAMED_CONTROLS)
    def test_control_resolves_fail_on_branch_not_protected(self, control_id, patched_gh_404):
        spec = _load_control(control_id)
        context = _make_context(control_id)
        orchestrator = SieveOrchestrator(stop_on_llm=True)

        result = orchestrator.verify(spec, context)
        legacy = result.to_legacy_dict()

        assert legacy["status"] == "FAIL", (
            f"{control_id}: expected FAIL on 404 'Branch not protected', "
            f"got {legacy['status']!r}. Message: {legacy.get('message')!r}"
        )


# ---------------------------------------------------------------------------
# FR-009 regression guard: healthy 200 -> PASS
# ---------------------------------------------------------------------------


class TestHealthyResponsePasses:
    """Regression guard: when branch protection IS enabled with the expected
    fields, the four named controls MUST still resolve to PASS. Feature 020's
    orchestrator change must not affect this path."""

    @pytest.mark.unit
    @pytest.mark.parametrize("control_id", NAMED_CONTROLS)
    def test_control_resolves_pass_on_healthy_body(self, control_id, patched_gh_200_healthy):
        spec = _load_control(control_id)
        context = _make_context(control_id)
        orchestrator = SieveOrchestrator(stop_on_llm=True)

        result = orchestrator.verify(spec, context)
        legacy = result.to_legacy_dict()

        assert legacy["status"] == "PASS", (
            f"{control_id}: expected PASS on healthy branch-protection body, "
            f"got {legacy['status']!r}. Message: {legacy.get('message')!r}"
        )
