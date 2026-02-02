"""OpenSSF Baseline Level 3 check functions (19 controls).

Level 3 represents the highest security requirements for critical open source projects.
"""

import os
import re

from darnit.core.logging import get_logger

from .constants import (
    SCA_TOOL_PATTERNS,
    THREAT_MODEL_DOCS,
)
from .helpers import (
    file_exists,
    gh_api,
    gh_api_safe,
    read_file,
    result,
)

logger = get_logger("checks.level3")


def check_level3_access_control(owner: str, repo: str, local_path: str) -> list[dict]:
    """Check Level 3 Access Control requirements."""
    results = []
    workflow_dir = os.path.join(local_path, ".github", "workflows")

    # OSPS-AC-04.02: Minimum privileges in CI/CD
    if os.path.exists(workflow_dir):
        critical_issues = []  # Issues that definitely need attention
        workflows_without_permissions = []  # Missing explicit permissions block

        for root, _, files in os.walk(workflow_dir):
            for file in files:
                if file.endswith(('.yml', '.yaml')):
                    content = read_file(root, file) or ""
                    content_lower = content.lower()

                    # Critical: permissions: write-all is always bad
                    if "permissions: write-all" in content_lower:
                        critical_issues.append(f"{file} (uses write-all)")
                        continue

                    # Check if workflow has explicit permissions block
                    has_permissions_block = "permissions:" in content_lower

                    if not has_permissions_block:
                        workflows_without_permissions.append(file)
                        continue

                    # Check for legitimately dangerous patterns
                    # pull_request_target with checkout is a known attack vector
                    if "pull_request_target" in content_lower and "checkout" in content_lower:
                        if "head.sha" in content_lower or "head_ref" in content_lower:
                            critical_issues.append(f"{file} (pull_request_target with PR checkout)")

                    # contents: write is OK if workflow legitimately needs it
                    if "contents: write" in content_lower:
                        legitimate_write_patterns = [
                            "auto-update", "autoupdate", "dependabot",
                            "release", "deploy", "publish", "gh-pages",
                            "changelog", "documentation", "docs",
                            "git push", "git commit", "create-pull-request"
                        ]
                        is_legitimate = any(pattern in content_lower for pattern in legitimate_write_patterns)

                        if not is_legitimate and "pull_request_target" in content_lower:
                            critical_issues.append(f"{file} (contents:write with pull_request_target)")

        # Determine result
        if critical_issues:
            results.append(result("OSPS-AC-04.02", "WARN",
                f"Critical permission issues: {', '.join(critical_issues[:3])}", level=3))
        elif workflows_without_permissions:
            if len(workflows_without_permissions) <= 2:
                results.append(result("OSPS-AC-04.02", "PASS",
                    f"Workflows use appropriate permissions. Consider adding explicit permissions to: {', '.join(workflows_without_permissions)}", level=3))
            else:
                results.append(result("OSPS-AC-04.02", "PASS",
                    f"Workflows use appropriate permissions. {len(workflows_without_permissions)} workflows lack explicit permissions blocks.", level=3))
        else:
            results.append(result("OSPS-AC-04.02", "PASS", "Workflows use appropriately scoped permissions.", level=3))
    else:
        results.append(result("OSPS-AC-04.02", "N/A", "No workflows found.", level=3))

    return results


