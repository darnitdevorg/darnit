"""Tests for the threat model remediation handler.

The handler never writes (feature 043, framework-design 4.2): it returns its
files as ``FileChange`` entries. ``_run`` checks that, then writes the planned
files as the remediation executor would, so the content tests read them back.
"""

import os
import subprocess
from pathlib import Path
from unittest.mock import patch

from darnit.remediation.plan import FileChange
from darnit.sieve.handler_registry import (
    HandlerContext,
    HandlerResult,
    HandlerResultStatus,
)
from darnit_baseline.threat_model.remediation import generate_threat_model_handler
from tests.conftest_helpers import snapshot


def _make_context(tmp_path: str) -> HandlerContext:
    return HandlerContext(
        local_path=tmp_path,
        owner="test-org",
        repo="test-repo",
        control_id="OSPS-SA-03.02",
    )


def _planned(result: HandlerResult) -> dict[str, FileChange]:
    return {c["path"]: FileChange.model_validate(c) for c in result.evidence.get("file_changes", [])}


def _run(config: dict, context: HandlerContext) -> HandlerResult:
    root = Path(context.local_path)
    before = snapshot(root)
    result = generate_threat_model_handler(config, context)
    assert snapshot(root) == before, "the handler must not write"
    for change in _planned(result).values():
        if change.changes:
            target = root / change.path
            target.parent.mkdir(parents=True, exist_ok=True)
            target.write_text(change.content or "", encoding="utf-8")
    return result


