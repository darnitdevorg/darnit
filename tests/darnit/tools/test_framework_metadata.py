"""Tests for `framework_metadata` audit-output header helper (issue #350)."""

from __future__ import annotations

import re


class TestFrameworkMetadata:
    def test_installed_framework_returns_full_metadata(self):
        from darnit.tools.audit import framework_metadata

        meta = framework_metadata("openssf-baseline")

        assert meta["name"] == "openssf-baseline"
        assert meta["display_name"] == "OpenSSF Baseline"
        assert meta["version"]  # non-empty
        assert meta["spec_version"].startswith("OSPS v")
        # ISO-8601 UTC with Z suffix
        assert re.match(
            r"^\d{4}-\d{2}-\d{2}T\d{2}:\d{2}:\d{2}(\.\d+)?Z$",
            meta["generated_at"],
        )

    def test_none_framework_falls_back_gracefully(self):
        from darnit.tools.audit import framework_metadata

        meta = framework_metadata(None)
        assert meta["name"] == "unknown"
        assert meta["display_name"] == ""
        assert meta["version"] == ""
        assert meta["spec_version"] == ""
        assert meta["generated_at"]

    def test_unknown_framework_uses_name_but_empty_fields(self, monkeypatch):
        """A framework that isn't registered still yields a metadata block
        so the audit output header is never missing its shape."""
        from darnit.tools import audit

        # Force get_implementation to return None (framework not installed).
        monkeypatch.setattr(
            "darnit.core.discovery.get_implementation", lambda _: None
        )

        meta = audit.framework_metadata("does-not-exist")
        assert meta["name"] == "does-not-exist"
        assert meta["display_name"] == ""
        assert meta["version"] == ""
        assert meta["spec_version"] == ""

    def test_discovery_exception_falls_back_never_raises(self, monkeypatch):
        """A broken get_implementation() implementation must not crash
        audit output generation."""
        from darnit.tools import audit

        def _boom(_):
            raise RuntimeError("registry corrupted")

        monkeypatch.setattr("darnit.core.discovery.get_implementation", _boom)

        meta = audit.framework_metadata("openssf-baseline")
        assert meta["name"] == "openssf-baseline"
        assert meta["display_name"] == ""
        assert meta["generated_at"]


class TestMarkdownHeaderIncludesMetadata:
    def test_header_lists_framework_spec_and_timestamp(self):
        from darnit.tools.audit import format_results_markdown

        out = format_results_markdown(
            owner="acme",
            repo="widget",
            results=[],
            summary={
                "PASS": 0, "FAIL": 0, "WARN": 0, "PENDING_LLM": 0,
                "N/A": 0, "ERROR": 0, "total": 0,
            },
            compliance={1: True, 2: True, 3: True},
            level=1,
            local_path="/tmp/notarealpath",
            report_title="OpenSSF Baseline Audit Report",
            framework_name="openssf-baseline",
        )

        assert "**Framework:** OpenSSF Baseline" in out
        assert "**Spec Version:** OSPS v" in out
        assert "**Generated At:**" in out
        assert "**Repository:** acme/widget" in out


class TestJsonOutputIncludesMetadata:
    def test_json_output_has_top_level_metadata_block(self, tmp_path, monkeypatch):
        """Every JSON audit output MUST include a top-level `metadata` block."""
        import json
        from unittest.mock import patch

        # Bypass the actual audit run -- we only care about the JSON shape.
        with patch(
            "darnit.tools.audit.run_sieve_audit",
            return_value=([], {
                "PASS": 0, "FAIL": 0, "WARN": 0, "PENDING_LLM": 0,
                "N/A": 0, "ERROR": 0, "total": 0,
            }),
        ), patch(
            "darnit.core.utils.detect_owner_repo",
            return_value=("acme", "widget"),
        ):
            from darnit_baseline.tools import audit_openssf_baseline

            raw = audit_openssf_baseline(
                local_path=str(tmp_path),
                output_format="json",
                auto_init_config=False,
                attest=False,
                prefer_upstream=False,
            )
        payload = json.loads(raw)
        assert "metadata" in payload
        meta = payload["metadata"]
        assert meta["name"] == "openssf-baseline"
        assert meta["display_name"] == "OpenSSF Baseline"
        assert meta["spec_version"].startswith("OSPS v")
        assert meta["generated_at"]
