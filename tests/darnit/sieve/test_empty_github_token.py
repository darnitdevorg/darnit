"""#752: an empty GitHub token must not hide a clean zizmor audit or fix.

The shipped controls and the shipped exec remediation run through
``SieveOrchestrator`` and ``RemediationExecutor``. ``zizmor`` is a subprocess
mock: an empty ``GH_TOKEN`` or ``GITHUB_TOKEN`` in the child environment is
the CLI usage error zizmor returns, and a child environment without one is a
clean audit or a one-line workflow fix.
"""

from __future__ import annotations

import os
import subprocess
from pathlib import Path
from typing import Any

import pytest

from darnit.config import load_framework_config
from darnit.config.control_loader import control_from_framework
from darnit.remediation.executor import RemediationExecutor
from darnit.sieve.handler_registry import reset_sieve_handler_registry
from darnit.sieve.models import CheckContext, ControlSpec, SieveResult
from darnit.sieve.orchestrator import SieveOrchestrator

REPO_ROOT = Path(__file__).resolve().parents[3]
BASELINE_TOML = REPO_ROOT / "packages/darnit-baseline/src/darnit_baseline/openssf-baseline.toml"
CONTROLS = ("OSPS-BR-01.01", "OSPS-AC-04.02")
TOKENS = ("GH_TOKEN", "GITHUB_TOKEN")
# The zizmor step follows github_workflows_present (#584).
ZIZMOR_STEP = 1
WORKFLOW = "name: ci\non:\n  push:\n\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
MARKER = "# fixed by zizmor\n"
USAGE = "error: invalid value '' for '--gh-token <GH_TOKEN>': GitHub token cannot be empty\n"
_GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}


@pytest.fixture(autouse=True)
def _baseline_handlers() -> None:
    reset_sieve_handler_registry()
    from darnit.core.discovery import get_implementation

    impl = get_implementation("openssf-baseline")
    assert impl is not None
    impl.register_handlers()


def _shipped(control_id: str) -> ControlSpec:
    framework = load_framework_config(BASELINE_TOML)
    return control_from_framework(
        control_id, framework.controls[control_id].model_copy(deep=True), framework=framework.metadata.name
    )


def _repo(tmp_path: Path) -> Path:
    repo = tmp_path / "repo"
    workflow = repo / ".github" / "workflows"
    workflow.mkdir(parents=True)
    (workflow / "ci.yml").write_text(WORKFLOW, encoding="utf-8")
    subprocess.run(
        ["git", "-c", "init.defaultBranch=main", "-c", "user.name=t", "-c", "user.email=t@example.com", "init", "-q"],
        cwd=repo,
        check=True,
        capture_output=True,
        env={**os.environ, **_GIT_ENV},
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            "add",
            "-A",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        env={**os.environ, **_GIT_ENV},
    )
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=t",
            "-c",
            "user.email=t@example.com",
            "commit",
            "-q",
            "--no-gpg-sign",
            "-m",
            "init",
        ],
        cwd=repo,
        check=True,
        capture_output=True,
        env={**os.environ, **_GIT_ENV},
    )
    return repo


def _mock_zizmor(monkeypatch: pytest.MonkeyPatch, seen: list[dict[str, str]], *, rewrite: bool = False) -> None:
    """Answer ``zizmor`` from the child environment. Every other command runs for real."""
    real_run = subprocess.run

    def run(cmd: Any, *args: Any, **kwargs: Any) -> subprocess.CompletedProcess:
        if isinstance(cmd, (list, tuple)) and cmd and cmd[0] == "zizmor":
            env = dict(kwargs.get("env") or {})
            seen.append(env)
            if env.get("GH_TOKEN") == "" or env.get("GITHUB_TOKEN") == "":
                return subprocess.CompletedProcess(cmd, 2, stdout="", stderr=USAGE)
            if rewrite:
                workflow = Path(kwargs["cwd"]) / ".github" / "workflows" / "ci.yml"
                text = workflow.read_text(encoding="utf-8")
                if MARKER not in text:
                    workflow.write_text(text + MARKER, encoding="utf-8")
            return subprocess.CompletedProcess(cmd, 0, stdout="[]", stderr="")
        return real_run(cmd, *args, **kwargs)

    monkeypatch.setattr("darnit.sieve.builtin_handlers.subprocess.run", run)


