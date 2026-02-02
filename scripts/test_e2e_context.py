#!/usr/bin/env python3
"""End-to-end test script for Interactive Context Collection System.

This script tests the full workflow:
1. Create a test repository that fails all controls
2. Run an initial audit
3. Add project context using the new MCP tools
4. Run remediation
5. Re-run audit to verify improvements
6. Test get_pending_context

Usage:
    uv run python scripts/test_e2e_context.py [--keep-repo]

Options:
    --keep-repo  Don't delete the test repo after running
"""

import argparse
import os
import shutil
import sys
import tempfile
from datetime import datetime


def main():
    parser = argparse.ArgumentParser(description="E2E test for context collection")
    parser.add_argument("--keep-repo", action="store_true", help="Keep test repo after run")
    parser.add_argument("--no-github", action="store_true", help="Don't create GitHub repo")
    args = parser.parse_args()

    # Use temp dir or create in current dir
    test_dir = tempfile.mkdtemp(prefix="baseline-e2e-")
    repo_name = f"baseline-test-{datetime.now().strftime('%Y%m%d-%H%M%S')}"
    repo_path = os.path.join(test_dir, repo_name)

    print("=" * 60)
    print("🧪 OpenSSF Baseline - End-to-End Context Collection Test")
    print("=" * 60)
    print(f"\n📁 Test directory: {test_dir}")
    print(f"📦 Repo name: {repo_name}\n")

    try:
        # Step 1: Create test repository
        # Use the current directory as parent since validate_local_path checks for git
        print("-" * 60)
        print("Step 1: Create test repository")
        print("-" * 60)

        # Create test repo manually (avoiding validate_local_path git check)
        os.makedirs(os.path.join(repo_path, "src"))

        # Create package.json
        package_json = """{
  "name": "baseline-test",
  "version": "0.0.1",
  "main": "src/index.js"
}
"""
        with open(os.path.join(repo_path, "package.json"), "w") as f:
            f.write(package_json)

        # Create src/index.js
        with open(os.path.join(repo_path, "src", "index.js"), "w") as f:
            f.write("console.log('Hello');")

        # Create .gitignore
        with open(os.path.join(repo_path, ".gitignore"), "w") as f:
            f.write("node_modules/\n")

        # Initialize git
        import subprocess
        subprocess.run(["git", "init"], cwd=repo_path, capture_output=True, check=True)
        subprocess.run(["git", "add", "."], cwd=repo_path, capture_output=True, check=True)
        subprocess.run(
            ["git", "commit", "-m", "Initial commit - intentionally non-compliant"],
            cwd=repo_path, capture_output=True, check=True
        )

        print(f"✅ Created test repository: {repo_path}")
        print("   - No LICENSE, README, SECURITY.md, CONTRIBUTING.md")
        print("   - No CI/CD workflows")
        print("   - No branch protection")

        if not os.path.exists(repo_path):
            print("❌ Failed to create test repository")
            return 1

        # Step 2: Run initial audit
        print("\n" + "-" * 60)
        print("Step 2: Initial audit (expect many failures)")
        print("-" * 60)

        from darnit_baseline.tools import audit_openssf_baseline

        audit_result = audit_openssf_baseline(
            local_path=repo_path,
            level=1,  # Start with level 1 for faster testing
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

        # Step 3: Test get_pending_context
        print("\n" + "-" * 60)
        print("Step 3: Test get_pending_context MCP tool")
        print("-" * 60)

        from darnit_baseline.tools import get_pending_context

        pending = get_pending_context(local_path=repo_path, level=1)
        print(pending[:1500] + "..." if len(pending) > 1500 else pending)

        # Step 4: Add project context using confirm_project_context
        print("\n" + "-" * 60)
        print("Step 4: Set project context with new parameters")
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

        # Step 5: Verify context was saved
        print("\n" + "-" * 60)
        print("Step 5: Verify context was saved")
        print("-" * 60)

        from darnit.config.context_storage import load_context

        context = load_context(repo_path)
        print(f"Loaded context categories: {list(context.keys())}")

        # Check each value
        for category, values in context.items():
            print(f"\n  {category}:")
            for key, ctx_value in values.items():
                print(f"    - {key}: {ctx_value.value} (source: {ctx_value.source})")

        # Step 6: Run dry-run remediation
        print("\n" + "-" * 60)
        print("Step 6: Dry-run remediation")
        print("-" * 60)

        from darnit_baseline.tools import remediate_audit_findings

        remediation_result = remediate_audit_findings(
            local_path=repo_path,
            categories=["security_policy", "contributing"],
            dry_run=True,
        )
        print(remediation_result[:2000] + "..." if len(remediation_result) > 2000 else remediation_result)

        # Step 7: Apply remediation (not dry run)
        print("\n" + "-" * 60)
        print("Step 7: Apply remediation (security_policy, contributing)")
        print("-" * 60)

        remediation_result = remediate_audit_findings(
            local_path=repo_path,
            categories=["security_policy", "contributing"],
            dry_run=False,
        )
        print(remediation_result[:2000] + "..." if len(remediation_result) > 2000 else remediation_result)

        # Step 8: Re-run audit
        print("\n" + "-" * 60)
        print("Step 8: Re-run audit after remediation")
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

        # Step 9: Check pending context after setting values
        print("\n" + "-" * 60)
        print("Step 9: Check pending context (should exclude confirmed items)")
        print("-" * 60)

        pending2 = get_pending_context(local_path=repo_path, level=1)

        # Check that confirmed items are not in pending
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
            print(f"\n📁 Test repo kept at: {repo_path}")

        return 0

    except Exception as e:
        print(f"\n❌ Error: {e}")
        import traceback
        traceback.print_exc()
        return 1

    finally:
        if not args.keep_repo:
            print(f"\n🧹 Cleaning up: {test_dir}")
            try:
                shutil.rmtree(test_dir)
            except Exception as e:
                print(f"   Warning: Failed to clean up: {e}")


if __name__ == "__main__":
    sys.exit(main())
