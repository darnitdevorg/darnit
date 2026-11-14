"""Remediation takes its trust identity from the operator, never from the checkout (framework-design 14.2, 15.4).

The repository the caller names (owner, repo, host) decides trust for the
remediation run, its context reads, its pending-context guard, and its
re-check. A checkout whose origin remote names a trusted repository is not
trusted when the caller names nothing.
"""

from __future__ import annotations

import subprocess
from pathlib import Path

import pytest

OWNER, REPO = "acme", "widget"
OWN = f"github.com/{OWNER}/{REPO}"
CLAIMED = "OSPS-DO-03.01"
# An honored claim makes the control N/A in the audit, so remediation leaves it out.
REMEDIATED = f"### {CLAIMED} "
BLOCKED = "Cannot remediate yet"
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
    "required_status_checks": ["build", "test"],
}


def _operator(tmp_path: Path, trusted: list[str]):
    from darnit.config.operator import loader

    path = tmp_path / "operator" / "config.toml"
    path.parent.mkdir()
    repos = ", ".join(f'"{r}"' for r in trusted)
    path.write_text(f"schema_version = 1\n\n[trust]\nrepos = [{repos}]\n", encoding="utf-8")
    path.chmod(0o600)
    loader.set_launch_options(path, strict=False)


def _repo(tmp_path: Path) -> Path:
    """A checkout whose origin remote names OWN, claiming CLAIMED not applicable with a reason."""
    path = tmp_path / "repo"
    path.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main", str(path)], check=True)
    subprocess.run(["git", "remote", "add", "origin", f"https://{OWN}.git"], cwd=path, check=True)
    (path / ".project").mkdir()
    (path / ".project" / "darnit.yaml").write_text(
        f"controls:\n  {CLAIMED}:\n    status: n/a\n    reason: reported upstream\n", encoding="utf-8"
    )
    return path


def _confirm_context(repo: Path, target: str) -> set[str]:
    """Confirm every context key as a person would; returns where the records went."""
    from darnit.config.context_writes import record_value_confirmations
    from darnit.config.operator.loader import resolve_operator_config

    results = record_value_confirmations(
        str(repo), CONFIRMED_VALUES, target=target, operator=resolve_operator_config(repo).config
    )
    assert all(r.outcome == "confirmed" for r in results), [(r.key, r.reason) for r in results]
    return {r.location for r in results}


def _remediate(checkout: Path, **kwargs) -> str:
    from darnit_baseline.tools import remediate_audit_findings

    return remediate_audit_findings(local_path=str(checkout), dry_run=True, **kwargs)


@pytest.mark.integration
class TestTrustTarget:
    def test_checkout_origin_does_not_make_remediation_trusted(self, tmp_path: Path) -> None:
        _operator(tmp_path, [OWN])
        repo = _repo(tmp_path)
        assert _confirm_context(repo, OWN) == {"repository"}

        output = _remediate(repo)

        assert BLOCKED not in output
        assert REMEDIATED in output

    def test_named_trusted_repository_honors_the_claim(self, tmp_path: Path) -> None:
        _operator(tmp_path, [OWN])
        repo = _repo(tmp_path)
        _confirm_context(repo, OWN)

        output = _remediate(repo, owner=OWNER, repo=REPO)

        assert "## Would Apply" in output
        assert REMEDIATED not in output

    def test_guard_reads_operator_side_confirmations_for_the_named_repository(self, tmp_path: Path) -> None:
        _operator(tmp_path, [])
        repo = _repo(tmp_path)
        assert _confirm_context(repo, OWN) == {"operator"}

        output = _remediate(repo, owner=OWNER, repo=REPO)

        assert BLOCKED not in output
        assert REMEDIATED in output

    def test_guard_ignores_operator_side_confirmations_without_a_named_repository(self, tmp_path: Path) -> None:
        _operator(tmp_path, [])
        repo = _repo(tmp_path)
        _confirm_context(repo, OWN)

        assert BLOCKED in _remediate(repo)

    def test_host_names_the_repository(self, tmp_path: Path) -> None:
        _operator(tmp_path, [])
        repo = _repo(tmp_path)
        _confirm_context(repo, f"gitlab.example.com/{OWNER}/{REPO}")

        assert BLOCKED in _remediate(repo, owner=OWNER, repo=REPO)
        assert BLOCKED not in _remediate(repo, owner=OWNER, repo=REPO, host="gitlab.example.com")