def _git(repo: Path, *args: str) -> None:
    subprocess.run(
        ["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
        cwd=repo,
        check=True,
        capture_output=True,
        env={**os.environ, "GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"},
    )


def _commit_all(repo: Path) -> None:
    if not (repo / ".git").exists():
        _git(repo, "init", "-q")
    _git(repo, "add", "-A")
    _git(repo, "commit", "-q", "--no-gpg-sign", "-m", "commit")


class TestDynamicGeneration:
    """Verify handler produces dynamic content."""

    def test_generates_dynamic_report(self, tmp_path):
        config = {"path": "THREAT_MODEL.md", "overwrite": False}
        context = _make_context(str(tmp_path))

        # Create a minimal repo structure so discovery has something to scan
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("# empty app\n")

        result = _run(config, context)
        assert result.status == HandlerResultStatus.PASS
        assert "THREAT_MODEL.md" in result.message

        report_path = tmp_path / "THREAT_MODEL.md"
        assert report_path.exists()
        content = report_path.read_text()
        assert "Threat Model Report" in content
        assert "Top Risks" in content

    def test_writes_report_even_with_no_assets(self, tmp_path):
        config = {"path": "THREAT_MODEL.md", "overwrite": False}
        context = _make_context(str(tmp_path))

        # Empty repo — no discoverable assets
        result = _run(config, context)
        assert result.status == HandlerResultStatus.PASS

        report_path = tmp_path / "THREAT_MODEL.md"
        assert report_path.exists()
        content = report_path.read_text()
        # Report should still be valid Markdown with STRIDE sections
        assert "Threat Model Report" in content


class TestOverwriteBehavior:
    """Verify overwrite flag is respected."""

    def test_skips_when_file_exists_and_overwrite_false(self, tmp_path):
        report_path = tmp_path / "THREAT_MODEL.md"
        report_path.write_text("existing content")

        config = {"path": "THREAT_MODEL.md", "overwrite": False}
        context = _make_context(str(tmp_path))

        result = _run(config, context)
        assert result.status == HandlerResultStatus.PASS
        assert "already exists" in result.message
        assert result.evidence.get("action") == "skipped"
        # Content should be unchanged
        assert report_path.read_text() == "existing content"

    def test_regenerates_when_overwrite_true(self, tmp_path):
        report_path = tmp_path / "THREAT_MODEL.md"
        report_path.write_text("old content")
        _commit_all(tmp_path)

        config = {"path": "THREAT_MODEL.md", "overwrite": True}
        context = _make_context(str(tmp_path))

        result = _run(config, context)
        assert result.status == HandlerResultStatus.PASS
        assert _planned(result)["THREAT_MODEL.md"].action == "modify"
        assert report_path.read_text() != "old content"
        assert "Threat Model Report" in report_path.read_text()

    def test_overwrite_leaves_a_file_git_does_not_track(self, tmp_path):
        (tmp_path / ".gitignore").write_text("THREAT_MODEL.md\n")
        _commit_all(tmp_path)
        report_path = tmp_path / "THREAT_MODEL.md"
        report_path.write_text("ignored, hand-written")

        result = _run({"path": "THREAT_MODEL.md", "overwrite": True}, _make_context(str(tmp_path)))

        assert result.status == HandlerResultStatus.PASS
        change = _planned(result)["THREAT_MODEL.md"]
        assert (change.action, change.reason) == ("none", "already_exists")
        assert report_path.read_text() == "ignored, hand-written"

    def test_overwrite_outside_git_leaves_existing_files(self, tmp_path):
        report_path = tmp_path / "THREAT_MODEL.md"
        report_path.write_text("old content")

        result = _run({"path": "THREAT_MODEL.md", "overwrite": True}, _make_context(str(tmp_path)))

        assert _planned(result)["THREAT_MODEL.md"].action == "none"
        assert report_path.read_text() == "old content"


class TestContainment:
    """Every planned path stays inside the repository (framework-design 4.2)."""

    def test_path_leaving_the_repository_is_refused(self, tmp_path):
        repo = tmp_path / "repo"
        repo.mkdir()

        result = _run({"path": "../escaped.md"}, _make_context(str(repo)))

        assert result.status == HandlerResultStatus.ERROR
        assert not (tmp_path / "escaped.md").exists()

    def test_symlinked_directory_leading_outside_is_refused(self, tmp_path):
        repo = tmp_path / "repo"
        outside = tmp_path / "outside"
        repo.mkdir()
        outside.mkdir()
        (repo / "docs").symlink_to(outside)

        result = _run({"path": "docs/threatmodel/SUMMARY.md"}, _make_context(str(repo)))

        assert result.status == HandlerResultStatus.ERROR
        assert "outside the repository" in result.message
        assert _planned(result) == {}
        assert list(outside.iterdir()) == []


class TestEdgeCases:
    """Verify edge case handling."""

    def test_error_when_no_path_specified(self, tmp_path):
        config = {}
        context = _make_context(str(tmp_path))

        result = _run(config, context)
        assert result.status == HandlerResultStatus.ERROR
        assert "No path" in result.message

    def test_creates_parent_directories(self, tmp_path):
        config = {"path": "docs/security/THREAT_MODEL.md", "overwrite": False}
        context = _make_context(str(tmp_path))

        result = _run(config, context)
        assert result.status == HandlerResultStatus.PASS
        assert (tmp_path / "docs" / "security" / "THREAT_MODEL.md").exists()


class TestFallbackBehavior:
    """Verify the template fallback when the new pipeline fails.

    The handler has two tiers:
    1. Primary: ``_run_ts_pipeline`` (tree-sitter discovery + new generator)
    2. Fallback: the static template passed as ``config["content"]``
    """

    def _force_pipeline_failure(self):
        """Patch the new pipeline to return result=None (pipeline failure)."""
        from darnit_baseline.threat_model.remediation import _TsRunOutput

        return patch(
            "darnit_baseline.threat_model.remediation._run_ts_pipeline",
            return_value=_TsRunOutput(
                result=None,
                ranked=[],
                groups=[],
                evidence={
                    "file_scan_stats": {},
                    "entry_point_count": 0,
                    "data_store_count": 0,
                    "candidate_finding_count": 0,
                    "opengrep_available": False,
                    "opengrep_degraded_reason": "test fixture",
                },
                failure_reason="forced for test",
            ),
        )

    def test_falls_back_to_template_on_pipeline_failure(self, tmp_path):
        template_content = "# Static Template\nGeneric threat model content"
        config = {
            "path": "THREAT_MODEL.md",
            "overwrite": False,
            "content": template_content,
        }
        context = _make_context(str(tmp_path))

        with self._force_pipeline_failure():
            result = _run(config, context)

        assert result.status == HandlerResultStatus.PASS
        assert "template" in result.message.lower()
        assert result.evidence.get("action") == "created_from_template"

        report_path = tmp_path / "THREAT_MODEL.md"
        assert report_path.read_text() == template_content

    def test_fallback_message_mentions_reason(self, tmp_path):
        config = {
            "path": "THREAT_MODEL.md",
            "content": "fallback content",
        }
        context = _make_context(str(tmp_path))

        with self._force_pipeline_failure():
            result = _run(config, context)

        assert "template" in result.message.lower()
        assert result.evidence.get("fallback_reason") is not None

    def test_error_when_pipeline_fails_and_no_template(self, tmp_path):
        config = {"path": "THREAT_MODEL.md"}
        context = _make_context(str(tmp_path))

        with self._force_pipeline_failure():
            result = _run(config, context)

        assert result.status == HandlerResultStatus.ERROR
        assert "no template content" in result.message.lower() or "pipeline failed" in result.message.lower()

    def test_new_pipeline_is_primary_source(self, tmp_path):
        """When the tree-sitter pipeline succeeds, the draft comes from
        the new generator."""
        config = {"path": "THREAT_MODEL.md", "overwrite": False}
        context = _make_context(str(tmp_path))
        result = _run(config, context)

        assert result.status == HandlerResultStatus.PASS
        assert result.evidence.get("generator") == "multi_file_renderers"
        assert result.evidence.get("action") == "created"
        draft = (tmp_path / "THREAT_MODEL.md").read_text()
        assert "# Threat Model Report" in draft
        assert "## Verification Prompts" in draft
        assert "<!-- darnit:verification-prompt-block -->" in draft


class TestLlmVerificationFlag:
    """Explicit negative assertions per the handler contract:
    ``evidence["llm_verification_required"]`` must be True ONLY on
    ``action="created"`` and absent on every other path.
    """

    def test_flag_set_on_created_action(self, tmp_path):
        config = {"path": "THREAT_MODEL.md", "overwrite": False}
        context = _make_context(str(tmp_path))
        result = _run(config, context)
        assert result.evidence.get("action") == "created"
        assert result.evidence.get("llm_verification_required") is True

    def test_flag_absent_on_skip_action(self, tmp_path):
        # Pre-create a file so the handler skips.
        existing = tmp_path / "THREAT_MODEL.md"
        existing.write_text("pre-existing content")

        config = {"path": "THREAT_MODEL.md", "overwrite": False}
        context = _make_context(str(tmp_path))
        result = _run(config, context)
        assert result.evidence.get("action") == "skipped"
        assert "llm_verification_required" not in result.evidence
        # Also confirm the original content was preserved
        assert existing.read_text() == "pre-existing content"

    def test_flag_absent_on_template_fallback_action(self, tmp_path):
        from darnit_baseline.threat_model.remediation import _TsRunOutput

        template_content = "# Static Template"
        config = {
            "path": "THREAT_MODEL.md",
            "overwrite": False,
            "content": template_content,
        }
        context = _make_context(str(tmp_path))

        with patch(
            "darnit_baseline.threat_model.remediation._run_ts_pipeline",
            return_value=_TsRunOutput(
                result=None,
                ranked=[],
                groups=[],
                evidence={
                    "file_scan_stats": {},
                    "entry_point_count": 0,
                    "data_store_count": 0,
                    "candidate_finding_count": 0,
                    "opengrep_available": False,
                    "opengrep_degraded_reason": "forced",
                },
                failure_reason="forced for test",
            ),
        ):
            result = _run(config, context)

        assert result.evidence.get("action") == "created_from_template"
        assert "llm_verification_required" not in result.evidence

    def test_flag_absent_on_error(self, tmp_path):
        config = {"path": ""}  # empty path → ERROR
        context = _make_context(str(tmp_path))
        result = _run(config, context)
        assert result.status == HandlerResultStatus.ERROR
        assert "llm_verification_required" not in result.evidence


class TestComplianceCycleSC004:
    """SC-004 regression: a full audit → remediate → audit cycle must
    transition the SA-03.02 control from FAIL to PASS without manual
    intervention.

    Implemented at the handler level (not the full orchestrator) by
    invoking ``file_exists_handler`` with the exact paths from the
    SA-03.02 TOML locator. This is the logical equivalent of running
    the sieve's first pass: the control PASSES iff a file exists at one
    of the accepted paths.
    """

    ACCEPTED_PATHS = [
        "THREAT_MODEL.md",
        "docs/threat-model.md",
        "docs/security/threat-model.md",
    ]

    def _check_sa0302(self, local_path: str) -> HandlerResultStatus:
        """Run the SA-03.02 file_exists pass and return its status."""
        from darnit.sieve.builtin_handlers import file_exists_handler

        context = _make_context(local_path)
        result = file_exists_handler({"files": self.ACCEPTED_PATHS}, context)
        return result.status

    def test_full_audit_remediate_audit_cycle(self, tmp_path):
        from darnit.sieve.handler_registry import HandlerResultStatus as Status

        # Step 1 — initial audit: control FAILs because no file exists.
        status_before = self._check_sa0302(str(tmp_path))
        assert status_before == Status.FAIL, f"Expected SA-03.02 to FAIL on empty repo, got {status_before}"

        # Step 2 — remediate: handler writes THREAT_MODEL.md.
        config = {"path": "THREAT_MODEL.md", "overwrite": False}
        context = _make_context(str(tmp_path))
        result = _run(config, context)
        assert result.status == Status.PASS
        assert (tmp_path / "THREAT_MODEL.md").exists()

        # Step 3 — re-audit: control PASSes because the file now exists.
        status_after = self._check_sa0302(str(tmp_path))
        assert status_after == Status.PASS, f"Expected SA-03.02 to PASS after remediation, got {status_after}"

    def test_remediation_file_lands_at_locator_path(self, tmp_path):
        """The file must be written to one of the SA-03.02 locator paths
        so the `file_exists` pass can find it on re-audit."""
        config = {"path": "THREAT_MODEL.md", "overwrite": False}
        context = _make_context(str(tmp_path))
        result = _run(config, context)
        assert result.status == HandlerResultStatus.PASS

        # The written file must be at one of the accepted locator paths.
        written = [p for p in self.ACCEPTED_PATHS if (tmp_path / p).exists()]
        assert len(written) >= 1, f"Expected file at one of {self.ACCEPTED_PATHS}, found none"

    def test_second_remediation_run_is_idempotent(self, tmp_path):
        """Running remediation twice without overwrite=True should leave
        the original file untouched and still report PASS (action=skipped
        the second time)."""
        from darnit.sieve.handler_registry import HandlerResultStatus as Status

        config = {"path": "THREAT_MODEL.md", "overwrite": False}
        context = _make_context(str(tmp_path))

        first = _run(config, context)
        assert first.status == Status.PASS
        assert first.evidence.get("action") == "created"
        draft_first = (tmp_path / "THREAT_MODEL.md").read_text()

        second = _run(config, context)
        assert second.status == Status.PASS
        assert second.evidence.get("action") == "skipped"
        draft_second = (tmp_path / "THREAT_MODEL.md").read_text()

        assert draft_first == draft_second, "Skip path must leave the file byte-identical"
