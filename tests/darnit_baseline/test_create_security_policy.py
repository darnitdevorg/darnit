"""``create_security_policy`` writes through the executor and the run manifest (feature 043 T055; framework-design 15.8).

It keeps its explicit-create semantics (no preview step), never overwrites an
existing SECURITY.md, and reports a structured ``RemediationRun`` with the
control's outcome (15.4).
"""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path

import pytest

from darnit.config.loader import clear_config_cache
from darnit.remediation import manifest
from darnit_baseline.tools import create_security_policy

OWNER, REPO = "test-owner", "test-repo"
TARGET = f"github.com/{OWNER}/{REPO}"
CHANGED = {"fixed", "changed_not_passing", "changed_not_verified"}


@pytest.fixture(autouse=True)
def clear_cache():
    clear_config_cache()
    yield
    clear_config_cache()


@pytest.fixture
def repo(tmp_path: Path) -> Path:
    path = tmp_path / "repo"
    path.mkdir()
    (path / "README.md").write_text("# Project\n", encoding="utf-8")
    for args in (["init", "-q"], ["add", "-A"], ["commit", "-q", "--no-gpg-sign", "-m", "init"]):
        subprocess.run(["git", "-c", "user.name=t", "-c", "user.email=t@example.com", *args], cwd=path, check=True)
    return path


def _confirm_security_contact(repo: Path) -> None:
    from darnit.config.context_keys import value_digest
    from darnit.config.operator.schema import OperatorConfig
    from darnit.trust.confirmations import record_context_confirmation

    value = "security@test-project.dev"
    operator = OperatorConfig.model_validate({"schema_version": 1})
    record_context_confirmation(
        TARGET, "security_contact", value_digest("security_contact", value), value, None, operator, checkout=repo
    )


def _run_block(output: str) -> dict:
    blocks = re.findall(r"```json\n(.*?)\n```", output, re.DOTALL)
    assert blocks, output
    return json.loads(blocks[-1])


@pytest.mark.integration
def test_creates_security_md_through_the_manifest(repo: Path) -> None:
    _confirm_security_contact(repo)

    output = create_security_policy(owner=OWNER, repo=REPO, local_path=str(repo))

    run = _run_block(output)
    assert run["mode"] == "apply"
    [outcome] = run["outcomes"]
    assert outcome["control_id"] == "OSPS-VM-02.01"
    assert outcome["kind"] in CHANGED
    assert "SECURITY.md" in [c["path"] for c in outcome["file_changes"] if c["action"] == "create"]
    assert (repo / "SECURITY.md").is_file()
    recorded = manifest.load_run(TARGET, run["run_id"], checkout=repo)
    assert recorded is not None
    assert "SECURITY.md" in [f.path for f in recorded.files]
    assert run["run_id"] in output.split("```json")[0]
    assert output.split("```json")[0].isascii()


@pytest.mark.integration
def test_never_overwrites_an_existing_security_md(repo: Path) -> None:
    _confirm_security_contact(repo)
    existing = "# Our own policy\n"
    (repo / "SECURITY.md").write_text(existing, encoding="utf-8")

    output = create_security_policy(owner=OWNER, repo=REPO, local_path=str(repo))

    assert (repo / "SECURITY.md").read_text(encoding="utf-8") == existing
    [outcome] = _run_block(output)["outcomes"]
    assert outcome["kind"] == "unchanged"
    assert "already_exists" in outcome["reason"]
    assert "Created" not in output
    assert manifest.load_run(TARGET, checkout=repo) is None, "nothing was written, so no run manifest"


@pytest.mark.integration
def test_unconfirmed_context_writes_nothing(repo: Path) -> None:
    output = create_security_policy(owner=OWNER, repo=REPO, local_path=str(repo))

    assert not (repo / "SECURITY.md").exists()
    [outcome] = _run_block(output)["outcomes"]
    assert outcome["kind"] == "needs_confirmation"
    assert "security_contact" in outcome["reason"]
