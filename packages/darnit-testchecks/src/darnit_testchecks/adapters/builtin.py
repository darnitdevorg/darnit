"""Builtin adapter for Test Checks Framework.

This adapter implements the trivial checks defined in testchecks.toml.
It demonstrates how to create custom check implementations for a
darnit framework.
"""

import logging
import re
from pathlib import Path
from typing import Any, Dict, List, Optional

from darnit.core.adapters import CheckAdapter, RemediationAdapter
from darnit.core.models import (
    AdapterCapability,
    CheckResult,
    CheckStatus,
    RemediationResult,
)

logger = logging.getLogger(__name__)


# =============================================================================
# Control Definitions
# =============================================================================

# Control metadata for quick lookup
CONTROLS = {
    # Level 1 - Documentation
    "TEST-DOC-01": {"name": "HasReadme", "level": 1, "domain": "DOC"},
    "TEST-DOC-02": {"name": "HasChangelog", "level": 1, "domain": "DOC"},
    "TEST-LIC-01": {"name": "HasLicense", "level": 1, "domain": "LIC"},
    "TEST-IGN-01": {"name": "HasGitignore", "level": 1, "domain": "CFG"},
    # Level 2 - Quality
    "TEST-QA-01": {"name": "NoTodoComments", "level": 2, "domain": "QA"},
    "TEST-QA-02": {"name": "NoPrintStatements", "level": 2, "domain": "QA"},
    "TEST-CFG-01": {"name": "HasEditorConfig", "level": 2, "domain": "CFG"},
    "TEST-CFG-02": {"name": "HasPreCommitConfig", "level": 2, "domain": "CFG"},
    # Level 3 - Security & CI
    "TEST-SEC-01": {"name": "NoHardcodedPasswords", "level": 3, "domain": "SEC"},
    "TEST-SEC-02": {"name": "GitignoreSecrets", "level": 3, "domain": "SEC"},
    "TEST-CI-01": {"name": "HasCIConfig", "level": 3, "domain": "CI"},
    "TEST-CI-02": {"name": "CIRunsTests", "level": 3, "domain": "CI"},
}


# =============================================================================
# Check Implementations
# =============================================================================


def check_file_exists(local_path: str, file_patterns: List[str]) -> tuple:
    """Check if any of the specified files exist.

    Args:
        local_path: Path to repository root
        file_patterns: List of file patterns to check

    Returns:
        Tuple of (exists: bool, found_file: Optional[str])
    """
    repo = Path(local_path)

    for pattern in file_patterns:
        if "*" in pattern:
            # Glob pattern
            matches = list(repo.glob(pattern))
            if matches:
                return True, str(matches[0].relative_to(repo))
        else:
            # Exact file
            if (repo / pattern).exists():
                return True, pattern

    return False, None


def check_pattern_not_found(
    local_path: str,
    file_patterns: List[str],
    regex_patterns: Dict[str, str],
) -> tuple:
    """Check that patterns are NOT found in files (for detecting bad practices).

    Args:
        local_path: Path to repository root
        file_patterns: Glob patterns for files to check
        regex_patterns: Dict of name -> regex pattern to search for

    Returns:
        Tuple of (passed: bool, violations: List[str])
    """
    repo = Path(local_path)
    violations = []

    for file_pattern in file_patterns:
        for file_path in repo.glob(file_pattern):
            if file_path.is_file():
                try:
                    content = file_path.read_text(errors="ignore")
                    for pattern_name, regex in regex_patterns.items():
                        matches = re.findall(regex, content, re.MULTILINE)
                        if matches:
                            rel_path = file_path.relative_to(repo)
                            violations.append(
                                f"{rel_path}: found {pattern_name} ({len(matches)} occurrences)"
                            )
                except Exception as e:
                    logger.debug(f"Could not read {file_path}: {e}")

    return len(violations) == 0, violations


