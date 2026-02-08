"""Git operation tools for compliance remediation workflow.

These tools provide a controlled interface for git operations during
remediation, ensuring proper error handling and workflow guidance.
"""

import subprocess

from darnit.core.utils import validate_local_path


def create_remediation_branch_impl(
    branch_name: str = "fix/compliance",
    local_path: str = ".",
    base_branch: str | None = None
) -> str:
    """Create a new branch for remediation work.

    Args:
        branch_name: Name for the new branch
        local_path: Path to the repository
        base_branch: Branch to base off of (default: current branch)

    Returns:
        Success message with branch name or error
    """
    resolved_path, error = validate_local_path(local_path)
    if error:
        return f"❌ Error: {error}"

    try:
        # Get current branch if base not specified
        if not base_branch:
            result = subprocess.run(
                ["git", "rev-parse", "--abbrev-ref", "HEAD"],
                cwd=resolved_path,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                return "❌ Error: Not a git repository or git not available"
            base_branch = result.stdout.strip()

        # Check if branch already exists
        result = subprocess.run(
            ["git", "rev-parse", "--verify", branch_name],
            cwd=resolved_path,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            # Branch exists, check it out
            result = subprocess.run(
                ["git", "checkout", branch_name],
                cwd=resolved_path,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                return f"❌ Error checking out existing branch: {result.stderr.strip()}"
            return f"""✅ Switched to existing branch '{branch_name}'

**Next steps:**
1. Apply remediations: `remediate_audit_findings(local_path="{resolved_path}", dry_run=False)`
2. Commit changes: `commit_remediation_changes(local_path="{resolved_path}")`
3. Create PR: `create_remediation_pr(local_path="{resolved_path}")`
"""

        # Create and checkout new branch
        result = subprocess.run(
            ["git", "checkout", "-b", branch_name],
            cwd=resolved_path,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            return f"❌ Error creating branch: {result.stderr.strip()}"

        return f"""✅ Created and switched to branch '{branch_name}'

**Base branch:** {base_branch}

**Next steps:**
1. Apply remediations: `remediate_audit_findings(local_path="{resolved_path}", dry_run=False)`
2. Commit changes: `commit_remediation_changes(local_path="{resolved_path}")`
3. Create PR: `create_remediation_pr(local_path="{resolved_path}")`
"""

    except FileNotFoundError:
        return "❌ Error: git command not found. Ensure git is installed."
    except Exception as e:
        return f"❌ Error: {str(e)}"


def commit_remediation_changes_impl(
    local_path: str = ".",
    message: str | None = None,
    add_all: bool = True
) -> str:
    """Commit remediation changes with a descriptive message.

    Args:
        local_path: Path to the repository
        message: Commit message (auto-generated if not provided)
        add_all: Whether to stage all changes (default: True)

    Returns:
        Success message with commit info or error
    """
    resolved_path, error = validate_local_path(local_path)
    if error:
        return f"❌ Error: {error}"

    try:
        # Check for changes
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=resolved_path,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            return "❌ Error: Not a git repository"

        changes = result.stdout.strip()
        if not changes:
            return "ℹ️ No changes to commit."

        # Parse changed files for commit message
        changed_files = []
        for line in changes.split('\n'):
            if line.strip():
                # Format: "XY filename" where XY is status
                parts = line.split(None, 1)
                if len(parts) >= 2:
                    changed_files.append(parts[1])

        # Stage changes
        if add_all:
            result = subprocess.run(
                ["git", "add", "-A"],
                cwd=resolved_path,
                capture_output=True,
                text=True
            )
            if result.returncode != 0:
                return f"❌ Error staging changes: {result.stderr.strip()}"

        # Generate commit message if not provided
        if not message:
            # Analyze files to create descriptive message
            file_descriptions = []
            for f in changed_files:
                if "SECURITY.md" in f:
                    file_descriptions.append("security policy")
                elif "CONTRIBUTING.md" in f:
                    file_descriptions.append("contribution guidelines")
                elif "GOVERNANCE.md" in f:
                    file_descriptions.append("governance documentation")
                elif "CODEOWNERS" in f:
                    file_descriptions.append("code owners")
                elif "dependabot" in f.lower():
                    file_descriptions.append("Dependabot configuration")
                elif ".github/ISSUE_TEMPLATE" in f:
                    file_descriptions.append("issue templates")
                elif "SUPPORT.md" in f:
                    file_descriptions.append("support documentation")

            if file_descriptions:
                items = ", ".join(sorted(set(file_descriptions)))
                message = f"chore(security): add {items} for compliance"
            else:
                message = "chore(security): apply compliance remediations"

        # Add trailer
        full_message = f"""{message}

Applied via darnit compliance server."""

        # Commit
        result = subprocess.run(
            ["git", "commit", "-m", full_message],
            cwd=resolved_path,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            error_msg = result.stderr.strip()
            if "nothing to commit" in error_msg.lower():
                return "ℹ️ No changes to commit."
            return f"❌ Error committing: {error_msg}"

        # Get commit hash
        result = subprocess.run(
            ["git", "rev-parse", "--short", "HEAD"],
            cwd=resolved_path,
            capture_output=True,
            text=True
        )
        commit_hash = result.stdout.strip() if result.returncode == 0 else "unknown"

        files_list = '\n'.join(f'  - {f}' for f in changed_files[:10])
        more_files = f'\n  ... and {len(changed_files) - 10} more' if len(changed_files) > 10 else ''

        return f"""✅ Changes committed successfully

**Commit:** {commit_hash}
**Message:** {message}
**Files:** {len(changed_files)} file(s) changed

**Changed files:**
{files_list}{more_files}

**Next step:**
Create a pull request: `create_remediation_pr(local_path="{resolved_path}")`
"""

    except FileNotFoundError:
        return "❌ Error: git command not found. Ensure git is installed."
    except Exception as e:
        return f"❌ Error: {str(e)}"


def create_remediation_pr_impl(
    local_path: str = ".",
    title: str | None = None,
    body: str | None = None,
    base_branch: str | None = None,
    draft: bool = False
) -> str:
    """Create a pull request for remediation changes.

    Args:
        local_path: Path to the repository
        title: PR title (auto-generated if not provided)
        body: PR body/description (auto-generated if not provided)
        base_branch: Target branch for PR (default: repo default branch)
        draft: Create as draft PR (default: False)

    Returns:
        Success message with PR URL or error
    """
    resolved_path, error = validate_local_path(local_path)
    if error:
        return f"❌ Error: {error}"

    try:
        # Get current branch
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=resolved_path,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            return "❌ Error: Not a git repository"
        current_branch = result.stdout.strip()

        if current_branch in ["main", "master"]:
            return f"""❌ Error: Cannot create PR from '{current_branch}' branch.

Create a remediation branch first:
`create_remediation_branch(local_path="{resolved_path}")`
"""

        # Push branch to remote
        result = subprocess.run(
            ["git", "push", "-u", "origin", current_branch],
            cwd=resolved_path,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            error_msg = result.stderr.strip()
            if "already exists" not in error_msg.lower() and "up-to-date" not in error_msg.lower():
                return f"❌ Error pushing branch: {error_msg}"

        # Get list of commits on this branch vs base
        base = base_branch or "main"
        result = subprocess.run(
            ["git", "log", f"{base}..HEAD", "--oneline"],
            cwd=resolved_path,
            capture_output=True,
            text=True
        )
        commits = result.stdout.strip().split('\n') if result.returncode == 0 else []
        commits = [c for c in commits if c.strip()]

        # Get changed files
        result = subprocess.run(
            ["git", "diff", "--name-only", f"{base}..HEAD"],
            cwd=resolved_path,
            capture_output=True,
            text=True
        )
        changed_files = result.stdout.strip().split('\n') if result.returncode == 0 else []
        changed_files = [f for f in changed_files if f.strip()]

        # Generate title if not provided
        if not title:
            title = "chore(security): compliance improvements"

        # Generate body if not provided
        if not body:
            body = """## Summary

This PR addresses compliance requirements.

## Changes

"""
            # Add file-specific descriptions
            file_changes = []
            for f in changed_files:
                if "SECURITY.md" in f:
                    file_changes.append("- Added/updated `SECURITY.md` with vulnerability reporting policy")
                elif "CONTRIBUTING.md" in f:
                    file_changes.append("- Added/updated `CONTRIBUTING.md` with contribution guidelines")
                elif "GOVERNANCE.md" in f:
                    file_changes.append("- Added/updated `GOVERNANCE.md` with project governance")
                elif "CODEOWNERS" in f:
                    file_changes.append("- Added/updated `CODEOWNERS` for code review requirements")
                elif "dependabot" in f.lower():
                    file_changes.append("- Configured Dependabot for automated dependency updates")
                elif "SUPPORT.md" in f:
                    file_changes.append("- Added `SUPPORT.md` with support information")
                elif ".github/ISSUE_TEMPLATE" in f:
                    file_changes.append("- Added issue templates for bug reports")

            if file_changes:
                body += '\n'.join(sorted(set(file_changes)))
            else:
                body += f"- Modified {len(changed_files)} file(s) for compliance"

            body += """

## Testing

- [ ] Reviewed changes for accuracy
- [ ] Verified no sensitive information exposed
- [ ] Re-ran compliance audit to confirm improvements

---
*Generated by darnit compliance server*
"""

        # Build gh pr create command
        cmd = ["gh", "pr", "create", "--title", title, "--body", body]
        if base_branch:
            cmd.extend(["--base", base_branch])
        if draft:
            cmd.append("--draft")

        result = subprocess.run(
            cmd,
            cwd=resolved_path,
            capture_output=True,
            text=True
        )

        if result.returncode != 0:
            error_msg = result.stderr.strip()
            if "already exists" in error_msg.lower():
                # PR already exists, try to get URL
                result = subprocess.run(
                    ["gh", "pr", "view", "--json", "url", "-q", ".url"],
                    cwd=resolved_path,
                    capture_output=True,
                    text=True
                )
                if result.returncode == 0:
                    pr_url = result.stdout.strip()
                    return f"""ℹ️ Pull request already exists

**URL:** {pr_url}

The branch already has an open PR. You can view or update it at the URL above.
"""
            return f"❌ Error creating PR: {error_msg}"

        pr_url = result.stdout.strip()

        return f"""✅ Pull request created successfully

**URL:** {pr_url}
**Title:** {title}
**Branch:** {current_branch}
**Files changed:** {len(changed_files)}

The PR is ready for review. After approval and merge, re-run the audit to verify improvements.
"""

    except FileNotFoundError:
        return "❌ Error: gh CLI not found. Install from https://cli.github.com/"
    except Exception as e:
        return f"❌ Error: {str(e)}"


def get_remediation_status_impl(local_path: str = ".") -> str:
    """Get the current git status for remediation work.

    Args:
        local_path: Path to the repository

    Returns:
        Current branch, uncommitted changes, and next steps
    """
    resolved_path, error = validate_local_path(local_path)
    if error:
        return f"❌ Error: {error}"

    try:
        # Get current branch
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=resolved_path,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            return "❌ Error: Not a git repository"
        current_branch = result.stdout.strip()

        # Get status
        result = subprocess.run(
            ["git", "status", "--porcelain"],
            cwd=resolved_path,
            capture_output=True,
            text=True
        )
        changes = result.stdout.strip()
        changed_files = [line.split(None, 1)[1] if len(line.split(None, 1)) > 1 else line
                        for line in changes.split('\n') if line.strip()]

        # Check for unpushed commits
        result = subprocess.run(
            ["git", "log", "@{u}..HEAD", "--oneline"],
            cwd=resolved_path,
            capture_output=True,
            text=True
        )
        unpushed = result.stdout.strip().split('\n') if result.returncode == 0 and result.stdout.strip() else []
        unpushed = [c for c in unpushed if c.strip()]

        # Check for existing PR
        pr_url = None
        result = subprocess.run(
            ["gh", "pr", "view", "--json", "url", "-q", ".url"],
            cwd=resolved_path,
            capture_output=True,
            text=True
        )
        if result.returncode == 0:
            pr_url = result.stdout.strip()

        # Build status report
        lines = [
            "## Remediation Status",
            "",
            f"**Current branch:** `{current_branch}`",
        ]

        if current_branch in ["main", "master"]:
            lines.append("")
            lines.append("⚠️ **Warning:** You're on the default branch. Create a remediation branch first:")
            lines.append("```python")
            lines.append(f'create_remediation_branch(local_path="{resolved_path}")')
            lines.append("```")

        if changed_files:
            lines.append("")
            lines.append(f"**Uncommitted changes:** {len(changed_files)} file(s)")
            for f in changed_files[:5]:
                lines.append(f"  - {f}")
            if len(changed_files) > 5:
                lines.append(f"  ... and {len(changed_files) - 5} more")
            lines.append("")
            lines.append("**Next step:** Commit your changes:")
            lines.append("```python")
            lines.append(f'commit_remediation_changes(local_path="{resolved_path}")')
            lines.append("```")
        elif unpushed:
            lines.append("")
            lines.append(f"**Unpushed commits:** {len(unpushed)}")
            lines.append("")
            lines.append("**Next step:** Create a pull request:")
            lines.append("```python")
            lines.append(f'create_remediation_pr(local_path="{resolved_path}")')
            lines.append("```")
        elif pr_url:
            lines.append("")
            lines.append(f"**Open PR:** {pr_url}")
            lines.append("")
            lines.append("✅ PR is open and ready for review!")
        else:
            lines.append("")
            lines.append("✅ Working directory is clean.")
            lines.append("")
            lines.append("**To start remediation:**")
            lines.append("```python")
            lines.append(f'create_remediation_branch(local_path="{resolved_path}")')
            lines.append(f'remediate_audit_findings(local_path="{resolved_path}", dry_run=False)')
            lines.append("```")

        return "\n".join(lines)

    except FileNotFoundError:
        return "❌ Error: git command not found. Ensure git is installed."
    except Exception as e:
        return f"❌ Error: {str(e)}"
