"""OpenSSF Baseline Level 2 check functions (18 controls).

Level 2 represents enhanced security requirements for more mature open source projects.
"""

import os
import re
from typing import Dict, List

from darnit.core.logging import get_logger
from .constants import (
    LOCKFILE_PATTERNS,
    GOVERNANCE_FILES,
    DESIGN_DOCS,
    API_DOCS,
    SECURITY_DOCS,
)
from .helpers import (
    gh_api,
    gh_api_safe,
    file_exists,
    read_file,
    result,
)

logger = get_logger("checks.level2")


def check_level2_access_control(owner: str, repo: str, local_path: str) -> List[Dict]:
    """Check Level 2 Access Control requirements."""
    results = []
    workflow_dir = os.path.join(local_path, ".github", "workflows")

    # OSPS-AC-04.01: CI/CD default to lowest permissions
    if os.path.exists(workflow_dir):
        has_permissions_defined = False
        for root, _, files in os.walk(workflow_dir):
            for file in files:
                if file.endswith(('.yml', '.yaml')):
                    content = read_file(root, file) or ""
                    if re.search(r'^permissions:', content, re.MULTILINE):
                        has_permissions_defined = True
                        break

        if has_permissions_defined:
            results.append(result("OSPS-AC-04.01", "PASS", "Workflows define explicit permissions.", level=2))
        else:
            results.append(result("OSPS-AC-04.01", "FAIL", "Workflows should define explicit permissions.", level=2))
    else:
        results.append(result("OSPS-AC-04.01", "N/A", "No workflows found.", level=2))

    return results


def check_level2_build_release(owner: str, repo: str, local_path: str) -> List[Dict]:
    """Check Level 2 Build & Release requirements."""
    results = []

    try:
        releases = gh_api(f"/repos/{owner}/{repo}/releases?per_page=5")

        # OSPS-BR-02.01: Unique version identifiers
        if releases:
            versions = [r.get("tag_name") for r in releases if r.get("tag_name")]
            if len(versions) == len(set(versions)):
                results.append(result("OSPS-BR-02.01", "PASS", f"Releases have unique versions: {', '.join(versions[:3])}", level=2))
            else:
                results.append(result("OSPS-BR-02.01", "FAIL", "Duplicate version identifiers found.", level=2))
        else:
            results.append(result("OSPS-BR-02.01", "N/A", "No releases found.", level=2))

        # OSPS-BR-04.01: Release contains changelog
        if releases and releases[0].get("body"):
            results.append(result("OSPS-BR-04.01", "PASS", "Latest release has release notes.", level=2))
        elif releases:
            results.append(result("OSPS-BR-04.01", "FAIL", "Latest release has no release notes.", level=2))
        else:
            results.append(result("OSPS-BR-04.01", "N/A", "No releases found.", level=2))

        # OSPS-BR-06.01: Signed releases or manifest with hashes
        if releases:
            latest = releases[0]
            assets = latest.get("assets", [])
            has_signature = any(a.get("name", "").endswith((".sig", ".asc", ".gpg")) for a in assets)
            has_checksum = any(a.get("name", "").endswith((".sha256", ".sha512", "checksums.txt", "SHASUMS")) for a in assets)

            if has_signature or has_checksum:
                results.append(result("OSPS-BR-06.01", "PASS", "Release has signatures or checksums.", level=2))
            else:
                results.append(result("OSPS-BR-06.01", "FAIL", "Release lacks signatures/checksums.", level=2))
        else:
            results.append(result("OSPS-BR-06.01", "N/A", "No releases found.", level=2))

    except (RuntimeError, KeyError, TypeError, AttributeError) as e:
        logger.debug(f"Could not check releases: {type(e).__name__}: {e}")
        results.append(result("OSPS-BR-02.01", "ERROR", f"Could not check releases: {str(e)}", level=2))
        results.append(result("OSPS-BR-04.01", "ERROR", f"Could not check releases: {str(e)}", level=2))
        results.append(result("OSPS-BR-06.01", "ERROR", f"Could not check releases: {str(e)}", level=2))

    # OSPS-BR-05.01: Standardized dependency tooling
    has_lockfile = file_exists(local_path, *LOCKFILE_PATTERNS)
    if has_lockfile:
        results.append(result("OSPS-BR-05.01", "PASS", "Uses standardized dependency tooling (lockfile found).", level=2))
    else:
        results.append(result("OSPS-BR-05.01", "FAIL", "No lockfile found (package-lock.json, yarn.lock, etc.). Dependencies are not pinned.", level=2))

    return results


