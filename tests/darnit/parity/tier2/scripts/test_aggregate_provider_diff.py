"""Smoke tests for aggregate_provider_diff (feature 029 T022).

The script itself is a local maintainer tool, not a CI-invoked check --
but the parsing + diff logic are worth testing to prevent silent bit-rot.
"""

from __future__ import annotations

from pathlib import Path

from tests.darnit.parity.tier2.scripts.aggregate_provider_diff import (
    _diff_one_fixture,
    _discover_fixtures,
    _find_message,
    main,
)


def _write_msg(root: Path, fixture: str, filename: str, content: str) -> None:
    d = root / fixture
    d.mkdir(parents=True, exist_ok=True)
    (d / filename).write_text(content)


class TestDiffOneFixture:
    def test_two_providers_agree(self) -> None:
        claude = "Passed: 1\n\n- **OSPS-DO-01.01**: PASS"
        openai = "Passed: 1\n\n- **OSPS-DO-01.01**: PASS"
        section = _diff_one_fixture("fx", claude, openai)
        assert "OSPS-DO-01.01 | PASS | PASS" in section
        assert "0 disagreements" in section

    def test_two_providers_disagree_flagged(self) -> None:
        claude = "Passed: 0\nFailed: 1\n\n- **OSPS-DO-01.01**: FAIL"
        openai = "Passed: 1\nFailed: 0\n\n- **OSPS-DO-01.01**: PASS"
        section = _diff_one_fixture("fx", claude, openai)
        assert "| YES |" in section
        assert "1 disagreements" in section

    def test_missing_openai_reported(self) -> None:
        claude = "Passed: 1\n\n- **OSPS-DO-01.01**: PASS"
        section = _diff_one_fixture("fx", claude, None)
        assert "OpenAI final message NOT found" in section

    def test_missing_claude_reported(self) -> None:
        openai = "Passed: 1\n\n- **OSPS-DO-01.01**: PASS"
        section = _diff_one_fixture("fx", None, openai)
        assert "Claude final message NOT found" in section

    def test_both_missing_reported(self) -> None:
        section = _diff_one_fixture("fx", None, None)
        assert "No final-message artifacts found" in section


class TestDiscoveryAndLookup:
    def test_discover_fixtures_across_roots(self, tmp_path: Path) -> None:
        claude_root = tmp_path / "claude"
        openai_root = tmp_path / "openai"
        _write_msg(claude_root, "a", "skill_final_message.md", "x")
        _write_msg(openai_root, "b", "openai_final_message.md", "x")
        _write_msg(claude_root, "c", "skill_final_message.md", "x")
        _write_msg(openai_root, "c", "openai_final_message.md", "x")

        found = _discover_fixtures(claude_root, openai_root)
        assert found == ["a", "b", "c"]

    def test_find_message_prefers_first_matching_root(
        self,
        tmp_path: Path,
    ) -> None:
        _write_msg(
            tmp_path / "openai",
            "fx",
            "openai_final_message.md",
            "openai-side",
        )
        _write_msg(
            tmp_path / "claude",
            "fx",
            "skill_final_message.md",
            "claude-side",
        )

        claude_msg = _find_message(
            "fx",
            "claude",
            [tmp_path / "claude", tmp_path / "openai"],
        )
        openai_msg = _find_message(
            "fx",
            "openai",
            [tmp_path / "openai", tmp_path / "claude"],
        )
        assert claude_msg == "claude-side"
        assert openai_msg == "openai-side"


class TestMainExitCode:
    def test_main_exits_2_with_no_roots(self) -> None:
        rc = main(argv=[])
        assert rc == 2

    def test_main_exits_1_when_no_fixtures_present(
        self,
        tmp_path: Path,
    ) -> None:
        rc = main(argv=["--artifacts", str(tmp_path)])
        assert rc == 1

    def test_main_success_end_to_end(
        self,
        tmp_path: Path,
        capsys,
    ) -> None:
        _write_msg(
            tmp_path / "cl",
            "fx",
            "skill_final_message.md",
            "Passed: 1\n\n- **OSPS-DO-01.01**: PASS",
        )
        _write_msg(
            tmp_path / "op",
            "fx",
            "openai_final_message.md",
            "Passed: 1\n\n- **OSPS-DO-01.01**: PASS",
        )
        rc = main(
            argv=[
                "--claude-artifacts",
                str(tmp_path / "cl"),
                "--openai-artifacts",
                str(tmp_path / "op"),
            ],
        )
        assert rc == 0
        captured = capsys.readouterr()
        assert "## Fixture: fx" in captured.out
        assert "OSPS-DO-01.01" in captured.out
