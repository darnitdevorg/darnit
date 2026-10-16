"""Not-applicable claims on operator custom controls (framework-design 14.3).

A custom control's ``contradicted_by`` is assessed like a framework control's:
contradicting evidence keeps a trusted repository's claim from being honored,
and the confirmation tool refuses to confirm it.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from tests.conftest_helpers import stand_in_tool

OWNER, REPO = "example", "repo"
OWN = f"github.com/{OWNER}/{REPO}"
CUSTOM = "CUSTOM-01"

_OPERATOR_TOML = f"""\
schema_version = 1

[trust]
repos = ["{OWN}"]

[custom_controls."{CUSTOM}"]
name = "Release notes"
description = "Releases carry release notes"
level = 1
domain = "ZZ"
contradicted_by = {{ context = "has_releases", when_value = true }}
passes = [{{ handler = "file_exists", files = ["RELEASE_NOTES.md"] }}]
"""


def _repo(tmp_path: Path, *, changelog: bool) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "--initial-branch=main", "-q"], cwd=path, check=True)
    subprocess.run(["git", "remote", "add", "origin", f"https://{OWN}.git"], cwd=path, check=True)
    if changelog:
        (path / "CHANGELOG.md").write_text("# 1.0.0\n", encoding="utf-8")
    (path / ".project").mkdir()
    (path / ".project" / "darnit.yaml").write_text(
        f"controls:\n  {CUSTOM}:\n    status: n/a\n    reason: no releases yet\n", encoding="utf-8"
    )
    return path


@pytest.fixture(autouse=True)
def _operator_config(tmp_path_factory: pytest.TempPathFactory) -> None:
    from darnit.config.operator import loader

    path = tmp_path_factory.mktemp("operator") / "config.toml"
    path.write_text(_OPERATOR_TOML, encoding="utf-8")
    path.chmod(0o600)
    loader.set_launch_options(path, strict=False)


def _audit(repo: Path) -> dict:
    from darnit.config.operator.loader import resolve_operator_config
    from darnit.tools.audit import run_sieve_audit

    results, _ = run_sieve_audit(
        owner=OWNER,
        repo=REPO,
        local_path=str(repo),
        default_branch="main",
        level=1,
        tags=["domain=ZZ"],
        framework_name="openssf-baseline",
        operator_config=resolve_operator_config(repo),
        target=OWN,
    )
    return {r["id"]: r for r in results}[CUSTOM]


@pytest.mark.integration
class TestCustomControlClaims:
    def test_contradicting_evidence_keeps_the_claim_from_being_honored(self, tmp_path: Path) -> None:
        result = _audit(_repo(tmp_path, changelog=True))

        assert result["assertion"]["outcome"] == "contradicted"
        assert result["assertion"]["contradiction"]["evidence_source"].startswith("context.has_releases")
        assert result["status"] != "N/A"

    def test_uncontradicted_claim_is_honored(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        # The platform lists no releases, so detection concludes has_releases = false.
        bin_dir = tmp_path / "bin"
        bin_dir.mkdir()
        stand_in_tool(monkeypatch, bin_dir, "gh")
        result = _audit(_repo(tmp_path, changelog=False))

        assert result["status"] == "N/A"
        assert result["assertion"]["outcome"] == "honored"

    def test_confirmation_refuses_a_contradicted_claim(self, tmp_path: Path) -> None:
        from darnit.server.tools.project_data import confirm_not_applicable_impl

        output = confirm_not_applicable_impl(
            str(_repo(tmp_path, changelog=True)),
            [CUSTOM],
            owner=OWNER,
            repo=REPO,
            framework_name="openssf-baseline",
        )

        assert f"- {CUSTOM}: not confirmed; has_releases detected as True" in output
