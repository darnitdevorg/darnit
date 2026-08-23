"""Unit tests for the github_branch_protection sieve handler.

Every test mocks at `darnit_baseline.branch_protection.gh_api_with_status`
(module-level substitution) rather than at `subprocess.run`, so the tests
are robust across gh CLI version changes and can assert on the exact
sequence of API calls the handler emits (spec SC-004).
"""

from __future__ import annotations

from typing import Any

import pytest

from darnit.sieve.handler_registry import HandlerContext, HandlerResultStatus
from darnit_baseline import branch_protection as bp
from darnit_baseline.branch_protection import (
    ProtectionRequirement,
    _ref_name_matches,
    _ruleset_satisfies,
    github_branch_protection_handler,
)

# ---------------------------------------------------------------------------
# Response-sequencer helper
# ---------------------------------------------------------------------------


class _GhResponseSequencer:
    """Feeds pre-canned (body, status, message) tuples for gh_api_with_status.

    Records every call so tests can assert on call count and order.
    """

    def __init__(self, responses: list[tuple[str, Any, int, str]]):
        """responses: list of (endpoint_glob, body, status, message)."""
        self._queue = list(responses)
        self.calls: list[tuple[str, bool]] = []

    def __call__(
        self, endpoint: str, *, paginate: bool = False
    ) -> tuple[Any, int, str]:
        self.calls.append((endpoint, paginate))
        for i, (pat, body, status, msg) in enumerate(self._queue):
            if pat in endpoint or endpoint.endswith(pat):
                self._queue.pop(i)
                return body, status, msg
        raise AssertionError(
            f"unexpected gh_api_with_status call to {endpoint!r} "
            f"(paginate={paginate}); remaining queue={[p for p,*_ in self._queue]}"
        )


@pytest.fixture()
def ctx() -> HandlerContext:
    return HandlerContext(
        local_path="/tmp",
        owner="octo",
        repo="hello",
        default_branch="main",
        control_id="TEST-01",
    )


def _install(monkeypatch, seq: _GhResponseSequencer) -> None:
    monkeypatch.setattr(bp, "gh_api_with_status", seq)


# ---------------------------------------------------------------------------
# Pure helper tests (T005 ref-name matching, T006 ruleset-satisfies)
# ---------------------------------------------------------------------------


class TestRefNameMatching:
    def test_default_branch_matches_when_equal(self):
        assert _ref_name_matches("main", "main", ["~DEFAULT_BRANCH"], []) is True

    def test_default_branch_no_match_when_different(self):
        assert _ref_name_matches("feature/foo", "main", ["~DEFAULT_BRANCH"], []) is False

    def test_default_branch_conservative_when_none(self):
        assert _ref_name_matches("main", None, ["~DEFAULT_BRANCH"], []) is False

    def test_all_matches(self):
        assert _ref_name_matches("anything", "main", ["~ALL"], []) is True

    def test_exact_bare_name(self):
        assert _ref_name_matches("main", "main", ["main"], []) is True

    def test_git_ref_form(self):
        assert _ref_name_matches("main", "main", ["refs/heads/main"], []) is True

    def test_exclude_wins(self):
        assert _ref_name_matches("main", "main", ["~ALL"], ["refs/heads/main"]) is False

    def test_glob_treated_as_non_match(self):
        assert _ref_name_matches("release/1.0", "main", ["refs/heads/release/*"], []) is False
        assert _ref_name_matches("main", "main", ["mai?"], []) is False
        assert _ref_name_matches("main", "main", ["[m]ain"], []) is False

    def test_no_include_no_match(self):
        assert _ref_name_matches("main", "main", [], []) is False
        assert _ref_name_matches("main", "main", None, None) is False


