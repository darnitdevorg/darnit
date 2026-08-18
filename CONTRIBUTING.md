# Contributing to darnit

Thank you for your interest in contributing! This document provides our contribution policy. For detailed setup and workflow instructions, see the [Getting Started Guide](GETTING_STARTED.md).

## Project Governance

The Project is governed under the [Technical Charter](CHARTER.md) for Darnit a Series of LF Projects, LLC, which is the binding authority. Where any other document differs from the Charter, the Charter controls.

[GOVERNANCE.md](GOVERNANCE.md) documents the Project's [roles](GOVERNANCE.md#roles-and-responsibilities) and the approach for [determining the TSC's voting members](GOVERNANCE.md#technical-steering-committee-membership), along with day-to-day practice: PR review thresholds, the release process, and how TSC decisions are recorded.

The current voting members of the TSC are listed in [TECHNICAL-STEERING-COMMITTEE.md](TECHNICAL-STEERING-COMMITTEE.md).

## Developer Certificate of Origin

All new inbound code contributions must be accompanied by a [Developer Certificate of Origin](https://developercertificate.org) sign-off (Charter 7.b.ii). Sign off by committing with:

```bash
git commit -s
```

This appends a `Signed-off-by:` line to the commit message. Pull requests without a sign-off on every commit will not be merged.

## Licensing of Contributions

- **Code**, inbound and outbound, is licensed under the Apache License, Version 2.0 — the Project License (Charter 7.b.i, 7.b.iii).
- **Documentation** is made available under the Creative Commons Attribution 4.0 International License (Charter 7.b.iv).
- **Copyright** in each contribution is retained by its copyright holder. No contributor is required to assign copyright to the Project, and there is no CLA (Charter 7.a).
- Contributed files should carry license information, such as an SPDX short-form identifier (Charter 7.d).
- Any other license, inbound or outbound, requires a TSC exception approved by a two-thirds vote of the entire TSC (Charter 7.c).

When the Project integrates with or contributes back to upstream projects, it conforms to those projects' license requirements and contribution processes (Charter 7.b.v).

## Code of Conduct

All Collaborators are expected to uphold a welcoming, harassment-free environment. The TSC may adopt a Project-specific Code of Conduct, which is subject to approval by the LF Projects Series Manager. Until such a Code of Conduct is approved, the [LF Projects Code of Conduct](https://lfprojects.org/policies) applies to all Collaborators in the Project (Charter 4.b).

## Getting Started

See the [Getting Started Guide](GETTING_STARTED.md) for:

- [Environment Setup](docs/getting-started/environment-setup.md) — Prerequisites, fork, clone, install
- [Development Workflow](docs/getting-started/development-workflow.md) — Branching, pre-commit checklist, PRs
- [Framework Development](docs/getting-started/framework-development.md) — Working on the core framework
- [Implementation Development](docs/getting-started/implementation-development.md) — Creating compliance plugins

## MCP Server Development

Most day-to-day darnit development happens through the local MCP server rather
than the debug-only CLI commands. If you are working on tools, framework
configuration, or MCP-facing behavior, start here.

### Start the Server

Install dependencies first:

```bash
uv sync
```

Common server startup commands:

```bash
# Use the built-in OpenSSF Baseline framework
uv run darnit serve --framework openssf-baseline

# Use a custom TOML framework file
uv run darnit serve path/to/framework.toml

# Auto-detect a framework from the current environment
uv run darnit serve
```

Useful development helpers:

```bash
# Show available frameworks
uv run darnit list

# Enable verbose logging while running the MCP server
uv run darnit -v serve --framework openssf-baseline
```

### Connect to Claude Code

Add the darnit MCP server to either your global Claude Code settings
(`~/.claude/settings.json`) or a project-local file (`.claude/settings.json`):

```json
{
  "mcpServers": {
    "openssf-baseline": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/absolute/path/to/darnit",
        "darnit",
        "serve",
        "--framework",
        "openssf-baseline"
      ]
    }
  }
}
```

### Connect to Cursor

Cursor supports the same stdio server model. Add the same server definition to
either a project-local `.cursor/mcp.json` file or your global
`~/.cursor/mcp.json`:

```json
{
  "mcpServers": {
    "openssf-baseline": {
      "command": "uv",
      "args": [
        "run",
        "--directory",
        "/absolute/path/to/darnit",
        "darnit",
        "serve",
        "--framework",
        "openssf-baseline"
      ]
    }
  }
}
```

### Smoke Test Tool Calls

After adding the server configuration, restart your MCP client and confirm that
the darnit tools are available.

Recommended first tool call:

```python
audit_openssf_baseline(
    local_path="/absolute/path/to/your/repo",
    level=1,
)
```

If the audit reports missing project context, continue with:

```python
get_pending_context(local_path="/absolute/path/to/your/repo")
```

Important path note: avoid `local_path="."` during MCP testing unless the
server is intentionally running from the target repository. In MCP contexts,
`.` resolves relative to the MCP server process, not your shell's current
directory.

### Debugging Tips

- Use `uv run darnit -v serve --framework openssf-baseline` to see verbose logs.
- Run `uv run darnit list` if the framework name is not being discovered.
- Use `uv run darnit validate path/to/framework.toml` when testing a custom
  TOML framework.
- In Claude Code, restart the client after changing MCP settings and verify the
  server with `/mcp`.
- In Cursor, check the MCP logs from the Output panel if the server fails to
  connect or a tool call does not appear.

## Development Guidelines

### Code Style

- Follow existing code patterns and conventions
- Write clear, self-documenting code
- Add comments only where necessary to explain complex logic

### Testing

- Write tests for new functionality
- Ensure all tests pass before submitting a PR
- Maintain or improve test coverage

See the [Testing Guide](docs/getting-started/testing.md) for details.

### Documentation

- Update relevant documentation for any changes
- Document public APIs and interfaces
- Include examples where helpful

## Questions?

If you have questions, feel free to:
- Check the [Troubleshooting Guide](docs/getting-started/troubleshooting.md)
- Open a GitHub Issue
- Start a Discussion

Thank you for contributing!
