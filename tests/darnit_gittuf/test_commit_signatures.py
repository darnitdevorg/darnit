"""GT-02.01 commit signatures against real git repositories.

Only a good signature (``%G?`` = ``G``) counts as signed. Signatures that
this machine cannot check are ERROR, and nothing passes on zero commits.
"""

from __future__ import annotations

import base64
import os
import subprocess
from pathlib import Path
from types import SimpleNamespace

import pytest
from darnit_gittuf import handlers
from darnit_gittuf.handlers import gittuf_commits_signed_handler

from darnit.sieve.handler_registry import HandlerContext, HandlerResultStatus

_IDENTITY = {
    "GIT_AUTHOR_NAME": "Test",
    "GIT_AUTHOR_EMAIL": "test@example.com",
    "GIT_COMMITTER_NAME": "Test",
    "GIT_COMMITTER_EMAIL": "test@example.com",
}


@pytest.fixture(autouse=True)
def _isolated_git(tmp_path_factory: pytest.TempPathFactory, monkeypatch: pytest.MonkeyPatch) -> None:
    """Keep the developer's git and gpg configuration out of signature verification."""
    home = tmp_path_factory.mktemp("home")
    gnupg = home / "gnupg"
    gnupg.mkdir(mode=0o700)
    global_config = home / "gitconfig"
    global_config.write_text("")
    monkeypatch.setenv("HOME", str(home))
    monkeypatch.setenv("GNUPGHOME", str(gnupg))
    monkeypatch.setenv("GIT_CONFIG_GLOBAL", str(global_config))
    monkeypatch.setenv("GIT_CONFIG_NOSYSTEM", "1")
    for name, value in _IDENTITY.items():
        monkeypatch.setenv(name, value)


def _git(repo: Path, *args: str, stdin: str | None = None) -> str:
    result = subprocess.run(["git", *args], cwd=repo, input=stdin, capture_output=True, text=True, check=True)
    return result.stdout.strip()


def _repo(tmp_path: Path, unsigned_commits: int = 1) -> Path:
    repo = tmp_path / "repo"
    repo.mkdir()
    _git(repo, "init", "-q", "-b", "main")
    for n in range(unsigned_commits):
        _git(repo, "commit", "-q", "--allow-empty", "-m", f"unsigned {n}")
    return repo


def _crc24(data: bytes) -> int:
    crc = 0xB704CE
    for byte in data:
        crc ^= byte << 16
        for _ in range(8):
            crc <<= 1
            if crc & 0x1000000:
                crc ^= 0x1864CFB
    return crc & 0xFFFFFF


def _random_openpgp_signature() -> str:
    """An armored v4 OpenPGP signature packet whose issuer and signature value are random bytes."""
    hashed = bytes([5, 2]) + (1_700_000_000).to_bytes(4, "big")  # signature creation time
    unhashed = bytes([9, 16]) + os.urandom(8)  # issuer key id
    value = os.urandom(256)
    value = bytes([value[0] | 0x80]) + value[1:]
    body = (
        bytes([4, 0x00, 1, 8])  # v4, binary document, RSA, SHA-256
        + len(hashed).to_bytes(2, "big")
        + hashed
        + len(unhashed).to_bytes(2, "big")
        + unhashed
        + os.urandom(2)
        + (2048).to_bytes(2, "big")
        + value
    )
    length = len(body) - 192
    packet = bytes([0xC2, (length >> 8) + 192, length & 0xFF]) + body
    armored = base64.b64encode(packet).decode()
    checksum = base64.b64encode(_crc24(packet).to_bytes(3, "big")).decode()
    return "\n".join(
        [
            "-----BEGIN PGP SIGNATURE-----",
            "",
            *(armored[i : i + 64] for i in range(0, len(armored), 64)),
            f"={checksum}",
            "-----END PGP SIGNATURE-----",
        ]
    )


