"""OpenSSF Baseline Level 1 check functions (24 controls).

Level 1 represents the baseline security requirements for open source projects.
"""

import glob as glob_module
import os
import re

from darnit.core.logging import get_logger

from .constants import (
    BINARY_EXTENSIONS,
    DANGEROUS_CONTEXTS,
    DANGEROUS_SECRET_FILES,
    DEPENDENCY_FILES,
    OSI_LICENSES,
)
from .helpers import (
    file_contains,
    file_exists,
    gh_api,
    gh_api_safe,
    read_file,
    result,
)

logger = get_logger("checks.level1")


def check_level1_access_control(
    owner: str, repo: str, local_path: str, default_branch: str
) -> list[dict]:
    """Check Level 1 Access Control requirements."""
    results = []

    # OSPS-AC-01.01: MFA requirement
    # Check if owner is an org or user, and verify MFA settings
    try:
        # First check if it's a user or org
        user_data = gh_api_safe(f"/users/{owner}")
        if user_data and user_data.get("type") == "User":
            # Personal accounts - check if user has 2FA enabled via authenticated user endpoint
            # Note: We can't check other users' 2FA status, only orgs
            results.append(result("OSPS-AC-01.01", "WARN",
                f"Owner '{owner}' is a personal account. MFA status cannot be verified via API. "
                "Verify account has 2FA enabled in GitHub settings."))
        else:
            # It's an organization - check org MFA requirement
            org_data = gh_api_safe(f"/orgs/{owner}")
            if org_data:
                mfa_required = org_data.get("two_factor_requirement_enabled")
                if mfa_required is True:
                    results.append(result("OSPS-AC-01.01", "PASS", "Organization requires MFA for all members."))
                elif mfa_required is False:
                    results.append(result("OSPS-AC-01.01", "FAIL",
                        f"Organization '{owner}' does NOT require MFA. Enable at: Settings → Authentication security"))
                else:
                    # null means we don't have permission to see this setting (not an org member)
                    results.append(result("OSPS-AC-01.01", "WARN",
                        f"Cannot verify MFA requirement for org '{owner}' (requires org member access). "
                        "Verify MFA is required in org settings."))
            else:
                results.append(result("OSPS-AC-01.01", "WARN",
                    f"Could not determine if '{owner}' is a user or organization."))
    except (RuntimeError, KeyError, TypeError, AttributeError) as e:
        logger.debug(f"Cannot verify MFA requirement: {type(e).__name__}: {e}")
        results.append(result("OSPS-AC-01.01", "WARN", f"Cannot verify MFA requirement: {str(e)}"))

    # OSPS-AC-02.01: Default collaborator permissions
    try:
        repo_data = gh_api(f"/repos/{owner}/{repo}")
        if repo_data.get("allow_forking", True):
            results.append(result("OSPS-AC-02.01", "PASS", "Repository allows forking (public collaboration model)."))
        else:
            results.append(result("OSPS-AC-02.01", "WARN", "Verify default collaborator permissions are minimal."))
    except (RuntimeError, KeyError, TypeError, AttributeError) as e:
        logger.debug(f"Could not check permissions: {type(e).__name__}: {e}")
        results.append(result("OSPS-AC-02.01", "ERROR", f"Could not check permissions: {str(e)}"))

    # OSPS-AC-03.01: Prevent direct commits to primary branch
    try:
        protection = gh_api(f"/repos/{owner}/{repo}/branches/{default_branch}/protection")
        if protection.get("required_pull_request_reviews") or protection.get("restrictions"):
            results.append(result("OSPS-AC-03.01", "PASS", f"Direct commits to '{default_branch}' are restricted."))
        else:
            results.append(result("OSPS-AC-03.01", "FAIL", "Branch protection exists but doesn't prevent direct commits."))
    except RuntimeError as e:
        if "404" in str(e):
            results.append(result("OSPS-AC-03.01", "FAIL", f"Branch '{default_branch}' is not protected."))
        else:
            results.append(result("OSPS-AC-03.01", "ERROR", str(e)))

    # OSPS-AC-03.02: Prevent deletion of primary branch
    try:
        protection = gh_api_safe(f"/repos/{owner}/{repo}/branches/{default_branch}/protection")
        if protection and not protection.get("allow_deletions", {}).get("enabled", True):
            results.append(result("OSPS-AC-03.02", "PASS", f"Deletion of '{default_branch}' is prevented."))
        elif protection:
            results.append(result("OSPS-AC-03.02", "FAIL", f"Branch '{default_branch}' can be deleted."))
        else:
            results.append(result("OSPS-AC-03.02", "FAIL", f"No protection rules for '{default_branch}'."))
    except (RuntimeError, KeyError, TypeError, AttributeError) as e:
        logger.debug(f"Could not verify branch deletion protection: {type(e).__name__}: {e}")
        results.append(result("OSPS-AC-03.02", "WARN", "Could not verify branch deletion protection."))

    return results