def check_level3_build_release(owner: str, repo: str, local_path: str) -> list[dict]:
    """Check Level 3 Build & Release requirements."""
    results = []

    # OSPS-BR-02.02: Assets clearly associated with release
    try:
        releases = gh_api(f"/repos/{owner}/{repo}/releases?per_page=1")
        if releases and releases[0].get("assets"):
            assets = releases[0]["assets"]
            tag = releases[0].get("tag_name", "")
            named_correctly = all(tag in a.get("name", "") or "latest" not in a.get("name", "").lower() for a in assets)
            if named_correctly:
                results.append(result("OSPS-BR-02.02", "PASS", "Release assets are clearly versioned.", level=3))
            else:
                results.append(result("OSPS-BR-02.02", "WARN", "Some assets may not be clearly versioned.", level=3))
        else:
            results.append(result("OSPS-BR-02.02", "N/A", "No release assets found.", level=3))
    except (RuntimeError, KeyError, TypeError, AttributeError) as e:
        logger.debug(f"Could not verify release assets: {type(e).__name__}: {e}")
        results.append(result("OSPS-BR-02.02", "WARN", "Could not verify release assets.", level=3))

    # OSPS-BR-07.02: Secrets management policy
    security_content = read_file(local_path, "SECURITY.md") or ""
    contributing_content = read_file(local_path, "CONTRIBUTING.md") or ""
    all_content = security_content + contributing_content

    if re.search(r'(secret|credential|key management|rotation|vault)', all_content, re.IGNORECASE):
        results.append(result("OSPS-BR-07.02", "PASS", "Secrets management policy documented.", level=3))
    else:
        results.append(result("OSPS-BR-07.02", "FAIL",
            "No secrets management policy found. Document in SECURITY.md or CONTRIBUTING.md.", level=3))

    return results


def check_level3_documentation(owner: str, repo: str, local_path: str) -> list[dict]:
    """Check Level 3 Documentation requirements."""
    results = []

    readme = read_file(local_path, "README.md") or ""
    security = read_file(local_path, "SECURITY.md") or ""
    support = read_file(local_path, "SUPPORT.md") or ""
    all_docs = readme + security + support

    # OSPS-DO-03.01: Verify release integrity instructions
    # OSPS-DO-03.02: Verify release author identity
    if re.search(r'(verify|signature|checksum|sha256|gpg|pgp|signing)', all_docs, re.IGNORECASE):
        results.append(result("OSPS-DO-03.01", "PASS", "Release verification instructions found.", level=3))
        results.append(result("OSPS-DO-03.02", "PASS", "Author verification documented.", level=3))
    else:
        results.append(result("OSPS-DO-03.01", "FAIL",
            "No release verification instructions. Document checksum/signature verification in README or SECURITY.md.", level=3))
        results.append(result("OSPS-DO-03.02", "FAIL",
            "No author verification instructions. Document GPG signing or identity verification.", level=3))

    # OSPS-DO-04.01: Support scope and duration
    has_support_doc = file_exists(local_path, "SUPPORT.md", "docs/SUPPORT.md")
    if has_support_doc or re.search(r'(support|maintenance|lts|long.term|eol|end.of.life)', all_docs, re.IGNORECASE):
        results.append(result("OSPS-DO-04.01", "PASS", "Support policy documented.", level=3))
    else:
        results.append(result("OSPS-DO-04.01", "FAIL",
            "No support scope documentation. Create SUPPORT.md with maintenance policy.", level=3))

    # OSPS-DO-05.01: End of security updates notice
    if has_support_doc and re.search(r'(end.of.support|end.of.life|eol|deprecat|unsupported|no longer maintained)', support, re.IGNORECASE):
        results.append(result("OSPS-DO-05.01", "PASS", "End-of-support policy documented in SUPPORT.md.", level=3))
    elif re.search(r'(deprecat|unsupported|no longer|end.of.life|eol|end.of.support)', all_docs, re.IGNORECASE):
        results.append(result("OSPS-DO-05.01", "PASS", "EOL/deprecation policy mentioned.", level=3))
    else:
        results.append(result("OSPS-DO-05.01", "FAIL",
            "No end-of-support documentation. Add EOL policy to SUPPORT.md.", level=3))

    return results