def check_level2_documentation(owner: str, repo: str, local_path: str) -> List[Dict]:
    """Check Level 2 Documentation requirements."""
    results = []

    # OSPS-DO-06.01: Dependency management documentation
    has_dependencies_doc = file_exists(local_path, "DEPENDENCIES.md", "docs/DEPENDENCIES.md", "DEPENDENCIES.rst")

    if has_dependencies_doc:
        results.append(result("OSPS-DO-06.01", "PASS", "Dependency management documented in DEPENDENCIES.md.", level=2))
    else:
        # Fall back to checking README/CONTRIBUTING for dependency info
        readme = read_file(local_path, "README.md") or ""
        contributing = read_file(local_path, "CONTRIBUTING.md") or ""
        all_docs = readme + contributing

        if re.search(r'(dependenc|package|install|requirements)', all_docs, re.IGNORECASE):
            results.append(result("OSPS-DO-06.01", "PASS", "Documentation mentions dependency management.", level=2))
        else:
            results.append(result("OSPS-DO-06.01", "WARN", "Dependency management process not clearly documented.", level=2))

    return results


def check_level2_governance(owner: str, repo: str, local_path: str) -> List[Dict]:
    """Check Level 2 Governance requirements."""
    results = []

    # OSPS-GV-01.01: List of members with sensitive access
    # OSPS-GV-01.02: Roles and responsibilities
    has_governance = any(file_exists(local_path, f) for f in GOVERNANCE_FILES)

    if has_governance:
        results.append(result("OSPS-GV-01.01", "PASS", "Governance/maintainers documentation found.", level=2))
        results.append(result("OSPS-GV-01.02", "PASS", "Roles documentation found.", level=2))
    else:
        results.append(result("OSPS-GV-01.01", "FAIL", "No GOVERNANCE.md, MAINTAINERS.md, or CODEOWNERS found.", level=2))
        results.append(result("OSPS-GV-01.02", "FAIL", "No roles/responsibilities documentation found.", level=2))

    # OSPS-GV-03.02: Contribution requirements
    contributing = read_file(local_path, "CONTRIBUTING.md") or ""
    if re.search(r'(requirement|guideline|standard|convention|must|should)', contributing, re.IGNORECASE):
        results.append(result("OSPS-GV-03.02", "PASS", "CONTRIBUTING.md includes contribution requirements.", level=2))
    elif contributing:
        results.append(result("OSPS-GV-03.02", "WARN", "CONTRIBUTING.md exists but may lack detailed requirements.", level=2))
    else:
        results.append(result("OSPS-GV-03.02", "FAIL", "No CONTRIBUTING.md with requirements found.", level=2))

    return results


def check_level2_legal(owner: str, repo: str, local_path: str) -> List[Dict]:
    """Check Level 2 Legal requirements."""
    results = []

    # OSPS-LE-01.01: DCO/CLA requirement
    has_dco = file_exists(local_path, "DCO", "DCO.md", ".github/DCO")
    has_cla = file_exists(local_path, "CLA", "CLA.md", ".github/CLA")

    # Check for DCO GitHub App config file
    has_dco_config = file_exists(local_path, ".github/dco.yml", ".github/dco.yaml")

    # Check for DCO bot or CLA bot in workflows
    workflow_dir = os.path.join(local_path, ".github", "workflows")
    has_dco_check = False
    if os.path.exists(workflow_dir):
        for root, _, files in os.walk(workflow_dir):
            for file in files:
                if file.endswith(('.yml', '.yaml')):
                    content = read_file(root, file) or ""
                    if "dco" in content.lower() or "cla" in content.lower() or "signed-off-by" in content.lower():
                        has_dco_check = True
                        break

    # Check CONTRIBUTING.md for DCO/CLA references
    has_dco_in_contributing = False
    contributing_content = read_file(local_path, "CONTRIBUTING.md") or ""
    if contributing_content:
        content_lower = contributing_content.lower()
        if any(marker in content_lower for marker in [
            "signed-off-by", "sign-off", "signoff",
            "developer certificate of origin", "dco",
            "git commit -s", "commit -s -m",
            "contributor license agreement", "cla"
        ]):
            has_dco_in_contributing = True

    if has_dco or has_cla or has_dco_check or has_dco_config or has_dco_in_contributing:
        results.append(result("OSPS-LE-01.01", "PASS", "DCO or CLA requirement found.", level=2))
    else:
        results.append(result("OSPS-LE-01.01", "FAIL", "No DCO/CLA requirement for contributions.", level=2))

    return results


