"""Tests for individual check functions."""

import sys
from pathlib import Path

# Add package paths for testing without installation
sys.path.insert(0, str(Path(__file__).parent.parent.parent / "darnit" / "src"))
sys.path.insert(0, str(Path(__file__).parent.parent / "src"))

from darnit.core.models import CheckStatus

from darnit_testchecks.adapters.builtin import (
    check_test_cfg_01,
    check_test_cfg_02,
    check_test_ci_01,
    check_test_ci_02,
    check_test_doc_01,
    check_test_doc_02,
    check_test_ign_01,
    check_test_lic_01,
    check_test_qa_01,
    check_test_qa_02,
    check_test_sec_01,
    check_test_sec_02,
)


class TestLevel1Checks:
    """Tests for Level 1 checks (basic project setup)."""

    def test_doc_01_passes_with_readme(self, minimal_repo: Path):
        """TEST-DOC-01 should pass when README.md exists."""
        result = check_test_doc_01(str(minimal_repo))
        assert result.status == CheckStatus.PASS
        assert "README.md" in result.message

    def test_doc_01_fails_without_readme(self, temp_repo: Path):
        """TEST-DOC-01 should fail when no README exists."""
        result = check_test_doc_01(str(temp_repo))
        assert result.status == CheckStatus.FAIL
        assert "No README" in result.message

    def test_doc_01_accepts_readme_variants(self, temp_repo: Path):
        """TEST-DOC-01 should accept README.rst, README.txt, etc."""
        (temp_repo / "README.rst").write_text("Test\n====\n")
        result = check_test_doc_01(str(temp_repo))
        assert result.status == CheckStatus.PASS

    def test_doc_02_passes_with_changelog(self, temp_repo: Path):
        """TEST-DOC-02 should pass when CHANGELOG.md exists."""
        (temp_repo / "CHANGELOG.md").write_text("# Changelog\n")
        result = check_test_doc_02(str(temp_repo))
        assert result.status == CheckStatus.PASS

    def test_doc_02_fails_without_changelog(self, temp_repo: Path):
        """TEST-DOC-02 should fail when no CHANGELOG exists."""
        result = check_test_doc_02(str(temp_repo))
        assert result.status == CheckStatus.FAIL

    def test_lic_01_passes_with_license(self, minimal_repo: Path):
        """TEST-LIC-01 should pass when LICENSE exists."""
        result = check_test_lic_01(str(minimal_repo))
        assert result.status == CheckStatus.PASS

    def test_lic_01_fails_without_license(self, temp_repo: Path):
        """TEST-LIC-01 should fail when no LICENSE exists."""
        result = check_test_lic_01(str(temp_repo))
        assert result.status == CheckStatus.FAIL

    def test_ign_01_passes_with_gitignore(self, temp_repo: Path):
        """TEST-IGN-01 should pass when .gitignore exists."""
        (temp_repo / ".gitignore").write_text("*.pyc\n")
        result = check_test_ign_01(str(temp_repo))
        assert result.status == CheckStatus.PASS

    def test_ign_01_fails_without_gitignore(self, temp_repo: Path):
        """TEST-IGN-01 should fail when no .gitignore exists."""
        result = check_test_ign_01(str(temp_repo))
        assert result.status == CheckStatus.FAIL


