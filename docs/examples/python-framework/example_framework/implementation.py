"""Example Framework Implementation - Full Python Version.

This file demonstrates the traditional Python approach to implementing
a compliance framework. Compare with the TOML-only approach in
../declarative-framework/example-framework.toml

Note how much more code is required for the same functionality:
- TOML version: ~300 lines (declarative, no logic)
- Python version: ~500+ lines (imperative, with logic)
"""

import os
import re
import glob
import subprocess
from typing import Dict, List, Any, Optional, Tuple
from dataclasses import dataclass

# These would normally be imported from darnit
# from darnit.core.models import CheckResult, CheckStatus
# from darnit.core.plugin import ComplianceImplementation


# =============================================================================
# Data Classes (normally from darnit.core.models)
# =============================================================================

@dataclass
class CheckResult:
    """Result of a compliance check."""
    id: str
    name: str
    status: str  # "PASS", "FAIL", "SKIP", "ERROR"
    message: str
    level: int
    domain: str
    details: Dict[str, Any] = None

    def to_dict(self) -> Dict[str, Any]:
        return {
            "id": self.id,
            "name": self.name,
            "status": self.status,
            "message": self.message,
            "level": self.level,
            "domain": self.domain,
            "details": self.details or {},
        }


# =============================================================================
# Check Functions - Each control needs its own function
# =============================================================================

def check_readme_exists(local_path: str) -> CheckResult:
    """Check EXAMPLE-DO-01: README file must exist."""
    readme_patterns = ["README.md", "README", "README.rst", "README.txt"]

    for pattern in readme_patterns:
        if os.path.exists(os.path.join(local_path, pattern)):
            return CheckResult(
                id="EXAMPLE-DO-01",
                name="ReadmeExists",
                status="PASS",
                message=f"README found: {pattern}",
                level=1,
                domain="DO",
                details={"file_found": pattern},
            )

    return CheckResult(
        id="EXAMPLE-DO-01",
        name="ReadmeExists",
        status="FAIL",
        message="No README file found",
        level=1,
        domain="DO",
        details={"searched": readme_patterns},
    )


def check_changelog_exists(local_path: str) -> CheckResult:
    """Check EXAMPLE-DO-02: CHANGELOG file must exist."""
    changelog_patterns = ["CHANGELOG.md", "CHANGELOG", "HISTORY.md", "NEWS.md"]

    for pattern in changelog_patterns:
        if os.path.exists(os.path.join(local_path, pattern)):
            return CheckResult(
                id="EXAMPLE-DO-02",
                name="ChangelogExists",
                status="PASS",
                message=f"CHANGELOG found: {pattern}",
                level=1,
                domain="DO",
                details={"file_found": pattern},
            )

    return CheckResult(
        id="EXAMPLE-DO-02",
        name="ChangelogExists",
        status="FAIL",
        message="No CHANGELOG file found",
        level=1,
        domain="DO",
        details={"searched": changelog_patterns},
    )


def check_license_exists(local_path: str) -> CheckResult:
    """Check EXAMPLE-LE-01: LICENSE file must exist."""
    license_patterns = ["LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"]

    for pattern in license_patterns:
        if os.path.exists(os.path.join(local_path, pattern)):
            return CheckResult(
                id="EXAMPLE-LE-01",
                name="LicenseExists",
                status="PASS",
                message=f"LICENSE found: {pattern}",
                level=1,
                domain="LE",
                details={"file_found": pattern},
            )

    return CheckResult(
        id="EXAMPLE-LE-01",
        name="LicenseExists",
        status="FAIL",
        message="No LICENSE file found",
        level=1,
        domain="LE",
        details={"searched": license_patterns},
    )