def check_level1_build_release(owner: str, repo: str, local_path: str) -> list[dict]:
    """Check Level 1 Build & Release requirements."""
    results = []
    workflow_dir = os.path.join(local_path, ".github", "workflows")

    # OSPS-BR-01.01: CI/CD input parameter sanitization
    # OSPS-BR-01.02: Branch name sanitization
    injection_risks = []
    branch_name_risks = []

    if os.path.exists(workflow_dir):
        for root, _, files in os.walk(workflow_dir):
            for file in files:
                if file.endswith(('.yml', '.yaml')):
                    filepath = os.path.join(root, file)
                    try:
                        with open(filepath) as f:
                            content = f.read()
                            lines = content.splitlines()

                        in_run_block = False
                        for i, line in enumerate(lines):
                            stripped = line.strip()

                            # Track when we're in a run: block (multi-line scripts)
                            if "run:" in stripped and not stripped.startswith("#"):
                                in_run_block = True
                            elif stripped.startswith("- name:") or stripped.startswith("- uses:"):
                                in_run_block = False
                            elif stripped and not stripped.startswith("-") and not stripped.startswith("#"):
                                if ":" in stripped and not in_run_block:
                                    in_run_block = False

                            # Only check for injection in run: blocks (shell context)
                            is_shell_context = in_run_block and ("run:" in stripped or "${{" in line)

                            if is_shell_context and "${{" in line:
                                # Check for dangerous contexts in shell scripts
                                if any(ctx in line for ctx in DANGEROUS_CONTEXTS):
                                    injection_risks.append(f"{file}:{i+1}")

                                # Branch names are dangerous ONLY in shell context
                                if "github.head_ref" in line or "github.ref_name" in line:
                                    branch_name_risks.append(f"{file}:{i+1}")

                    except OSError as e:
                        logger.debug(f"Could not read workflow {filepath}: {type(e).__name__}")
                        continue

        if not injection_risks:
            results.append(result("OSPS-BR-01.01", "PASS", "No obvious input injection vulnerabilities in workflows."))
        else:
            results.append(result("OSPS-BR-01.01", "WARN", f"Potential injection risks: {', '.join(injection_risks[:3])}"))

        if not branch_name_risks:
            results.append(result("OSPS-BR-01.02", "PASS", "Branch names appear to be safely handled in workflows."))
        else:
            results.append(result("OSPS-BR-01.02", "WARN", f"Branch name injection risks: {', '.join(branch_name_risks[:3])}"))
    else:
        results.append(result("OSPS-BR-01.01", "N/A", "No GitHub Actions workflows found."))
        results.append(result("OSPS-BR-01.02", "N/A", "No GitHub Actions workflows found."))

    # OSPS-BR-03.01: Official URIs use HTTPS
    # OSPS-BR-03.02: Distribution URIs use HTTPS
    try:
        repo_data = gh_api(f"/repos/{owner}/{repo}")
        homepage = repo_data.get("homepage", "")
        html_url = repo_data.get("html_url", "")

        if html_url.startswith("https://"):
            results.append(result("OSPS-BR-03.01", "PASS", "Repository URL uses HTTPS."))
        else:
            results.append(result("OSPS-BR-03.01", "FAIL", "Repository URL does not use HTTPS."))

        if not homepage or homepage.startswith("https://"):
            results.append(result("OSPS-BR-03.02", "PASS", "Homepage/distribution URL uses HTTPS (or not set)."))
        else:
            results.append(result("OSPS-BR-03.02", "FAIL", f"Homepage uses non-HTTPS: {homepage}"))
    except (RuntimeError, KeyError, TypeError, AttributeError) as e:
        logger.debug(f"Could not verify URL encryption: {type(e).__name__}: {e}")
        results.append(result("OSPS-BR-03.01", "WARN", "Could not verify URL encryption."))
        results.append(result("OSPS-BR-03.02", "WARN", "Could not verify distribution URL encryption."))

    # OSPS-BR-07.01: Prevent unencrypted secrets in VCS
    secrets_found = []
    gitignore_exists = file_exists(local_path, ".gitignore")
    env_in_gitignore = False

    if gitignore_exists:
        gitignore_content = read_file(local_path, ".gitignore") or ""
        env_in_gitignore = ".env" in gitignore_content or "*.env" in gitignore_content

    # Check for common secret files
    for df in DANGEROUS_SECRET_FILES:
        if file_exists(local_path, df):
            secrets_found.append(df)

    if not secrets_found and (gitignore_exists and env_in_gitignore):
        results.append(result("OSPS-BR-07.01", "PASS", "Secret files appear to be gitignored."))
    elif secrets_found:
        results.append(result("OSPS-BR-07.01", "FAIL", f"Potential secrets in repo: {', '.join(secrets_found[:3])}"))
    else:
        results.append(result("OSPS-BR-07.01", "WARN", "Verify .gitignore excludes secret files (.env, credentials, etc.)."))

    return results


