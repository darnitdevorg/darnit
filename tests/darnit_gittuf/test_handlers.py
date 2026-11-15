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

    def test_error_when_gittuf_not_installed(self, tmp_path: Path) -> None:
        ctx = make_ctx(tmp_path)
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = gittuf_verify_policy_handler({}, ctx)
        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "missing_tool"

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
        # Format is %H%x1f%G?%x1f%GK, one commit per line
        mock_result.stdout = "c1\x1fG\x1fabc123\nc2\x1fG\x1fabc124\nc3\x1fG\x1fabc125\n"
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
        mock_result.stdout = "c1\x1fG\x1fabc123\nc2\x1fN\x1f\nc3\x1fG\x1fabc125\n"
        with patch("subprocess.run", return_value=mock_result):
            result = gittuf_commits_signed_handler({}, ctx)
        assert result.status == HandlerResultStatus.FAIL
        assert result.evidence["unsigned"] == 1
        assert result.message == "2 of last 3 commits have a good signature: 1 unsigned"

    def test_fail_message_reports_unverifiable_and_unsigned_counts(self, tmp_path: Path) -> None:
        """When commits fail, the message reports both not-good and unverifiable counts (fixes #679)."""
        ctx = make_ctx(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 0
        # 1 signed (G), 1 unsigned (N), 2 unverifiable (E)
        mock_result.stdout = "c1\x1fG\x1fabc123\nc2\x1fN\x1f\nc3\x1fE\x1fabc124\nc4\x1fE\x1fabc125\n"
        with patch("subprocess.run", return_value=mock_result):
            result = gittuf_commits_signed_handler({}, ctx)
        assert result.status == HandlerResultStatus.FAIL
        assert result.message == (
            "1 of last 4 commits have a good signature: 1 unsigned, 2 could not be checked on this machine"
        )

    def test_fail_message_when_zero_signed_and_mix_of_n_and_e(self, tmp_path: Path) -> None:
        """Reproduce issue #679: 1 unsigned and 4 unverifiable commits report 0 signed."""
        ctx = make_ctx(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 0
        # 1 unsigned (N), 4 unverifiable (E)
        mock_result.stdout = "c1\x1fN\x1f\nc2\x1fE\x1f\nc3\x1fE\x1f\nc4\x1fE\x1f\nc5\x1fE\x1f\n"
        with patch("subprocess.run", return_value=mock_result):
            result = gittuf_commits_signed_handler({}, ctx)
        assert result.status == HandlerResultStatus.FAIL
        assert result.message == (
            "0 of last 5 commits have a good signature: 1 unsigned, 4 could not be checked on this machine"
        )

    def test_fail_when_bad_signature(self, tmp_path: Path) -> None:
        ctx = make_ctx(tmp_path)
        mock_result = MagicMock()
        mock_result.returncode = 0
        # B = bad signature
        mock_result.stdout = "c1\x1fG\x1fabc123\nc2\x1fB\x1fabc124\nc3\x1fG\x1fabc125\n"
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

    def test_error_when_git_not_found(self, tmp_path: Path) -> None:
        ctx = make_ctx(tmp_path)
        with patch("subprocess.run", side_effect=FileNotFoundError):
            result = gittuf_commits_signed_handler({}, ctx)
        assert result.status == HandlerResultStatus.ERROR
        assert result.error_class == "missing_tool"