def _commit_with_signature(repo: Path, signature: str) -> str:
    """Write a commit object carrying ``signature`` in its gpgsig header and move HEAD to it.

    The commit's parent is HEAD; in a repository with no commits it is a root commit.
    """
    tree = _git(repo, "write-tree")
    head = subprocess.run(["git", "rev-parse", "--verify", "--quiet", "HEAD"], cwd=repo, capture_output=True, text=True)
    parent = f"parent {head.stdout.strip()}\n" if head.returncode == 0 else ""
    header = "gpgsig " + "\n ".join(signature.splitlines())
    commit = (
        f"tree {tree}\n{parent}"
        "author Test <test@example.com> 1700000000 +0000\n"
        "committer Test <test@example.com> 1700000000 +0000\n"
        f"{header}\n\nfabricated signature\n"
    )
    sha = _git(repo, "hash-object", "-t", "commit", "-w", "--stdin", stdin=commit)
    _git(repo, "update-ref", "HEAD", sha)
    return sha


def _ssh_signed_commit(repo: Path, tmp_path: Path) -> Path:
    """Sign a commit with a fresh SSH key; return the public key path."""
    key = tmp_path / "id_ed25519"
    subprocess.run(["ssh-keygen", "-q", "-t", "ed25519", "-N", "", "-f", str(key)], check=True)
    _git(
        repo, "-c", "gpg.format=ssh", "-c", f"user.signingkey={key}", "commit", "-q", "-S", "--allow-empty", "-m", "ssh"
    )
    return key.with_suffix(".pub")


def _ctx(repo: Path) -> HandlerContext:
    return HandlerContext(
        local_path=str(repo),
        owner="testorg",
        repo="testrepo",
        default_branch="main",
        control_id="GT-02.01",
        project_context={},
        gathered_evidence={},
        dependency_results={},
    )


def _status_shim(monkeypatch: pytest.MonkeyPatch, status: str) -> None:
    """Report every commit with ``status``: git cannot easily produce R, Y or X locally."""
    real_run = subprocess.run

    def run(args, **kwargs):
        result = real_run(args, **kwargs)
        if list(args[:2]) == ["git", "log"]:
            lines = []
            for line in result.stdout.splitlines():
                if "\x1f" in line:
                    sha, _status, key = line.split("\x1f")
                    lines.append("\x1f".join([sha, status, key or "0123456789ABCDEF"]))
                else:  # the alternating %G?/%GK lines read before this fix
                    lines.append(status if line == "N" else line)
            result = subprocess.CompletedProcess(args, result.returncode, "\n".join(lines) + "\n", result.stderr)
        return result

    monkeypatch.setattr(handlers, "subprocess", SimpleNamespace(run=run, TimeoutExpired=subprocess.TimeoutExpired))


