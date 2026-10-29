# SPDX-License-Identifier: Apache-2.0
"""Generated two-commit repositories exercise minimal gittuf onboarding."""

import base64
import json
import os
import shutil
import subprocess
import sys
from pathlib import Path

import pytest
from darnit_gittuf.setup import POLICY, ROOT_KEY, RSL, SetupError, initialize, references

from darnit.config.merger import load_framework_by_name
from darnit.config.operator import loader
from darnit.remediation.executor import RemediationExecutor
from darnit.server.tools.project_data import confirm_project_data_impl
from darnit.sieve.builtin_handlers import exec_handler
from darnit.sieve.handler_registry import HandlerContext, HandlerResultStatus


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()


@pytest.fixture
def generated_repo(tmp_path, monkeypatch):
    for tool in ("git", "ssh-keygen"):
        if not shutil.which(tool):
            pytest.skip(f"{tool} is required")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    monkeypatch.setenv("PATH", str(Path(sys.executable).parent) + os.pathsep + os.environ["PATH"])
    for name in list(os.environ):
        if name.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")) or name in (
            "GIT_CONFIG_COUNT",
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "GIT_COMMON_DIR",
        ):
            monkeypatch.delenv(name)
    # Both the test and the exec child use this isolated operator configuration.
    config_root = tmp_path / "config"
    monkeypatch.setenv("XDG_CONFIG_HOME", str(config_root))
    operator = config_root / "darnit" / "config.toml"
    operator.parent.mkdir(parents=True)
    operator.write_text('schema_version = 1\n[trust]\nrepos = ["github.com/fixture/onboarding"]\n')
    loader.set_launch_options(operator, strict=False)
    repo = tmp_path / "generated repo"
    repo.mkdir()
    git(repo, "init", "-q", "-b", "main")
    git(repo, "config", "user.name", "Fixture Maintainer")
    git(repo, "config", "user.email", "fixture@example.invalid")
    git(repo, "config", "commit.gpgsign", "false")
    for i in range(2):
        (repo / "README.md").write_text(f"Generated revision {i}\n")
        git(repo, "add", "README.md")
        git(repo, "commit", "-q", "-m", f"Revision {i}")
    key = tmp_path / "test key"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    return repo, key


@pytest.fixture
def real_gittuf():
    if not shutil.which("gittuf"):
        pytest.skip("Install gittuf on PATH to run the actual initialization tests")


def confirm(repo, key):
    result = confirm_project_data_impl(
        str(repo), owner="fixture", repo="onboarding", framework_name="gittuf", **{ROOT_KEY: str(key)}
    )
    assert "confirmed" in result, result


def test_missing_gittuf(generated_repo, monkeypatch):
    repo, _key = generated_repo
    which = shutil.which
    monkeypatch.setattr(shutil, "which", lambda name: None if name == "gittuf" else which(name))
    with pytest.raises(SetupError, match="gittuf is not installed"):
        initialize(str(repo), "fixture", "onboarding")
    assert not references(str(repo))


@pytest.mark.parametrize("choice", ["unconfirmed", "missing", "public"])
def test_no_usable_signing_key(generated_repo, real_gittuf, choice):
    repo, key = generated_repo
    if choice == "unconfirmed":
        (repo / ".project").mkdir()
        (repo / ".project" / "darnit.yaml").write_text(f"context:\n  {ROOT_KEY}: {key}\n")
    else:
        confirm(repo, key.with_suffix(".pub") if choice == "public" else key.parent / "missing")
    with pytest.raises(SetupError, match="confirm_project_data|existing SSH signing key"):
        initialize(str(repo), "fixture", "onboarding")
    assert not references(str(repo))


@pytest.mark.parametrize("ref", [POLICY, "refs/gittuf/policy-staging"])
def test_existing_metadata_is_preserved(generated_repo, real_gittuf, ref):
    repo, key = generated_repo
    confirm(repo, key)
    git(repo, "update-ref", ref, "HEAD")
    before = references(str(repo))
    with pytest.raises(SetupError, match="already exist"):
        initialize(str(repo), "fixture", "onboarding")
    assert references(str(repo)) == before


def test_declared_remediation_initializes_a_real_repo(generated_repo, real_gittuf):
    repo, key = generated_repo
    confirm(repo, key)
    control = load_framework_by_name("gittuf").controls["GT-01.01"]
    check = control.passes[0].model_extra
    ctx = HandlerContext(local_path=str(repo))
    assert exec_handler(check, ctx).status == HandlerResultStatus.FAIL
    before_head = git(repo, "rev-parse", "HEAD")
    before_config = (repo / ".git" / "config").read_bytes()
    (repo / "README.md").write_text("Uncommitted user work\n")
    executor = RemediationExecutor(local_path=str(repo), owner="fixture", repo="onboarding")
    preview = executor.execute("GT-01.01", control.remediation)
    assert preview.success and not references(str(repo))
    # Reuse the framework's existing approval mechanism, without extending it.
    executor = RemediationExecutor(
        local_path=str(repo), owner="fixture", repo="onboarding", approvals=[p.digest for p in preview.plan]
    )
    result = executor.execute("GT-01.01", control.remediation, dry_run=False)
    assert result.success, result.details
    assert {POLICY, RSL} <= references(str(repo)).keys()
    assert exec_handler(check, ctx).status == HandlerResultStatus.PASS
    envelope = json.loads(git(repo, "show", f"{POLICY}:metadata/root.json"))
    root = json.loads(base64.b64decode(envelope["payload"]))
    fingerprint = subprocess.check_output(["ssh-keygen", "-l", "-E", "sha256", "-f", str(key)], text=True).split()[1]
    assert root["roles"]["root"]["principalIDs"] == [fingerprint]
    assert "targets" not in root["roles"]
    assert git(repo, "rev-parse", "HEAD") == before_head
    assert (repo / ".git" / "config").read_bytes() == before_config
    assert (repo / "README.md").read_text() == "Uncommitted user work\n"