def check_level2_quality(owner: str, repo: str, local_path: str, default_branch: str) -> List[Dict]:
    """Check Level 2 Quality Assurance requirements."""
    results = []

    # OSPS-QA-03.01: Status checks must pass
    try:
        protection = gh_api_safe(f"/repos/{owner}/{repo}/branches/{default_branch}/protection")
        if protection and protection.get("required_status_checks"):
            contexts = protection["required_status_checks"].get("contexts", [])
            results.append(result("OSPS-QA-03.01", "PASS", f"Required status checks: {', '.join(contexts) or 'enabled'}", level=2))
        elif protection:
            results.append(result("OSPS-QA-03.01", "FAIL", "Branch protection exists but no required status checks.", level=2))
        else:
            results.append(result("OSPS-QA-03.01", "FAIL", "No branch protection with status checks.", level=2))
    except (RuntimeError, KeyError, TypeError, AttributeError) as e:
        logger.debug(f"Could not verify status check requirements: {type(e).__name__}: {e}")
        results.append(result("OSPS-QA-03.01", "WARN", "Could not verify status check requirements.", level=2))

    # OSPS-QA-06.01: Automated test suite in CI
    workflow_dir = os.path.join(local_path, ".github", "workflows")
    has_tests = False
    if os.path.exists(workflow_dir):
        for root, _, files in os.walk(workflow_dir):
            for file in files:
                if file.endswith(('.yml', '.yaml')):
                    content = read_file(root, file) or ""
                    if re.search(r'(npm test|yarn test|pytest|jest|mocha|rspec|go test|cargo test|mvn test|gradle test)', content, re.IGNORECASE):
                        has_tests = True
                        break

    if has_tests:
        results.append(result("OSPS-QA-06.01", "PASS", "CI workflows include automated tests.", level=2))
    elif os.path.exists(workflow_dir):
        results.append(result("OSPS-QA-06.01", "FAIL",
            "CI workflows exist but no test commands found (npm test, pytest, etc.).", level=2))
    else:
        results.append(result("OSPS-QA-06.01", "FAIL",
            "No CI workflows found. Add GitHub Actions with automated tests.", level=2))

    return results


def check_level2_security_architecture(owner: str, repo: str, local_path: str) -> List[Dict]:
    """Check Level 2 Security Architecture requirements."""
    results = []

    # OSPS-SA-01.01: Design documentation
    has_design = any(file_exists(local_path, d) for d in DESIGN_DOCS)

    if has_design:
        results.append(result("OSPS-SA-01.01", "PASS", "Architecture/design documentation found.", level=2))
    else:
        results.append(result("OSPS-SA-01.01", "FAIL",
            "No architecture documentation found. Create ARCHITECTURE.md, DESIGN.md, or docs/architecture/.", level=2))

    # OSPS-SA-02.01: External interface documentation
    has_api_docs = any(file_exists(local_path, d) for d in API_DOCS)

    if has_api_docs:
        results.append(result("OSPS-SA-02.01", "PASS", "API/interface documentation found.", level=2))
    else:
        results.append(result("OSPS-SA-02.01", "FAIL",
            "No API/interface documentation found. Create API.md, docs/api/, or openapi.yaml.", level=2))

    # OSPS-SA-03.01: Security assessment
    has_security_assessment = any(file_exists(local_path, d) for d in SECURITY_DOCS)

    security_content = read_file(local_path, "SECURITY.md") or ""
    has_assessment = re.search(r'(threat|risk|assessment|vulnerability|attack)', security_content, re.IGNORECASE)

    if has_assessment:
        results.append(result("OSPS-SA-03.01", "PASS", "Security assessment documentation found.", level=2))
    elif has_security_assessment:
        results.append(result("OSPS-SA-03.01", "WARN", "SECURITY.md exists but may lack threat assessment.", level=2))
    else:
        results.append(result("OSPS-SA-03.01", "FAIL", "No security assessment documentation found.", level=2))

    return results


