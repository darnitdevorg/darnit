"""GitHub API remediation actions.

This module contains functions that use the GitHub API to configure
repository settings like branch protection rules.
"""

import json
import os
import subprocess
from typing import Any

from darnit.core.logging import get_logger
from darnit.core.utils import detect_repo_from_git, gh_api_safe

logger = get_logger("remediation.github")


def detect_workflow_checks(local_path: str) -> list[dict[str, Any]]:
    """
    Detect potential status check names from GitHub Actions workflows.

    Args:
        local_path: Path to the repository

    Returns:
        A list of dicts with job info including workflow, job_id, job_name,
        check_name, and source filename.
    """
    workflow_dir = os.path.join(local_path, ".github", "workflows")
    checks = []

    if not os.path.exists(workflow_dir):
        return checks

    try:
        import yaml
    except ImportError:
        logger.debug("PyYAML not available for workflow detection")
        return checks

    try:
        filenames = os.listdir(workflow_dir)
    except OSError as e:
        logger.debug(f"Cannot read workflow directory: {e}")
        return checks

    for filename in filenames:
        if not filename.endswith(('.yml', '.yaml')):
            continue

        filepath = os.path.join(workflow_dir, filename)
        try:
            with open(filepath, encoding='utf-8') as f:
                content = f.read()

            workflow = yaml.safe_load(content)
            if workflow and isinstance(workflow, dict):
                workflow_name = workflow.get('name', filename.replace('.yml', '').replace('.yaml', ''))
                jobs = workflow.get('jobs', {})

                for job_id, job_config in jobs.items():
                    if isinstance(job_config, dict):
                        job_name = job_config.get('name', job_id)
                        # Check for matrix builds
                        strategy = job_config.get('strategy', {})
                        matrix = strategy.get('matrix', {})

                        if matrix:
                            # Expand matrix combinations for common patterns
                            for _key, values in matrix.items():
                                if isinstance(values, list):
                                    for val in values:
                                        checks.append({
                                            'workflow': workflow_name,
                                            'job_id': job_id,
                                            'job_name': job_name,
                                            'check_name': f"{job_name} ({val})",
                                            'source': filename
                                        })
                        else:
                            checks.append({
                                'workflow': workflow_name,
                                'job_id': job_id,
                                'job_name': job_name,
                                'check_name': job_name,
                                'source': filename
                            })
        except OSError as e:
            logger.debug(f"Cannot read workflow file {filename}: {e}")
            continue
        except yaml.YAMLError as e:
            logger.debug(f"Invalid YAML in {filename}: {e}")
            continue

    return checks


