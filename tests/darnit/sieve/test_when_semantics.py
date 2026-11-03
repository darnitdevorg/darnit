"""One ``when`` evaluator for controls and steps (framework-design 5.1.1).

A list value means membership, a missing key never excludes, and a value
read from the audited repository that no honored claim backs does not
exclude a control or a step. Exercised through ``run_sieve_audit`` with a
small framework file.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from darnit.tools.audit import calculate_compliance

OWN = "github.com/example/repo"
_CI_VARS = ("GITHUB_ACTIONS", "GITLAB_CI", "CI", "JENKINS_URL", "TF_BUILD", "BUILDKITE", "CIRCLECI", "TRAVIS")

FRAMEWORK = """\
[metadata]
name = "when-probe"
display_name = "When probe"
version = "0.0.1"
schema_version = "0.1.0-alpha"
spec_version = "test"

[context.ships_widgets]
type = "boolean"
prompt = "Does this project ship widgets?"
auto_detect = false

[controls."PRB-W"]
name = "RepositoryClaimedWhen"
description = "Applies to projects that ship widgets"
level = 1
when = { ships_widgets = true }
passes = [
    { handler = "file_exists", files = ["MISSING.md"] },
]

[controls."PRB-L"]
name = "ListWhen"
description = "Applies to GitHub and GitLab CI"
level = 1
when = { ci_provider = ["github", "gitlab"] }
passes = [
    { handler = "file_exists", files = ["MISSING.md"] },
]

[controls."PRB-P"]
name = "Present"
description = "README is present"
level = 1
passes = [
    { handler = "file_exists", files = ["README.md"], existence = true },
]

[controls."PRB-MISSING"]
name = "StepWhenMissingKey"
description = "A step whose when names a key the context does not hold"
level = 1
passes = [
    { handler = "file_exists", files = ["MISSING.md"], when = { has_widgets = true } },
    { handler = "file_exists", files = ["README.md"], existence = true },
]

[controls."PRB-STEPLIST"]
name = "StepWhenList"
description = "A step whose when is a list"
level = 1
passes = [
    { handler = "file_exists", files = ["MISSING.md"], when = { ci_provider = ["github", "gitlab"] } },
    { handler = "file_exists", files = ["README.md"], existence = true },
]

[controls."PRB-REPO"]
name = "StepWhenRepositoryValue"
description = "A step whose when the repository's .project/project.yaml contradicts"
level = 1
passes = [
    { handler = "file_exists", files = ["MISSING.md"], when = { "project.type" = "application" } },
    { handler = "file_exists", files = ["README.md"], existence = true },
]

[controls."PRB-MISMATCH"]
name = "StepWhenDetectedMismatch"
description = "A step whose when this run's detection contradicts is skipped"
level = 1
passes = [
    { handler = "file_exists", files = ["MISSING.md"], when = { ci_provider = "jenkins" } },
    { handler = "file_exists", files = ["README.md"], existence = true },
]

