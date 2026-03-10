# Tutorial: Add a New Control to OpenSSF Baseline

This tutorial walks you through adding a new compliance control to the existing OpenSSF Baseline implementation. By the end, you'll have a new control that appears in audit results.

**Time**: ~20 minutes
**Prerequisites**: [Environment Setup](../getting-started/environment-setup.md) complete

## What We'll Build

We'll add a hypothetical control `OSPS-DO-99.01` that checks whether a project has a `CODE_OF_CONDUCT.md` file. This is a simple file-existence check with a remediation that creates the file from a template.

## Step 1: Understand the TOML Structure

Open `packages/darnit-baseline/openssf-baseline.toml`. This is the source of truth for all controls. You'll see sections for:

- `[metadata]` — Framework metadata
- `[templates.*]` — Content templates for remediation
- `[context.*]` — Project context collection
- `[controls.*]` — Control definitions

## Step 2: Add a Template

First, add a template that remediation will use to create the file. Find the `[templates]` section and add:

```toml
[templates.code_of_conduct]
description = "Standard CODE_OF_CONDUCT.md template"
content = """# Code of Conduct

## Our Pledge

We as members, contributors, and leaders pledge to make participation in our
community a harassment-free experience for everyone.

## Enforcement

Instances of abusive, harassing, or otherwise unacceptable behavior may be
reported to the project team. All complaints will be reviewed and investigated.
"""
```

## Step 3: Add the Control Definition

Find the controls section (controls are grouped by category prefix). Add the new control:

```toml
[controls."OSPS-DO-99.01"]
name = "CodeOfConductExists"
description = "Project must have a Code of Conduct"
tags = { level = 1, domain = "DO", documentation = true }
docs_url = "https://baseline.openssf.org/versions/2025-10-10#OSPS-DO-99.01"
help_md = """Create a CODE_OF_CONDUCT.md file in the repository root.

**Remediation:**
1. Create CODE_OF_CONDUCT.md
2. Consider adopting the Contributor Covenant: https://www.contributor-covenant.org/

**References:**
- [GitHub Code of Conduct guide](https://docs.github.com/en/communities/setting-up-your-project-for-healthy-contributions/adding-a-code-of-conduct-to-your-project)
"""
```

## Step 4: Add Pass Definitions

Add the sieve passes that check whether the control is met. We'll use a `file_exists` pass (deterministic) and a `manual` fallback:

```toml
[[controls."OSPS-DO-99.01".passes]]
handler = "file_exists"
files = [
    "CODE_OF_CONDUCT.md",
    ".github/CODE_OF_CONDUCT.md",
    "docs/CODE_OF_CONDUCT.md",
    "CODE_OF_CONDUCT",
]

[[controls."OSPS-DO-99.01".passes]]
handler = "manual"
steps = [
    "Check repository root for a Code of Conduct file",
    "Verify the Code of Conduct covers expected behavior and enforcement",
]
```

## Step 5: Add Remediation

Add a remediation section that creates the file from the template:

```toml
[controls."OSPS-DO-99.01".remediation]
safe = true
dry_run_supported = true

[controls."OSPS-DO-99.01".remediation.file_create]
path = "CODE_OF_CONDUCT.md"
template = "code_of_conduct"
overwrite = false

[controls."OSPS-DO-99.01".remediation.project_update]
set = { "governance.code_of_conduct.path" = "CODE_OF_CONDUCT.md" }
```

## Step 6: Validate Sync

Run the validation script to ensure your changes are consistent:

```bash
uv run python scripts/validate_sync.py --verbose
```

Expected output — all checks should pass:

```
Checking framework-design spec...
✓ TOML Schema section found
✓ Built-in Pass Types section found
✓ Sieve Orchestrator section found
All sync checks passed!
```

## Step 7: Run an Audit

Test the new control by running an audit against a repository that lacks a Code of Conduct:

```bash
# Create a test directory
mkdir -p /tmp/test-repo && cd /tmp/test-repo && git init

# Run the audit
cd /path/to/baseline-mcp
uv run darnit audit /tmp/test-repo --level 1
```

You should see `OSPS-DO-99.01` in the output with status WARN or FAIL (since the test repo has no CODE_OF_CONDUCT.md).

## Step 8: Verify Remediation (Optional)

Test that remediation creates the file:

```bash
uv run darnit remediate /tmp/test-repo --categories code_of_conduct --dry-run
```

Expected: The dry-run output shows that CODE_OF_CONDUCT.md would be created.

## Step 9: Run Tests

Make sure existing tests still pass:

```bash
uv run pytest tests/ --ignore=tests/integration/ -q
```

## Step 10: Complete Pre-Commit Checklist

Before committing, run the full validation:

```bash
# Lint
uv run ruff check .

# Tests
uv run pytest tests/ --ignore=tests/integration/ -q

# Spec sync
uv run python scripts/validate_sync.py --verbose

# Regenerate docs
uv run python scripts/generate_docs.py
git diff docs/generated/
```

## Summary

You've added a new control by:

1. Adding a template in `[templates.code_of_conduct]`
2. Defining the control in `[controls."OSPS-DO-99.01"]`
3. Adding `file_exists` and `manual` passes
4. Adding `file_create` remediation with a template
5. Validating and testing the change

The entire control was defined in TOML — no Python code needed.

## Next Steps

- [CEL Reference](../getting-started/cel-reference.md) — Add CEL expressions for more complex checks
- [Implementation Development](../getting-started/implementation-development.md) — Custom handlers and advanced features
- [Tutorial: Create a New Implementation](create-new-implementation.md) — Build a plugin from scratch
- Back to [Getting Started](../getting-started/README.md)