class TestRulesetSatisfies:
    def test_pull_request_ok(self):
        ok, _ = _ruleset_satisfies({"type": "pull_request"}, ProtectionRequirement.REQUIRE_PULL_REQUEST, 1)
        assert ok

    def test_pull_request_wrong_type(self):
        ok, reason = _ruleset_satisfies({"type": "deletion"}, ProtectionRequirement.REQUIRE_PULL_REQUEST, 1)
        assert ok is False and "need 'pull_request'" in reason

    def test_deletion_ok(self):
        ok, _ = _ruleset_satisfies({"type": "deletion"}, ProtectionRequirement.PREVENT_DELETION, 1)
        assert ok

    def test_status_checks_ok(self):
        ok, _ = _ruleset_satisfies({"type": "required_status_checks"}, ProtectionRequirement.REQUIRE_STATUS_CHECKS, 1)
        assert ok

    def test_approvals_meets_minimum(self):
        ok, _ = _ruleset_satisfies(
            {"type": "pull_request", "parameters": {"required_approving_review_count": 2}},
            ProtectionRequirement.REQUIRE_APPROVALS,
            2,
        )
        assert ok

    def test_approvals_below_minimum(self):
        ok, reason = _ruleset_satisfies(
            {"type": "pull_request", "parameters": {"required_approving_review_count": 1}},
            ProtectionRequirement.REQUIRE_APPROVALS,
            2,
        )
        assert ok is False and "is 1, need >= 2" in reason

    def test_approvals_wrong_rule_type(self):
        ok, reason = _ruleset_satisfies(
            {"type": "deletion"}, ProtectionRequirement.REQUIRE_APPROVALS, 1
        )
        assert ok is False and "need 'pull_request'" in reason


# ---------------------------------------------------------------------------
# US1: PASS via ruleset (T017-T026)
# ---------------------------------------------------------------------------


def _ruleset_detail(rule_type: str, review_count: int = 1) -> dict[str, Any]:
    return {
        "id": 1,
        "name": "Protect main",
        "enforcement": "active",
        "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
        "rules": [
            {"type": rule_type, "parameters": {"required_approving_review_count": review_count}}
            if rule_type == "pull_request"
            else {"type": rule_type}
        ],
    }


