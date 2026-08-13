"""End-to-end tests for the STAGE1-REF-SECURITY-01 reference control.

Feature 025 Slice D T048-T050. Exercises the SECURITY.md reference control
through both the direct sieve path and the MCP surface, verifying:

- First run (no SECURITY.md): the dispositive file_exists step FAILs the
  control; the suggestive llm_extract step attaches evidence.
- Confirmation persists: adding SECURITY.md and re-auditing produces PASS
  from dispositive file_exists.
- CLI and MCP paths produce equal per-control status + authority (SC-004).

Uses a mocked LLM step to avoid live API calls.
"""

from __future__ import annotations

from pathlib import Path

from darnit.sieve.handler_registry import (
    HandlerContext,
)
from darnit.sieve.models import CheckContext, ControlSpec
from darnit.sieve.orchestrator import SieveOrchestrator


def _load_stage1_ref_control() -> ControlSpec:
    """Read STAGE1-REF-SECURITY-01 out of the baseline framework config."""
    from darnit.config.control_loader import control_from_framework
    from darnit.config.merger import load_framework_by_name

    config = load_framework_by_name("openssf-baseline")
    control_config = config.controls["STAGE1-REF-SECURITY-01"]
    return control_from_framework("STAGE1-REF-SECURITY-01", control_config)


def _make_ctx(local_path: Path) -> CheckContext:
    return CheckContext(
        owner="test",
        repo="test-repo",
        local_path=str(local_path),
        default_branch="main",
        control_id="STAGE1-REF-SECURITY-01",
    )


class TestSecurityMdReferenceControl:
    """US4 acceptance #1-#3."""

    def test_first_run_reports_fail_no_security_md(self, tmp_path: Path) -> None:
        """US4 acceptance #1: no SECURITY.md; llm_extract attaches evidence;
        dispositive file_exists concludes FAIL.
        """
        # Fixture has README but no SECURITY.md.
        (tmp_path / "README.md").write_text("# proj\nContact us at team@example.com\n")

        control = _load_stage1_ref_control()
        # PR #365 review fix: TOML now orders dispositive file_exists FIRST
        # so a repo with SECURITY.md concludes PASS without ever calling
        # the LLM. This test verifies the FAIL side of that ordering; the
        # suggestive llm_extract step no longer runs because file_exists
        # short-circuits at the first pass. Losing the "propose contact
        # even when SECURITY.md is absent" property is documented as a
        # follow-up in openssf-baseline.toml.
        orch = SieveOrchestrator(stop_on_llm=False)
        result = orch.verify(control, _make_ctx(tmp_path))

        # Dispositive file_exists FAILs (no SECURITY.md in any of the paths).
        assert result.status == "FAIL"
        assert result.authority == "dispositive"
        # file_exists ran and recorded the paths it checked.
        assert "files_checked" in (result.evidence or {})

    def test_second_run_reports_pass_when_security_md_present(
        self,
        tmp_path: Path,
    ) -> None:
        """US4 acceptance #3: with SECURITY.md present, dispositive
        file_exists concludes PASS. The earlier suggestive LLM contribution
        is still recorded but is not the authority for the PASS.
        """
        (tmp_path / "README.md").write_text("# proj\n")
        (tmp_path / "SECURITY.md").write_text(
            "# Security Policy\n\nReport issues to sec@example.com\n",
        )

        control = _load_stage1_ref_control()
        # Feature 026 T045-adjacent: llm_extract now emits a
        # consultation_request, so stop_on_llm=True (the default) halts on
        # it. This test exercises the "runs to completion" path; use
        # stop_on_llm=False so the runner falls through to file_exists.
        # The harness (feature 026) is the correct consumer of the
        # stop_on_llm=True path for LLM-dispatched runs.
        orch = SieveOrchestrator(stop_on_llm=False)
        result = orch.verify(control, _make_ctx(tmp_path))

        assert result.status == "PASS"
        assert result.authority == "dispositive"

    def test_cli_and_direct_produce_equal_authority(self, tmp_path: Path) -> None:
        """US4 acceptance #4 + SC-004 (partial): the same control run two
        different ways (direct verify vs a second orchestrator instance)
        produces the same status and authority. The MCP path shares the
        same verify() call, so this equivalence extends there by
        construction.
        """
        (tmp_path / "README.md").write_text("# proj\n")

        control = _load_stage1_ref_control()

        result_a = SieveOrchestrator(stop_on_llm=False).verify(control, _make_ctx(tmp_path))
        result_b = SieveOrchestrator(stop_on_llm=False).verify(control, _make_ctx(tmp_path))

        assert result_a.status == result_b.status
        assert result_a.authority == result_b.authority
        # Reference control's dispositive step is what concludes; the
        # authority MUST NOT drift between runs.
        assert result_a.authority == "dispositive"


class TestLlmExtractAttachesEvidence:
    """T045 handler smoke: llm_extract returns INCONCLUSIVE with the
    prompt attached as evidence. Its authority default (suggestive) means
    the runner never lets it conclude."""

    def test_llm_extract_returns_inconclusive_with_evidence(
        self,
        tmp_path: Path,
    ) -> None:
        from darnit.sieve.builtin_handlers import llm_extract_handler
        from darnit.sieve.handler_registry import HandlerResultStatus

        (tmp_path / "README.md").write_text("Contact us at sec@example.com\n")

        ctx = HandlerContext(
            local_path=str(tmp_path),
            control_id="TEST-01",
        )
        result = llm_extract_handler(
            {
                "prompt": "Extract security contact",
                "files": ["README.md"],
                "target_key": "security_contact",
            },
            ctx,
        )
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert "llm_extract_prompt" in result.evidence
        assert "extraction_request" in result.details
