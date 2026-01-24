"""Lint enforcement tests.

These tests ensure code quality by running linters and failing if issues are found.
This prevents regression of unused imports, variables, and other lint issues.
"""

import subprocess
import sys

import pytest


class TestRuffLint:
    """Tests that enforce ruff lint rules."""

    @pytest.mark.unit
    def test_no_unused_imports(self) -> None:
        """Ensure no unused imports (F401) exist in the codebase."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--select",
                "F401",
                "packages/",
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            pytest.fail(
                f"Unused imports found (F401). Run 'ruff check --select F401 --fix packages/' to fix.\n\n"
                f"{result.stdout}"
            )

    @pytest.mark.unit
    def test_no_unused_variables(self) -> None:
        """Ensure no unused variables (F841) exist in the codebase."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--select",
                "F841",
                "packages/",
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            pytest.fail(
                f"Unused variables found (F841). Review and remove unused assignments.\n\n"
                f"{result.stdout}"
            )

    @pytest.mark.unit
    def test_no_undefined_names(self) -> None:
        """Ensure no undefined names (F821) exist in the codebase."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--select",
                "F821",
                "packages/",
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            pytest.fail(
                f"Undefined names found (F821). Fix missing imports or typos.\n\n"
                f"{result.stdout}"
            )

    @pytest.mark.unit
    def test_no_redefined_unused(self) -> None:
        """Ensure no redefined-while-unused (F811) issues exist."""
        result = subprocess.run(
            [
                sys.executable,
                "-m",
                "ruff",
                "check",
                "--select",
                "F811",
                "packages/",
            ],
            capture_output=True,
            text=True,
        )

        if result.returncode != 0:
            pytest.fail(
                f"Redefined while unused found (F811). Remove duplicate definitions.\n\n"
                f"{result.stdout}"
            )