class TestHandlerOnRealGit:
    def test_unsigned_commits_fail(self, tmp_path: Path) -> None:
        result = gittuf_commits_signed_handler({}, _ctx(_repo(tmp_path, unsigned_commits=3)))

        assert result.status == HandlerResultStatus.FAIL
        assert result.evidence["unsigned"] == 3

    def test_random_bytes_signature_is_an_error_never_a_pass(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, unsigned_commits=0)
        _commit_with_signature(repo, _random_openpgp_signature())

        result = gittuf_commits_signed_handler({}, _ctx(repo))

        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "evaluation"

    def test_ssh_signature_without_allowed_signers_is_an_error(self, tmp_path: Path) -> None:
        """git reports N for an SSH signature it is not configured to check; the commit is signed."""
        repo = _repo(tmp_path, unsigned_commits=0)
        _ssh_signed_commit(repo, tmp_path)

        result = gittuf_commits_signed_handler({}, _ctx(repo))

        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "evaluation"
        assert "allowedSignersFile" in result.message

    def test_ssh_unknown_validity_is_not_a_pass(self, tmp_path: Path) -> None:
        """git reports U when gpg.ssh.allowedSignersFile is set, even to a path that does not exist."""
        repo = _repo(tmp_path, unsigned_commits=0)
        _ssh_signed_commit(repo, tmp_path)
        _git(repo, "config", "gpg.ssh.allowedSignersFile", str(tmp_path / "missing"))

        result = gittuf_commits_signed_handler({}, _ctx(repo))

        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.evidence["statuses"] == {"U": 1}

    def test_ssh_good_signature_passes(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, unsigned_commits=0)
        public_key = _ssh_signed_commit(repo, tmp_path)
        allowed = tmp_path / "allowed_signers"
        allowed.write_text(f"test@example.com {public_key.read_text()}")
        _git(repo, "config", "gpg.ssh.allowedSignersFile", str(allowed))

        result = gittuf_commits_signed_handler({}, _ctx(repo))

        assert result.status == HandlerResultStatus.PASS
        assert result.evidence["signed"] == 1

    def test_unsigned_commit_outweighs_an_unverifiable_one(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, unsigned_commits=1)
        _commit_with_signature(repo, _random_openpgp_signature())

        result = gittuf_commits_signed_handler({}, _ctx(repo))

        assert result.status == HandlerResultStatus.FAIL

    def test_no_commits_is_inconclusive(self, tmp_path: Path) -> None:
        result = gittuf_commits_signed_handler({}, _ctx(_repo(tmp_path, unsigned_commits=0)))

        assert result.status == HandlerResultStatus.INCONCLUSIVE

    @pytest.mark.parametrize("status", ["B", "R", "Y", "X"])
    def test_bad_revoked_or_expired_fails(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str) -> None:
        repo = _repo(tmp_path, unsigned_commits=2)
        _status_shim(monkeypatch, status)

        result = gittuf_commits_signed_handler({}, _ctx(repo))

        assert result.status == HandlerResultStatus.FAIL
        assert result.evidence["statuses"] == {status: 2}
        assert "All 0" not in result.message

    def test_unrecognized_status_is_an_error(self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
        repo = _repo(tmp_path, unsigned_commits=1)
        _status_shim(monkeypatch, "Q")

        result = gittuf_commits_signed_handler({}, _ctx(repo))

        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "evaluation"


class TestThroughAudit:
    """GT-02.01 through the canonical audit pipeline."""

    def _gt_02_01(self, repo: Path) -> dict:
        from darnit_gittuf.implementation import GittufImplementation

        from darnit.config import load_controls_from_framework
        from darnit.config.merger import load_framework_config
        from darnit.tools.audit import run_sieve_audit

        impl = GittufImplementation()
        controls = [
            c
            for c in load_controls_from_framework(load_framework_config(impl.get_framework_config_path()))
            if c.control_id == "GT-02.01"
        ]
        results, _ = run_sieve_audit(
            "testorg",
            "testrepo",
            str(repo),
            "main",
            controls=controls,
            evaluate_claims=False,
            stop_on_llm=False,
            framework_name="gittuf",
            write_cache=False,
        )
        (result,) = results
        return result

    def test_unsigned_commits_fail(self, tmp_path: Path) -> None:
        result = self._gt_02_01(_repo(tmp_path, unsigned_commits=2))

        assert result["status"] == "FAIL"

    def test_random_bytes_signature_is_an_error(self, tmp_path: Path) -> None:
        repo = _repo(tmp_path, unsigned_commits=0)
        _commit_with_signature(repo, _random_openpgp_signature())

        result = self._gt_02_01(repo)

        assert result["status"] == "ERROR"
        assert result["error"]["class"] == "evaluation"

    @pytest.mark.parametrize("status", ["R", "Y"])
    def test_revoked_or_expired_key_history_fails(
        self, tmp_path: Path, monkeypatch: pytest.MonkeyPatch, status: str
    ) -> None:
        repo = _repo(tmp_path, unsigned_commits=2)
        _status_shim(monkeypatch, status)

        result = self._gt_02_01(repo)

        assert result["status"] == "FAIL"