def check_level2_vulnerability(owner: str, repo: str, local_path: str) -> List[Dict]:
    """Check Level 2 Vulnerability Management requirements."""
    results = []

    security_content = read_file(local_path, "SECURITY.md") or ""

    # OSPS-VM-01.01: CVD policy with timeframe
    if re.search(r'(disclosure|response|timeframe|\d+\s*days)', security_content, re.IGNORECASE):
        results.append(result("OSPS-VM-01.01", "PASS", "SECURITY.md includes disclosure policy.", level=2))
    elif security_content:
        # SECURITY.md exists but missing timeframe - this is a specific deficiency
        results.append(result("OSPS-VM-01.01", "FAIL",
            "SECURITY.md exists but lacks disclosure timeframe. Add response timeline (e.g., '48 hours', '90 days').", level=2))
    else:
        results.append(result("OSPS-VM-01.01", "FAIL", "No coordinated vulnerability disclosure policy. Create SECURITY.md.", level=2))

    # OSPS-VM-03.01: Private vulnerability reporting
    try:
        repo_data = gh_api(f"/repos/{owner}/{repo}")

        # Check SECURITY.md for private reporting mechanism
        has_private_contact = re.search(
            r'(private|confidential|email|pgp|gpg|security@|privately)',
            security_content,
            re.IGNORECASE
        )

        if has_private_contact:
            results.append(result("OSPS-VM-03.01", "PASS", "Private vulnerability reporting mechanism documented.", level=2))
        elif security_content:
            results.append(result("OSPS-VM-03.01", "FAIL",
                "SECURITY.md exists but lacks private reporting method. Add email or PGP key.", level=2))
        else:
            results.append(result("OSPS-VM-03.01", "FAIL",
                "No private vulnerability reporting mechanism. Create SECURITY.md with security contact.", level=2))
    except (RuntimeError, KeyError, TypeError, AttributeError) as e:
        # API error - this is a true WARN case
        logger.debug(f"Could not verify private reporting: {type(e).__name__}: {e}")
        results.append(result("OSPS-VM-03.01", "WARN", f"Could not verify private reporting: {str(e)[:50]}", level=2))

    # OSPS-VM-04.01: Public vulnerability data (security advisories)
    try:
        # Check if security advisories are enabled via repository settings
        repo_data = gh_api_safe(f"/repos/{owner}/{repo}")
        if repo_data:
            has_issues = repo_data.get("has_issues", False)
            # Security advisories require issues to be enabled
            # Also check if there are any published advisories
            advisories = gh_api_safe(f"/repos/{owner}/{repo}/security-advisories")

            if advisories is not None:
                results.append(result("OSPS-VM-04.01", "PASS",
                    f"Security advisories enabled ({len(advisories)} published).", level=2))
            elif has_issues:
                # Can't access advisories but issues are enabled, might just be no advisories yet
                results.append(result("OSPS-VM-04.01", "PASS",
                    "Repository supports security advisories (none published yet).", level=2))
            else:
                results.append(result("OSPS-VM-04.01", "FAIL",
                    "Issues disabled - security advisories require issues to be enabled.", level=2))
        else:
            results.append(result("OSPS-VM-04.01", "WARN", "Could not access repository settings.", level=2))
    except (RuntimeError, KeyError, TypeError, AttributeError) as e:
        logger.debug(f"Could not verify advisories: {type(e).__name__}: {e}")
        results.append(result("OSPS-VM-04.01", "WARN", f"Could not verify advisories: {str(e)[:50]}", level=2))

    return results


def run_all_level2_checks(
    owner: str, repo: str, local_path: str, default_branch: str
) -> List[Dict]:
    """Run all Level 2 checks and return combined results."""
    results = []
    results.extend(check_level2_access_control(owner, repo, local_path))
    results.extend(check_level2_build_release(owner, repo, local_path))
    results.extend(check_level2_documentation(owner, repo, local_path))
    results.extend(check_level2_governance(owner, repo, local_path))
    results.extend(check_level2_legal(owner, repo, local_path))
    results.extend(check_level2_quality(owner, repo, local_path, default_branch))
    results.extend(check_level2_security_architecture(owner, repo, local_path))
    results.extend(check_level2_vulnerability(owner, repo, local_path))
    return results


__all__ = [
    "check_level2_access_control",
    "check_level2_build_release",
    "check_level2_documentation",
    "check_level2_governance",
    "check_level2_legal",
    "check_level2_quality",
    "check_level2_security_architecture",
    "check_level2_vulnerability",
    "run_all_level2_checks",
]
