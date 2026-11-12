# SPDX-License-Identifier: Apache-2.0
"""Generated two-commit repositories exercise minimal gittuf onboarding."""

import base64
import json
import os
import shutil
import subprocess
import time
import venv

import pytest
from darnit_gittuf.handlers import gittuf_initialize_handler
from darnit_gittuf.implementation import GittufImplementation
from darnit_gittuf.setup import POLICY, ROOT_KEY, RSL, SetupError, initialize, references

from darnit.config import load_controls_from_framework
from darnit.config.merger import load_framework_by_name
from darnit.config.operator import loader
from darnit.remediation.executor import RemediationExecutor
from darnit.server.tools.project_data import confirm_project_data_impl
from darnit.sieve.builtin_handlers import exec_handler
from darnit.sieve.handler_registry import HandlerContext, HandlerResultStatus
from darnit.tools.audit import run_sieve_audit


def git(repo, *args):
    return subprocess.run(["git", *args], cwd=repo, text=True, capture_output=True, check=True).stdout.strip()


@pytest.fixture
def generated_repo(tmp_path, monkeypatch):
    for tool in ("git", "ssh-keygen"):
        if not shutil.which(tool):
            pytest.skip(f"{tool} is required")
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", os.devnull)
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name in list(os.environ):
        if name.startswith(("GIT_CONFIG_KEY_", "GIT_CONFIG_VALUE_")) or name in (
            "GIT_CONFIG_COUNT",
            "GIT_DIR",
            "GIT_WORK_TREE",
            "GIT_INDEX_FILE",
            "GIT_COMMON_DIR",
        ):
            monkeypatch.delenv(name)
    # Use an isolated operator configuration for this repository.
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
    result = gittuf_initialize_handler({}, HandlerContext(local_path=str(repo), owner="fixture", repo="onboarding"))
    assert result.status == HandlerResultStatus.ERROR
    assert "gittuf is not installed" in result.message
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


def apply_setup(repo, control):
    GittufImplementation().register_handlers()
    executor = RemediationExecutor(local_path=str(repo), owner="fixture", repo="onboarding")
    preview = executor.execute("GT-01.01", control.remediation)
    assert preview.success and not references(str(repo)), preview.details
    # Reuse the framework's existing approval mechanism, without extending it.
    executor = RemediationExecutor(
        local_path=str(repo), owner="fixture", repo="onboarding", approvals=[p.digest for p in preview.plan]
    )
    result = executor.execute("GT-01.01", control.remediation, dry_run=False)
    assert result.success, result.details


def test_declared_remediation_initializes_a_real_repo(generated_repo, real_gittuf, tmp_path, monkeypatch):
    # An isolated tool install need not share the Python interpreter on PATH.
    unrelated_python = tmp_path / "unrelated-python"
    venv.EnvBuilder(with_pip=False).create(unrelated_python)
    monkeypatch.setenv("PATH", str(unrelated_python / "bin") + os.pathsep + os.environ["PATH"])
    repo, key = generated_repo
    confirm(repo, key)
    control = load_framework_by_name("gittuf").controls["GT-01.01"]
    check = control.passes[0].model_extra
    ctx = HandlerContext(local_path=str(repo))
    assert exec_handler(check, ctx).status == HandlerResultStatus.FAIL
    before_head = git(repo, "rev-parse", "HEAD")
    before_config = (repo / ".git" / "config").read_bytes()
    (repo / "README.md").write_text("Uncommitted user work\n")
    apply_setup(repo, control)
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


def test_locked_key_fails_fast_without_changing_refs(generated_repo, real_gittuf, monkeypatch):
    repo, key = generated_repo
    subprocess.run(["ssh-keygen", "-p", "-P", "", "-N", "test-passphrase", "-f", str(key)], check=True)
    confirm(repo, key)
    monkeypatch.delenv("SSH_AUTH_SOCK", raising=False)
    monkeypatch.setenv("SSH_ASKPASS_REQUIRE", "force")
    monkeypatch.setenv("SSH_ASKPASS", shutil.which("false"))
    start = time.monotonic()
    result = gittuf_initialize_handler({}, HandlerContext(local_path=str(repo), owner="fixture", repo="onboarding"))
    assert time.monotonic() - start < 10
    assert result.status == HandlerResultStatus.ERROR
    assert "ssh-agent" in result.message and "passphrase" in result.message
    assert not references(str(repo))