def _unix(text: str) -> str:
    return text.replace("\r\n", "\n")


def _porcelain(repo: Path) -> list[str]:
    """Paths with any staged, unstaged, or untracked change.

    Run manifests are operator-side, outside this checkout, so they do not
    appear here. Anything this command lists is a repository change.
    """
    result = subprocess.run(
        ["git", "--no-optional-locks", "status", "--porcelain", "--untracked-files=all"],
        cwd=repo,
        check=True,
        capture_output=True,
        text=True,
        env={**os.environ, **_GIT_ENV},
    )
    paths: list[str] = []
    for line in result.stdout.splitlines():
        if len(line) < 4:
            continue
        path = line[3:]
        if " -> " in path:
            path = path.split(" -> ", 1)[1]
        if len(path) >= 2 and path[0] == path[-1] == '"':
            path = path[1:-1]
        paths.append(path.replace("\\", "/"))
    return paths


def _no_empty_token(env: dict[str, str], token: str) -> None:
    assert env.get("GH_TOKEN") != ""
    assert env.get("GITHUB_TOKEN") != ""
    assert token not in env


@pytest.mark.unit
@pytest.mark.parametrize("control_id", CONTROLS)
@pytest.mark.parametrize("token", TOKENS)
def test_empty_token_still_passes_shipped_zizmor_control(
    control_id: str, token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv(token, "")
    parent = os.environ.copy()
    seen: list[dict[str, str]] = []
    _mock_zizmor(monkeypatch, seen)
    repo = _repo(tmp_path)

    result: SieveResult = SieveOrchestrator(stop_on_llm=False).verify(
        _shipped(control_id),
        CheckContext(
            owner="example-org",
            repo="example",
            local_path=str(repo),
            default_branch="main",
            control_id=control_id,
        ),
    )

    assert seen, "zizmor was not run"
    for env in seen:
        _no_empty_token(env, token)
    step = result.pass_history[ZIZMOR_STEP].result
    assert step.evidence["exit_code"] == 0
    assert step.evidence["json"] == []
    assert (result.status, result.concluded_by, result.resolving_pass_index) == ("PASS", "exec", ZIZMOR_STEP)
    assert os.environ.copy() == parent
    assert os.environ[token] == ""


@pytest.mark.unit
@pytest.mark.parametrize("token", TOKENS)
def test_empty_token_does_not_block_zizmor_fix(token: str, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    """The shipped BR-01.01 exec remediation previews and applies through the same child environment."""
    monkeypatch.setenv(token, "")
    parent = os.environ.copy()
    seen: list[dict[str, str]] = []
    _mock_zizmor(monkeypatch, seen, rewrite=True)
    repo = _repo(tmp_path)
    assert _porcelain(repo) == []
    remediation = load_framework_config(BASELINE_TOML).controls["OSPS-BR-01.01"].remediation
    assert remediation is not None

    preview = RemediationExecutor(local_path=str(repo), owner="o", repo="r").execute(
        "OSPS-BR-01.01", remediation, dry_run=True
    )

    workflow = repo / ".github" / "workflows" / "ci.yml"
    assert _unix(workflow.read_text(encoding="utf-8")) == WORKFLOW
    exec_item = next(item for item in preview.plan if item.step == "exec[0]")
    assert exec_item.previewable is True
    [change] = [change for change in exec_item.file_changes if change.changes]
    assert change.path == ".github/workflows/ci.yml"
    assert _unix(change.content or "") == WORKFLOW + MARKER
    assert _porcelain(repo) == []

    approvals = [item.digest for item in preview.plan if item.requires_individual_approval]
    applied = RemediationExecutor(local_path=str(repo), owner="o", repo="r", approvals=approvals).execute(
        "OSPS-BR-01.01", remediation, dry_run=False
    )

    assert applied.success is True
    assert _unix(workflow.read_text(encoding="utf-8")) == WORKFLOW + MARKER
    assert _porcelain(repo) == [".github/workflows/ci.yml"]
    assert len(seen) >= 2
    for env in seen:
        _no_empty_token(env, token)
    assert os.environ.copy() == parent
    assert os.environ[token] == ""
