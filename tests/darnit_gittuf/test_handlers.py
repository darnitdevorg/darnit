"""Tests for Gittuf sieve handlers."""

from pathlib import Path
from unittest.mock import MagicMock, patch

from darnit_gittuf.handlers import (
    gittuf_commits_signed_handler,
    gittuf_verify_policy_handler,
)

from darnit.sieve.handler_registry import HandlerContext, HandlerResultStatus


def make_ctx(tmp_path: Path) -> HandlerContext:
    """Helper to build a minimal HandlerContext."""
    return HandlerContext(
        local_path=str(tmp_path),
        owner="testorg",
        repo="testrepo",
        default_branch="main",
        control_id="GT-01.02",
        project_context={},
        gathered_evidence={},
        shared_cache={},
        dependency_results={},
    )


class TestGittufVerifyPolicyHandler:
    """Tests for gittuf_verify_policy_handler()."""

    def test_pass_when_gittuf_exits_zero(self, tmp_path: Path) -> None:
        ctx = make_ctx(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = "Policy verified"
        mock_result.stderr = ""
        with patch("subprocess.run", return_value=mock_result):
            result = gittuf_verify_policy_handler({}, ctx)
        assert result.status == HandlerResultStatus.PASS

    def test_fail_when_gittuf_exits_nonzero(self, tmp_path: Path) -> None:
        ctx = make_ctx(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 1
        mock_result.stdout = ""
        mock_result.stderr = "policy violation"
        with patch("subprocess.run", return_value=mock_result):
            result = gittuf_verify_policy_handler({}, ctx)
        assert result.status == HandlerResultStatus.FAIL
        assert "policy violation" in result.message

    def test_inconclusive_when_gittuf_not_installed(self, tmp_path: Path) -> None:
        ctx = make_ctx(tmp_path)
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = gittuf_verify_policy_handler({}, ctx)
        assert result.status == HandlerResultStatus.INCONCLUSIVE
        assert result.confidence == 0.0

    def test_inconclusive_on_timeout(self, tmp_path: Path) -> None:
        import subprocess

        ctx = make_ctx(tmp_path)
        with patch("subprocess.run", side_effect=subprocess.TimeoutExpired("gittuf", 30)):
            result = gittuf_verify_policy_handler({}, ctx)
        assert result.status == HandlerResultStatus.INCONCLUSIVE


class TestGittufCommitsSignedHandler:
    """Tests for gittuf_commits_signed_handler()."""

    def test_pass_when_all_commits_signed(self, tmp_path: Path) -> None:
        ctx = make_ctx(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 0
        # Format is %G?%n%GK — status line then key line alternating
        mock_result.stdout = "G\nabc123\nG\nabc124\nG\nabc125\n"
        with patch("subprocess.run", return_value=mock_result):
            result = gittuf_commits_signed_handler({}, ctx)
        assert result.status == HandlerResultStatus.PASS
        assert result.evidence["signed"] == 3
        assert result.evidence["unsigned"] == 0

    def test_fail_when_some_commits_unsigned(self, tmp_path: Path) -> None:
        ctx = make_ctx(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 0
        # G = signed, N = unsigned, empty key for unsigned commits
        mock_result.stdout = "G\nabc123\nN\n\nG\nabc125\n"
        with patch("subprocess.run", return_value=mock_result):
            result = gittuf_commits_signed_handler({}, ctx)
        assert result.status == HandlerResultStatus.FAIL
        assert result.evidence["unsigned"] == 1

    def test_fail_when_bad_signature(self, tmp_path: Path) -> None:
        ctx = make_ctx(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 0
        # B = bad signature
        mock_result.stdout = "G\nabc123\nB\nabc124\nG\nabc125\n"
        with patch("subprocess.run", return_value=mock_result):
            result = gittuf_commits_signed_handler({}, ctx)
        assert result.status == HandlerResultStatus.FAIL
        assert "BAD" in result.message

    def test_inconclusive_when_no_commits(self, tmp_path: Path) -> None:
        ctx = make_ctx(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 0
        mock_result.stdout = ""
        with patch("subprocess.run", return_value=mock_result):
            result = gittuf_commits_signed_handler({}, ctx)
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    def test_inconclusive_when_git_not_found(self, tmp_path: Path) -> None:
        ctx = make_ctx(tmp_path)
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = gittuf_commits_signed_handler({}, ctx)
        assert result.status == HandlerResultStatus.INCONCLUSIVE

    def test_handler_ignores_planted_gpg_program(self, tmp_path: Path) -> None:
        """Planted gpg.program in .git/config must not execute during signature check (issue #617)."""
        import subprocess

        repo = tmp_path / "repo"
        repo.mkdir()
        subprocess.run(["git", "init"], cwd=repo, capture_output=True, check=True)
        subprocess.run(["git", "config", "user.name", "Tester"], cwd=repo, check=True)
        subprocess.run(["git", "config", "user.email", "test@example.com"], cwd=repo, check=True)

        # Create a signed commit object so git log --format=%G? triggers signature verification
        tree = subprocess.run(
            ["git", "write-tree"],
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        commit_content = (
            f"tree {tree}\n"
            "author Tester <test@example.com> 1700000000 +0000\n"
            "committer Tester <test@example.com> 1700000000 +0000\n"
            "gpgsig -----BEGIN PGP SIGNATURE-----\n"
            " Version: GnuPG v2\n"
            " \n"
            " iQEcBAABCAAGBQJk...\n"
            " =fake\n"
            " -----END PGP SIGNATURE-----\n"
            "\n"
            "signed init\n"
        )
        commit_sha = subprocess.run(
            ["git", "hash-object", "-t", "commit", "-w", "--stdin"],
            input=commit_content,
            cwd=repo,
            capture_output=True,
            text=True,
            check=True,
        ).stdout.strip()
        subprocess.run(["git", "update-ref", "refs/heads/main", commit_sha], cwd=repo, check=True)

        witness = repo / ".git" / "gpg_witness.txt"
        evil_gpg = repo / ".git" / "evil_gpg.sh"
        evil_gpg.write_text(f"#!/bin/sh\necho evil > {witness}\nexit 1\n")
        evil_gpg.chmod(0o755)

        subprocess.run(["git", "config", "gpg.program", str(evil_gpg)], cwd=repo, check=True)

        ctx = make_ctx(repo)
        result = gittuf_commits_signed_handler({}, ctx)
        assert not witness.exists(), "Planted gpg.program must not execute!"
        assert result.status in (HandlerResultStatus.PASS, HandlerResultStatus.FAIL)