class TestRulesetPass:
    def test_ruleset_pull_request_pass(self, monkeypatch, ctx):
        seq = _GhResponseSequencer([
            ("/branches/main/protection", None, 404, "HTTP 404: Not Found"),
            ("/rulesets", [{"id": 1, "name": "Protect main", "target": "branch", "enforcement": "active"}], 200, ""),
            ("/rulesets/1", _ruleset_detail("pull_request"), 200, ""),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request"}, ctx
        )
        assert result.status == HandlerResultStatus.PASS, result.message
        ev = result.evidence
        assert ev["source"] == "ruleset"
        assert ev["matched_ruleset"] == {"id": 1, "name": "Protect main"}
        assert ev["classic_status"] == 404
        assert ev["rulesets_status"] == 200

    def test_ruleset_deletion_pass(self, monkeypatch, ctx):
        seq = _GhResponseSequencer([
            ("/branches/main/protection", None, 404, "HTTP 404: Not Found"),
            ("/rulesets", [{"id": 1, "name": "R", "target": "branch", "enforcement": "active"}], 200, ""),
            ("/rulesets/1", _ruleset_detail("deletion"), 200, ""),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "prevent_deletion"}, ctx
        )
        assert result.status == HandlerResultStatus.PASS
        assert result.evidence["source"] == "ruleset"

    def test_ruleset_status_checks_pass(self, monkeypatch, ctx):
        seq = _GhResponseSequencer([
            ("/branches/main/protection", None, 404, "HTTP 404: Not Found"),
            ("/rulesets", [{"id": 1, "name": "R", "target": "branch", "enforcement": "active"}], 200, ""),
            ("/rulesets/1", _ruleset_detail("required_status_checks"), 200, ""),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_status_checks"}, ctx
        )
        assert result.status == HandlerResultStatus.PASS
        assert result.evidence["source"] == "ruleset"

    def test_ruleset_approvals_pass(self, monkeypatch, ctx):
        seq = _GhResponseSequencer([
            ("/branches/main/protection", None, 404, "HTTP 404: Not Found"),
            ("/rulesets", [{"id": 1, "name": "R", "target": "branch", "enforcement": "active"}], 200, ""),
            ("/rulesets/1", _ruleset_detail("pull_request", review_count=1), 200, ""),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_approvals"}, ctx
        )
        assert result.status == HandlerResultStatus.PASS
        assert result.evidence["source"] == "ruleset"

    def test_ruleset_approvals_minimum_enforced(self, monkeypatch, ctx):
        seq = _GhResponseSequencer([
            ("/branches/main/protection", None, 404, "HTTP 404: Not Found"),
            ("/rulesets", [{"id": 1, "name": "Skimpy", "target": "branch", "enforcement": "active"}], 200, ""),
            ("/rulesets/1", _ruleset_detail("pull_request", review_count=1), 200, ""),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_approvals", "required_approvals_minimum": 2}, ctx
        )
        assert result.status == HandlerResultStatus.FAIL
        assert result.evidence["source"] == "neither-surface-provided-protection"
        assert "is 1, need >= 2" in result.evidence["considered_rulesets"][0]["reason"]

    def test_matched_ruleset_evidence_no_considered_list(self, monkeypatch, ctx):
        seq = _GhResponseSequencer([
            ("/branches/main/protection", None, 404, "HTTP 404: Not Found"),
            ("/rulesets", [{"id": 1, "name": "R", "target": "branch", "enforcement": "active"}], 200, ""),
            ("/rulesets/1", _ruleset_detail("pull_request"), 200, ""),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request"}, ctx
        )
        assert result.evidence["source"] == "ruleset"
        assert "considered_rulesets" not in result.evidence

    def test_pass_via_classic_skips_rulesets(self, monkeypatch, ctx):
        seq = _GhResponseSequencer([
            ("/branches/main/protection", {"required_pull_request_reviews": {"required_approving_review_count": 1}}, 200, ""),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request"}, ctx
        )
        assert result.status == HandlerResultStatus.PASS
        assert result.evidence["source"] == "classic"
        assert "rulesets_status" not in result.evidence  # never consulted
        # And confirm we made exactly one call.
        assert len(seq.calls) == 1


class TestRefMatchingViaHandler:
    def test_pseudo_default_branch_covers_when_equal(self, monkeypatch, ctx):
        seq = _GhResponseSequencer([
            ("/branches/main/protection", None, 404, "HTTP 404: Not Found"),
            ("/rulesets", [{"id": 1, "name": "R", "target": "branch", "enforcement": "active"}], 200, ""),
            ("/rulesets/1", _ruleset_detail("pull_request"), 200, ""),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request"}, ctx
        )
        assert result.status == HandlerResultStatus.PASS

    def test_pseudo_default_branch_does_not_cover_non_default(self, monkeypatch, ctx):
        # Audited branch is `develop`, but ruleset targets ~DEFAULT_BRANCH (main).
        ctx = HandlerContext(
            local_path="/tmp", owner="octo", repo="hello",
            default_branch="main", control_id="TEST-01",
        )
        seq = _GhResponseSequencer([
            ("/branches/develop/protection", None, 404, "HTTP 404: Not Found"),
            ("/rulesets", [{"id": 1, "name": "R", "target": "branch", "enforcement": "active"}], 200, ""),
            ("/rulesets/1", _ruleset_detail("pull_request"), 200, ""),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request", "branch": "develop"}, ctx
        )
        assert result.status == HandlerResultStatus.FAIL
        assert "cover branch 'develop'" in result.evidence["considered_rulesets"][0]["reason"]

    def test_exclude_wins_over_include(self, monkeypatch, ctx):
        detail = _ruleset_detail("pull_request")
        detail["conditions"] = {"ref_name": {"include": ["~ALL"], "exclude": ["refs/heads/main"]}}
        seq = _GhResponseSequencer([
            ("/branches/main/protection", None, 404, "HTTP 404: Not Found"),
            ("/rulesets", [{"id": 1, "name": "R", "target": "branch", "enforcement": "active"}], 200, ""),
            ("/rulesets/1", detail, 200, ""),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request"}, ctx
        )
        assert result.status == HandlerResultStatus.FAIL

    def test_glob_ref_treated_as_non_match(self, monkeypatch, ctx):
        detail = _ruleset_detail("pull_request")
        detail["conditions"] = {"ref_name": {"include": ["refs/heads/release/*"], "exclude": []}}
        seq = _GhResponseSequencer([
            ("/branches/main/protection", None, 404, "HTTP 404: Not Found"),
            ("/rulesets", [{"id": 1, "name": "R", "target": "branch", "enforcement": "active"}], 200, ""),
            ("/rulesets/1", detail, 200, ""),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request"}, ctx
        )
        assert result.status == HandlerResultStatus.FAIL


# ---------------------------------------------------------------------------
# US2: FAIL when no protection + cross-surface layering + helper coverage
# ---------------------------------------------------------------------------


class TestFailPaths:
    def test_no_classic_no_rulesets_fails(self, monkeypatch, ctx):
        seq = _GhResponseSequencer([
            ("/branches/main/protection", None, 404, "HTTP 404: Not Found"),
            ("/rulesets", [], 200, ""),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request"}, ctx
        )
        assert result.status == HandlerResultStatus.FAIL
        assert result.evidence["source"] == "neither-surface-provided-protection"
        assert result.evidence["considered_rulesets"] == []

    def test_only_evaluate_mode_rulesets_fails(self, monkeypatch, ctx):
        seq = _GhResponseSequencer([
            ("/branches/main/protection", None, 404, "HTTP 404: Not Found"),
            ("/rulesets", [{"id": 1, "name": "Dry run", "target": "branch", "enforcement": "evaluate"}], 200, ""),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request"}, ctx
        )
        assert result.status == HandlerResultStatus.FAIL
        # Evaluate-mode rulesets are filtered at the summary level before
        # detail fetch, so they do not appear in considered_rulesets.
        assert result.evidence["considered_rulesets"] == []

    def test_rulesets_dont_cover_branch_fails(self, monkeypatch, ctx):
        detail = _ruleset_detail("pull_request")
        detail["conditions"] = {"ref_name": {"include": ["refs/heads/develop"], "exclude": []}}
        seq = _GhResponseSequencer([
            ("/branches/main/protection", None, 404, "HTTP 404: Not Found"),
            ("/rulesets", [{"id": 1, "name": "Wrong branch", "target": "branch", "enforcement": "active"}], 200, ""),
            ("/rulesets/1", detail, 200, ""),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request"}, ctx
        )
        assert result.status == HandlerResultStatus.FAIL
        considered = result.evidence["considered_rulesets"]
        assert len(considered) == 1
        assert considered[0]["id"] == 1

    def test_empty_rules_array_fails(self, monkeypatch, ctx):
        detail = _ruleset_detail("pull_request")
        detail["rules"] = []
        seq = _GhResponseSequencer([
            ("/branches/main/protection", None, 404, "HTTP 404: Not Found"),
            ("/rulesets", [{"id": 1, "name": "Empty", "target": "branch", "enforcement": "active"}], 200, ""),
            ("/rulesets/1", detail, 200, ""),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request"}, ctx
        )
        assert result.status == HandlerResultStatus.FAIL
        assert result.evidence["considered_rulesets"][0]["reason"] == "no rules declared"

    def test_considered_rulesets_populated_on_fail(self, monkeypatch, ctx):
        # Three active rulesets, all failing for distinct reasons.
        def _r(rid, name, rule_type, refs=None):
            d = _ruleset_detail(rule_type)
            d["id"] = rid
            d["name"] = name
            if refs is not None:
                d["conditions"] = {"ref_name": refs}
            return d

        seq = _GhResponseSequencer([
            ("/branches/main/protection", None, 404, "HTTP 404: Not Found"),
            ("/rulesets", [
                {"id": 1, "name": "Wrong rule", "target": "branch", "enforcement": "active"},
                {"id": 2, "name": "Wrong branch", "target": "branch", "enforcement": "active"},
                {"id": 3, "name": "No rules", "target": "branch", "enforcement": "active"},
            ], 200, ""),
            ("/rulesets/1", _r(1, "Wrong rule", "deletion"), 200, ""),
            ("/rulesets/2", _r(2, "Wrong branch", "pull_request",
                               refs={"include": ["refs/heads/other"], "exclude": []}), 200, ""),
            ("/rulesets/3", {"id": 3, "name": "No rules", "enforcement": "active",
                              "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
                              "rules": []}, 200, ""),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request"}, ctx
        )
        assert result.status == HandlerResultStatus.FAIL
        considered = result.evidence["considered_rulesets"]
        assert [c["id"] for c in considered] == [1, 2, 3]
        assert "need 'pull_request'" in considered[0]["reason"]
        assert "cover branch" in considered[1]["reason"]
        assert considered[2]["reason"] == "no rules declared"
        assert result.evidence["considered_rulesets_truncated"] == 0

    def test_considered_rulesets_truncation(self, monkeypatch, ctx):
        summaries = [
            {"id": i, "name": f"R{i}", "target": "branch", "enforcement": "active"}
            for i in range(1, 26)  # 25 rulesets
        ]
        details = [
            (f"/rulesets/{i}",
             {"id": i, "name": f"R{i}", "enforcement": "active",
              "conditions": {"ref_name": {"include": ["~DEFAULT_BRANCH"], "exclude": []}},
              "rules": [{"type": "deletion"}]},  # wrong type for require_pull_request
             200, "")
            for i in range(1, 26)
        ]
        seq = _GhResponseSequencer(
            [("/branches/main/protection", None, 404, "HTTP 404: Not Found"),
             ("/rulesets", summaries, 200, "")]
            + details
        )
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request"}, ctx
        )
        assert result.status == HandlerResultStatus.FAIL
        assert len(result.evidence["considered_rulesets"]) == 20
        assert result.evidence["considered_rulesets_truncated"] == 5

    def test_classic_partial_signal_falls_through_to_rulesets(self, monkeypatch, ctx):
        """Q1 clarification: classic 200 without the required signal STILL consults rulesets."""
        seq = _GhResponseSequencer([
            # Classic returns 200 with allow_deletions=false (satisfies PREVENT_DELETION)
            # but NO required_pull_request_reviews (does NOT satisfy REQUIRE_PULL_REQUEST).
            ("/branches/main/protection", {"allow_deletions": {"enabled": False}}, 200, ""),
            ("/rulesets", [{"id": 1, "name": "R", "target": "branch", "enforcement": "active"}], 200, ""),
            ("/rulesets/1", _ruleset_detail("pull_request"), 200, ""),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request"}, ctx
        )
        assert result.status == HandlerResultStatus.PASS
        assert result.evidence["source"] == "ruleset"
        assert result.evidence["classic_status"] == 200

    def test_both_surfaces_confirm_uses_classic_first(self, monkeypatch, ctx):
        """Classic 200 with signal short-circuits; rulesets endpoint is never called."""
        seq = _GhResponseSequencer([
            ("/branches/main/protection", {"required_pull_request_reviews": {"required_approving_review_count": 1}}, 200, ""),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request"}, ctx
        )
        assert result.status == HandlerResultStatus.PASS
        assert result.evidence["source"] == "classic"
        # Exactly one API call was made.
        assert len(seq.calls) == 1
        assert "/rulesets" not in seq.calls[0][0]


# ---------------------------------------------------------------------------
# US3: WARN (INCONCLUSIVE) on ambiguous responses
# ---------------------------------------------------------------------------


class TestAmbiguousResponses:
    def test_classic_403_returns_inconclusive(self, monkeypatch, ctx):
        seq = _GhResponseSequencer([
            ("/branches/main/protection", None, 403, "HTTP 403: Forbidden"),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request"}, ctx
        )
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.evidence["source"] == "insufficient-access"
        assert result.evidence["classic_status"] == 403
        assert "rulesets_status" not in result.evidence  # never consulted

    def test_classic_401_returns_inconclusive(self, monkeypatch, ctx):
        seq = _GhResponseSequencer([
            ("/branches/main/protection", None, 401, "HTTP 401: Unauthorized"),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request"}, ctx
        )
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.evidence["source"] == "insufficient-access"

    def test_classic_5xx_returns_inconclusive(self, monkeypatch, ctx):
        seq = _GhResponseSequencer([
            ("/branches/main/protection", None, 502, "HTTP 502: Bad Gateway"),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request"}, ctx
        )
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.evidence["classic_status"] == 502

    def test_rulesets_403_returns_inconclusive(self, monkeypatch, ctx):
        seq = _GhResponseSequencer([
            ("/branches/main/protection", None, 404, "HTTP 404: Not Found"),
            ("/rulesets", None, 403, "HTTP 403: Forbidden"),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request"}, ctx
        )
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.evidence["source"] == "insufficient-access"
        assert result.evidence["classic_status"] == 404
        assert result.evidence["rulesets_status"] == 403

    def test_rulesets_429_returns_inconclusive(self, monkeypatch, ctx):
        seq = _GhResponseSequencer([
            ("/branches/main/protection", None, 404, "HTTP 404: Not Found"),
            ("/rulesets", None, 429, "HTTP 429: Too Many Requests"),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request"}, ctx
        )
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.evidence["rulesets_status"] == 429

    def test_partial_fetch_returns_inconclusive(self, monkeypatch, ctx):
        # List succeeds; detail 404s (ruleset deleted between calls).
        seq = _GhResponseSequencer([
            ("/branches/main/protection", None, 404, "HTTP 404: Not Found"),
            ("/rulesets", [{"id": 42, "name": "R", "target": "branch", "enforcement": "active"}], 200, ""),
            ("/rulesets/42", None, 404, "HTTP 404: Not Found"),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request"}, ctx
        )
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.evidence["source"] == "partial-fetch"
        assert "ruleset 42" in result.message

    def test_gh_cli_missing_returns_inconclusive(self, monkeypatch, ctx):
        seq = _GhResponseSequencer([
            ("/branches/main/protection", None, 0,
             "GitHub CLI (gh) not found. Install it from https://cli.github.com/"),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request"}, ctx
        )
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.evidence["source"] == "insufficient-access"
        assert result.evidence["classic_status"] == 0
        assert "gh) not found" in result.message

    def test_classic_status_zero_returns_inconclusive(self, monkeypatch, ctx):
        seq = _GhResponseSequencer([
            ("/branches/main/protection", None, 0, "connection reset by peer"),
        ])
        _install(monkeypatch, seq)
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request"}, ctx
        )
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.evidence["source"] == "insufficient-access"


# ---------------------------------------------------------------------------
# Config-validation errors -> HandlerResult.ERROR
# ---------------------------------------------------------------------------


class TestConfigValidation:
    def test_missing_requirement(self, ctx):
        result = github_branch_protection_handler({}, ctx)
        assert result.status == HandlerResultStatus.ERROR
        assert "requirement" in result.message

    def test_unknown_requirement(self, ctx):
        result = github_branch_protection_handler({"requirement": "bogus"}, ctx)
        assert result.status == HandlerResultStatus.ERROR
        assert "bogus" in result.message

    def test_minimum_out_of_range_low(self, ctx):
        result = github_branch_protection_handler(
            {"requirement": "require_approvals", "required_approvals_minimum": 0}, ctx
        )
        assert result.status == HandlerResultStatus.ERROR

    def test_minimum_out_of_range_high(self, ctx):
        result = github_branch_protection_handler(
            {"requirement": "require_approvals", "required_approvals_minimum": 11}, ctx
        )
        assert result.status == HandlerResultStatus.ERROR

    def test_missing_owner_repo(self):
        ctx_empty = HandlerContext(
            local_path="/tmp", owner="", repo="", default_branch="main", control_id="X",
        )
        result = github_branch_protection_handler(
            {"requirement": "require_pull_request"}, ctx_empty
        )
        assert result.status == HandlerResultStatus.ERROR
        assert "owner/repo" in result.message
