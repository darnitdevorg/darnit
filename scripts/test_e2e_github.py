#!/usr/bin/env python3
"""End-to-end test script using GitHub template repository.

This script tests the full workflow by:
1. Creating a new repo from a template using `gh repo create --template`
2. Cloning the repo locally
3. Running an initial audit
4. Adding project context using the MCP tools
5. Running remediation
6. Re-running audit to verify improvements
7. Automatically cleaning up the GitHub repo (unless --keep-repo)

Usage:
    uv run python scripts/test_e2e_github.py [options]

Options:
    --keep-repo         Don't delete the GitHub repo after running
    --org ORG           GitHub org to create repo in (default: darnit-tests)
    --template OWNER/REPO  Template repo to use (default: mlieberman85/baseline-test-repo)
    --name NAME         Name for the test repo (default: baseline-test-TIMESTAMP)
    --private           Create private repo instead of public

Examples:
    # Run with defaults (creates in darnit-tests org, cleans up after)
    uv run python scripts/test_e2e_github.py

    # Use a different org
    uv run python scripts/test_e2e_github.py --org my-other-org

    # Keep the repo for manual inspection
    uv run python scripts/test_e2e_github.py --keep-repo

    # Use a different template
    uv run python scripts/test_e2e_github.py --template myorg/my-template

Setup (one-time):
    # Create a dedicated test org on GitHub (recommended for safety)
    # Go to: https://github.com/organizations/plan
    # Or use an existing org you control

    # Ensure gh CLI has delete_repo scope
    gh auth refresh -h github.com -s delete_repo
"""

import argparse
import os
import shutil
import subprocess
import sys
import tempfile
from datetime import datetime


def run_cmd(cmd: list[str], cwd: str | None = None, check: bool = True) -> subprocess.CompletedProcess:
    """Run a command and return the result."""
    result = subprocess.run(cmd, cwd=cwd, capture_output=True, text=True)
    if check and result.returncode != 0:
        print(f"❌ Command failed: {' '.join(cmd)}")
        print(f"   stdout: {result.stdout}")
        print(f"   stderr: {result.stderr}")
        raise subprocess.CalledProcessError(result.returncode, cmd)
    return result


def check_gh_cli():
    """Check that gh CLI is installed and authenticated."""
    try:
        result = run_cmd(["gh", "auth", "status"], check=False)
        if result.returncode != 0:
            print("❌ GitHub CLI not authenticated. Run: gh auth login")
            return False
        return True
    except FileNotFoundError:
        print("❌ GitHub CLI (gh) not found. Install from: https://cli.github.com/")
        return False


def get_gh_username() -> str:
    """Get the authenticated GitHub username."""
    result = run_cmd(["gh", "api", "user", "--jq", ".login"])
    return result.stdout.strip()


def wait_for_template_ready(repo: str, max_wait: int = 30) -> bool:
    """Wait for template files to be copied to the new repo.

    GitHub's template copying is asynchronous, so we need to wait
    for the files to appear before cloning.
    """
    import time

    print("⏳ Waiting for template files to be copied...")
    for i in range(max_wait):
        result = run_cmd(
            ["gh", "api", f"repos/{repo}/contents", "--jq", "length"],
            check=False
        )
        if result.returncode == 0:
            file_count = int(result.stdout.strip() or "0")
            if file_count > 0:
                print(f"✅ Template files ready ({file_count} items)")
                return True
        time.sleep(1)
        if (i + 1) % 5 == 0:
            print(f"   Still waiting... ({i + 1}s)")

    print(f"⚠️  Timeout waiting for template files after {max_wait}s")
    return False


def create_repo_from_template(template: str, name: str, org: str | None = None, private: bool = False) -> str:
    """Create a new repo from template and return the full repo name."""
    visibility = "--private" if private else "--public"

    # If org specified, create as org/name, otherwise just name (personal account)
    repo_name = f"{org}/{name}" if org else name

    print(f"📦 Creating repo from template: {template}")
    print(f"   Target: {repo_name}")
    run_cmd([
        "gh", "repo", "create", repo_name,
        "--template", template,
        visibility,
        "--confirm"
    ])

    # Get the full repo name (owner/repo)
    if org:
        return f"{org}/{name}"
    else:
        username = get_gh_username()
        return f"{username}/{name}"


def clone_repo(repo: str, dest: str) -> str:
    """Clone a repo to destination and return the path."""
    print(f"📥 Cloning {repo}...")
    run_cmd(["gh", "repo", "clone", repo, dest])
    return dest


