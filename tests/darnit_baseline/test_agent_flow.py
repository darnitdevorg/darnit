"""Integration test for the agent flow (audit -> confirm context -> re-audit).

Addresses issue #664: after project data questions are answered and confirmed
operator-side for an untrusted repository, the subsequent audit report's
Next Steps section must not ask for project context.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

from darnit.config.context_writes import record_value_confirmations
from darnit.config.operator.loader import resolve_operator_config, set_launch_options
from darnit_baseline.tools import audit_openssf_baseline

OWNER, REPO = "acme", "widget"
OWN = f"github.com/{OWNER}/{REPO}"
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


def _operator(tmp_path: Path, trusted: list[str]) -> None:
    path = tmp_path / "operator" / "config.toml"
    path.parent.mkdir(parents=True, exist_ok=True)
    repos = ", ".join(f'"{r}"' for r in trusted)
    path.write_text(f"schema_version = 1\n\n[trust]\nrepos = [{repos}]\n", encoding="utf-8")
    path.chmod(0o600)
    set_launch_options(path, strict=False)


def _repo(tmp_path: Path) -> Path:
    """A checkout whose origin remote names OWN."""
    path = tmp_path / "repo"
    path.mkdir(parents=True, exist_ok=True)
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "remote", "add", "origin", f"https://{OWN}.git"], cwd=path, check=True)
    return path


@pytest.mark.integration
class TestAgentFlowNextSteps:
    def test_next_steps_omits_project_context_after_operator_confirmations(self, tmp_path: Path) -> None:
        # Untrusted repository: operator trust list is empty
        _operator(tmp_path, [])
        repo = _repo(tmp_path)

        # Before confirmations, the audit's Next Steps asks to confirm project context
        initial_report = audit_openssf_baseline(
            local_path=str(repo), owner=OWNER, repo=REPO, level=1
        )
        assert "Confirm project context" in initial_report

        # Confirm all project context keys operator-side
        results = record_value_confirmations(
            str(repo),
            CONFIRMED_VALUES,
            target=OWN,
            operator=resolve_operator_config(repo).config,
        )
        assert all(r.outcome == "confirmed" for r in results)
        assert {r.location for r in results} == {"operator"}

        # After confirmations, the audit's Next Steps must not ask to confirm project context (#664)
        subsequent_report = audit_openssf_baseline(
            local_path=str(repo), owner=OWNER, repo=REPO, level=1
        )
        assert "Confirm project context" not in subsequent_report