def check_pattern_found(
    local_path: str,
    file_patterns: List[str],
    regex_patterns: Dict[str, str],
) -> tuple:
    """Check that patterns ARE found in files (for detecting required content).

    Args:
        local_path: Path to repository root
        file_patterns: Glob patterns for files to check
        regex_patterns: Dict of name -> regex pattern to search for

    Returns:
        Tuple of (passed: bool, found: Dict[str, bool])
    """
    repo = Path(local_path)
    found = {name: False for name in regex_patterns}

    for file_pattern in file_patterns:
        for file_path in repo.glob(file_pattern):
            if file_path.is_file():
                try:
                    content = file_path.read_text(errors="ignore")
                    for pattern_name, regex in regex_patterns.items():
                        if re.search(regex, content, re.MULTILINE):
                            found[pattern_name] = True
                except Exception as e:
                    logger.debug(f"Could not read {file_path}: {e}")

    all_found = all(found.values())
    return all_found, found


# =============================================================================
# Control Check Functions
# =============================================================================


def check_test_doc_01(local_path: str) -> CheckResult:
    """TEST-DOC-01: HasReadme"""
    exists, found = check_file_exists(
        local_path,
        ["README.md", "README.rst", "README.txt", "README"],
    )
    return CheckResult(
        control_id="TEST-DOC-01",
        status=CheckStatus.PASS if exists else CheckStatus.FAIL,
        message=f"Found {found}" if exists else "No README file found",
        level=1,
        source="testchecks",
    )


def check_test_doc_02(local_path: str) -> CheckResult:
    """TEST-DOC-02: HasChangelog"""
    exists, found = check_file_exists(
        local_path,
        ["CHANGELOG.md", "CHANGELOG.txt", "CHANGELOG", "HISTORY.md", "CHANGES.md"],
    )
    return CheckResult(
        control_id="TEST-DOC-02",
        status=CheckStatus.PASS if exists else CheckStatus.FAIL,
        message=f"Found {found}" if exists else "No CHANGELOG file found",
        level=1,
        source="testchecks",
    )


def check_test_lic_01(local_path: str) -> CheckResult:
    """TEST-LIC-01: HasLicense"""
    exists, found = check_file_exists(
        local_path,
        ["LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"],
    )
    return CheckResult(
        control_id="TEST-LIC-01",
        status=CheckStatus.PASS if exists else CheckStatus.FAIL,
        message=f"Found {found}" if exists else "No LICENSE file found",
        level=1,
        source="testchecks",
    )


def check_test_ign_01(local_path: str) -> CheckResult:
    """TEST-IGN-01: HasGitignore"""
    exists, found = check_file_exists(local_path, [".gitignore"])
    return CheckResult(
        control_id="TEST-IGN-01",
        status=CheckStatus.PASS if exists else CheckStatus.FAIL,
        message=f"Found {found}" if exists else "No .gitignore file found",
        level=1,
        source="testchecks",
    )


def check_test_qa_01(local_path: str) -> CheckResult:
    """TEST-QA-01: NoTodoComments"""
    passed, violations = check_pattern_not_found(
        local_path,
        ["**/*.py", "**/*.js", "**/*.ts"],
        {"TODO comment": r"#\s*TODO|//\s*TODO|/\*\s*TODO"},
    )
    if passed:
        message = "No TODO comments found"
    else:
        message = f"Found TODO comments: {', '.join(violations[:5])}"
        if len(violations) > 5:
            message += f" (and {len(violations) - 5} more)"
    return CheckResult(
        control_id="TEST-QA-01",
        status=CheckStatus.PASS if passed else CheckStatus.FAIL,
        message=message,
        level=2,
        source="testchecks",
    )