def delete_repo(repo: str):
    """Delete a GitHub repository."""
    print(f"🗑️  Deleting GitHub repo: {repo}")
    run_cmd(["gh", "repo", "delete", repo, "--yes"])


def main():
    parser = argparse.ArgumentParser(
        description="E2E test using GitHub template repository",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog=__doc__
    )
    parser.add_argument(
        "--keep-repo",
        action="store_true",
        help="Don't delete the GitHub repo after running"
    )
    parser.add_argument(
        "--org",
        default=os.environ.get("BASELINE_TEST_ORG", "darnit-tests"),
        help="GitHub org to create repo in (default: darnit-tests, or BASELINE_TEST_ORG env var)"
    )
    parser.add_argument(
        "--template",
        default="mlieberman85/baseline-test-repo",
        help="Template repo to use (default: mlieberman85/baseline-test-repo)"
    )
    parser.add_argument(
        "--name",
        default=None,
        help="Name for the test repo (default: baseline-test-TIMESTAMP)"
    )
    parser.add_argument(
        "--private",
        action="store_true",
        help="Create private repo instead of public"
    )
    args = parser.parse_args()

    # Verify org exists if specified
    if args.org:
        result = run_cmd(["gh", "api", f"orgs/{args.org}", "--jq", ".login"], check=False)
        if result.returncode != 0:
            print(f"❌ Organization '{args.org}' not found or not accessible.")
            print("   Create it at: https://github.com/organizations/plan")
            print("   Or check your access permissions.")
            return 1

    # Generate repo name if not provided
    if args.name is None:
        args.name = f"baseline-test-{datetime.now().strftime('%Y%m%d-%H%M%S')}"

    print("=" * 60)
    print("🧪 OpenSSF Baseline - End-to-End GitHub Template Test")
    print("=" * 60)
    print(f"\n📋 Template: {args.template}")
    print(f"📦 Repo name: {args.org + '/' if args.org else ''}{args.name}")
    print(f"🏢 Organization: {args.org or '(personal account)'}")
    print(f"🔒 Visibility: {'private' if args.private else 'public'}")
    print(f"🧹 Cleanup: {'manual' if args.keep_repo else 'automatic'}")

    if not args.org and not args.keep_repo:
        print("\n⚠️  Warning: Creating in personal account without --keep-repo.")
        print("   Consider using --org <test-org> for safer automated cleanup.")
        print()
    elif args.org:
        print()  # Just add spacing

    # Check prerequisites
    if not check_gh_cli():
        return 1

    # Create temp directory for clone
    test_dir = tempfile.mkdtemp(prefix="baseline-e2e-")
    repo_path = os.path.join(test_dir, args.name)
    full_repo_name = None

    try:
        # Step 1: Create repo from template
        print("-" * 60)
        print("Step 1: Create repo from template")
        print("-" * 60)

        full_repo_name = create_repo_from_template(
            args.template,
            args.name,
            org=args.org,
            private=args.private,
        )
        print(f"✅ Created: https://github.com/{full_repo_name}")

        # Wait for template files to be copied (GitHub does this asynchronously)
        if not wait_for_template_ready(full_repo_name):
            print("❌ Template files were not copied in time")
            return 1

        # Step 2: Clone the repo
        print("\n" + "-" * 60)
        print("Step 2: Clone repository")
        print("-" * 60)

        clone_repo(full_repo_name, repo_path)
        print(f"✅ Cloned to: {repo_path}")

        # Step 3: Run initial audit
        print("\n" + "-" * 60)
        print("Step 3: Initial audit (expect many failures)")
        print("-" * 60)

        from darnit_baseline.tools import audit_openssf_baseline

        audit_result = audit_openssf_baseline(
            local_path=repo_path,
            level=1,
            output_format="markdown",
        )

        # Count results
        pass_count = audit_result.count("✅ Pass") + audit_result.count("✅ PASS")
        fail_count = audit_result.count("❌ Fail") + audit_result.count("❌ FAIL")

        print(f"\n📊 Initial Results: {pass_count} PASS, {fail_count} FAIL")

        # Show summary section only
        if "## Summary" in audit_result:
            summary_start = audit_result.index("## Summary")
            summary_end = audit_result.index("## Level", summary_start) if "## Level" in audit_result else summary_start + 500
            print(audit_result[summary_start:summary_end])

        # Step 4: Test get_pending_context
        print("\n" + "-" * 60)
        print("Step 4: Test get_pending_context MCP tool")
        print("-" * 60)

        from darnit_baseline.tools import get_pending_context

        pending = get_pending_context(local_path=repo_path, level=1)
        print(pending[:1500] + "..." if len(pending) > 1500 else pending)

        # Step 5: Add project context
        print("\n" + "-" * 60)
        print("Step 5: Set project context with new parameters")
        print("-" * 60)

        from darnit_baseline.tools import confirm_project_context

        context_result = confirm_project_context(
            local_path=repo_path,
            has_releases=True,
            is_library=False,
            ci_provider="github",
            maintainers=["@test-maintainer"],
            security_contact="security@example.com",
            governance_model="bdfl",
        )
        print(context_result)

        # Step 6: Verify context was saved
        print("\n" + "-" * 60)
        print("Step 6: Verify context was saved")
        print("-" * 60)

        from darnit.config.context_storage import load_context

        context = load_context(repo_path)
        print(f"Loaded context categories: {list(context.keys())}")

        for category, values in context.items():
            print(f"\n  {category}:")
            for key, ctx_value in values.items():
                print(f"    - {key}: {ctx_value.value} (source: {ctx_value.source})")

        # Step 7: Dry-run remediation
        print("\n" + "-" * 60)
        print("Step 7: Dry-run remediation")
        print("-" * 60)

        from darnit_baseline.tools import remediate_audit_findings

        remediation_result = remediate_audit_findings(
            local_path=repo_path,
            categories=["security_policy", "contributing"],
            dry_run=True,
        )
        print(remediation_result[:2000] + "..." if len(remediation_result) > 2000 else remediation_result)

        # Step 8: Apply remediation
        print("\n" + "-" * 60)
        print("Step 8: Apply remediation (security_policy, contributing)")
        print("-" * 60)

        remediation_result = remediate_audit_findings(
            local_path=repo_path,
            categories=["security_policy", "contributing"],
            dry_run=False,
        )
        print(remediation_result[:2000] + "..." if len(remediation_result) > 2000 else remediation_result)

        # Step 9: Re-run audit
        print("\n" + "-" * 60)
        print("Step 9: Re-run audit after remediation")
        print("-" * 60)

        audit_result2 = audit_openssf_baseline(
            local_path=repo_path,
            level=1,
            output_format="markdown",
        )

        pass_count2 = audit_result2.count("✅ Pass") + audit_result2.count("✅ PASS")
        fail_count2 = audit_result2.count("❌ Fail") + audit_result2.count("❌ FAIL")

        print(f"\n📊 After Remediation: {pass_count2} PASS, {fail_count2} FAIL")
        print(f"   Improvement: +{pass_count2 - pass_count} controls fixed")

        # Check for "Help Improve This Audit" section
        if "Help Improve This Audit" in audit_result2:
            print("\n✅ 'Help Improve This Audit' section is present in audit output!")
        else:
            print("\n⚠️  'Help Improve This Audit' section not found (may have no pending context)")

        # Step 10: Check pending context after setting values
        print("\n" + "-" * 60)
        print("Step 10: Check pending context (should exclude confirmed items)")
        print("-" * 60)

        pending2 = get_pending_context(local_path=repo_path, level=1)

        if "maintainers" not in pending2:
            print("✅ 'maintainers' correctly excluded from pending context")
        else:
            print("⚠️  'maintainers' still in pending (may need investigation)")

        if "ci_provider" not in pending2:
            print("✅ 'ci_provider' correctly excluded from pending context")
        else:
            print("⚠️  'ci_provider' still in pending (may need investigation)")

        print("\n" + "=" * 60)
        print("✅ End-to-end test completed!")
        print("=" * 60)

        if args.keep_repo:
            print(f"\n📁 Local clone: {repo_path}")
            print(f"🌐 GitHub repo: https://github.com/{full_repo_name}")
            print("\n⚠️  Remember to delete the repo when done:")
            print(f"   gh repo delete {full_repo_name} --yes")

        return 0

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        # Cleanup
        if not args.keep_repo:
            # Delete GitHub repo
            if full_repo_name:
                print(f"\n🧹 Cleaning up GitHub repo: {full_repo_name}")
                try:
                    delete_repo(full_repo_name)
                    print("✅ GitHub repo deleted")
                except Exception as e:
                    print(f"⚠️  Failed to delete GitHub repo: {e}")
                    print(f"   Manual cleanup: gh repo delete {full_repo_name} --yes")

            # Delete local clone
            print(f"🧹 Cleaning up local files: {test_dir}")
            try:
                shutil.rmtree(test_dir)
            except Exception as e:
                print(f"   Warning: Failed to clean up local files: {e}")
        else:
            print(f"\n📁 Test files kept at: {repo_path}")


if __name__ == "__main__":
    sys.exit(main())
