"""Git operation tools for compliance remediation workflow.

These tools provide a controlled interface for git operations during
remediation, ensuring proper error handling and workflow guidance.

Feature 043 (framework-design.md 15.7): each tool works on one remediation
run, read from the operator-side run manifest (``run_id``, default the
latest run for the repository). The branch tool never stashes; the commit
tool stages only the manifest's files whose content still matches what
remediation wrote, never ignored files, and adds a ``Darnit-Remediation-Run``
trailer; the PR tool pushes only the run's branch. The repository-state
precondition is :func:`darnit.remediation.git_state.check_repository_state`.
"""

import os
import subprocess

from darnit.core.utils import detect_repo_from_git, validate_local_path
from darnit.remediation import manifest
from darnit.remediation.git_state import (
    PROTECTED_BRANCHES,
    TRAILER_KEY,
    GitStateError,
    base_branch_name,
    branch_exists,
    check_repository_state,
    current_branch,
    describe_foreign_commits,
    from_root,
    has_uncommitted_changes,
    holds_commit,
    is_ignored,
    is_work_tree,
    merge_base,
    resolve_base,
    resolve_commit,
    run_git,
    show_prefix,
)
from darnit.remediation.plan import content_digest

_REMOTE = "origin"


def _gh(repo: str, *args: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(["gh", *args], cwd=repo, capture_output=True, text=True)


def _error(message: str) -> str:
    return f"Error: {message}"


def _repository(local_path: str, owner: str | None, repo: str | None) -> str:
    """The identity the remediation executor records this checkout's runs under."""
    if not owner or not repo:
        detected = detect_repo_from_git(local_path)
        if detected:
            owner = owner or detected.get("owner")
            repo = repo or detected.get("repo")
    return manifest.repository_identity(local_path, owner, repo)


def _load_run(repository: str, run_id: str | None, checkout: str) -> tuple[manifest.RunManifest | None, str | None]:
    try:
        run = manifest.load_run(repository, run_id, checkout=checkout)
    except ValueError as e:
        return None, str(e)
    if run is None:
        named = f"run {run_id}" if run_id else "run"
        return None, f"no remediation {named} is recorded for this repository; apply remediation first"
    return run, None


def _bullets(items: list[str]) -> str:
    return "\n".join(f"  - {item}" for item in items)


def create_remediation_branch_impl(
    branch_name: str = "fix/compliance",
    local_path: str = ".",
    base_branch: str | None = None,
    run_id: str | None = None,
    *,
    owner: str | None = None,
    repo: str | None = None,
) -> str:
    """Create, or switch to, the branch for a remediation run.

    Never stashes. A new branch is created from HEAD and the user's
    uncommitted changes stay in the working tree untouched. An existing
    branch is used only if every commit on it beyond its base carries the
    ``Darnit-Remediation-Run`` trailer, and switching to it requires a clean
    working tree. A detached HEAD or a merge or rebase in progress is
    refused. On any refusal nothing is changed.

    Args:
        branch_name: Name for the branch
        local_path: Path to the repository
        base_branch: The base an existing branch's commits are checked
            against (default: current branch); for a new branch it must be HEAD
        run_id: Remediation run to record the branch in. Default: the
            latest run for the repository, if it is not yet committed
        owner: Repository owner the run is recorded under (default: detected as the executor does)
        repo: Repository name the run is recorded under (default: detected as the executor does)

    Returns:
        Success message with branch name or error
    """
    resolved_path, error = validate_local_path(local_path)
    if error:
        return _error(error)

    try:
        refusal = check_repository_state(resolved_path, branch_name, base_branch)
        if refusal:
            return _error(f"cannot use remediation branch '{branch_name}': {refusal}. Nothing was changed.")

        repository = _repository(resolved_path, owner, repo)
        try:
            run = manifest.load_run(repository, run_id, checkout=resolved_path)
        except ValueError as e:
            return _error(f"{e}. Nothing was changed.")
        if run_id is None and run is not None and run.commit is not None:
            run = None
        if run is not None and run.commit is not None and run.branch not in (None, branch_name):
            return _error(f"remediation run {run.run_id} was committed on branch '{run.branch}'. Nothing was changed.")

        existed = branch_exists(resolved_path, branch_name)
        previous = current_branch(resolved_path)
        if existed:
            if previous != branch_name:
                result = run_git(resolved_path, "checkout", "-q", branch_name, "--")
                if result.returncode != 0:
                    return _error(f"checking out existing branch: {result.stderr.strip()}")
        else:
            result = run_git(resolved_path, "checkout", "-q", "-b", branch_name)
            if result.returncode != 0:
                return _error(f"creating branch: {result.stderr.strip()}")

        if run is None and run_id is not None:
            run = manifest.start_run(repository, checkout=resolved_path, run_id=run_id)
        if run is not None:
            pr_base = resolve_base(resolved_path, branch_name, base_branch, current_first=False)
            manifest.set_branch(
                repository,
                run.run_id,
                branch_name,
                checkout=resolved_path,
                base=pr_base,
                base_commit=resolve_commit(resolved_path, pr_base) if pr_base else None,
            )
            recorded = f"**Remediation run:** {run.run_id}"
            run_arg = f', run_id="{run.run_id}"'
        else:
            recorded = (
                "**Remediation run:** none recorded yet; the commit step records the branch in the run it commits"
            )
            run_arg = ""

        if existed:
            headline = f"Switched to existing branch '{branch_name}'"
        else:
            headline = (
                f"Created and switched to branch '{branch_name}'\n\n**Base branch:** {base_branch or previous}\n\n"
                "Uncommitted changes were left in the working tree; nothing was stashed."
            )

        return f"""{headline}

{recorded}

**Next steps:**
1. Apply remediations: `remediate_audit_findings(local_path="{resolved_path}", dry_run=False)`
2. Commit changes: `commit_remediation_changes(local_path="{resolved_path}"{run_arg})`
3. Create PR: `create_remediation_pr(local_path="{resolved_path}"{run_arg})`
"""

    except FileNotFoundError:
        return "Error: git command not found. Ensure git is installed."
    except Exception as e:
        return f"Error: {str(e)}"


def _describe(paths: list[str]) -> str:
    file_descriptions = []
    for f in paths:
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
        return f"chore(security): add {', '.join(sorted(set(file_descriptions)))} for compliance"
    return "chore(security): apply compliance remediations"


def commit_remediation_changes_impl(
    local_path: str = ".",
    message: str | None = None,
    run_id: str | None = None,
    *,
    owner: str | None = None,
    repo: str | None = None,
) -> str:
    """Commit the files a remediation run wrote, and nothing else.

    Stages, with explicit pathspecs, only the run manifest's files whose
    current content digest equals the digest remediation wrote; a file
    changed or deleted since is a conflict and nothing is committed. Ignored
    files are never staged. Other staged or unstaged changes are left as they
    are. The message carries ``Darnit-Remediation-Run: <run_id>``; the commit
    (and, if none was recorded, the branch) is recorded in the manifest.

    Args:
        local_path: Path to the repository
        message: Commit message (auto-generated if not provided)
        run_id: Remediation run to commit (default: the latest run)
        owner: Repository owner the run is recorded under (default: detected as the executor does)
        repo: Repository name the run is recorded under (default: detected as the executor does)

    Returns:
        Success message listing every committed file, or error
    """
    resolved_path, error = validate_local_path(local_path)
    if error:
        return _error(error)

    try:
        refusal = check_repository_state(resolved_path)
        if refusal:
            return _error(f"cannot commit remediation changes: {refusal}. Nothing was committed.")

        repository = _repository(resolved_path, owner, repo)
        run, problem = _load_run(repository, run_id, resolved_path)
        if run is None:
            return _error(f"{problem}. Nothing was committed.")
        branch = current_branch(resolved_path)
        if run.branch and branch != run.branch:
            return _error(
                f"remediation run {run.run_id} belongs to branch '{run.branch}', and '{branch}' is checked out. "
                "Nothing was committed."
            )

        conflicts: list[str] = []
        ignored: list[str] = []
        to_commit: list[str] = []
        for entry in run.files:
            if is_ignored(resolved_path, entry.path):
                ignored.append(entry.path)
                continue
            try:
                with open(os.path.join(resolved_path, entry.path), "rb") as f:
                    current = f.read()
            except FileNotFoundError:
                conflicts.append(f"{entry.path} (deleted since remediation wrote it)")
                continue
            if content_digest(current) != entry.after_digest:
                conflicts.append(f"{entry.path} (changed since remediation wrote it)")
                continue
            if has_uncommitted_changes(resolved_path, entry.path):
                to_commit.append(entry.path)

        if conflicts:
            return f"""Conflict: files changed after remediation wrote them. Nothing was committed.

**Run:** {run.run_id}

**Conflicting files:**
{_bullets(conflicts)}

Review these files, then re-run remediation or commit them yourself.
"""

        ignored_note = f"\n\n**Not staged (ignored by the repository):**\n{_bullets(ignored)}" if ignored else ""
        if not to_commit:
            return f"No remediation changes to commit for run {run.run_id}.{ignored_note}"

        prefix = show_prefix(resolved_path)
        result = run_git(resolved_path, "--literal-pathspecs", "add", "--", *to_commit)
        if result.returncode != 0:
            return _error(f"staging remediation files: {result.stderr.strip()}")

        message = message or _describe(to_commit)
        full_message = f"{message}\n\nApplied via darnit compliance server.\n\n{TRAILER_KEY}: {run.run_id}\n"
        commit_args = ("--literal-pathspecs", "commit", "-q", "--only", "-F", "-", "--", *to_commit)
        result = run_git(resolved_path, *commit_args, stdin=full_message)
        if result.returncode != 0:
            return _error(
                f"committing: {result.stderr.strip() or result.stdout.strip()}. Nothing was committed; "
                "the remediation files remain staged."
            )
    except FileNotFoundError:
        return "Error: git command not found. Ensure git is installed."
    except GitStateError as e:
        return _error(f"{e}. Nothing was committed.")
    except Exception as e:
        return f"Error: {str(e)}"

    return _report_commit(resolved_path, repository, run, branch, message, to_commit, prefix, ignored_note)


def _report_commit(
    resolved_path: str,
    repository: str,
    run: manifest.RunManifest,
    branch: str | None,
    message: str,
    to_commit: list[str],
    prefix: str,
    ignored_note: str,
) -> str:
    """Record and report a remediation commit that ``git commit`` has made.

    The commit is recorded in the run manifest before anything else that can
    fail; a later failure is reported with the commit, never as "Nothing was
    committed".
    """
    try:
        commit_sha = resolve_commit(resolved_path, "HEAD")
    except Exception:
        commit_sha = None
    if commit_sha is None:
        return _error(
            "the remediation files were committed, but HEAD cannot be read, so the commit is not recorded in "
            f"remediation run {run.run_id}. Check `git log` before committing again."
        )
    try:
        manifest.set_commit(repository, run.run_id, commit_sha, checkout=resolved_path)
    except Exception as e:
        return _error(
            f"committed {commit_sha[:12]}, but the commit is not recorded in remediation run {run.run_id}: {e}. "
            "The pull request tool needs it recorded; do not commit again."
        )
    if run.branch is None and branch:
        try:
            manifest.set_branch(repository, run.run_id, branch, checkout=resolved_path)
        except Exception as e:
            return _error(
                f"committed {commit_sha[:12]} and recorded it in remediation run {run.run_id}, but branch "
                f"'{branch}' is not recorded: {e}. The pull request tool needs the branch recorded; "
                "do not commit again."
            )
    try:
        listed = run_git(resolved_path, "diff-tree", "-r", "--no-commit-id", "--name-only", "-z", "--root", "HEAD")
        committed = sorted(from_root(resolved_path, [p for p in listed.stdout.split("\0") if p], prefix=prefix))
    except Exception as e:
        return _error(
            f"committed {commit_sha[:12]} and recorded it in remediation run {run.run_id}, "
            f"but its files cannot be listed: {e}. Check `git show --stat {commit_sha[:12]}`."
        )

    unexpected = sorted(set(committed) - set(to_commit))
    unexpected_note = (
        f"\n\n**Warning:** a commit hook added files outside the remediation run:\n{_bullets(unexpected)}"
        if unexpected
        else ""
    )

    return f"""Changes committed successfully

**Commit:** {commit_sha[:12]}
**Run:** {run.run_id}
**Message:** {message}
**Files:** {len(committed)} file(s) committed

**Committed files:**
{_bullets(committed)}{ignored_note}{unexpected_note}

**Next step:**
Create a pull request: `create_remediation_pr(local_path="{resolved_path}", run_id="{run.run_id}")`
"""


def _pr_body(changed_files: list[str]) -> str:
    body = """## Summary

This PR addresses compliance requirements.

## Changes

"""
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
        body += "\n".join(sorted(set(file_changes)))
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
    return body


def create_remediation_pr_impl(
    local_path: str = ".",
    title: str | None = None,
    body: str | None = None,
    base_branch: str | None = None,
    draft: bool = False,
    run_id: str | None = None,
    *,
    owner: str | None = None,
    repo: str | None = None,
) -> str:
    """Push a remediation run's branch, and only that branch, and open a pull request.

    The branch must hold the run's commit (or a rebased copy with the same
    patch), and every commit on it beyond its merge base with the base must
    carry the ``Darnit-Remediation-Run`` trailer. Unless ``base_branch`` is
    given, the base is the ref recorded with the run's branch. Commits and
    changed files are listed against the merge base of the branch and that
    ref as it is now; the commit recorded with the base is used only when the
    ref cannot be resolved.

    Args:
        local_path: Path to the repository
        title: PR title (auto-generated if not provided)
        body: PR body/description (auto-generated if not provided)
        base_branch: Target branch for PR (default: the base recorded with
            the run's branch, else the remote's default branch, else ``main``
            or ``master``)
        draft: Create as draft PR (default: False)
        run_id: Remediation run whose branch to push (default: the latest run)
        owner: Repository owner the run is recorded under (default: detected as the executor does)
        repo: Repository name the run is recorded under (default: detected as the executor does)

    Returns:
        Success message with PR URL or error
    """
    resolved_path, error = validate_local_path(local_path)
    if error:
        return _error(error)

    try:
        if not is_work_tree(resolved_path):
            return "Error: Not a git repository"

        repository = _repository(resolved_path, owner, repo)
        run, problem = _load_run(repository, run_id, resolved_path)
        if run is None:
            return _error(f"{problem}. Nothing was pushed.")
        branch = run.branch
        if branch is None:
            return _error(
                f"remediation run {run.run_id} has no branch. Create one first: "
                f'`create_remediation_branch(local_path="{resolved_path}", run_id="{run.run_id}")`'
            )
        if branch in PROTECTED_BRANCHES:
            return f"""Error: Cannot create PR from '{branch}' branch.

Create a remediation branch first:
`create_remediation_branch(local_path="{resolved_path}")`
"""
        if run.commit is None:
            return _error(
                f"nothing is committed for remediation run {run.run_id}; commit it first. Nothing was pushed."
            )
        tip = resolve_commit(resolved_path, f"refs/heads/{branch}")
        if tip is None:
            return _error(f"branch '{branch}' of remediation run {run.run_id} does not exist. Nothing was pushed.")
        if not holds_commit(resolved_path, tip, run.commit):
            return _error(
                f"branch '{branch}' does not contain the run's commit {run.commit[:12]} or a rebased copy of it. "
                "Nothing was pushed."
            )

        if base_branch is None and run.base:
            base = run.base
        else:
            base = resolve_base(resolved_path, branch, base_branch, current_first=False)
            if base is None:
                return _error(f"cannot determine the base of branch '{branch}'; pass base_branch. Nothing was pushed.")
        since = merge_base(resolved_path, base, branch)
        if since is None and resolve_commit(resolved_path, base) is None and base == run.base:
            since = run.base_commit
        if since is None:
            return _error(
                f"cannot determine where branch '{branch}' diverged from '{base}'; pass base_branch. Nothing was pushed."
            )
        if branch == base_branch_name(base):
            return _error(f"a pull request cannot be opened from '{branch}' into itself. Nothing was pushed.")
        foreign = describe_foreign_commits(resolved_path, since, branch, f"beyond '{base}'")
        if foreign:
            return _error(f"branch '{branch}' has {foreign}; it holds work remediation did not make. Nothing was pushed.")

        ref = f"refs/heads/{branch}"
        result = run_git(
            resolved_path,
            "push",
            "--no-follow-tags",
            "--recurse-submodules=no",
            "--set-upstream",
            _REMOTE,
            f"{ref}:{ref}",
        )
        if result.returncode != 0:
            return _error(f"pushing branch: {result.stderr.strip()}")

        result = run_git(resolved_path, "log", "--oneline", f"{since}..{ref}", "--")
        commits = [c for c in result.stdout.splitlines() if c.strip()] if result.returncode == 0 else []
        result = run_git(resolved_path, "diff", "--name-only", "-z", f"{since}...{ref}", "--")
        changed_files = [f for f in result.stdout.split("\0") if f] if result.returncode == 0 else []

        title = title or "chore(security): compliance improvements"
        body = body or _pr_body(changed_files)
        target = base_branch_name(base)

        cmd = ["pr", "create", "--head", branch, "--base", target, "--title", title, "--body", body]
        if draft:
            cmd.append("--draft")
        result = _gh(resolved_path, *cmd)

        if result.returncode != 0:
            error_msg = result.stderr.strip()
            if "already exists" in error_msg.lower():
                result = _gh(resolved_path, "pr", "view", branch, "--json", "url", "-q", ".url")
                if result.returncode == 0:
                    pr_url = result.stdout.strip()
                    return f"""Pull request already exists

**URL:** {pr_url}

The branch already has an open PR. You can view or update it at the URL above.
"""
            return f"Error creating PR: {error_msg}"

        pr_url = result.stdout.strip()

        return f"""Pull request created successfully

**URL:** {pr_url}
**Title:** {title}
**Branch:** {branch}
**Base:** {target}
**Run:** {run.run_id}
**Commits:** {len(commits)}
**Files changed:** {len(changed_files)}

The PR is ready for review. After approval and merge, re-run the audit to verify improvements.
"""

    except FileNotFoundError:
        return "Error: gh CLI not found. Install from https://cli.github.com/"
    except GitStateError as e:
        return _error(f"{e}. Nothing was pushed.")
    except Exception as e:
        return f"Error: {str(e)}"


def get_remediation_status_impl(local_path: str = ".") -> str:
    """Get the current git status for remediation work.

    Args:
        local_path: Path to the repository

    Returns:
        Current branch, uncommitted changes, and next steps
    """
    resolved_path, error = validate_local_path(local_path)
    if error:
        return f"Error: {error}"

    try:
        # Get current branch
        result = subprocess.run(
            ["git", "rev-parse", "--abbrev-ref", "HEAD"],
            cwd=resolved_path,
            capture_output=True,
            text=True
        )
        if result.returncode != 0:
            return "Error: Not a git repository"
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
            lines.append("**Warning:** You're on the default branch. Create a remediation branch first:")
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
            lines.append("PR is open and ready for review!")
        else:
            lines.append("")
            lines.append("Working directory is clean.")
            lines.append("")
            lines.append("**To start remediation:**")
            lines.append("```python")
            lines.append(f'create_remediation_branch(local_path="{resolved_path}")')
            lines.append(f'remediate_audit_findings(local_path="{resolved_path}", dry_run=False)')
            lines.append("```")

        return "\n".join(lines)

    except FileNotFoundError:
        return "Error: git command not found. Ensure git is installed."
    except Exception as e:
        return f"Error: {str(e)}"