def check_level3_governance(owner: str, repo: str, local_path: str) -> list[dict]:
    """Check Level 3 Governance requirements."""
    results = []

    # OSPS-GV-04.01: Collaborator review policy
    governance = read_file(local_path, "GOVERNANCE.md") or ""
    security = read_file(local_path, "SECURITY.md") or ""
    all_docs = governance + security

    if re.search(r'(collaborator|maintainer|review|vetting|access.review)', all_docs, re.IGNORECASE):
        results.append(result("OSPS-GV-04.01", "PASS", "Collaborator review policy documented.", level=3))
    else:
        results.append(result("OSPS-GV-04.01", "FAIL",
            "No collaborator vetting policy. Document access review process in GOVERNANCE.md.", level=3))

    return results


def check_level3_quality(owner: str, repo: str, local_path: str, default_branch: str) -> list[dict]:
    """Check Level 3 Quality Assurance requirements."""
    results = []

    # OSPS-QA-02.02: SBOM for compiled releases
    try:
        releases = gh_api(f"/repos/{owner}/{repo}/releases?per_page=1")
        if releases:
            assets = releases[0].get("assets", [])
            has_sbom = any(
                "sbom" in a.get("name", "").lower() or
                "bom" in a.get("name", "").lower() or
                a.get("name", "").endswith((".spdx", ".spdx.json", ".cdx.json"))
                for a in assets
            )
            if has_sbom:
                results.append(result("OSPS-QA-02.02", "PASS", "SBOM included in release.", level=3))
            else:
                results.append(result("OSPS-QA-02.02", "WARN", "No SBOM found in release assets.", level=3))
        else:
            results.append(result("OSPS-QA-02.02", "N/A", "No releases found.", level=3))
    except (RuntimeError, KeyError, TypeError, AttributeError) as e:
        logger.debug(f"Could not verify SBOM presence: {type(e).__name__}: {e}")
        results.append(result("OSPS-QA-02.02", "WARN", "Could not verify SBOM presence.", level=3))

    # OSPS-QA-04.02: Subproject security requirements
    has_subprojects = file_exists(local_path, "packages/*", "apps/*", "modules/*")
    if has_subprojects:
        has_shared_config = file_exists(local_path, ".github/workflows/*.yml")
        if has_shared_config:
            results.append(result("OSPS-QA-04.02", "PASS", "Subprojects share CI/security config.", level=3))
        else:
            results.append(result("OSPS-QA-04.02", "WARN", "Verify subprojects have equivalent security.", level=3))
    else:
        results.append(result("OSPS-QA-04.02", "N/A", "No subprojects detected.", level=3))

    # OSPS-QA-06.02: Test documentation
    readme = read_file(local_path, "README.md") or ""
    contributing = read_file(local_path, "CONTRIBUTING.md") or ""

    if re.search(r'(how to.*test|running tests|test.*instruction)', readme + contributing, re.IGNORECASE):
        results.append(result("OSPS-QA-06.02", "PASS", "Test instructions documented.", level=3))
    else:
        results.append(result("OSPS-QA-06.02", "WARN", "Test instructions not clearly documented.", level=3))

    # OSPS-QA-06.03: Test policy for changes
    if re.search(r'(test.*required|must.*test|test.*coverage)', contributing, re.IGNORECASE):
        results.append(result("OSPS-QA-06.03", "PASS", "Test requirements for contributions documented.", level=3))
    else:
        results.append(result("OSPS-QA-06.03", "WARN", "No explicit test requirements for changes.", level=3))

    # OSPS-QA-07.01: Non-author approval required
    try:
        protection = gh_api_safe(f"/repos/{owner}/{repo}/branches/{default_branch}/protection")
        if protection:
            pr_reviews = protection.get("required_pull_request_reviews", {})
            approvals = pr_reviews.get("required_approving_review_count", 0)
            if approvals >= 1:
                results.append(result("OSPS-QA-07.01", "PASS", f"Requires {approvals} non-author approval(s).", level=3))
            else:
                results.append(result("OSPS-QA-07.01", "FAIL", "No required approvals configured.", level=3))
        else:
            results.append(result("OSPS-QA-07.01", "FAIL", "No branch protection configured.", level=3))
    except (RuntimeError, KeyError, TypeError, AttributeError) as e:
        logger.debug(f"Could not verify approval requirements: {type(e).__name__}: {e}")
        results.append(result("OSPS-QA-07.01", "WARN", "Could not verify approval requirements.", level=3))

    return results