def check_no_secrets(local_path: str) -> CheckResult:
    """Check EXAMPLE-SE-01: No hardcoded secrets in repository."""
    # Check for forbidden files
    forbidden_files = [".env", ".env.local", "secrets.json", "credentials.json"]
    found_forbidden = []

    for pattern in forbidden_files:
        if os.path.exists(os.path.join(local_path, pattern)):
            found_forbidden.append(pattern)

    # Check for key files
    for ext in ["*.pem", "*.key"]:
        matches = glob.glob(os.path.join(local_path, "**", ext), recursive=True)
        found_forbidden.extend(matches)

    if found_forbidden:
        return CheckResult(
            id="EXAMPLE-SE-01",
            name="NoHardcodedSecrets",
            status="FAIL",
            message=f"Found {len(found_forbidden)} forbidden file(s)",
            level=1,
            domain="SE",
            details={"forbidden_files": found_forbidden},
        )

    # Check for secret patterns in code
    secret_patterns = {
        "aws_key": r"AKIA[0-9A-Z]{16}",
        "private_key": r"-----BEGIN (RSA |EC |DSA )?PRIVATE KEY-----",
        "api_token": r"(api[_-]?key|api[_-]?token|access[_-]?token)\s*[=:]\s*['\"][a-zA-Z0-9]{20,}",
    }

    code_extensions = ["*.py", "*.js", "*.ts", "*.go", "*.java"]
    secrets_found = []

    for ext in code_extensions:
        for filepath in glob.glob(os.path.join(local_path, "**", ext), recursive=True):
            try:
                with open(filepath, "r", encoding="utf-8", errors="ignore") as f:
                    content = f.read()
                for pattern_name, pattern in secret_patterns.items():
                    if re.search(pattern, content):
                        secrets_found.append({
                            "file": filepath,
                            "pattern": pattern_name,
                        })
            except (IOError, OSError):
                continue

    if secrets_found:
        return CheckResult(
            id="EXAMPLE-SE-01",
            name="NoHardcodedSecrets",
            status="FAIL",
            message=f"Found {len(secrets_found)} potential secret(s) in code",
            level=1,
            domain="SE",
            details={"secrets_found": secrets_found[:10]},  # Limit output
        )

    return CheckResult(
        id="EXAMPLE-SE-01",
        name="NoHardcodedSecrets",
        status="PASS",
        message="No hardcoded secrets detected",
        level=1,
        domain="SE",
    )


def check_cicd_configured(local_path: str) -> CheckResult:
    """Check EXAMPLE-QA-01: CI/CD must be configured."""
    cicd_patterns = [
        ".github/workflows/*.yml",
        ".github/workflows/*.yaml",
        ".gitlab-ci.yml",
        "Jenkinsfile",
        ".circleci/config.yml",
        ".travis.yml",
        "azure-pipelines.yml",
    ]

    for pattern in cicd_patterns:
        matches = glob.glob(os.path.join(local_path, pattern))
        if matches:
            return CheckResult(
                id="EXAMPLE-QA-01",
                name="CICDConfigured",
                status="PASS",
                message=f"CI/CD configuration found",
                level=2,
                domain="QA",
                details={"files_found": matches},
            )

    return CheckResult(
        id="EXAMPLE-QA-01",
        name="CICDConfigured",
        status="FAIL",
        message="No CI/CD configuration found",
        level=2,
        domain="QA",
        details={"searched": cicd_patterns},
    )


def check_tests_exist(local_path: str) -> CheckResult:
    """Check EXAMPLE-QA-02: Tests must exist."""
    test_patterns = [
        "tests/**/*.py",
        "test/**/*.py",
        "**/*_test.py",
        "**/*_test.go",
        "**/*.test.js",
        "**/*.test.ts",
        "**/*.spec.js",
        "**/*.spec.ts",
    ]

    all_tests = []
    for pattern in test_patterns:
        matches = glob.glob(os.path.join(local_path, pattern), recursive=True)
        all_tests.extend(matches)

    if all_tests:
        return CheckResult(
            id="EXAMPLE-QA-02",
            name="TestsExist",
            status="PASS",
            message=f"Found {len(all_tests)} test file(s)",
            level=2,
            domain="QA",
            details={"test_files": all_tests[:10]},
        )

    return CheckResult(
        id="EXAMPLE-QA-02",
        name="TestsExist",
        status="FAIL",
        message="No test files found",
        level=2,
        domain="QA",
        details={"searched": test_patterns},
    )


def check_codeowners_exists(local_path: str) -> CheckResult:
    """Check EXAMPLE-GV-01: CODEOWNERS file must exist."""
    codeowners_patterns = ["CODEOWNERS", ".github/CODEOWNERS", "docs/CODEOWNERS"]

    for pattern in codeowners_patterns:
        if os.path.exists(os.path.join(local_path, pattern)):
            return CheckResult(
                id="EXAMPLE-GV-01",
                name="CodeOwnersExists",
                status="PASS",
                message=f"CODEOWNERS found: {pattern}",
                level=2,
                domain="GV",
                details={"file_found": pattern},
            )

    return CheckResult(
        id="EXAMPLE-GV-01",
        name="CodeOwnersExists",
        status="FAIL",
        message="No CODEOWNERS file found",
        level=2,
        domain="GV",
        details={"searched": codeowners_patterns},
    )


