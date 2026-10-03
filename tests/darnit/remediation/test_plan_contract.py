"""Preview equals apply for every shipped remediation (feature 043 US5, T047; SC-005, FR-021 to FR-023).

framework-design 4.2: for every remediation in every shipped framework TOML,
on a fixture repository with a recording platform:

- plan mode changes no file, writes no run manifest, and makes no platform write;
- plan then apply (every previewable item approved) applies exactly the
  planned file changes and platform operations;
- a step that cannot be previewed exactly is flagged ``previewable = False``,
  is not run in plan mode, and is skipped in a batch apply without its own
  ``PlanItem.digest``.

Exec steps run a stand-in ``zizmor`` placed first on ``PATH``, so the
previewable zizmor steps (T052) are previewed and applied the same way
whether or not the real tool is installed.
"""

from __future__ import annotations

import os
import subprocess
from collections.abc import Iterator, Sequence
from contextlib import contextmanager
from pathlib import Path
from typing import Any

import pytest

from darnit.config import load_framework_config
from darnit.config.framework_schema import FrameworkConfig, HandlerInvocation, RemediationConfig
from darnit.config.operator.schema import RemediationSettings
from darnit.core.utils import set_gh_api_responder
from darnit.remediation import manifest
from darnit.remediation.executor import RemediationExecutor, RemediationResult
from darnit.remediation.plan import FileChange, PlanItem
from darnit.remediation.platform import PlatformSession, ResolvedPolicy
from darnit.sieve.handler_registry import get_sieve_handler_registry
from tests.conftest_helpers import snapshot
from tests.darnit.remediation.platform.conftest import SimulatedGitHub, _base, recorded_gh

REPO_ROOT = Path(__file__).resolve().parents[3]
OWNER, REPO = "o", "r"
REPOSITORY = "github.com/o/r"
WORKFLOW = "name: ci\non:\n  push:\n\njobs:\n  build:\n    runs-on: ubuntu-latest\n"
_GIT_ENV = {"GIT_CONFIG_GLOBAL": os.devnull, "GIT_CONFIG_NOSYSTEM": "1"}
# A confirmed answer for the user-judgment key the license steps need, so
# LICENSE creation is previewed and applied like every other file.
CONTEXT = {"license_type": "mit"}


def _shipped_tomls() -> list[Path]:
    packages = REPO_ROOT / "packages"
    nested = sorted(packages.glob("*/src/*/*.toml"))
    top = sorted(p for p in packages.glob("*/*.toml") if p.name != "pyproject.toml")
    return nested + top


def _remediations() -> list[tuple[Path, str]]:
    found = []
    for path in _shipped_tomls():
        framework = load_framework_config(path)
        for control_id, control in framework.controls.items():
            if control.remediation is not None and control.remediation.handlers:
                found.append((path, control_id))
    return found


REMEDIATIONS = _remediations()


def _steps() -> list[tuple[Path, str, int, HandlerInvocation]]:
    steps = []
    for path, control_id in REMEDIATIONS:
        remediation = load_framework_config(path).controls[control_id].remediation
        assert remediation is not None
        for index, step in enumerate(remediation.handlers):
            steps.append((path, control_id, index, step))
    return steps


def _id(path: Path, control_id: str) -> str:
    return f"{path.stem}:{control_id}"


ZIZMOR_FIX = "# fixed by zizmor\n"
FAKE_ZIZMOR = f"""#!/bin/sh
for target; do :; done
printf '{ZIZMOR_FIX.strip()}\\n' >> "$target/.github/workflows/ci.yml"
exit 0
"""


