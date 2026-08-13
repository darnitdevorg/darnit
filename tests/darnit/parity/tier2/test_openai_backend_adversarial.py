"""OpenAI backend adversarial tests (feature 029 T016 + T017).

Covers:
  - SC-003: skill reclassification (WARN -> PASS) caught, any authority
  - SC-011: turn_cap_exhausted outcome + exit code 5
  - FR-008 + FR-010 + FR-011 + FR-14 (MC2 parser reuse) + B-17 (local_path guard)
"""

from __future__ import annotations

import asyncio
import json
import os
import subprocess
import sys
from pathlib import Path
from types import SimpleNamespace
from unittest.mock import AsyncMock, patch

import pytest

from tests.darnit.parity.tier1.comparator import AuditResult, Control
from tests.darnit.parity.tier2.backends.base import (
    SetupError,
)
from tests.darnit.parity.tier2.backends.openai_backend import (
    OpenAIBackend,
    _dispatch_tool_call,
)
from tests.darnit.parity.tier2.diff import diff
from tests.darnit.parity.tier2.skill_markdown_parser import SkillReport


def _run(coro):
    return asyncio.new_event_loop().run_until_complete(coro)


def _mcp_result(*controls: Control) -> AuditResult:
    return AuditResult(controls=tuple(controls), source="mcp_tool")


def _canned_response(*, tool_calls=None, content=None):
    """Build a minimal ChatCompletion-shaped SimpleNamespace stub."""
    msg = SimpleNamespace(
        tool_calls=tool_calls,
        content=content,
    )
    choice = SimpleNamespace(message=msg)
    return SimpleNamespace(choices=[choice])


class TestSC003SkillReclassificationCaught:
    def test_warn_reclassified_as_pass_is_caught(self) -> None:
        """SC-003 shape at the diff layer: parsed skill claim (PASS) vs
        tool (WARN) -> per_control_disagree."""
        skill_md = "Passed: 1\nFailed: 0\n\n**OSPS-DO-01.01**: PASS"
        skill_report = SkillReport.parse(skill_md)
        assert skill_report.parseable
        mcp = _mcp_result(
            Control(id="OSPS-DO-01.01", status="WARN", authority="suggestive"),
        )
        report = diff(mcp, skill_report, "sc003")
        assert report.outcome == "per_control_disagree"

    def test_dispositive_authority_still_caught(self) -> None:
        """FR-008/FR-11: authority level does not license reinterpretation."""
        skill_md = "Passed: 1\nFailed: 0\n\n**OSPS-LE-03.01**: PASS"
        skill_report = SkillReport.parse(skill_md)
        mcp = _mcp_result(
            Control(id="OSPS-LE-03.01", status="FAIL", authority="dispositive"),
        )
        report = diff(mcp, skill_report, "auth")
        assert report.outcome == "per_control_disagree"