def check_level1_documentation(owner: str, repo: str, local_path: str) -> list[dict]:
    """Check Level 1 Documentation requirements."""
    results = []

    try:
        community = gh_api(f"/repos/{owner}/{repo}/community/profile")
        files = community.get("files", {})

        # OSPS-DO-01.01: User guides (README)
        if files.get("readme"):
            results.append(result("OSPS-DO-01.01", "PASS", "README detected with user documentation."))
        else:
            results.append(result("OSPS-DO-01.01", "FAIL", "No README found."))

        # OSPS-DO-02.01: Defect reporting guide
        issue_template = files.get("issue_template")
        has_bug_template = file_exists(local_path, ".github/ISSUE_TEMPLATE/bug*.md", ".github/ISSUE_TEMPLATE/bug*.yml")

        if issue_template or has_bug_template:
            results.append(result("OSPS-DO-02.01", "PASS", "Issue/bug reporting template found."))
        else:
            # Check if README mentions how to report issues
            readme_content = read_file(local_path, "README.md") or ""
            if re.search(r'(bug|issue|report|defect)', readme_content, re.IGNORECASE):
                results.append(result("OSPS-DO-02.01", "WARN", "README may contain reporting info. Verify manually."))
            else:
                results.append(result("OSPS-DO-02.01", "FAIL", "No defect reporting guide found."))

    except (RuntimeError, KeyError, TypeError, AttributeError) as e:
        logger.debug(f"Could not check documentation: {type(e).__name__}: {e}")
        results.append(result("OSPS-DO-01.01", "ERROR", f"Could not check documentation: {str(e)}"))
        results.append(result("OSPS-DO-02.01", "ERROR", f"Could not check documentation: {str(e)}"))

    return results


