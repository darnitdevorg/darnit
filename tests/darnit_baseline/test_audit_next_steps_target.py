"""The audit's Next Steps read project data confirmed for the named repository (#664).

For an untrusted repository, a person's answers are recorded operator-side
under the repository the caller names. The report's "Confirm project context"
step must read them the same way, or it keeps asking for answers already
given.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

OWNER, REPO = "acme", "widget"
OWN = f"github.com/{OWNER}/{REPO}"
ASK = "Confirm project context"
CONFIRMED_VALUES = {
    "has_releases": False,
    "maintainers": ["@alice"],
    "security_contact": "security@example.com",
    "governance_model": "bdfl",
    "is_library": False,
    "has_compiled_assets": False,
    "ci_provider": "github",
    "license_type": "mit",
    "has_subprojects": False,
}


@pytest.fixture
def untrusted_repo(tmp_path: Path) -> Path:
    from darnit.config.operator import loader

    config = tmp_path / "operator" / "config.toml"
    config.parent.mkdir()
    config.write_text("schema_version = 1\n\n[trust]\nrepos = []\n", encoding="utf-8")
    config.chmod(0o600)
    loader.set_launch_options(config, strict=False)

    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "remote", "add", "origin", f"https://{OWN}.git"], cwd=path, check=True)
    return path


def _confirm(repo: Path) -> None:
    from darnit.config.context_writes import record_value_confirmations
    from darnit.config.operator.loader import resolve_operator_config

    results = record_value_confirmations(
        str(repo), CONFIRMED_VALUES, target=OWN, operator=resolve_operator_config(repo).config
    )
    assert {r.location for r in results} == {"operator"}


def _report(checkout: Path, **names: str) -> str:
    from darnit_baseline.tools import audit_openssf_baseline

    return audit_openssf_baseline(local_path=str(checkout), **names)


@pytest.mark.integration
class TestNextStepsForTheNamedRepository:
    def test_asks_for_project_data_before_it_is_confirmed(self, untrusted_repo: Path) -> None:
        assert ASK in _report(untrusted_repo, owner=OWNER, repo=REPO)

    def test_does_not_ask_again_once_confirmed_operator_side(self, untrusted_repo: Path) -> None:
        _confirm(untrusted_repo)

        assert ASK not in _report(untrusted_repo, owner=OWNER, repo=REPO)

    def test_an_unnamed_audit_does_not_read_operator_side_answers(self, untrusted_repo: Path) -> None:
        _confirm(untrusted_repo)

        assert ASK in _report(untrusted_repo)