def check_test_qa_02(local_path: str) -> CheckResult:
    """TEST-QA-02: NoPrintStatements"""
    passed, violations = check_pattern_not_found(
        local_path,
        ["**/*.py"],
        {"print statement": r"^\s*print\s*\("},
    )
    if passed:
        message = "No print() statements found"
    else:
        message = f"Found print statements: {', '.join(violations[:5])}"
        if len(violations) > 5:
            message += f" (and {len(violations) - 5} more)"
    return CheckResult(
        control_id="TEST-QA-02",
        status=CheckStatus.PASS if passed else CheckStatus.FAIL,
        message=message,
        level=2,
        source="testchecks",
    )


def check_test_cfg_01(local_path: str) -> CheckResult:
    """TEST-CFG-01: HasEditorConfig"""
    exists, found = check_file_exists(local_path, [".editorconfig"])
    return CheckResult(
        control_id="TEST-CFG-01",
        status=CheckStatus.PASS if exists else CheckStatus.FAIL,
        message=f"Found {found}" if exists else "No .editorconfig file found",
        level=2,
        source="testchecks",
    )


def check_test_cfg_02(local_path: str) -> CheckResult:
    """TEST-CFG-02: HasPreCommitConfig"""
    exists, found = check_file_exists(
        local_path,
        [".pre-commit-config.yaml", ".pre-commit-config.yml"],
    )
    return CheckResult(
        control_id="TEST-CFG-02",
        status=CheckStatus.PASS if exists else CheckStatus.FAIL,
        message=f"Found {found}" if exists else "No pre-commit config found",
        level=2,
        source="testchecks",
    )


def check_test_sec_01(local_path: str) -> CheckResult:
    """TEST-SEC-01: NoHardcodedPasswords"""
    passed, violations = check_pattern_not_found(
        local_path,
        ["**/*.py", "**/*.js", "**/*.ts", "**/*.yaml", "**/*.yml", "**/*.json"],
        {
            "password assignment": r'password\s*=\s*["\'][^"\']+["\']',
            "secret assignment": r'secret\s*=\s*["\'][^"\']+["\']',
            "api_key assignment": r'api_key\s*=\s*["\'][^"\']+["\']',
        },
    )
    if passed:
        message = "No hardcoded secrets found"
    else:
        message = f"Potential hardcoded secrets: {', '.join(violations[:3])}"
        if len(violations) > 3:
            message += f" (and {len(violations) - 3} more)"
    return CheckResult(
        control_id="TEST-SEC-01",
        status=CheckStatus.PASS if passed else CheckStatus.FAIL,
        message=message,
        level=3,
        source="testchecks",
    )


def check_test_sec_02(local_path: str) -> CheckResult:
    """TEST-SEC-02: GitignoreSecrets"""
    gitignore_path = Path(local_path) / ".gitignore"
    if not gitignore_path.exists():
        return CheckResult(
            control_id="TEST-SEC-02",
            status=CheckStatus.FAIL,
            message="No .gitignore file found",
            level=3,
            source="testchecks",
        )

    passed, found = check_pattern_found(
        local_path,
        [".gitignore"],
        {
            "env files": r"\.env",
            "key files": r"\*\.key|\*\.pem",
        },
    )
    missing = [name for name, was_found in found.items() if not was_found]
    if passed:
        message = ".gitignore includes common secret patterns"
    else:
        message = f".gitignore missing patterns for: {', '.join(missing)}"
    return CheckResult(
        control_id="TEST-SEC-02",
        status=CheckStatus.PASS if passed else CheckStatus.FAIL,
        message=message,
        level=3,
        source="testchecks",
    )


def check_test_ci_01(local_path: str) -> CheckResult:
    """TEST-CI-01: HasCIConfig"""
    exists, found = check_file_exists(
        local_path,
        [
            ".github/workflows/*.yml",
            ".github/workflows/*.yaml",
            ".gitlab-ci.yml",
            ".circleci/config.yml",
            "Jenkinsfile",
            ".travis.yml",
            "azure-pipelines.yml",
        ],
    )
    return CheckResult(
        control_id="TEST-CI-01",
        status=CheckStatus.PASS if exists else CheckStatus.FAIL,
        message=f"Found CI config: {found}" if exists else "No CI configuration found",
        level=3,
        source="testchecks",
    )


