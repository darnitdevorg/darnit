"""Lint enforcement tests.

These tests ensure code quality by running linters and failing if issues are found.
This prevents regression of unused imports, variables, and other lint issues.
"""

import subprocess
import sys
from pathlib import Path

import pytest

# Get the project root directory
PROJECT_ROOT = Path(__file__).parent.parent


def _run_ruff(rule: str) -> subprocess.CompletedProcess[str]:
    """Run ruff check with the specified rule."""
    return subprocess.run(
        [
            sys.executable,
            "-m",
            "ruff",
            "check",
            "--select",
            rule,
            str(PROJECT_ROOT / "packages"),
        ],
        capture_output=True,
        text=True,
    )


def _check_ruff_available() -> bool:
    """Check if ruff is available."""
    try:
        result = subprocess.run(
            [sys.executable, "-m", "ruff", "--version"],
            capture_output=True,
            text=True,
        )
        return result.returncode == 0
    except Exception:
        return False


# Skip all tests in this module if ruff is not available
pytestmark = pytest.mark.skipif(
    not _check_ruff_available(),
    reason="ruff is not installed"
)


class TestRuffLint:
    """Tests that enforce ruff lint rules."""

    @pytest.mark.unit
    def test_no_unused_imports(self) -> None:
        """Ensure no unused imports (F401) exist in the codebase."""
        result = _run_ruff("F401")

        if result.returncode != 0:
            output = result.stdout or result.stderr
            pytest.fail(
                f"Unused imports found (F401). Run 'ruff check --select F401 --fix packages/' to fix.\n\n"
                f"{output}"
            )

    @pytest.mark.unit
    def test_no_unused_variables(self) -> None:
        """Ensure no unused variables (F841) exist in the codebase."""
        result = _run_ruff("F841")

        if result.returncode != 0:
            output = result.stdout or result.stderr
            pytest.fail(
                f"Unused variables found (F841). Review and remove unused assignments.\n\n"
                f"{output}"
            )

    @pytest.mark.unit
    def test_no_undefined_names(self) -> None:
        """Ensure no undefined names (F821) exist in the codebase."""
        result = _run_ruff("F821")

        if result.returncode != 0:
            output = result.stdout or result.stderr
            pytest.fail(
                f"Undefined names found (F821). Fix missing imports or typos.\n\n"
                f"{output}"
            )

    @pytest.mark.unit
    def test_no_redefined_unused(self) -> None:
        """Ensure no redefined-while-unused (F811) issues exist."""
        result = _run_ruff("F811")

        if result.returncode != 0:
            output = result.stdout or result.stderr
            pytest.fail(
                f"Redefined while unused found (F811). Remove duplicate definitions.\n\n"
                f"{output}"
            )