def enable_branch_protection(
    owner: str | None = None,
    repo: str | None = None,
    branch: str = "main",
    required_approvals: int = 1,
    enforce_admins: bool = True,
    require_pull_request: bool = True,
    require_status_checks: bool = False,
    status_checks: list[str] | None = None,
    local_path: str = ".",
    dry_run: bool = False
) -> str:
    """
    Enable branch protection rules to satisfy OSPS-AC-03.01, OSPS-AC-03.02, and OSPS-QA-07.01.

    Args:
        owner: GitHub Org/User (auto-detected from git if not provided)
        repo: Repository Name (auto-detected from git if not provided)
        branch: Branch to protect (default: main)
        required_approvals: Number of required PR approvals (default: 1)
        enforce_admins: Apply rules to admins too (default: True)
        require_pull_request: Require pull requests for changes (default: True).
            Setting to False allows direct pushes while still protecting against
            force-push and deletion. NOTE: Disabling this means OSPS-QA-07.01
            (peer review requirement) will NOT be satisfied.
        require_status_checks: Require status checks to pass (default: False)
        status_checks: List of required status check contexts (e.g., ["ci/test"])
        local_path: Local path to repo for auto-detection (default: ".")
        dry_run: If True, show what would be configured without making changes (default: False)

    Returns:
        Success message with configuration details or error message
    """
    if not owner or not repo:
        detected = detect_repo_from_git(local_path)
        if detected:
            owner = owner or detected["owner"]
            repo = repo or detected["repo"]
        else:
            return "❌ Error: Could not auto-detect owner/repo."

    # Check for existing rulesets that might conflict
    ruleset_warning = ""
    try:
        rulesets = gh_api_safe(f"/repos/{owner}/{repo}/rulesets")
        if rulesets:
            conflicting_rulesets = []
            for rs in rulesets:
                rs_detail = gh_api_safe(f"/repos/{owner}/{repo}/rulesets/{rs['id']}")
                if rs_detail and rs_detail.get("enforcement") == "active":
                    conditions = rs_detail.get("conditions", {})
                    ref_name = conditions.get("ref_name", {})
                    includes = ref_name.get("include", [])
                    if any(inc in ["~DEFAULT_BRANCH", f"refs/heads/{branch}", branch] for inc in includes):
                        conflicting_rulesets.append({
                            "name": rs["name"],
                            "id": rs["id"],
                            "rules": rs_detail.get("rules", [])
                        })

            if conflicting_rulesets:
                ruleset_warning = f"""
⚠️ **WARNING: Existing rulesets detected that may override branch protection!**

The following rulesets target `{branch}`:
"""
                for rs in conflicting_rulesets:
                    ruleset_warning += f"- **{rs['name']}** (ID: {rs['id']})\n"
                    for rule in rs['rules']:
                        if rule.get('type') == 'pull_request':
                            params = rule.get('parameters', {})
                            rs_approvals = params.get('required_approving_review_count', 0)
                            if rs_approvals != required_approvals:
                                ruleset_warning += f"  - Ruleset requires {rs_approvals} approvals (you requested {required_approvals})\n"

                ruleset_warning += """
**Note:** Repository rulesets take precedence over branch protection rules.
To modify rulesets, go to: Settings → Rules → Rulesets

"""
    except RuntimeError:
        pass  # Rulesets API may not be available

    endpoint = f"/repos/{owner}/{repo}/branches/{branch}/protection"

    # Build protection config as a proper dict (NOT string)
    protection_config: dict[str, Any] = {
        "enforce_admins": enforce_admins,
        "restrictions": None,
        "required_linear_history": False,
        "allow_force_pushes": False,
        "allow_deletions": False
    }

    # Only require PRs if explicitly enabled
    if require_pull_request:
        protection_config["required_pull_request_reviews"] = {
            "required_approving_review_count": required_approvals,
            "dismiss_stale_reviews": True,
            "require_code_owner_reviews": False
        }
    else:
        protection_config["required_pull_request_reviews"] = None

    if require_status_checks and status_checks:
        protection_config["required_status_checks"] = {
            "strict": True,
            "contexts": status_checks
        }
    else:
        protection_config["required_status_checks"] = None

    config_json = json.dumps(protection_config)

    # Build compliance warning if PR reviews are disabled or no approvals required
    compliance_warning = ""
    if not require_pull_request:
        compliance_warning = """
⚠️ **COMPLIANCE WARNING**: Pull request reviews are DISABLED.
- OSPS-QA-07.01 (peer review requirement) will NOT be satisfied
- This configuration is suitable for solo maintainers but does not meet
  full OpenSSF Baseline Level 1 compliance
- Consider enabling PR reviews when you have additional contributors

"""
    elif required_approvals == 0:
        compliance_warning = """
⚠️ **COMPLIANCE NOTE**: Pull requests required but NO approvals needed.
- OSPS-QA-07.01 (peer review requirement) will NOT be satisfied
- PRs provide traceability but not actual peer review
- This configuration is suitable for solo maintainers
- Consider requiring approvals when you have additional contributors

"""

    # Dry run - show what would be configured
    if dry_run:
        pr_config_display = f"""- Require pull requests: {require_pull_request}
- Required approvals: {required_approvals}
- Dismiss stale reviews: Yes""" if require_pull_request else "- Require pull requests: No (direct pushes allowed)"

        return f"""🔍 **DRY RUN** - Branch protection preview for {owner}/{repo}:{branch}
{ruleset_warning}{compliance_warning}
**Would configure:**
{pr_config_display}
- Enforce for admins: {enforce_admins}
- Prevent force push: Yes
- Prevent deletion: Yes
- Require status checks: {require_status_checks}
{f"- Status checks: {', '.join(status_checks)}" if status_checks else ""}

**API endpoint:** PUT {endpoint}

**Configuration JSON:**
```json
{json.dumps(protection_config, indent=2)}
```

**OSPS Controls that would be addressed:**
- OSPS-AC-03.01: {"Direct commits prevented" if require_pull_request else "⚠️ NOT SATISFIED (direct pushes allowed)"}
- OSPS-AC-03.02: Branch deletion prevented
- OSPS-QA-07.01: {"Peer review required" if require_pull_request and required_approvals >= 1 else "⚠️ NOT SATISFIED (no peer review requirement)"}

**To apply:** Run again with `dry_run=False`
"""

    # IMPORTANT: Use --input - to pass JSON body via stdin
    # This avoids shell escaping issues with -f flags that cause
    # "is not an object" errors from GitHub's API
    try:
        result = subprocess.run(
            [
                "gh", "api",
                "-X", "PUT",
                endpoint,
                "-H", "Accept: application/vnd.github+json",
                "--input", "-"
            ],
            input=config_json,
            capture_output=True,
            text=True,
            timeout=30
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip()
            # Provide helpful context for common errors
            if "Not Found" in error_msg:
                logger.warning(f"Repository {owner}/{repo} not found or no admin access")
                return f"❌ Failed: Repository {owner}/{repo} not found or you don't have admin access."
            elif "Resource not accessible" in error_msg:
                logger.warning(f"No admin permissions on {owner}/{repo}")
                return f"❌ Failed: You need admin permissions on {owner}/{repo} to set branch protection."
            logger.error(f"Branch protection failed: {error_msg}")
            return f"❌ Failed: {error_msg}"

        logger.info(f"Enabled branch protection for {owner}/{repo}:{branch}")

        pr_config_display = f"""- Require pull requests: Yes
- Required approvals: {required_approvals}
- Dismiss stale reviews: Yes""" if require_pull_request else "- Require pull requests: No (direct pushes allowed)"

        return f"""✅ Branch protection enabled for {owner}/{repo}:{branch}
{ruleset_warning}{compliance_warning}
**Configuration:**
{pr_config_display}
- Enforce for admins: {enforce_admins}
- Prevent force push: Yes
- Prevent deletion: Yes

**OSPS Controls Addressed:**
- OSPS-AC-03.01: {"Direct commits prevented" if require_pull_request else "⚠️ NOT SATISFIED (direct pushes allowed)"}
- OSPS-AC-03.02: Branch deletion prevented
- OSPS-QA-07.01: {"Peer review required" if require_pull_request and required_approvals >= 1 else "⚠️ NOT SATISFIED (no peer review requirement)"}"""

    except FileNotFoundError:
        logger.error("gh CLI not found")
        return "❌ Error: `gh` CLI not found. Install from https://cli.github.com/"
    except subprocess.TimeoutExpired:
        logger.error("Branch protection API call timed out")
        return "❌ Error: GitHub API call timed out"
    except subprocess.SubprocessError as e:
        logger.error(f"Branch protection subprocess error: {e}")
        return f"❌ Error: {str(e)}"


__all__ = [
    "detect_workflow_checks",
    "enable_branch_protection",
]