def check_test_ci_02(local_path: str) -> CheckResult:
    """TEST-CI-02: CIRunsTests"""
    passed, found = check_pattern_found(
        local_path,
        [".github/workflows/*.yml", ".github/workflows/*.yaml", ".gitlab-ci.yml"],
        {
            "test command": r"(npm test|pytest|go test|cargo test|mvn test|make test)",
        },
    )
    if passed:
        message = "CI configuration runs tests"
    else:
        message = "No test commands found in CI configuration"
    return CheckResult(
        control_id="TEST-CI-02",
        status=CheckStatus.PASS if passed else CheckStatus.FAIL,
        message=message,
        level=3,
        source="testchecks",
    )


# Mapping of control ID to check function
CHECK_FUNCTIONS = {
    "TEST-DOC-01": check_test_doc_01,
    "TEST-DOC-02": check_test_doc_02,
    "TEST-LIC-01": check_test_lic_01,
    "TEST-IGN-01": check_test_ign_01,
    "TEST-QA-01": check_test_qa_01,
    "TEST-QA-02": check_test_qa_02,
    "TEST-CFG-01": check_test_cfg_01,
    "TEST-CFG-02": check_test_cfg_02,
    "TEST-SEC-01": check_test_sec_01,
    "TEST-SEC-02": check_test_sec_02,
    "TEST-CI-01": check_test_ci_01,
    "TEST-CI-02": check_test_ci_02,
}


# =============================================================================
# Test Check Adapter
# =============================================================================


class TrivialCheckAdapter(CheckAdapter):
    """Adapter for running Test Checks Framework controls.

    This adapter demonstrates how to implement a custom check adapter
    for a darnit compliance framework.
    """

    def __init__(self):
        """Initialize the test check adapter."""
        pass

    def name(self) -> str:
        """Return adapter name."""
        return "testchecks"

    def capabilities(self) -> AdapterCapability:
        """Return what controls this adapter can check."""
        return AdapterCapability(
            control_ids=set(CHECK_FUNCTIONS.keys()),
            supports_batch=True,
        )

    def check(
        self,
        control_id: str,
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any],
    ) -> CheckResult:
        """Run check for a specific control.

        Args:
            control_id: Control identifier (e.g., "TEST-DOC-01")
            owner: GitHub owner/org (unused for local checks)
            repo: Repository name (unused for local checks)
            local_path: Path to local repository clone
            config: Additional configuration

        Returns:
            CheckResult for the specified control
        """
        check_func = CHECK_FUNCTIONS.get(control_id)
        if not check_func:
            return CheckResult(
                control_id=control_id,
                status=CheckStatus.ERROR,
                message=f"Unknown control: {control_id}",
                level=CONTROLS.get(control_id, {}).get("level", 1),
                source="testchecks",
            )

        try:
            return check_func(local_path)
        except Exception as e:
            logger.error(f"Error checking {control_id}: {e}")
            return CheckResult(
                control_id=control_id,
                status=CheckStatus.ERROR,
                message=f"Check failed: {e}",
                level=CONTROLS.get(control_id, {}).get("level", 1),
                source="testchecks",
            )

    def check_batch(
        self,
        control_ids: List[str],
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any],
    ) -> List[CheckResult]:
        """Run checks for multiple controls.

        Args:
            control_ids: List of control identifiers
            owner: GitHub owner/org
            repo: Repository name
            local_path: Path to local repository clone
            config: Additional configuration

        Returns:
            List of CheckResult for all requested controls
        """
        return [
            self.check(control_id, owner, repo, local_path, config)
            for control_id in control_ids
        ]


# =============================================================================
# Test Remediation Adapter
# =============================================================================