def check_branch_protection(
    owner: str,
    repo: str,
    branch: str,
) -> CheckResult:
    """Check EXAMPLE-AC-01: Branch protection must be enabled."""
    try:
        result = subprocess.run(
            ["gh", "api", f"/repos/{owner}/{repo}/branches/{branch}/protection"],
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            return CheckResult(
                id="EXAMPLE-AC-01",
                name="BranchProtectionEnabled",
                status="PASS",
                message="Branch protection is enabled",
                level=2,
                domain="AC",
            )
        else:
            return CheckResult(
                id="EXAMPLE-AC-01",
                name="BranchProtectionEnabled",
                status="FAIL",
                message="Branch protection is not enabled",
                level=2,
                domain="AC",
                details={"error": result.stderr[:200]},
            )

    except FileNotFoundError:
        return CheckResult(
            id="EXAMPLE-AC-01",
            name="BranchProtectionEnabled",
            status="ERROR",
            message="gh CLI not found",
            level=2,
            domain="AC",
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            id="EXAMPLE-AC-01",
            name="BranchProtectionEnabled",
            status="ERROR",
            message="API call timed out",
            level=2,
            domain="AC",
        )


def check_dependency_scanning(local_path: str) -> CheckResult:
    """Check EXAMPLE-VM-01: Dependency scanning must be configured."""
    scanning_patterns = [
        ".github/dependabot.yml",
        ".github/dependabot.yaml",
        "renovate.json",
        ".renovaterc",
        ".renovaterc.json",
    ]

    for pattern in scanning_patterns:
        if os.path.exists(os.path.join(local_path, pattern)):
            return CheckResult(
                id="EXAMPLE-VM-01",
                name="DependencyScanningEnabled",
                status="PASS",
                message=f"Dependency scanning configured: {pattern}",
                level=3,
                domain="VM",
                details={"file_found": pattern},
            )

    return CheckResult(
        id="EXAMPLE-VM-01",
        name="DependencyScanningEnabled",
        status="FAIL",
        message="No dependency scanning configuration found",
        level=3,
        domain="VM",
        details={"searched": scanning_patterns},
    )


def check_sbom_compliance(local_path: str) -> CheckResult:
    """Check EXAMPLE-VM-02: SBOM compliance using external tool."""
    try:
        result = subprocess.run(
            ["kusari", "repo", "scan", local_path, "HEAD"],
            capture_output=True,
            text=True,
            timeout=120,
        )

        if result.returncode == 0:
            return CheckResult(
                id="EXAMPLE-VM-02",
                name="SBOMCompliance",
                status="PASS",
                message="SBOM compliance check passed",
                level=3,
                domain="VM",
            )
        else:
            return CheckResult(
                id="EXAMPLE-VM-02",
                name="SBOMCompliance",
                status="FAIL",
                message="SBOM compliance check failed",
                level=3,
                domain="VM",
                details={"output": result.stdout[:500]},
            )

    except FileNotFoundError:
        return CheckResult(
            id="EXAMPLE-VM-02",
            name="SBOMCompliance",
            status="SKIP",
            message="kusari tool not installed",
            level=3,
            domain="VM",
        )
    except subprocess.TimeoutExpired:
        return CheckResult(
            id="EXAMPLE-VM-02",
            name="SBOMCompliance",
            status="ERROR",
            message="SBOM check timed out",
            level=3,
            domain="VM",
        )


# =============================================================================
# Remediation Functions - Each remediation needs its own function
# =============================================================================

def create_readme(
    local_path: str,
    owner: str,
    repo: str,
    dry_run: bool = True,
) -> str:
    """Create README.md file."""
    content = f"""# {repo}

A project by {owner}.

## Installation

```bash
# Clone the repository
git clone https://github.com/{owner}/{repo}.git
cd {repo}

# Install dependencies
npm install  # or pip install -r requirements.txt
```

## Usage

See the [documentation](docs/) for detailed usage instructions.

## Contributing

Please read [CONTRIBUTING.md](CONTRIBUTING.md) for details on our code of conduct
and the process for submitting pull requests.

## License

This project is licensed under the terms specified in [LICENSE](LICENSE).
"""

    filepath = os.path.join(local_path, "README.md")

    if dry_run:
        return f"Would create: {filepath}"

    if os.path.exists(filepath):
        return f"File already exists: {filepath}"

    with open(filepath, "w") as f:
        f.write(content)

    return f"Created: {filepath}"


def create_changelog(
    local_path: str,
    dry_run: bool = True,
) -> str:
    """Create CHANGELOG.md file."""
    from datetime import datetime

    content = f"""# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.0.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Added
- Initial project setup

### Changed
- Nothing yet

### Fixed
- Nothing yet

## [0.1.0] - {datetime.now().strftime("%Y-%m-%d")}

### Added
- Initial release
"""

    filepath = os.path.join(local_path, "CHANGELOG.md")

    if dry_run:
        return f"Would create: {filepath}"

    if os.path.exists(filepath):
        return f"File already exists: {filepath}"

    with open(filepath, "w") as f:
        f.write(content)

    return f"Created: {filepath}"


def create_codeowners(
    local_path: str,
    owner: str,
    dry_run: bool = True,
) -> str:
    """Create CODEOWNERS file."""
    content = f"""# Code Owners
# These owners will be requested for review when someone opens a pull request.

# Default owners for everything in the repo
*       @{owner}

# Documentation
/docs/  @{owner}
*.md    @{owner}
"""

    filepath = os.path.join(local_path, "CODEOWNERS")

    if dry_run:
        return f"Would create: {filepath}"

    if os.path.exists(filepath):
        return f"File already exists: {filepath}"

    with open(filepath, "w") as f:
        f.write(content)

    return f"Created: {filepath}"


def enable_branch_protection(
    owner: str,
    repo: str,
    branch: str,
    dry_run: bool = True,
) -> str:
    """Enable branch protection via GitHub API."""
    import json

    payload = {
        "enforce_admins": True,
        "required_pull_request_reviews": {
            "required_approving_review_count": 1,
        },
        "required_status_checks": None,
        "restrictions": None,
        "allow_force_pushes": False,
        "allow_deletions": False,
    }

    endpoint = f"/repos/{owner}/{repo}/branches/{branch}/protection"

    if dry_run:
        return f"Would call: PUT {endpoint}\nPayload: {json.dumps(payload, indent=2)}"

    try:
        result = subprocess.run(
            ["gh", "api", "-X", "PUT", endpoint, "--input", "-"],
            input=json.dumps(payload),
            capture_output=True,
            text=True,
            timeout=30,
        )

        if result.returncode == 0:
            return f"Branch protection enabled for {branch}"
        else:
            return f"Failed: {result.stderr}"

    except (FileNotFoundError, subprocess.TimeoutExpired) as e:
        return f"Error: {str(e)}"


# =============================================================================
# Implementation Class - Ties everything together
# =============================================================================

class ExampleFrameworkImplementation:
    """Example compliance framework implementation.

    This class provides the interface that darnit expects for compliance
    framework plugins.
    """

    name = "example-framework"
    display_name = "Example Compliance Framework"
    version = "1.0.0"

    # Control definitions
    CONTROLS = {
        "EXAMPLE-DO-01": {"name": "ReadmeExists", "level": 1, "domain": "DO"},
        "EXAMPLE-DO-02": {"name": "ChangelogExists", "level": 1, "domain": "DO"},
        "EXAMPLE-LE-01": {"name": "LicenseExists", "level": 1, "domain": "LE"},
        "EXAMPLE-SE-01": {"name": "NoHardcodedSecrets", "level": 1, "domain": "SE"},
        "EXAMPLE-QA-01": {"name": "CICDConfigured", "level": 2, "domain": "QA"},
        "EXAMPLE-QA-02": {"name": "TestsExist", "level": 2, "domain": "QA"},
        "EXAMPLE-GV-01": {"name": "CodeOwnersExists", "level": 2, "domain": "GV"},
        "EXAMPLE-AC-01": {"name": "BranchProtectionEnabled", "level": 2, "domain": "AC"},
        "EXAMPLE-VM-01": {"name": "DependencyScanningEnabled", "level": 3, "domain": "VM"},
        "EXAMPLE-VM-02": {"name": "SBOMCompliance", "level": 3, "domain": "VM"},
    }

    def run_checks(
        self,
        owner: str,
        repo: str,
        local_path: str,
        default_branch: str,
        level: int = 3,
    ) -> List[Dict[str, Any]]:
        """Run all checks up to the specified level.

        Args:
            owner: Repository owner
            repo: Repository name
            local_path: Path to local repository
            default_branch: Default branch name
            level: Maximum level to check (1, 2, or 3)

        Returns:
            List of check results as dictionaries
        """
        results = []

        # Level 1 checks
        results.append(check_readme_exists(local_path).to_dict())
        results.append(check_changelog_exists(local_path).to_dict())
        results.append(check_license_exists(local_path).to_dict())
        results.append(check_no_secrets(local_path).to_dict())

        if level >= 2:
            results.append(check_cicd_configured(local_path).to_dict())
            results.append(check_tests_exist(local_path).to_dict())
            results.append(check_codeowners_exists(local_path).to_dict())
            results.append(check_branch_protection(owner, repo, default_branch).to_dict())

        if level >= 3:
            results.append(check_dependency_scanning(local_path).to_dict())
            results.append(check_sbom_compliance(local_path).to_dict())

        return results

    def get_controls(self) -> Dict[str, Dict]:
        """Get all control definitions."""
        return self.CONTROLS

    def get_remediation(self, control_id: str):
        """Get remediation function for a control."""
        remediation_map = {
            "EXAMPLE-DO-01": create_readme,
            "EXAMPLE-DO-02": create_changelog,
            "EXAMPLE-GV-01": create_codeowners,
            "EXAMPLE-AC-01": enable_branch_protection,
        }
        return remediation_map.get(control_id)
