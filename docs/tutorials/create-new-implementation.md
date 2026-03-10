# Tutorial: Create a New Compliance Implementation

This tutorial walks you through creating a brand new compliance framework plugin for darnit from scratch. By the end, you'll have a working plugin that the framework discovers and can audit against.

**Time**: ~40 minutes
**Prerequisites**: [Environment Setup](../getting-started/environment-setup.md) complete

## What We'll Build

We'll create `darnit-hygiene`, a simple "code hygiene" compliance framework with two controls:
- `HYG-01`: Project must have a README
- `HYG-02`: Project must have a LICENSE file

## Step 1: Create the Package Directory

```bash
cd /path/to/baseline-mcp
mkdir -p packages/darnit-hygiene/src/darnit_hygiene
```

## Step 2: Create pyproject.toml

Create `packages/darnit-hygiene/pyproject.toml`:

```toml
[project]
name = "darnit-hygiene"
version = "0.1.0"
description = "Code hygiene compliance checks for darnit"
requires-python = ">=3.11"
dependencies = [
    "darnit>=0.1.0",
]

[project.entry-points."darnit.implementations"]
hygiene = "darnit_hygiene:register"

[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"

[tool.hatch.build.targets.wheel]
packages = ["src/darnit_hygiene"]
```

The critical part is the entry point:
```toml
[project.entry-points."darnit.implementations"]
hygiene = "darnit_hygiene:register"
```

This tells darnit to call `darnit_hygiene.register()` when discovering implementations.

## Step 3: Create the TOML Configuration

Create `packages/darnit-hygiene/hygiene.toml`:

```toml
[metadata]
name = "hygiene"
display_name = "Code Hygiene Standard"
version = "0.1.0"
schema_version = "0.1.0-alpha"
spec_version = "Hygiene v1.0"
description = "Basic code hygiene checks for any project"

[defaults]
check_adapter = "builtin"
remediation_adapter = "builtin"

# Templates for remediation
[templates.readme]
description = "Basic README template"
content = """# $REPO

A brief description of this project.

## Getting Started

TODO: Add getting started instructions.

## License

See LICENSE file.
"""

[templates.license_mit]
description = "MIT License template"
content = """MIT License

Copyright (c) 2026 $OWNER

Permission is hereby granted, free of charge, to any person obtaining a copy
of this software and associated documentation files (the "Software"), to deal
in the Software without restriction, including without limitation the rights
to use, copy, modify, merge, publish, distribute, sublicense, and/or sell
copies of the Software, and to permit persons to whom the Software is
furnished to do so, subject to the following conditions:

The above copyright notice and this permission notice shall be included in all
copies or substantial portions of the Software.

THE SOFTWARE IS PROVIDED "AS IS", WITHOUT WARRANTY OF ANY KIND, EXPRESS OR
IMPLIED, INCLUDING BUT NOT LIMITED TO THE WARRANTIES OF MERCHANTABILITY,
FITNESS FOR A PARTICULAR PURPOSE AND NONINFRINGEMENT.
"""

# Control 1: README exists
[controls."HYG-01"]
name = "ReadmeExists"
description = "Project must have a README file"
tags = { level = 1, domain = "DOC" }
help_md = """Create a README.md file in the project root with a description of your project."""

[[controls."HYG-01".passes]]
handler = "file_exists"
files = ["README.md", "README.rst", "README.txt", "README"]

[[controls."HYG-01".passes]]
handler = "manual"
steps = ["Check repository root for a README file"]

[controls."HYG-01".remediation]
safe = true
dry_run_supported = true

[controls."HYG-01".remediation.file_create]
path = "README.md"
template = "readme"
overwrite = false

# Control 2: LICENSE exists
[controls."HYG-02"]
name = "LicenseExists"
description = "Project must have a LICENSE file"
tags = { level = 1, domain = "LE" }
help_md = """Create a LICENSE file in the project root. Choose an appropriate open source license."""

[[controls."HYG-02".passes]]
handler = "file_exists"
files = ["LICENSE", "LICENSE.md", "LICENSE.txt", "COPYING"]

[[controls."HYG-02".passes]]
handler = "manual"
steps = ["Check repository root for a LICENSE file"]

[controls."HYG-02".remediation]
safe = true
dry_run_supported = true

[controls."HYG-02".remediation.file_create]
path = "LICENSE"
template = "license_mit"
overwrite = false

# MCP Tools (built-in)
[mcp.tools.audit]
builtin = "audit"
description = "Run code hygiene audit"

[mcp.tools.remediate]
builtin = "remediate"
description = "Auto-fix failing hygiene controls"

[mcp.tools.list_controls]
builtin = "list_controls"
description = "List all hygiene controls"
```

## Step 4: Create the Implementation Class

Create `packages/darnit-hygiene/src/darnit_hygiene/implementation.py`:

```python
"""Code Hygiene compliance implementation for darnit."""

from pathlib import Path
from typing import Any

from darnit.core.plugin import ControlSpec


class HygieneImplementation:
    """Code Hygiene Standard implementation."""

    @property
    def name(self) -> str:
        return "hygiene"

    @property
    def display_name(self) -> str:
        return "Code Hygiene Standard"

    @property
    def version(self) -> str:
        return "0.1.0"

    @property
    def spec_version(self) -> str:
        return "Hygiene v1.0"

    def get_all_controls(self) -> list[ControlSpec]:
        controls = []
        for level in [1, 2, 3]:
            controls.extend(self.get_controls_by_level(level))
        return controls

    def get_controls_by_level(self, level: int) -> list[ControlSpec]:
        from darnit.sieve.registry import get_control_registry

        registry = get_control_registry()
        return registry.get_specs_by_level(level)

    def get_rules_catalog(self) -> dict[str, Any]:
        return {}

    def get_remediation_registry(self) -> dict[str, Any]:
        return {}

    def get_framework_config_path(self) -> Path | None:
        # Navigate: implementation.py → darnit_hygiene/ → src/ → darnit-hygiene/ → hygiene.toml
        return Path(__file__).parent.parent.parent / "hygiene.toml"

    def register_controls(self) -> None:
        """TOML-first: controls are defined in hygiene.toml.

        No Python registration needed for simple implementations.
        """
        pass
```

## Step 5: Create the Register Function

Create `packages/darnit-hygiene/src/darnit_hygiene/__init__.py`:

```python
"""darnit-hygiene: Code Hygiene compliance checks."""


def register():
    """Register the Hygiene implementation with darnit.

    Called by darnit's plugin discovery via entry points.
    """
    from .implementation import HygieneImplementation

    return HygieneImplementation()
```

## Step 6: Verify the File Structure

Your package should look like this:

```bash
ls -R packages/darnit-hygiene/
```

Expected output:

```
packages/darnit-hygiene/:
hygiene.toml  pyproject.toml  src

packages/darnit-hygiene/src:
darnit_hygiene

packages/darnit-hygiene/src/darnit_hygiene:
__init__.py  implementation.py
```

## Step 7: Install the Package

Install the new package in development mode:

```bash
uv pip install -e packages/darnit-hygiene
```

Expected output:

```
Resolved X packages in Xms
Installed 1 package in Xms
 + darnit-hygiene==0.1.0 (from file:///path/to/baseline-mcp/packages/darnit-hygiene)
```

## Step 8: Verify Plugin Discovery

Check that darnit discovers your new implementation:

```bash
uv run python -c "
from darnit.core.discovery import discover_implementations
impls = discover_implementations()
for impl in impls:
    print(f'{impl.name}: {impl.display_name} v{impl.version}')
"
```

Expected output (your plugin should appear):

```
openssf-baseline: OpenSSF Baseline v0.1.0
hygiene: Code Hygiene Standard v0.1.0
```

## Step 9: Run an Audit

Test against a repository:

```bash
# Create a test repo without README or LICENSE
mkdir -p /tmp/test-hygiene && cd /tmp/test-hygiene && git init

# Audit with the hygiene framework
cd /path/to/baseline-mcp
uv run darnit audit /tmp/test-hygiene --framework hygiene
```

Expected: Both `HYG-01` and `HYG-02` should show as WARN or FAIL (no README or LICENSE in the test repo).

Now add a README and re-audit:

```bash
echo "# Test Project" > /tmp/test-hygiene/README.md
uv run darnit audit /tmp/test-hygiene --framework hygiene
```

Expected: `HYG-01` now shows PASS, `HYG-02` still WARN/FAIL.

## Step 10: Test as MCP Server (Optional)

Serve the hygiene framework as an MCP server:

```bash
uv run darnit serve --framework hygiene
```

Or configure in Claude Code settings:

```json
{
  "mcpServers": {
    "hygiene": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/baseline-mcp", "darnit", "serve", "--framework", "hygiene"]
    }
  }
}
```

## Step 11: Clean Up

If this was just for learning, remove the package:

```bash
uv pip uninstall darnit-hygiene
rm -rf packages/darnit-hygiene
```

## Summary

You've created a complete compliance implementation by:

1. Creating a package with `pyproject.toml` and entry points
2. Writing a TOML configuration with controls, passes, templates, and remediation
3. Implementing the `ComplianceImplementation` protocol class
4. Writing the `register()` function
5. Installing and testing the plugin

The entire implementation was **TOML-first** — the Python code is minimal boilerplate. All control definitions, pass logic, templates, and remediation are in `hygiene.toml`.

## Next Steps

- [Implementation Development](../getting-started/implementation-development.md) — Custom handlers, CEL expressions, advanced features
- [CEL Reference](../getting-started/cel-reference.md) — Add CEL expressions to your controls
- [Tutorial: Add a New Control](add-new-control.md) — Add controls to an existing implementation
- Back to [Getting Started](../getting-started/README.md)