[controls."PRB-NA"]
name = "ControlWhenDetectedMismatch"
description = "A control whose when this run's detection contradicts is N/A"
level = 1
when = { ci_provider = ["github", "jenkins"] }
passes = [
    { handler = "file_exists", files = ["MISSING.md"] },
]
"""


@pytest.fixture(autouse=True)
def _outside_ci(monkeypatch: pytest.MonkeyPatch) -> None:
    for var in _CI_VARS:
        monkeypatch.delenv(var, raising=False)


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    """A GitLab CI repository whose ``.project/project.yaml`` says it is a library."""
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main", "-q"], cwd=path, check=True)
    subprocess.run(["git", "remote", "add", "origin", f"https://{OWN}.git"], cwd=path, check=True)
    (path / "README.md").write_text("# repo\n", encoding="utf-8")
    (path / ".gitlab-ci.yml").write_text("test:\n  script: [echo hi]\n", encoding="utf-8")
    (path / ".project").mkdir()
    (path / ".project" / "project.yaml").write_text("name: repo\ntype: library\n", encoding="utf-8")
    return path


@pytest.fixture
def widgets_repo(repo: Path) -> Path:
    """``repo`` with ``ships_widgets: false`` confirmed in its own ``.project/darnit.yaml``."""
    import yaml

    from darnit.config.context_keys import value_digest

    data = {
        "context": {"ships_widgets": False},
        "confirmations": {
            "ships_widgets": {
                "value_digest": value_digest("ships_widgets", False),
                "confirmed_by": "maintainer",
                "confirmed_at": "2026-09-01T00:00:00Z",
                "last_validated": "2026-09-01T00:00:00Z",
            }
        },
    }
    (repo / ".project" / "darnit.yaml").write_text(yaml.safe_dump(data), encoding="utf-8")
    return repo


def _audit(
    repo: Path, tmp_path: Path, *, trusted: bool = False, monkeypatch: pytest.MonkeyPatch | None = None
) -> list[dict]:
    from darnit.config import load_controls_from_framework, load_framework_config
    from darnit.config.operator.loader import LoadedOperatorConfig
    from darnit.config.operator.schema import OperatorConfig
    from darnit.tools import audit
    from darnit.tools.audit import run_sieve_audit

    framework_path = tmp_path / "when-probe.toml"
    framework_path.write_text(FRAMEWORK, encoding="utf-8")
    if monkeypatch is not None:
        # Audit against this framework file, so its claims are assessed (feature 040).
        monkeypatch.setattr(audit, "_get_framework_config_path", lambda name=None: framework_path)
    controls = load_controls_from_framework(load_framework_config(framework_path))
    operator = LoadedOperatorConfig(
        config=OperatorConfig.model_validate({"schema_version": 1, "trust": {"repos": [OWN] if trusted else []}}),
        source="test",
        digest=None,
        permission_check="ok",
        strict=False,
    )
    results, _ = run_sieve_audit(
        owner="example",
        repo="repo",
        local_path=str(repo),
        default_branch="main",
        level=1,
        controls=controls,
        operator_config=operator,
        target=OWN,
        write_cache=False,
    )
    return results


@pytest.mark.integration
class TestWhenThroughTheAudit:
    def test_list_valued_control_when_runs_the_control_when_the_value_is_listed(
        self, repo: Path, tmp_path: Path
    ) -> None:
        results = _audit(repo, tmp_path)
        by_id = {r["id"]: r for r in results}

        assert by_id["PRB-L"]["status"] == "FAIL"
        assert by_id["PRB-P"]["status"] == "PASS"
        assert calculate_compliance([by_id["PRB-L"], by_id["PRB-P"]], 1) == {1: False}

    def test_control_when_that_detection_contradicts_is_not_applicable(self, repo: Path, tmp_path: Path) -> None:
        by_id = {r["id"]: r for r in _audit(repo, tmp_path)}

        assert by_id["PRB-NA"]["status"] == "N/A"

    def test_step_when_with_a_missing_key_runs_the_step(self, repo: Path, tmp_path: Path) -> None:
        by_id = {r["id"]: r for r in _audit(repo, tmp_path)}

        assert by_id["PRB-MISSING"]["status"] == "FAIL"

    def test_list_valued_step_when_runs_the_step_when_the_value_is_listed(self, repo: Path, tmp_path: Path) -> None:
        by_id = {r["id"]: r for r in _audit(repo, tmp_path)}

        assert by_id["PRB-STEPLIST"]["status"] == "FAIL"

    def test_unconfirmed_repository_value_does_not_skip_a_step(self, repo: Path, tmp_path: Path) -> None:
        by_id = {r["id"]: r for r in _audit(repo, tmp_path)}

        assert by_id["PRB-REPO"]["status"] == "FAIL"

    def test_step_when_that_detection_contradicts_skips_the_step(self, repo: Path, tmp_path: Path) -> None:
        by_id = {r["id"]: r for r in _audit(repo, tmp_path)}

        assert by_id["PRB-MISMATCH"]["status"] == "PASS"

    def test_honored_repository_value_makes_the_control_not_applicable(
        self, widgets_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        by_id = {r["id"]: r for r in _audit(widgets_repo, tmp_path, trusted=True, monkeypatch=monkeypatch)}

        assert by_id["PRB-W"]["assertion"]["outcome"] == "honored"
        assert by_id["PRB-W"]["status"] == "N/A"

    def test_unhonored_repository_value_does_not_make_the_control_not_applicable(
        self, widgets_repo: Path, tmp_path: Path, monkeypatch: pytest.MonkeyPatch
    ) -> None:
        by_id = {r["id"]: r for r in _audit(widgets_repo, tmp_path, trusted=False, monkeypatch=monkeypatch)}

        assert by_id["PRB-W"]["assertion"]["outcome"] == "pending"
        assert by_id["PRB-W"]["status"] == "FAIL"