@pytest.fixture(autouse=True)
def _fake_zizmor(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    bin_dir = tmp_path_factory.mktemp("bin")
    tool = bin_dir / "zizmor"
    tool.write_text(FAKE_ZIZMOR, encoding="utf-8")
    tool.chmod(0o755)
    monkeypatch.setenv("PATH", f"{bin_dir}{os.pathsep}{os.environ.get('PATH', '')}")


@pytest.fixture(autouse=True, scope="module")
def _plugin_handlers() -> None:
    from darnit_baseline.implementation import OSPSBaselineImplementation

    OSPSBaselineImplementation().register_handlers()


def _previewable(step: HandlerInvocation) -> bool:
    extra = step.model_extra or {}
    if step.handler == "exec":
        return extra.get("effects") == "working_tree" and extra.get("offline") is True
    info = get_sieve_handler_registry().get(step.handler)
    return info is not None and info.supports_plan


NOT_PREVIEWABLE = [s for s in _steps() if not _previewable(s[3])]


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    (path / ".github" / "workflows").mkdir(parents=True)
    (path / ".github" / "workflows" / "ci.yml").write_text(WORKFLOW, encoding="utf-8")
    (path / "pyproject.toml").write_text('[project]\nname = "fixture"\nversion = "0.1.0"\n', encoding="utf-8")
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "--no-gpg-sign", "-m", "init"]):
        subprocess.run(
            ["git", "-c", "init.defaultBranch=main", "-c", "user.name=t", "-c", "user.email=t@example.com", *args],
            cwd=path,
            check=True,
            capture_output=True,
            env={**os.environ, **_GIT_ENV},
        )
    return path


@contextmanager
def _installed(responder: SimulatedGitHub) -> Iterator[SimulatedGitHub]:
    previous = set_gh_api_responder(responder)
    try:
        yield responder
    finally:
        set_gh_api_responder(previous)


def _platform() -> dict[str, dict[str, Any]]:
    return _base(protection=None, private=True, pvr_enabled=False)


def _policy() -> ResolvedPolicy:
    return ResolvedPolicy(settings=RemediationSettings(), operator_config_digest=None, operator="tester")


def _executor(repo: Path, path: Path, framework: FrameworkConfig, approvals: Sequence[str] = ()) -> RemediationExecutor:
    return RemediationExecutor(
        local_path=str(repo),
        owner=OWNER,
        repo=REPO,
        templates=framework.templates,
        framework_path=str(path),
        context_values=CONTEXT,
        platform=PlatformSession(REPOSITORY, policy=_policy(), approvals=approvals),
    )


def _file_changes(changes: list[FileChange]) -> dict[str, tuple[str, str | None]]:
    return {c.path: (c.action, c.content) for c in changes if c.changes}


def _planned_operations(plan: list[PlanItem]) -> list[tuple[str, str, Any]]:
    return [
        (op["method"], op["endpoint"], op["body"])
        for item in plan
        for change_set in item.change_sets
        for op in change_set["operations"]
    ]


def _may_act(item: PlanItem) -> bool:
    return not item.previewable or item.changes or bool(item.commands)


def _approvals(plan: list[PlanItem]) -> list[str]:
    digests = [item.digest for item in plan if item.previewable]
    digests += [cs["digest"] for item in plan for cs in item.change_sets]
    return digests


def _preview(repo: Path, path: Path, control_id: str) -> tuple[FrameworkConfig, RemediationResult]:
    framework = load_framework_config(path)
    remediation = framework.controls[control_id].remediation
    assert remediation is not None
    return framework, _executor(repo, path, framework).execute(control_id, remediation, dry_run=True)


@pytest.mark.unit
def test_every_shipped_framework_is_covered() -> None:
    frameworks = {path.stem for path, _ in REMEDIATIONS}

    assert {"openssf-baseline", "community-spec", "reproducibility", "gittuf", "hello"} <= frameworks
    assert len(REMEDIATIONS) >= 60


@pytest.mark.unit
def test_the_fixture_exercises_files_and_platform_settings(repo: Path) -> None:
    with_files, with_operations = set(), set()
    with recorded_gh(_platform()):
        for path, control_id in REMEDIATIONS:
            _framework, preview = _preview(repo, path, control_id)
            if any(item.changes for item in preview.plan if item.file_changes):
                with_files.add(control_id)
            if _planned_operations(preview.plan):
                with_operations.add(control_id)

    assert len(with_files) >= 40
    assert {"OSPS-AC-03.01", "OSPS-AC-03.02", "OSPS-QA-07.01", "OSPS-QA-01.01", "OSPS-VM-03.01"} <= with_operations


