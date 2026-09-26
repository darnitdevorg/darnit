"""Not-applicable claims read from ``.project/darnit.yaml`` (feature 040, US2, T037)."""

from __future__ import annotations

import logging
from pathlib import Path

import pytest

from darnit.trust.assertions import ProjectAssertion, collect_assertions

FRAMEWORK_IDS = {"OSPS-BR-02.01", "OSPS-DO-01.01", "OSPS-VM-02.01", "OSPS-QA-01.01"}


def _darnit_yaml(repo: Path, text: str) -> None:
    (repo / ".project").mkdir(exist_ok=True)
    (repo / ".project" / "darnit.yaml").write_text(text, encoding="utf-8")


@pytest.mark.unit
class TestProjectClaims:
    def test_claim_with_reason_and_asserter(self, tmp_path: Path) -> None:
        _darnit_yaml(
            tmp_path,
            """controls:
  OSPS-BR-02.01:
    status: n/a
    reason: "Pre-1.0 project with no releases yet"
    asserted_by: "@maintainer"
""",
        )

        assert collect_assertions(tmp_path, FRAMEWORK_IDS) == [
            ProjectAssertion(
                control_id="OSPS-BR-02.01",
                claim="not_applicable",
                reason="Pre-1.0 project with no releases yet",
                asserted_by="@maintainer",
                location=".project/darnit.yaml:controls.OSPS-BR-02.01",
                origin="explicit_claim",
            )
        ]

    def test_asserter_defaults_to_repository_content(self, tmp_path: Path) -> None:
        _darnit_yaml(tmp_path, "controls:\n  OSPS-DO-01.01:\n    status: n/a\n    reason: docs elsewhere\n")

        (claim,) = collect_assertions(tmp_path, FRAMEWORK_IDS)
        assert claim.asserted_by == "repository content"

    @pytest.mark.parametrize("reason_line", ["", "    reason: \n", "    reason: '   '\n"])
    def test_missing_reason_is_recorded_as_none(self, tmp_path: Path, reason_line: str) -> None:
        _darnit_yaml(tmp_path, f"controls:\n  OSPS-DO-01.01:\n    status: n/a\n{reason_line}")

        (claim,) = collect_assertions(tmp_path, FRAMEWORK_IDS)
        assert claim.reason is None

    def test_disabled_is_a_not_applicable_claim(self, tmp_path: Path) -> None:
        _darnit_yaml(tmp_path, "controls:\n  OSPS-DO-01.01:\n    status: disabled\n    reason: not for us\n")

        (claim,) = collect_assertions(tmp_path, FRAMEWORK_IDS)
        assert claim.claim == "not_applicable"

    def test_enabled_is_not_a_claim(self, tmp_path: Path) -> None:
        _darnit_yaml(tmp_path, "controls:\n  OSPS-DO-01.01:\n    status: enabled\n")

        assert collect_assertions(tmp_path, FRAMEWORK_IDS) == []

    def test_unknown_control_is_reported_and_ignored(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        _darnit_yaml(
            tmp_path,
            "controls:\n  OSPS-XX-99.99:\n    status: n/a\n    reason: x\n"
            "  OSPS-DO-01.01:\n    status: n/a\n    reason: y\n",
        )

        with caplog.at_level(logging.WARNING):
            claims = collect_assertions(tmp_path, FRAMEWORK_IDS)

        assert [c.control_id for c in claims] == ["OSPS-DO-01.01"]
        assert "OSPS-XX-99.99" in caplog.text

    def test_malformed_entries_are_reported_and_ignored(self, tmp_path: Path, caplog: pytest.LogCaptureFixture) -> None:
        _darnit_yaml(
            tmp_path,
            "controls:\n  OSPS-DO-01.01:\n    status: maybe\n  OSPS-VM-02.01: n/a\n"
            "  OSPS-QA-01.01:\n    status: n/a\n    reason: ok\n",
        )

        with caplog.at_level(logging.WARNING):
            claims = collect_assertions(tmp_path, FRAMEWORK_IDS)

        assert [c.control_id for c in claims] == ["OSPS-QA-01.01"]
        assert "OSPS-DO-01.01" in caplog.text

    @pytest.mark.parametrize("text", ["controls: [", "- a list\n", "controls: 3\n", ""])
    def test_unreadable_file_yields_no_claims(self, tmp_path: Path, text: str) -> None:
        _darnit_yaml(tmp_path, text)

        assert collect_assertions(tmp_path, FRAMEWORK_IDS) == []

    def test_no_files_no_claims(self, tmp_path: Path) -> None:
        assert collect_assertions(tmp_path, FRAMEWORK_IDS) == []


@pytest.mark.unit
class TestBaselineTomlClaims:
    def test_status_and_reason_flow_into_the_same_path(self, tmp_path: Path) -> None:
        (tmp_path / ".baseline.toml").write_text(
            '[controls."OSPS-VM-02.01"]\nstatus = "n/a"\nreason = "library"\npasses = [{ handler = "manual" }]\n',
            encoding="utf-8",
        )

        assert collect_assertions(tmp_path, FRAMEWORK_IDS) == [
            ProjectAssertion(
                control_id="OSPS-VM-02.01",
                claim="not_applicable",
                reason="library",
                asserted_by="repository content",
                location=".baseline.toml:controls.OSPS-VM-02.01",
                origin="explicit_claim",
            )
        ]

    def test_project_claim_takes_precedence(self, tmp_path: Path) -> None:
        (tmp_path / ".baseline.toml").write_text(
            '[controls."OSPS-DO-01.01"]\nstatus = "n/a"\nreason = "old"\n', encoding="utf-8"
        )
        _darnit_yaml(tmp_path, "controls:\n  OSPS-DO-01.01:\n    status: n/a\n    reason: new\n")

        (claim,) = collect_assertions(tmp_path, FRAMEWORK_IDS)
        assert claim.reason == "new"
        assert claim.location == ".project/darnit.yaml:controls.OSPS-DO-01.01"


@pytest.mark.unit
def test_report_block_for_pending_claim() -> None:
    claim = ProjectAssertion(
        control_id="OSPS-DO-01.01",
        claim="not_applicable",
        reason=None,
        asserted_by="repository content",
        location=".project/darnit.yaml:controls.OSPS-DO-01.01",
        origin="explicit_claim",
    )

    assert claim.report("pending") == {
        "outcome": "pending",
        "origin": "explicit_claim",
        "reason": None,
        "asserted_by": "repository content",
        "location": ".project/darnit.yaml:controls.OSPS-DO-01.01",
        "confirmation": None,
        "contradiction": None,
    }