def check_level1_governance(owner: str, repo: str, local_path: str) -> list[dict]:
    """Check Level 1 Governance requirements."""
    results = []

    try:
        community = gh_api(f"/repos/{owner}/{repo}/community/profile")
        files = community.get("files", {})
        repo_data = gh_api(f"/repos/{owner}/{repo}")

        # OSPS-GV-02.01: Public discussion mechanisms
        has_issues = repo_data.get("has_issues", False)
        has_discussions = repo_data.get("has_discussions", False)

        if has_issues or has_discussions:
            mechanisms = []
            if has_issues:
                mechanisms.append("Issues")
            if has_discussions:
                mechanisms.append("Discussions")
            results.append(result("OSPS-GV-02.01", "PASS", f"Public discussion via: {', '.join(mechanisms)}"))
        else:
            results.append(result("OSPS-GV-02.01", "FAIL", "No public discussion mechanism (Issues/Discussions disabled)."))

        # OSPS-GV-03.01: Contribution process explanation
        # First check GitHub's community profile API
        if files.get("contributing"):
            results.append(result("OSPS-GV-03.01", "PASS", "CONTRIBUTING.md detected."))
        else:
            # Fallback to local filesystem check (API may not detect all files)
            has_contributing = file_exists(
                local_path,
                "CONTRIBUTING.md",
                ".github/CONTRIBUTING.md",
                "docs/CONTRIBUTING.md",
                "CONTRIBUTING",
                "CONTRIBUTING.rst",
                "CONTRIBUTING.txt",
            )
            if has_contributing:
                results.append(result("OSPS-GV-03.01", "PASS", "CONTRIBUTING file found locally."))
            else:
                results.append(result("OSPS-GV-03.01", "FAIL", "No CONTRIBUTING.md found."))

    except (RuntimeError, KeyError, TypeError, AttributeError) as e:
        logger.debug(f"Could not check governance: {type(e).__name__}: {e}")
        results.append(result("OSPS-GV-02.01", "ERROR", f"Could not check governance: {str(e)}"))
        results.append(result("OSPS-GV-03.01", "ERROR", f"Could not check governance: {str(e)}"))

    return results


def check_level1_legal(owner: str, repo: str, local_path: str) -> list[dict]:
    """Check Level 1 Legal requirements."""
    results = []

    try:
        repo_data = gh_api(f"/repos/{owner}/{repo}")
        license_info = repo_data.get("license")

        # OSPS-LE-02.01: OSI-approved license for source
        # OSPS-LE-02.02: OSI-approved license for releases
        detected_license = None

        if license_info:
            spdx_id = license_info.get("spdx_id", "").lower()
            if spdx_id in OSI_LICENSES:
                detected_license = spdx_id
                results.append(result("OSPS-LE-02.01", "PASS", f"OSI-approved license: {spdx_id}"))
                results.append(result("OSPS-LE-02.02", "PASS", f"Release license: {spdx_id}"))
            elif spdx_id == "noassertion":
                results.append(result("OSPS-LE-02.01", "WARN", "License exists but not recognized. Verify manually."))
                results.append(result("OSPS-LE-02.02", "WARN", "License exists but not recognized. Verify manually."))
            else:
                results.append(result("OSPS-LE-02.01", "FAIL", f"License '{spdx_id}' may not be OSI-approved."))
                results.append(result("OSPS-LE-02.02", "FAIL", f"License '{spdx_id}' may not be OSI-approved."))
        else:
            # Fallback: GitHub API didn't detect license, check local files
            license_content = None
            for license_file in ["LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING", "license"]:
                content = read_file(local_path, license_file)
                if content:
                    license_content = content
                    break

            if license_content:
                # Try to detect common OSI licenses from content
                content_lower = license_content.lower()
                if "apache license" in content_lower and "version 2.0" in content_lower:
                    detected_license = "apache-2.0"
                elif "mit license" in content_lower or "permission is hereby granted, free of charge" in content_lower:
                    detected_license = "mit"
                elif "gnu general public license" in content_lower:
                    if "version 3" in content_lower:
                        detected_license = "gpl-3.0"
                    elif "version 2" in content_lower:
                        detected_license = "gpl-2.0"
                elif "bsd" in content_lower and "3-clause" in content_lower:
                    detected_license = "bsd-3-clause"
                elif "bsd" in content_lower and "2-clause" in content_lower:
                    detected_license = "bsd-2-clause"
                elif "mozilla public license" in content_lower and "2.0" in content_lower:
                    detected_license = "mpl-2.0"
                elif "isc license" in content_lower:
                    detected_license = "isc"

                if detected_license and detected_license in OSI_LICENSES:
                    results.append(result("OSPS-LE-02.01", "PASS", f"OSI-approved license detected locally: {detected_license}"))
                    results.append(result("OSPS-LE-02.02", "PASS", f"Release license: {detected_license}"))
                else:
                    # License file exists but couldn't identify the type
                    results.append(result("OSPS-LE-02.01", "WARN", "LICENSE file found but type not auto-detected. Verify manually."))
                    results.append(result("OSPS-LE-02.02", "WARN", "LICENSE file found but type not auto-detected. Verify manually."))
            else:
                results.append(result("OSPS-LE-02.01", "FAIL", "No license detected."))
                results.append(result("OSPS-LE-02.02", "FAIL", "No license detected."))

        # OSPS-LE-03.01: License file in repository
        # OSPS-LE-03.02: License in releases
        has_license_file = file_exists(local_path, "LICENSE", "LICENSE.*", "COPYING", "COPYING.*", "LICENSE/*")
        if has_license_file:
            results.append(result("OSPS-LE-03.01", "PASS", "LICENSE file found in repository."))
            results.append(result("OSPS-LE-03.02", "PASS", "LICENSE file present (will be in releases)."))
        else:
            results.append(result("OSPS-LE-03.01", "FAIL", "No LICENSE/COPYING file found."))
            results.append(result("OSPS-LE-03.02", "FAIL", "No LICENSE file to include in releases."))

    except (RuntimeError, KeyError, TypeError, AttributeError) as e:
        logger.debug(f"Could not check license: {type(e).__name__}: {e}")
        results.append(result("OSPS-LE-02.01", "ERROR", f"Could not check license: {str(e)}"))
        results.append(result("OSPS-LE-02.02", "ERROR", f"Could not check license: {str(e)}"))
        results.append(result("OSPS-LE-03.01", "ERROR", f"Could not check license: {str(e)}"))
        results.append(result("OSPS-LE-03.02", "ERROR", f"Could not check license: {str(e)}"))

    return results


