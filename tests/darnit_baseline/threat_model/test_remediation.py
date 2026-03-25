"""Tests for the threat model remediation handler."""

from unittest.mock import patch

from darnit.sieve.handler_registry import (
    HandlerContext,
    HandlerResultStatus,
)
from darnit_baseline.threat_model.remediation import generate_threat_model_handler


def _make_context(tmp_path: str) -> HandlerContext:
    return HandlerContext(
        local_path=tmp_path,
        owner="test-org",
        repo="test-repo",
        control_id="OSPS-SA-03.02",
    )


class TestDynamicGeneration:
    """Verify handler produces dynamic content."""

    def test_generates_dynamic_report(self, tmp_path):
        config = {"path": "THREAT_MODEL.md", "overwrite": False}
        context = _make_context(str(tmp_path))

        # Create a minimal repo structure so discovery has something to scan
        (tmp_path / "src").mkdir()
        (tmp_path / "src" / "app.py").write_text("# empty app\n")

        result = generate_threat_model_handler(config, context)
        assert result.status == HandlerResultStatus.PASS
        assert "THREAT_MODEL.md" in result.message

        report_path = tmp_path / "THREAT_MODEL.md"
        assert report_path.exists()
        content = report_path.read_text()
        assert "Threat Model Report" in content
        assert "STRIDE" in content

    def test_writes_report_even_with_no_assets(self, tmp_path):
        config = {"path": "THREAT_MODEL.md", "overwrite": False}
        context = _make_context(str(tmp_path))

        # Empty repo — no discoverable assets
        result = generate_threat_model_handler(config, context)
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

        result = generate_threat_model_handler(config, context)
        assert result.status == HandlerResultStatus.PASS
        assert "already exists" in result.message
        assert result.evidence.get("action") == "skipped"
        # Content should be unchanged
        assert report_path.read_text() == "existing content"

    def test_regenerates_when_overwrite_true(self, tmp_path):
        report_path = tmp_path / "THREAT_MODEL.md"
        report_path.write_text("old content")

        config = {"path": "THREAT_MODEL.md", "overwrite": True}
        context = _make_context(str(tmp_path))

        result = generate_threat_model_handler(config, context)
        assert result.status == HandlerResultStatus.PASS
        assert report_path.read_text() != "old content"
        assert "Threat Model Report" in report_path.read_text()


class TestEdgeCases:
    """Verify edge case handling."""

    def test_error_when_no_path_specified(self, tmp_path):
        config = {}
        context = _make_context(str(tmp_path))

        result = generate_threat_model_handler(config, context)
        assert result.status == HandlerResultStatus.ERROR
        assert "No path" in result.message

    def test_creates_parent_directories(self, tmp_path):
        config = {"path": "docs/security/THREAT_MODEL.md", "overwrite": False}
        context = _make_context(str(tmp_path))

        result = generate_threat_model_handler(config, context)
        assert result.status == HandlerResultStatus.PASS
        assert (tmp_path / "docs" / "security" / "THREAT_MODEL.md").exists()


class TestFallbackBehavior:
    """Verify fallback to static template on analysis failure."""

    def test_falls_back_to_template_on_analysis_error(self, tmp_path):
        template_content = "# Static Template\nGeneric threat model content"
        config = {
            "path": "THREAT_MODEL.md",
            "overwrite": False,
            "content": template_content,
        }
        context = _make_context(str(tmp_path))

        with patch(
            "darnit_baseline.threat_model.remediation._run_dynamic_analysis",
            side_effect=RuntimeError("Analysis failed"),
        ):
            result = generate_threat_model_handler(config, context)

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

        with patch(
            "darnit_baseline.threat_model.remediation._run_dynamic_analysis",
            side_effect=ValueError("Bad input"),
        ):
            result = generate_threat_model_handler(config, context)

        assert "template" in result.message.lower()
        assert result.evidence.get("fallback_reason") is not None

    def test_error_when_analysis_fails_and_no_template(self, tmp_path):
        config = {"path": "THREAT_MODEL.md"}
        context = _make_context(str(tmp_path))

        with patch(
            "darnit_baseline.threat_model.remediation._run_dynamic_analysis",
            side_effect=RuntimeError("Analysis failed"),
        ):
            result = generate_threat_model_handler(config, context)

        assert result.status == HandlerResultStatus.ERROR
        assert "no template content" in result.message.lower()