class TrivialRemediationAdapter(RemediationAdapter):
    """Adapter for running Test Checks Framework remediations.

    Provides simple file-creation remediations for basic controls.
    """

    def __init__(self):
        """Initialize the test remediation adapter."""
        pass

    def name(self) -> str:
        """Return adapter name."""
        return "testchecks"

    def capabilities(self) -> AdapterCapability:
        """Return what controls this adapter can remediate."""
        return AdapterCapability(
            control_ids={"TEST-DOC-01", "TEST-IGN-01"},
            supports_batch=False,
        )

    def remediate(
        self,
        control_id: str,
        owner: str,
        repo: str,
        local_path: str,
        config: Dict[str, Any],
        dry_run: bool = True,
    ) -> RemediationResult:
        """Apply remediation for a specific control.

        Args:
            control_id: Control identifier
            owner: GitHub owner/org
            repo: Repository name
            local_path: Path to local repository clone
            config: Additional configuration
            dry_run: If True, show what would be done without making changes

        Returns:
            RemediationResult describing the outcome
        """
        if control_id == "TEST-DOC-01":
            return self._create_readme(local_path, repo, dry_run)
        elif control_id == "TEST-IGN-01":
            return self._create_gitignore(local_path, dry_run)
        else:
            return RemediationResult(
                control_id=control_id,
                success=False,
                message=f"No remediation available for {control_id}",
                source="testchecks",
            )

    def _create_readme(
        self, local_path: str, repo: str, dry_run: bool
    ) -> RemediationResult:
        """Create a basic README.md file."""
        readme_path = Path(local_path) / "README.md"
        content = f"""# {repo}

A brief description of this project.

## Installation

```bash
# Installation instructions
```

## Usage

```bash
# Usage examples
```

## License

See [LICENSE](LICENSE) for details.
"""
        if dry_run:
            return RemediationResult(
                control_id="TEST-DOC-01",
                success=True,
                message=f"Would create {readme_path}",
                changes_made=[],
                source="testchecks",
            )

        readme_path.write_text(content)
        return RemediationResult(
            control_id="TEST-DOC-01",
            success=True,
            message=f"Created {readme_path}",
            changes_made=[str(readme_path)],
            source="testchecks",
        )

    def _create_gitignore(self, local_path: str, dry_run: bool) -> RemediationResult:
        """Create a basic .gitignore file."""
        gitignore_path = Path(local_path) / ".gitignore"
        content = """# Environment
.env
.env.local
.env.*.local

# Secrets
*.key
*.pem
credentials.json
secrets.yaml

# Python
__pycache__/
*.py[cod]
.venv/
venv/
.pytest_cache/

# Node
node_modules/
.npm/

# IDE
.idea/
.vscode/
*.swp

# OS
.DS_Store
Thumbs.db
"""
        if dry_run:
            return RemediationResult(
                control_id="TEST-IGN-01",
                success=True,
                message=f"Would create {gitignore_path}",
                changes_made=[],
                source="testchecks",
            )

        gitignore_path.write_text(content)
        return RemediationResult(
            control_id="TEST-IGN-01",
            success=True,
            message=f"Created {gitignore_path}",
            changes_made=[str(gitignore_path)],
            source="testchecks",
        )


# =============================================================================
# Factory Functions
# =============================================================================

_test_check_adapter: Optional[TrivialCheckAdapter] = None
_test_remediation_adapter: Optional[TrivialRemediationAdapter] = None


def get_test_check_adapter() -> TrivialCheckAdapter:
    """Get the singleton test check adapter instance."""
    global _test_check_adapter
    if _test_check_adapter is None:
        _test_check_adapter = TrivialCheckAdapter()
    return _test_check_adapter


def get_test_remediation_adapter() -> TrivialRemediationAdapter:
    """Get the singleton test remediation adapter instance."""
    global _test_remediation_adapter
    if _test_remediation_adapter is None:
        _test_remediation_adapter = TrivialRemediationAdapter()
    return _test_remediation_adapter