class TestLevel2Checks:
    """Tests for Level 2 checks (code quality)."""

    def test_qa_01_passes_without_todos(self, temp_repo: Path):
        """TEST-QA-01 should pass when no TODO comments exist."""
        (temp_repo / "app.py").write_text('def hello():\n    return "world"\n')
        result = check_test_qa_01(str(temp_repo))
        assert result.status == CheckStatus.PASS

    def test_qa_01_fails_with_todos(self, temp_repo: Path):
        """TEST-QA-01 should fail when TODO comments exist."""
        (temp_repo / "app.py").write_text("# TODO: implement this\ndef hello(): pass\n")
        result = check_test_qa_01(str(temp_repo))
        assert result.status == CheckStatus.FAIL
        assert "TODO" in result.message

    def test_qa_01_detects_js_todos(self, temp_repo: Path):
        """TEST-QA-01 should detect TODO in JavaScript files."""
        (temp_repo / "app.js").write_text("// TODO: fix this\nfunction hello() {}\n")
        result = check_test_qa_01(str(temp_repo))
        assert result.status == CheckStatus.FAIL

    def test_qa_02_passes_without_prints(self, temp_repo: Path):
        """TEST-QA-02 should pass when no print statements exist."""
        (temp_repo / "app.py").write_text(
            'import logging\nlogger = logging.getLogger(__name__)\n'
            'logger.info("hello")\n'
        )
        result = check_test_qa_02(str(temp_repo))
        assert result.status == CheckStatus.PASS

    def test_qa_02_fails_with_prints(self, temp_repo: Path):
        """TEST-QA-02 should fail when print statements exist."""
        (temp_repo / "app.py").write_text('print("hello")\n')
        result = check_test_qa_02(str(temp_repo))
        assert result.status == CheckStatus.FAIL
        assert "print" in result.message

    def test_cfg_01_passes_with_editorconfig(self, temp_repo: Path):
        """TEST-CFG-01 should pass when .editorconfig exists."""
        (temp_repo / ".editorconfig").write_text("[*]\nindent_style = space\n")
        result = check_test_cfg_01(str(temp_repo))
        assert result.status == CheckStatus.PASS

    def test_cfg_01_fails_without_editorconfig(self, temp_repo: Path):
        """TEST-CFG-01 should fail when no .editorconfig exists."""
        result = check_test_cfg_01(str(temp_repo))
        assert result.status == CheckStatus.FAIL

    def test_cfg_02_passes_with_precommit(self, temp_repo: Path):
        """TEST-CFG-02 should pass when pre-commit config exists."""
        (temp_repo / ".pre-commit-config.yaml").write_text("repos: []\n")
        result = check_test_cfg_02(str(temp_repo))
        assert result.status == CheckStatus.PASS

    def test_cfg_02_fails_without_precommit(self, temp_repo: Path):
        """TEST-CFG-02 should fail when no pre-commit config exists."""
        result = check_test_cfg_02(str(temp_repo))
        assert result.status == CheckStatus.FAIL


class TestLevel3Checks:
    """Tests for Level 3 checks (security & CI)."""

    def test_sec_01_passes_without_secrets(self, temp_repo: Path):
        """TEST-SEC-01 should pass when no hardcoded secrets exist."""
        (temp_repo / "config.py").write_text(
            'import os\npassword = os.environ.get("PASSWORD")\n'
        )
        result = check_test_sec_01(str(temp_repo))
        assert result.status == CheckStatus.PASS

    def test_sec_01_fails_with_password(self, temp_repo: Path):
        """TEST-SEC-01 should fail when hardcoded password exists."""
        (temp_repo / "config.py").write_text('password = "secret123"\n')
        result = check_test_sec_01(str(temp_repo))
        assert result.status == CheckStatus.FAIL
        assert "secret" in result.message.lower()

    def test_sec_01_fails_with_api_key(self, temp_repo: Path):
        """TEST-SEC-01 should fail when hardcoded api_key exists."""
        (temp_repo / "config.py").write_text('api_key = "abc123"\n')
        result = check_test_sec_01(str(temp_repo))
        assert result.status == CheckStatus.FAIL

    def test_sec_02_passes_with_patterns(self, temp_repo: Path):
        """TEST-SEC-02 should pass when .gitignore has secret patterns."""
        (temp_repo / ".gitignore").write_text(".env\n*.key\n*.pem\n")
        result = check_test_sec_02(str(temp_repo))
        assert result.status == CheckStatus.PASS

    def test_sec_02_fails_without_patterns(self, temp_repo: Path):
        """TEST-SEC-02 should fail when .gitignore missing patterns."""
        (temp_repo / ".gitignore").write_text("*.pyc\n__pycache__/\n")
        result = check_test_sec_02(str(temp_repo))
        assert result.status == CheckStatus.FAIL

    def test_sec_02_fails_without_gitignore(self, temp_repo: Path):
        """TEST-SEC-02 should fail when no .gitignore exists."""
        result = check_test_sec_02(str(temp_repo))
        assert result.status == CheckStatus.FAIL

    def test_ci_01_passes_with_github_actions(self, temp_repo: Path):
        """TEST-CI-01 should pass when GitHub Actions workflow exists."""
        workflows = temp_repo / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").write_text("name: CI\non: push\n")
        result = check_test_ci_01(str(temp_repo))
        assert result.status == CheckStatus.PASS

    def test_ci_01_passes_with_gitlab_ci(self, temp_repo: Path):
        """TEST-CI-01 should pass when .gitlab-ci.yml exists."""
        (temp_repo / ".gitlab-ci.yml").write_text("stages:\n  - test\n")
        result = check_test_ci_01(str(temp_repo))
        assert result.status == CheckStatus.PASS

    def test_ci_01_fails_without_ci(self, temp_repo: Path):
        """TEST-CI-01 should fail when no CI config exists."""
        result = check_test_ci_01(str(temp_repo))
        assert result.status == CheckStatus.FAIL

    def test_ci_02_passes_with_test_command(self, temp_repo: Path):
        """TEST-CI-02 should pass when CI runs tests."""
        workflows = temp_repo / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").write_text(
            "name: CI\non: push\njobs:\n  test:\n    steps:\n      - run: pytest\n"
        )
        result = check_test_ci_02(str(temp_repo))
        assert result.status == CheckStatus.PASS

    def test_ci_02_fails_without_tests(self, temp_repo: Path):
        """TEST-CI-02 should fail when CI doesn't run tests."""
        workflows = temp_repo / ".github" / "workflows"
        workflows.mkdir(parents=True)
        (workflows / "ci.yml").write_text(
            "name: CI\non: push\njobs:\n  build:\n    steps:\n      - run: echo hi\n"
        )
        result = check_test_ci_02(str(temp_repo))
        assert result.status == CheckStatus.FAIL