def test_passphrase_key_unlocked_in_agent_initializes(generated_repo, real_gittuf, monkeypatch):
    repo, key = generated_repo
    # Load the disposable key, then encrypt the file. The agent alone can sign.
    agent = subprocess.check_output(["ssh-agent", "-s"], text=True)
    for name in ("SSH_AUTH_SOCK", "SSH_AGENT_PID"):
        monkeypatch.setenv(name, agent.split(f"{name}=", 1)[1].split(";", 1)[0])
    try:
        subprocess.run(["ssh-add", str(key)], check=True, capture_output=True)
        subprocess.run(["ssh-keygen", "-p", "-P", "", "-N", "test-passphrase", "-f", str(key)], check=True)
        confirm(repo, key)
        result = gittuf_initialize_handler({}, HandlerContext(local_path=str(repo), owner="fixture", repo="onboarding"))
        assert result.status == HandlerResultStatus.PASS, result.message
        assert {POLICY, RSL} <= references(str(repo)).keys()
    finally:
        subprocess.run(["ssh-agent", "-k"], check=True, capture_output=True)


def test_audit_rejects_unauthorized_main_update(generated_repo, real_gittuf):
    repo, key = generated_repo
    confirm(repo, key)
    framework = load_framework_by_name("gittuf")
    apply_setup(repo, framework.controls["GT-01.01"])
    controls = [c for c in load_controls_from_framework(framework) if c.control_id in ("GT-01.01", "GT-01.02")]

    def audit():
        results, _ = run_sieve_audit(
            "fixture",
            "onboarding",
            str(repo),
            "main",
            controls=controls,
            evaluate_claims=False,
            stop_on_llm=False,
            framework_name="gittuf",
            write_cache=False,
        )
        return {r["id"]: r for r in results}

    def gittuf(*args):
        subprocess.run(["gittuf", *args], cwd=repo, check=True, capture_output=True, text=True, timeout=15)

    # Setup creates trust metadata, but does not record or protect main.
    initial = audit()
    assert initial["GT-01.01"]["status"] == "PASS"
    assert initial["GT-01.02"]["status"] == "FAIL"
    assert "unable to find RSL entry" in initial["GT-01.02"]["evidence"]["gittuf_error"]

    # This policy belongs to the test maintainer, not to the remediation.
    git(repo, "config", "gpg.format", "ssh")
    git(repo, "config", "user.signingkey", str(key))
    public = str(key.with_suffix(".pub"))
    fingerprint = subprocess.check_output(["ssh-keygen", "-lf", public], text=True).split()[1]
    gittuf("trust", "add-policy-key", "-k", str(key), "--policy-key", public)
    gittuf("policy", "init", "-k", str(key))
    gittuf("policy", "add-key", "-k", str(key), "--public-key", public)
    gittuf(
        "policy",
        "add-rule",
        "-k",
        str(key),
        "--rule-name",
        "protect-main",
        "--rule-pattern",
        "git:refs/heads/main",
        "--authorize",
        fingerprint,
    )
    gittuf("policy", "stage", "--local-only")
    gittuf("policy", "apply", "--local-only")
    gittuf("rsl", "record", "main", "--local-only")
    assert {k: r["status"] for k, r in audit().items()} == {"GT-01.01": "PASS", "GT-01.02": "PASS"}

    # Record an unsigned main commit with a valid but unauthorized RSL signing key.
    other = key.parent / "unauthorized"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(other)], check=True)
    git(repo, "config", "user.signingkey", str(other))
    git(repo, "commit", "--allow-empty", "-qm", "unauthorized update")
    gittuf("rsl", "record", "main", "--local-only")
    tampered = audit()
    assert tampered["GT-01.01"]["status"] == "PASS"
    assert tampered["GT-01.02"]["status"] == "FAIL"
    assert "gittuf policy verification failed" in tampered["GT-01.02"]["evidence"]["gittuf_error"]
