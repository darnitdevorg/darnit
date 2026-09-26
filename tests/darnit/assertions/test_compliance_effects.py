"""Compliance effects of assertion outcomes (feature 040, US3, T045, SC-003, SC-004)."""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from darnit.tools.audit import calculate_compliance

OWN = "github.com/example/repo"
CLAIMED = "OSPS-DO-01.01"
RELEASE_CLAIMED = "OSPS-BR-06.01"
_CI_VARS = ("GITHUB_ACTIONS", "GITLAB_CI", "CI", "JENKINS_URL", "TF_BUILD", "BUILDKITE", "CIRCLECI", "TRAVIS")


def _r(control_id: str, status: str, outcome: str | None = None, level: int = 1) -> dict:
    result = {"id": control_id, "status": status, "level": level}
    if outcome:
        result["assertion"] = {"outcome": outcome}
    return result


@pytest.mark.unit
class TestCalculateCompliance:
    def test_honored_claim_is_excluded_like_na(self) -> None:
        results = [_r("A", "PASS"), _r("B", "N/A", "honored")]

        assert calculate_compliance(results, 1) == {1: True}

    def test_pending_claim_counts_as_non_compliant_even_when_control_passes(self) -> None:
        results = [_r("A", "PASS"), _r("B", "PASS", "pending")]

        assert calculate_compliance(results, 1) == {1: False}

    def test_contradicted_claim_has_no_effect(self) -> None:
        assert calculate_compliance([_r("A", "PASS"), _r("B", "PASS", "contradicted")], 1) == {1: True}
        assert calculate_compliance([_r("A", "PASS"), _r("B", "FAIL", "contradicted")], 1) == {1: False}

    @pytest.mark.parametrize("status", ["WARN", "ERROR", "PENDING_LLM", "FAIL"])
    def test_unverified_statuses_are_non_compliant(self, status: str) -> None:
        assert calculate_compliance([_r("A", "PASS"), _r("B", status)], 1) == {1: False}


@pytest.fixture(autouse=True)
def _outside_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _CI_VARS:
        monkeypatch.delenv(var, raising=False)


def _repo(tmp_path: Path, *, claims: bool, changelog: bool = False) -> Path:
    path = tmp_path / ("claimed" if claims else "plain")
    path.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main", "-q"], cwd=path, check=True)
    subprocess.run(["git", "remote", "add", "origin", f"https://{OWN}.git"], cwd=path, check=True)
    if changelog:
        (path / "CHANGELOG.md").write_text("# 1.0.0\n", encoding="utf-8")
    if claims:
        (path / ".project").mkdir()
        (path / ".project" / "darnit.yaml").write_text(
            "controls:\n"
            f"  {CLAIMED}:\n    status: n/a\n    reason: docs live elsewhere\n"
            f"  {RELEASE_CLAIMED}:\n    status: n/a\n    reason: no releases yet\n",
            encoding="utf-8",
        )
    return path


def _operator(trusted: bool):
    from darnit.config.operator.loader import LoadedOperatorConfig
    from darnit.config.operator.schema import OperatorConfig

    config = OperatorConfig.model_validate({"schema_version": 1, "trust": {"repos": [OWN] if trusted else []}})
    return LoadedOperatorConfig(config=config, source="test", digest=None, permission_check="ok", strict=False)


def _audit(repo: Path, *, trusted: bool) -> list[dict]:
    from darnit.config import load_controls_from_framework, load_framework_config
    from darnit.tools.audit import _get_framework_config_path, run_sieve_audit

    framework = load_framework_config(_get_framework_config_path("openssf-baseline"))
    controls = [c for c in load_controls_from_framework(framework) if c.control_id in (CLAIMED, RELEASE_CLAIMED)]
    results, _ = run_sieve_audit(
        owner="example",
        repo="repo",
        local_path=str(repo),
        default_branch="main",
        level=3,
        controls=controls,
        framework_name="openssf-baseline",
        operator_config=_operator(trusted),
        target=OWN,
    )
    return results


def _counted(results: list[dict]) -> set[str]:
    return {r["id"] for r in results if r["status"] != "N/A"}


def _by_id(results: list[dict]) -> dict[str, dict]:
    return {r["id"]: r for r in results}


@pytest.mark.integration
class TestAuditedClaims:
    def test_sc003_untrusted_claims_do_not_reduce_the_denominator(self, tmp_path: Path) -> None:
        baseline = _audit(_repo(tmp_path, claims=False), trusted=False)
        claimed = _audit(_repo(tmp_path, claims=True), trusted=False)

        assert _counted(claimed) == _counted(baseline)
        assert {r["assertion"]["outcome"] for r in claimed} == {"pending"}
        assert calculate_compliance(claimed, 1)[1] is False

    def test_trusted_claim_without_declared_evidence_is_honored(self, tmp_path: Path) -> None:
        result = _by_id(_audit(_repo(tmp_path, claims=True), trusted=True))[CLAIMED]

        assert result["status"] == "N/A"
        assert result["authority"] == "asserted"
        assert result["assertion"]["outcome"] == "honored"
        assert result["assertion"]["asserted_by"] == "repository content"

    def test_sc004_contradicted_claim_is_never_honored(self, tmp_path: Path) -> None:
        result = _by_id(_audit(_repo(tmp_path, claims=True, changelog=True), trusted=True))[RELEASE_CLAIMED]

        assert result["assertion"]["outcome"] == "contradicted"
        assert result["assertion"]["contradiction"]["evidence_source"].startswith("context.has_releases")
        assert result["status"] != "N/A"

    def test_confirmation_honors_a_pending_claim(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        from darnit.trust import confirmations
        from darnit.trust.assertions import collect_assertions, evidence_digest

        monkeypatch.setattr(confirmations, "user_data_root", lambda: tmp_path / "data")
        repo = _repo(tmp_path, claims=True)
        claim = next(c for c in collect_assertions(repo, {CLAIMED}) if c.control_id == CLAIMED)
        confirmations.record_confirmation(
            OWN, CLAIMED, "not_applicable", evidence_digest(claim, None), _operator(False).config
        )

        result = _by_id(_audit(repo, trusted=False))[CLAIMED]

        assert result["status"] == "N/A"
        assert result["assertion"]["outcome"] == "honored"
        assert result["assertion"]["confirmation"]["confirmed_by"]
