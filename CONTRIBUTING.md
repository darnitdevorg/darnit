# Contributing to darnit

Thank you for your interest in contributing! This document provides guidelines and instructions for contributing.

## Code of Conduct

Please read and follow our Code of Conduct to maintain a welcoming environment for all contributors.

## Getting Started

### Prerequisites

- Git
- A GitHub account

### Setup

1. Fork the repository on GitHub
2. Clone your fork locally:
   ```bash
   git clone https://github.com/YOUR-USERNAME/darnit.git
   cd darnit
   ```
3. Add the upstream remote:
   ```bash
   git remote add upstream https://github.com/kusari-oss/darnit.git
   ```

## Making Changes

### Branch Naming

Create a branch with a descriptive name:
- `feat/description` - New features
- `fix/description` - Bug fixes
- `docs/description` - Documentation updates
- `refactor/description` - Code refactoring

### Commit Messages

Write clear, concise commit messages:
```
type: short description

Longer description if needed explaining the what and why.
```

Types: `feat`, `fix`, `docs`, `test`, `refactor`, `ci`, `chore`

### Pull Request Process

1. Update your fork with the latest upstream changes:
   ```bash
   git fetch upstream
   git rebase upstream/main
   ```
2. Push your changes to your fork
3. Open a Pull Request against the `main` branch
4. Fill out the PR template with relevant details
5. Wait for review and address any feedback

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

### Documentation

- Update relevant documentation for any changes
- Document public APIs and interfaces
- Include examples where helpful

## Questions?

If you have questions, feel free to:
- Open a GitHub Issue
- Start a Discussion

Thank you for contributing!