def check_level3_security_architecture(owner: str, repo: str, local_path: str) -> list[dict]:
    """Check Level 3 Security Architecture requirements."""
    results = []

    # OSPS-SA-03.02: Threat modeling
    has_threat_model = any(file_exists(local_path, d) for d in THREAT_MODEL_DOCS)

    security = read_file(local_path, "SECURITY.md") or ""
    has_threat_content = re.search(r'(threat.model|attack.surface|attack.vector)', security, re.IGNORECASE)

    if has_threat_model or has_threat_content:
        results.append(result("OSPS-SA-03.02", "PASS", "Threat modeling documentation found.", level=3))
    else:
        results.append(result("OSPS-SA-03.02", "WARN", "No explicit threat model found.", level=3))

    return results


def check_level3_vulnerability(owner: str, repo: str, local_path: str) -> list[dict]:
    """Check Level 3 Vulnerability Management requirements."""
    results = []
    workflow_dir = os.path.join(local_path, ".github", "workflows")

    # OSPS-VM-04.02: VEX documents or VEX policy
    has_vex = file_exists(local_path, "*.vex.json", "vex.json", ".vex/*", "vex/*.json")
    security_md = read_file(local_path, "SECURITY.md") or ""

    # Check for VEX policy documentation in SECURITY.md
    has_vex_policy = bool(re.search(
        r'(vex|vulnerability.exploitability|exploitability.exchange|'
        r'will.*(provide|publish|generate|create).*vex|'
        r'vex.*(document|statement|policy)|'
        r'affected.*not.affected.*under.investigation)',
        security_md, re.IGNORECASE
    ))

    if has_vex:
        results.append(result("OSPS-VM-04.02", "PASS", "VEX document found.", level=3))
    elif has_vex_policy:
        results.append(result("OSPS-VM-04.02", "PASS", "VEX policy documented in SECURITY.md.", level=3))
    else:
        results.append(result("OSPS-VM-04.02", "WARN", "No VEX document or VEX policy found. Add VEX policy to SECURITY.md.", level=3))

    # OSPS-VM-05.01: SCA remediation threshold policy
    security = read_file(local_path, "SECURITY.md") or ""
    if re.search(r'(sca|software.composition|dependency.*scan|remediation.*policy)', security, re.IGNORECASE):
        results.append(result("OSPS-VM-05.01", "PASS", "SCA remediation policy documented.", level=3))
    else:
        results.append(result("OSPS-VM-05.01", "WARN", "No SCA remediation policy found.", level=3))

    # OSPS-VM-05.02: SCA violations before release
    has_sca_check = False
    sca_tool_found = None

    # Check for Kusari GitHub App installation
    try:
        check_runs = gh_api_safe(f"/repos/{owner}/{repo}/check-runs?per_page=10")
        if check_runs and check_runs.get("check_runs"):
            for check in check_runs["check_runs"]:
                app_name = check.get("app", {}).get("slug", "").lower()
                check_name = check.get("name", "").lower()
                if "kusari" in app_name or "kusari" in check_name:
                    has_sca_check = True
                    sca_tool_found = "Kusari GitHub App"
                    break
    except (RuntimeError, KeyError, TypeError, AttributeError) as e:
        logger.debug(f"Could not check for Kusari GitHub App: {type(e).__name__}: {e}")

    # Check for SCA tools in workflow files
    if not has_sca_check and os.path.exists(workflow_dir):
        for wf_file in os.listdir(workflow_dir):
            if wf_file.endswith(('.yml', '.yaml')):
                wf_content = read_file(workflow_dir, wf_file) or ""

                for pattern, tool_name in SCA_TOOL_PATTERNS:
                    if re.search(pattern, wf_content, re.IGNORECASE):
                        # Verify it runs on pull_request (pre-release)
                        if re.search(r'on:\s*\n\s*(pull_request|pull_request_target)|on:\s*\[.*pull_request', wf_content):
                            has_sca_check = True
                            sca_tool_found = tool_name
                            break

                if has_sca_check:
                    break

    if has_sca_check:
        results.append(result("OSPS-VM-05.02", "PASS", f"Pre-release SCA check found ({sca_tool_found}).", level=3))
    else:
        results.append(result("OSPS-VM-05.02", "WARN", "No pre-release SCA workflow found. Add dependency-review-action or Kusari on pull_request.", level=3))

    # OSPS-VM-05.03: Automated dependency scanning
    has_dependabot = file_exists(local_path, ".github/dependabot.yml", ".github/dependabot.yaml")
    has_renovate = file_exists(local_path, "renovate.json", ".renovaterc", ".renovaterc.json")

    dep_scan_in_ci = False
    if os.path.exists(workflow_dir):
        for root, _, files in os.walk(workflow_dir):
            for file in files:
                if file.endswith(('.yml', '.yaml')):
                    content = read_file(root, file) or ""
                    if re.search(r'(snyk|trivy|grype|dependency.check|npm audit|safety check)', content, re.IGNORECASE):
                        dep_scan_in_ci = True
                        break

    if has_dependabot or has_renovate or dep_scan_in_ci:
        results.append(result("OSPS-VM-05.03", "PASS", "Automated dependency scanning configured.", level=3))
    else:
        results.append(result("OSPS-VM-05.03", "FAIL", "No automated dependency scanning found.", level=3))

    # OSPS-VM-06.01: SAST remediation threshold
    if re.search(r'(sast|static.analysis|code.*scan.*policy)', security, re.IGNORECASE):
        results.append(result("OSPS-VM-06.01", "PASS", "SAST remediation policy documented.", level=3))
    else:
        results.append(result("OSPS-VM-06.01", "WARN", "No SAST remediation policy found.", level=3))

    # OSPS-VM-06.02: Automated SAST in CI
    sast_in_ci = False
    if os.path.exists(workflow_dir):
        for root, _, files in os.walk(workflow_dir):
            for file in files:
                if file.endswith(('.yml', '.yaml')):
                    content = read_file(root, file) or ""
                    if re.search(r'(codeql|semgrep|sonar|bandit|brakeman|gosec|eslint.*security)', content, re.IGNORECASE):
                        sast_in_ci = True
                        break

    if sast_in_ci:
        results.append(result("OSPS-VM-06.02", "PASS", "Automated SAST found in CI.", level=3))
    else:
        results.append(result("OSPS-VM-06.02", "WARN", "No automated SAST found in CI.", level=3))

    return results


def run_all_level3_checks(
    owner: str, repo: str, local_path: str, default_branch: str
) -> list[dict]:
    """Run all Level 3 checks and return combined results."""
    results = []
    results.extend(check_level3_access_control(owner, repo, local_path))
    results.extend(check_level3_build_release(owner, repo, local_path))
    results.extend(check_level3_documentation(owner, repo, local_path))
    results.extend(check_level3_governance(owner, repo, local_path))
    results.extend(check_level3_quality(owner, repo, local_path, default_branch))
    results.extend(check_level3_security_architecture(owner, repo, local_path))
    results.extend(check_level3_vulnerability(owner, repo, local_path))
    return results


__all__ = [
    "check_level3_access_control",
    "check_level3_build_release",
    "check_level3_documentation",
    "check_level3_governance",
    "check_level3_quality",
    "check_level3_security_architecture",
    "check_level3_vulnerability",
    "run_all_level3_checks",
]