class TestCompleteRepo:
    """Tests using the complete_repo fixture."""

    def test_complete_repo_passes_level1(self, complete_repo: Path):
        """Complete repo should pass all Level 1 checks."""
        results = [
            check_test_doc_01(str(complete_repo)),
            check_test_doc_02(str(complete_repo)),
            check_test_lic_01(str(complete_repo)),
            check_test_ign_01(str(complete_repo)),
        ]
        for result in results:
            assert result.status == CheckStatus.PASS, f"{result.control_id} failed: {result.message}"

    def test_complete_repo_passes_level2(self, complete_repo: Path):
        """Complete repo should pass all Level 2 checks."""
        results = [
            check_test_qa_01(str(complete_repo)),
            check_test_qa_02(str(complete_repo)),
            check_test_cfg_01(str(complete_repo)),
            check_test_cfg_02(str(complete_repo)),
        ]
        for result in results:
            assert result.status == CheckStatus.PASS, f"{result.control_id} failed: {result.message}"

    def test_complete_repo_passes_level3(self, complete_repo: Path):
        """Complete repo should pass all Level 3 checks."""
        results = [
            check_test_sec_01(str(complete_repo)),
            check_test_sec_02(str(complete_repo)),
            check_test_ci_01(str(complete_repo)),
            check_test_ci_02(str(complete_repo)),
        ]
        for result in results:
            assert result.status == CheckStatus.PASS, f"{result.control_id} failed: {result.message}"


class TestRepoWithViolations:
    """Tests using the repo_with_violations fixture."""

    def test_violations_detected(self, repo_with_violations: Path):
        """Repo with violations should fail quality checks."""
        # Should fail TODO check
        result = check_test_qa_01(str(repo_with_violations))
        assert result.status == CheckStatus.FAIL

        # Should fail print check
        result = check_test_qa_02(str(repo_with_violations))
        assert result.status == CheckStatus.FAIL

        # Should fail secrets check
        result = check_test_sec_01(str(repo_with_violations))
        assert result.status == CheckStatus.FAIL

        # Should fail gitignore patterns check
        result = check_test_sec_02(str(repo_with_violations))
        assert result.status == CheckStatus.FAIL