@pytest.mark.unit
@pytest.mark.parametrize(("path", "control_id"), REMEDIATIONS, ids=[_id(*r) for r in REMEDIATIONS])
class TestPreviewEqualsApply:
    def test_plan_changes_nothing(self, repo: Path, path: Path, control_id: str) -> None:
        before = snapshot(repo)

        with recorded_gh(_platform()) as gh:
            _framework, preview = _preview(repo, path, control_id)

        assert snapshot(repo) == before
        assert gh.writes == []
        assert manifest.load_run(REPOSITORY, checkout=repo) is None
        assert preview.plan, "every remediation step appears in the preview"

    def test_apply_makes_exactly_the_planned_changes(self, repo: Path, path: Path, control_id: str) -> None:
        with recorded_gh(_platform()):
            framework, preview = _preview(repo, path, control_id)
        planned_files = _file_changes([c for item in preview.plan for c in item.file_changes])
        planned_operations = _planned_operations(preview.plan)
        gated = [item for item in preview.plan if not item.previewable and _may_act(item)]
        before = snapshot(repo)

        remediation = framework.controls[control_id].remediation
        assert remediation is not None

        with _installed(SimulatedGitHub(_platform())) as gh:
            result = _executor(repo, path, framework, _approvals(preview.plan)).execute(
                control_id, remediation, dry_run=False
            )

        if gated:
            assert result.needs_approval == [item.digest for item in gated]
            assert result.changed is False
            assert snapshot(repo) == before
            assert gh.writes == []
            return

        assert result.needs_approval == []
        assert _file_changes(result.file_changes) == planned_files
        after = snapshot(repo)
        touched = {p for p in after if after[p] is not None and before.get(p) != after[p]}
        assert touched == set(planned_files)
        assert [(w.method, w.endpoint, w.body) for w in gh.writes] == planned_operations


@pytest.mark.unit
@pytest.mark.parametrize(
    ("path", "control_id", "index", "step"),
    NOT_PREVIEWABLE,
    ids=[f"{_id(p, c)}:{s.handler}[{i}]" for p, c, i, s in NOT_PREVIEWABLE],
)
class TestNotPreviewableSteps:
    def _config(self, step: HandlerInvocation) -> RemediationConfig:
        return RemediationConfig(handlers=[step.model_copy(update={"when": None})])

    def test_flagged_and_not_run_in_plan_mode(
        self, repo: Path, path: Path, control_id: str, index: int, step: HandlerInvocation
    ) -> None:
        framework = load_framework_config(path)
        before = snapshot(repo)

        with recorded_gh(_platform()) as gh:
            result = _executor(repo, path, framework).execute(control_id, self._config(step), dry_run=True)

        assert snapshot(repo) == before
        assert gh.calls == []
        [item] = result.plan
        assert item.previewable is False
        assert item.requires_individual_approval is True

    def test_skipped_in_batch_apply_without_its_digest(
        self, repo: Path, path: Path, control_id: str, index: int, step: HandlerInvocation
    ) -> None:
        framework = load_framework_config(path)
        before = snapshot(repo)

        with recorded_gh(_platform()) as gh:
            result = _executor(repo, path, framework).execute(control_id, self._config(step), dry_run=False)

        assert snapshot(repo) == before
        assert gh.writes == []
        assert result.changed is False
        assert len(result.needs_approval) == 1


@pytest.mark.unit
@pytest.mark.parametrize("control_id", ["OSPS-BR-01.01", "OSPS-BR-01.02"])
def test_zizmor_fix_is_previewed(repo: Path, control_id: str) -> None:
    path = next(p for p, c in REMEDIATIONS if c == control_id)
    before = snapshot(repo)

    with recorded_gh(_platform()):
        _framework, preview = _preview(repo, path, control_id)

    assert snapshot(repo) == before
    [item] = [item for item in preview.plan if item.step == "exec[0]"]
    assert item.previewable is True
    assert item.requires_individual_approval is True
    [change] = item.file_changes
    assert (change.path, change.action) == (".github/workflows/ci.yml", "modify")
    assert change.content == WORKFLOW + ZIZMOR_FIX


@pytest.mark.unit
def test_shipped_steps_that_cannot_be_previewed_are_found() -> None:
    handlers = {step.handler for _, _, _, step in NOT_PREVIEWABLE}

    assert "generate_threat_model" in handlers
    assert ("reproducibility", "RE-01.01") in {(p.stem, c) for p, c, _, s in NOT_PREVIEWABLE if s.handler == "exec"}
    assert not any(c.startswith("OSPS-BR-01.0") for _, c, _, s in NOT_PREVIEWABLE if s.handler == "exec")


@pytest.mark.unit
def test_threat_model_handler_declares_no_plan_support() -> None:
    info = get_sieve_handler_registry().get("generate_threat_model")

    assert info is not None
    assert info.supports_plan is False
