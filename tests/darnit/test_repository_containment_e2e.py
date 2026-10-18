"""An audited repository's links to files outside it never reach audit output (framework-design.md 3.0.4).

The repository's README.md, SECURITY.md, MAINTAINERS.md, and other documents
are symbolic links to one file outside it holding a marker. The marker must
not appear in the audit JSON, the pending-data payload, a harness report, or
any model request; links that stay inside the repository are still read.
"""

from __future__ import annotations

import asyncio
import json
import subprocess
from pathlib import Path

import pytest

from darnit.core.llm_step import LLMJudgment, MockLLMStep
from darnit.harness.driver import HarnessRun

OUTSIDE_MARKER = "outsidemarker7f3a"
INSIDE_MARKER = "insidemarker5c1d"
LINKED_DOCUMENTS = (
    "README.md",
    "SECURITY.md",
    "MAINTAINERS.md",
    "CONTRIBUTING.md",
    "GOVERNANCE.md",
    "CODEOWNERS",
    "SUPPORT.md",
    "CHANGELOG.md",
)


def _document(marker: str) -> str:
    return (
        f"# Project {marker}\n\n"
        f"{marker} is a library for parsing things.\n\n"
        "## Security\n\n"
        f"Report vulnerabilities to {marker}@example.com. We respond within 14 days.\n\n"
        "## Maintainers\n\n"
        f"- @{marker}\n\n"
        "## Contributing\n\n"
        f"Open a pull request; {marker} reviews every change.\n"
    )


@pytest.fixture(autouse=True)
def _isolated_home(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    home = tmp_path_factory.mktemp("home")
    monkeypatch.setenv("HOME", str(home))
    for var in ("XDG_CONFIG_HOME", "XDG_DATA_HOME", "XDG_CACHE_HOME", "XDG_STATE_HOME"):
        monkeypatch.setenv(var, str(home / var.lower()))
    monkeypatch.setenv("ANTHROPIC_API_KEY", "test-key-not-real")


def _git_repo(path: Path) -> Path:
    subprocess.run(["git", "init", "--initial-branch=main", "-q"], cwd=path, check=True)
    subprocess.run(["git", "remote", "add", "origin", "https://github.com/example/project.git"], cwd=path, check=True)
    return path


@pytest.fixture
def linked_out_repo(tmp_path: Path) -> Path:
    outside = tmp_path / "outside"
    outside.mkdir()
    secret = outside / "credentials.txt"
    secret.write_text(_document(OUTSIDE_MARKER), encoding="utf-8")
    repo = tmp_path / "repo"
    (repo / ".github").mkdir(parents=True)
    (repo / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    for name in LINKED_DOCUMENTS:
        (repo / name).symlink_to(secret)
    (repo / ".github" / "SECURITY.md").symlink_to(secret)
    (repo / "docs").symlink_to(outside, target_is_directory=True)
    return _git_repo(repo)


@pytest.fixture
def linked_in_repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    (repo / "docs").mkdir(parents=True)
    (repo / "docs" / "README.md").write_text(_document(INSIDE_MARKER), encoding="utf-8")
    (repo / "LICENSE").write_text("MIT License\n", encoding="utf-8")
    for name in ("README.md", "SECURITY.md"):
        (repo / name).symlink_to(f"docs/{name}" if name == "README.md" else "docs/README.md")
    return _git_repo(repo)


def _audit_json(repo: Path) -> str:
    from darnit_baseline.tools import audit_openssf_baseline

    output = audit_openssf_baseline(local_path=str(repo), level=3, output_format="json")
    json.loads(output)
    return output


def _harness(repo: Path) -> tuple[str, MockLLMStep]:
    llm = MockLLMStep(LLMJudgment(outcome="inconclusive", confidence=0.0, reasoning="mock"))
    run = HarnessRun(
        local_path=str(repo),
        framework_name="openssf-baseline",
        level=3,
        llm_step=llm,
        per_call_timeout_s=10,
        total_run_timeout_s=300,
    )
    report = asyncio.new_event_loop().run_until_complete(run.run())
    calls = json.dumps([call.model_dump(mode="json") for call in llm.calls])
    return report.to_json() + "\n" + calls, llm


@pytest.mark.integration
def test_links_outside_never_reach_audit_output(linked_out_repo: Path) -> None:
    output = _audit_json(linked_out_repo)
    assert OUTSIDE_MARKER not in output
    assert "credentials.txt" not in output
    assert "skipped_outside_repository" in output


@pytest.mark.integration
def test_links_outside_never_reach_pending_data(linked_out_repo: Path) -> None:
    from darnit_baseline.tools import get_pending_data

    output = get_pending_data(local_path=str(linked_out_repo), limit=50)
    assert OUTSIDE_MARKER not in output
    assert "credentials.txt" not in output


@pytest.mark.integration
def test_links_outside_never_reach_the_model(linked_out_repo: Path) -> None:
    output, llm = _harness(linked_out_repo)
    assert OUTSIDE_MARKER not in output
    assert "credentials.txt" not in output
    assert all(OUTSIDE_MARKER not in json.dumps(call.file_contents) for call in llm.calls)


@pytest.mark.integration
def test_links_inside_are_still_read(linked_in_repo: Path) -> None:
    assert INSIDE_MARKER in _audit_json(linked_in_repo)
    _output, llm = _harness(linked_in_repo)
    assert any(INSIDE_MARKER in json.dumps(call.file_contents) for call in llm.calls)


@pytest.mark.integration
def test_links_outside_never_reach_a_judgment_regather(linked_out_repo: Path) -> None:
    from darnit.config.operator.loader import resolve_operator_config
    from darnit.tools.audit import judgment_consultations

    consultations = judgment_consultations(
        str(linked_out_repo),
        ["OSPS-DO-01.01", "OSPS-VM-01.01", "OSPS-GV-01.01", "OSPS-VM-02.01"],
        "openssf-baseline",
        resolve_operator_config(linked_out_repo),
        "example",
        "project",
        None,
    )
    assert any(consultations.values())
    assert OUTSIDE_MARKER not in json.dumps(consultations, default=str)