def check_level1_quality(owner: str, repo: str, local_path: str) -> list[dict]:
    """Check Level 1 Quality Assurance requirements."""
    results = []

    try:
        repo_data = gh_api(f"/repos/{owner}/{repo}")

        # OSPS-QA-01.01: Public readable repository
        # OSPS-QA-01.02: Public commit history
        is_private = repo_data.get("private", True)
        if not is_private:
            results.append(result("OSPS-QA-01.01", "PASS", "Repository is publicly readable."))
            results.append(result("OSPS-QA-01.02", "PASS", "Commit history is publicly visible."))
        else:
            results.append(result("OSPS-QA-01.01", "FAIL", "Repository is private."))
            results.append(result("OSPS-QA-01.02", "FAIL", "Commit history not publicly visible."))

    except (RuntimeError, KeyError, TypeError, AttributeError) as e:
        logger.debug(f"Could not check visibility: {type(e).__name__}: {e}")
        results.append(result("OSPS-QA-01.01", "ERROR", f"Could not check visibility: {str(e)}"))
        results.append(result("OSPS-QA-01.02", "ERROR", f"Could not check visibility: {str(e)}"))

    # OSPS-QA-02.01: Dependency list for direct dependencies
    found_dep_files = [f for f in DEPENDENCY_FILES if file_exists(local_path, f)]
    if found_dep_files:
        results.append(result("OSPS-QA-02.01", "PASS", f"Dependency files found: {', '.join(found_dep_files[:3])}"))
    else:
        results.append(result("OSPS-QA-02.01", "WARN", "No standard dependency manifest found."))

    # OSPS-QA-04.01: List of subprojects
    has_subprojects = file_exists(local_path, "packages/*", "apps/*", "modules/*", "workspaces/*")
    has_subproject_docs = file_contains(local_path, ["README.md"], r"(subproject|workspace|package|monorepo)")

    if not has_subprojects:
        results.append(result("OSPS-QA-04.01", "N/A", "No subprojects detected (single-project repo)."))
    elif has_subproject_docs:
        results.append(result("OSPS-QA-04.01", "PASS", "Subprojects documented in README."))
    else:
        results.append(result("OSPS-QA-04.01", "WARN", "Subprojects exist but may not be documented."))

    # OSPS-QA-05.01: No generated executables in VCS
    # OSPS-QA-05.02: No unreviewable binaries
    binary_files = []
    for ext in BINARY_EXTENSIONS:
        matches = glob_module.glob(os.path.join(local_path, f"**/*{ext}"), recursive=True)
        # Exclude common acceptable locations
        for m in matches:
            if not any(skip in m for skip in [".git", "node_modules", "vendor", "__pycache__", "venv", ".venv"]):
                binary_files.append(os.path.basename(m))

    if not binary_files:
        results.append(result("OSPS-QA-05.01", "PASS", "No generated executables found in repository."))
        results.append(result("OSPS-QA-05.02", "PASS", "No unreviewable binary artifacts found."))
    else:
        results.append(result("OSPS-QA-05.01", "FAIL", f"Binary files found: {', '.join(binary_files[:5])}"))
        results.append(result("OSPS-QA-05.02", "FAIL", f"Unreviewable binaries: {', '.join(binary_files[:5])}"))

    return results


