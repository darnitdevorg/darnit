"""Remediation prompts show candidates as labelled data and placeholder-only commands (feature 042, US3, FR-013, FR-014)."""

from __future__ import annotations

import re
from pathlib import Path

import pytest

from darnit.config.context_keys import value_digest
from darnit.config.context_schema import Origin, OriginKind, ResolvedValue, Standing
from darnit.config.framework_schema import ContextDefinitionConfig, ContextRequirement
from darnit.remediation.context_validator import format_context_prompt

MAINTAINERS = ["@alice", "@bob"]
DEFINITION = ContextDefinitionConfig(
    type="list_or_path",
    prompt="Who are the project maintainers?",
    hint="Provide GitHub usernames or path to MAINTAINERS.md",
    examples=["@user1, @user2", "MAINTAINERS.md"],
    hint_sources=["MAINTAINERS.md"],
    allow_sieve_hints=True,
)
TEMPLATES = (
    'confirm_project_data(accept_candidates={"maintainers": "<candidate digest if the person accepts it>"}, '
    "owner=..., repo=...)",
    "confirm_project_data(maintainers=<the person's answer>, owner=..., repo=...)",
)


def _code_blocks(text: str) -> str:
    return "\n".join(re.findall(r"```[a-z]*\n(.*?)```", text, flags=re.DOTALL))


def _candidate(value: object = MAINTAINERS, kind: OriginKind = OriginKind.SIEVE_HINT) -> ResolvedValue:
    return ResolvedValue(
        key="maintainers",
        standing=Standing.CANDIDATE,
        value=value,
        origin=Origin(kind=kind, method="MAINTAINERS.md", confidence=0.95),
    )


def _prompt(candidate: ResolvedValue | None, local_path: str | None = None) -> str:
    return format_context_prompt(
        context_key="maintainers",
        definition=DEFINITION,
        requirement=ContextRequirement(key="maintainers", prompt_if_auto_detected=True),
        candidate=candidate,
        local_path=local_path,
    )


@pytest.mark.unit
class TestFormatContextPrompt:
    def test_candidate_is_labelled_data_with_origin_and_digest(self) -> None:
        prompt = _prompt(_candidate())

        assert "UNCONFIRMED" in prompt
        assert "sieve_hint" in prompt
        assert "MAINTAINERS.md" in prompt
        assert value_digest("maintainers", MAINTAINERS) in prompt
        for handle in MAINTAINERS:
            assert handle in prompt

    def test_commands_hold_placeholders_only(self) -> None:
        commands = _code_blocks(_prompt(_candidate()))

        for template in TEMPLATES:
            assert template in commands
        for handle in MAINTAINERS:
            assert handle not in commands
        assert value_digest("maintainers", MAINTAINERS) not in commands

    def test_stored_value_is_shown_as_a_candidate(self) -> None:
        prompt = _prompt(_candidate(kind=OriginKind.STORED_UNCONFIRMED))

        assert "stored_unconfirmed" in prompt
        assert "@alice" not in _code_blocks(prompt)

    def test_without_candidate_only_the_answer_template(self) -> None:
        prompt = _prompt(None)

        assert _code_blocks(prompt).strip() == TEMPLATES[1]
        assert "accept_candidates" not in prompt

    @pytest.mark.parametrize("with_candidate", [True, False])
    def test_examples_are_never_offered_as_values(self, with_candidate: bool) -> None:
        prompt = _prompt(_candidate() if with_candidate else None)

        commands = _code_blocks(prompt)
        for example in DEFINITION.examples:
            assert example not in commands
        assert "Format (not an answer): @user1, @user2 or MAINTAINERS.md" in prompt

    def test_hint_file_values_are_not_parsed_into_the_prompt(self, tmp_path: Path) -> None:
        """Only the resolver's candidate is shown, so accepting its digest confirms what the person saw."""
        (tmp_path / "MAINTAINERS.md").write_text("- @charlie\n")

        prompt = _prompt(_candidate(), local_path=str(tmp_path))

        assert "@charlie" not in prompt
        assert "`MAINTAINERS.md`" in prompt


@pytest.mark.unit
class TestPreflightPrompt:
    def _context_info(self) -> dict:
        candidate = _candidate()
        return {
            "missing_context": ["maintainers", "governance_model"],
            "auto_detected": {"maintainers": MAINTAINERS},
            "candidates": {"maintainers": candidate},
            "prompts": [_prompt(candidate)],
            "key_to_controls": {"maintainers": ["OSPS-GV-04.01"], "governance_model": ["OSPS-GV-01.01"]},
        }

    def test_preflight_commands_hold_placeholders_only(self) -> None:
        from darnit_baseline.remediation.orchestrator import _format_preflight_prompt

        text = _format_preflight_prompt(self._context_info(), "/repo")

        commands = _code_blocks(text)
        for handle in MAINTAINERS:
            assert handle not in commands
        assert value_digest("maintainers", MAINTAINERS) not in commands
        assert "maintainers=<the person's answer>" in commands
        assert "governance_model=<the person's answer>" in commands

    def test_preflight_lists_the_candidate_as_data(self) -> None:
        from darnit_baseline.remediation.orchestrator import _format_preflight_prompt

        text = _format_preflight_prompt(self._context_info(), "/repo")

        assert "UNCONFIRMED" in text
        assert value_digest("maintainers", MAINTAINERS) in text
        assert "@alice" in text


@pytest.mark.integration
def test_preflight_on_a_repository_with_detected_maintainers(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    import os
    import shutil
    import subprocess

    from darnit_baseline.remediation.orchestrator import _format_preflight_prompt, _preflight_context_check

    bin_dir = tmp_path / "bin"
    bin_dir.mkdir()
    (bin_dir / "gh").symlink_to(shutil.which("false"))
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")
    repo = tmp_path / "repo"
    repo.mkdir()
    (repo / "MAINTAINERS.md").write_text("# Maintainers\n\n- Alice Example <alice@realcorp.io> @alice\n")
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)

    ready, info = _preflight_context_check(["OSPS-GV-04.01"], str(repo), "example-org", "repo")
    text = _format_preflight_prompt(info, str(repo))

    assert not ready
    assert "@alice" in text
    assert "@alice" not in _code_blocks(text)