class TestSC011TurnCapExhausted:
    """SC-011 / FR-010: model that keeps calling tools without summarizing
    produces `turn_cap_exhausted=True`; runner returns exit 5."""

    def test_turn_cap_exhausted_returns_flag_set(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        # Mock AsyncOpenAI so every response has tool_calls and no content.
        fake_call = SimpleNamespace(
            id="call_1",
            function=SimpleNamespace(
                name="audit_openssf_baseline",
                arguments=json.dumps({"local_path": "/tmp"}),
            ),
        )
        fake_response = _canned_response(tool_calls=[fake_call], content=None)

        mock_client = SimpleNamespace(
            chat=SimpleNamespace(
                completions=SimpleNamespace(
                    create=AsyncMock(return_value=fake_response),
                ),
            ),
        )

        monkeypatch.setenv("OPENAI_API_KEY", "fake-key-for-mock")

        with (
            patch(
                "tests.darnit.parity.tier2.backends.openai_backend.AsyncOpenAI",
                create=True,
                return_value=mock_client,
            ),
            patch(
                "tests.darnit.parity.tier2.backends.openai_backend._dispatch_tool_call",
                return_value='{"results": []}',
            ),
        ):
            # Also stub the openai import (delayed inside invoke()).
            # PR #371 review fix: skip cleanly when the parity-tier2 extra
            # is not installed (unit runs on a lean env), instead of
            # blowing up with ImportError.
            openai = pytest.importorskip("openai")

            openai.AsyncOpenAI = lambda: mock_client  # type: ignore[assignment]

            backend = OpenAIBackend()
            result = _run(
                backend.invoke(
                    fixture_dir=Path("/tmp/fake_fixture"),
                    model="gpt-4o-2024-08-06",
                    max_turns=3,
                ),
            )

        assert result.turn_cap_exhausted is True
        assert result.final_message == ""
        assert result.turn_count == 3


class TestLocalPathForcedToFixtureDir:
    """B-17: a rogue model cannot make the audit tool wander outside the
    fixture directory. `_dispatch_tool_call` overrides `local_path`."""

    def test_malicious_local_path_ignored(
        self,
        monkeypatch: pytest.MonkeyPatch,
        tmp_path: Path,
    ) -> None:
        """The model tries to audit /etc/passwd; the backend forces the
        fixture_dir."""
        call = SimpleNamespace(
            id="call_evil",
            function=SimpleNamespace(
                name="audit_openssf_baseline",
                arguments=json.dumps({"local_path": "/etc/passwd"}),
            ),
        )
        captured_local_path: dict[str, str] = {}

        def _mock_audit(**kwargs):
            captured_local_path["value"] = kwargs["local_path"]
            return '{"results": []}'

        # Patch the audit function at the import site inside _dispatch_tool_call.
        with patch(
            "darnit_baseline.tools.audit_openssf_baseline",
            side_effect=_mock_audit,
        ):
            _dispatch_tool_call(call, tmp_path / "safe_fixture")

        # The malicious /etc/passwd path was overridden to the fixture dir.
        assert captured_local_path["value"] == str(tmp_path / "safe_fixture")
        assert captured_local_path["value"] != "/etc/passwd"


class TestFR010MissingApiKey:
    def test_check_env_raises_setup_error(
        self,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """FR-008 / SC-004: OpenAIBackend.check_env() with no OPENAI_API_KEY
        raises SetupError naming the missing variable."""
        monkeypatch.delenv("OPENAI_API_KEY", raising=False)
        with pytest.raises(SetupError, match="OPENAI_API_KEY"):
            OpenAIBackend.check_env()

    def test_run_py_exits_3_without_openai_key(
        self,
        tmp_path: Path,
        monkeypatch: pytest.MonkeyPatch,
    ) -> None:
        """SC-004: run.py subprocess exit code 3 when OPENAI_API_KEY absent."""
        env = {k: v for k, v in os.environ.items() if k != "OPENAI_API_KEY"}
        env["PYTHONPATH"] = str(Path.cwd())
        # Keep ANTHROPIC_API_KEY in env just to prove it's ignored -- the
        # OpenAI backend only checks OPENAI_API_KEY.
        env["ANTHROPIC_API_KEY"] = "anthropic-key-should-not-help-openai"

        rc = subprocess.run(
            [
                sys.executable,
                "-m",
                "tests.darnit.parity.tier2.run",
                "--backend",
                "openai",
                "--fixture-glob",
                "all_pass_repo",
                "--artifact-dir",
                str(tmp_path / "artifacts"),
            ],
            env=env,
            capture_output=True,
            text=True,
            timeout=30,
        )
        assert rc.returncode == 3, f"expected exit 3, got {rc.returncode}\nstderr: {rc.stderr}"
        assert "OPENAI_API_KEY" in rc.stderr


class TestFR14MC2SharedParserHandlesOpenAIMarkdown:
    """MC2 fix: an OpenAI-shaped final message is parseable by feature 028's
    shared parser. Guards against silent parser fork."""

    def test_openai_style_markdown_is_parseable(self) -> None:
        openai_style = (
            "# Audit Report\n\n"
            "Passed: 3\nFailed: 1\nWarned: 0\n\n"
            "## Details\n\n"
            "- **OSPS-DO-01.01**: PASS\n"
            "- **OSPS-LE-03.01**: PASS\n"
            "- **OSPS-GV-01.01**: FAIL\n"
            "- **OSPS-BR-06.01**: PASS\n"
        )
        report = SkillReport.parse(openai_style)
        assert report.parseable
        assert report.counts is not None
        assert report.counts.get("pass") == 3
        assert report.counts.get("fail") == 1
        assert report.controls is not None
        ids = {c.id for c in report.controls}
        assert "OSPS-GV-01.01" in ids
        assert "OSPS-DO-01.01" in ids