def check_level1_vulnerability(owner: str, repo: str, local_path: str) -> list[dict]:
    """Check Level 1 Vulnerability Management requirements."""
    results = []

    # OSPS-VM-02.01: Security contacts / SECURITY.md
    has_security_file = file_exists(
        local_path, "SECURITY.md", "SECURITY", "SECURITY.rst",
        ".github/SECURITY.md", "docs/SECURITY.md"
    )

    if has_security_file:
        # Verify it has contact/reporting info
        security_content = (
            read_file(local_path, "SECURITY.md") or
            read_file(local_path, ".github/SECURITY.md") or
            read_file(local_path, "docs/SECURITY.md") or ""
        )
        if re.search(r'(report|contact|email|security@|vulnerability|disclose)', security_content, re.IGNORECASE):
            results.append(result("OSPS-VM-02.01", "PASS", "SECURITY.md with reporting instructions found."))
        else:
            results.append(result("OSPS-VM-02.01", "WARN", "SECURITY.md exists but may lack reporting instructions."))
    else:
        # Fall back to GitHub API community profile check
        try:
            community = gh_api(f"/repos/{owner}/{repo}/community/profile")
            files = community.get("files", {})
            if files.get("security"):
                results.append(result("OSPS-VM-02.01", "PASS", "SECURITY.md detected via GitHub."))
            else:
                results.append(result("OSPS-VM-02.01", "FAIL", "No SECURITY.md found."))
        except (RuntimeError, KeyError, TypeError, AttributeError) as e:
            logger.debug(f"Could not check SECURITY.md via API: {type(e).__name__}: {e}")
            results.append(result("OSPS-VM-02.01", "FAIL", "No SECURITY.md found locally or via API."))

    return results


def run_all_level1_checks(
    owner: str, repo: str, local_path: str, default_branch: str
) -> list[dict]:
    """Run all Level 1 checks and return combined results."""
    results = []
    results.extend(check_level1_access_control(owner, repo, local_path, default_branch))
    results.extend(check_level1_build_release(owner, repo, local_path))
    results.extend(check_level1_documentation(owner, repo, local_path))
    results.extend(check_level1_governance(owner, repo, local_path))
    results.extend(check_level1_legal(owner, repo, local_path))
    results.extend(check_level1_quality(owner, repo, local_path))
    results.extend(check_level1_vulnerability(owner, repo, local_path))
    return results


__all__ = [
    "check_level1_access_control",
    "check_level1_build_release",
    "check_level1_documentation",
    "check_level1_governance",
    "check_level1_legal",
    "check_level1_quality",
    "check_level1_vulnerability",
    "run_all_level1_checks",
]
