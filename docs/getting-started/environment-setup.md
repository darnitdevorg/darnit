# Environment Setup

This guide walks you through setting up a development environment for the darnit project, from a fresh clone to running tests.

## Prerequisites

You'll need the following tools installed:

| Tool | Minimum Version | Purpose |
|------|----------------|---------|
| Python | 3.11+ | Runtime (project targets 3.11/3.12) |
| [uv](https://docs.astral.sh/uv/) | Latest | Dependency management and task runner |
| [Git](https://git-scm.com/) | 2.x | Version control |
| [GitHub CLI](https://cli.github.com/) (`gh`) | Latest | GitHub API access for integration tests |

**Platform**: macOS and Linux are the primary development platforms. Windows users should use [WSL](https://learn.microsoft.com/en-us/windows/wsl/) (Windows Subsystem for Linux).

### Installing Prerequisites

**Python 3.11+**:
```bash
# macOS (Homebrew)
brew install python@3.12

# Ubuntu/Debian
sudo apt install python3.12 python3.12-venv

# Verify
python3 --version
```

**uv**:
```bash
# Install uv
curl -LsSf https://astral.sh/uv/install.sh | sh

# Verify
uv --version
```

**GitHub CLI**:
```bash
# macOS
brew install gh

# Ubuntu/Debian
# See https://github.com/cli/cli/blob/trunk/docs/install_linux.md

# Verify
gh --version
```

## Fork and Clone

This project uses a fork-based workflow. All contributions come through pull requests from your fork.

### 1. Fork the repository

Go to [github.com/kusari-oss/darnit](https://github.com/kusari-oss/darnit) and click **Fork**.

### 2. Clone your fork

```bash
git clone https://github.com/YOUR-USERNAME/darnit.git
cd darnit
```

### 3. Add the upstream remote

```bash
git remote add upstream https://github.com/kusari-oss/darnit.git
```

### 4. Verify remotes

```bash
git remote -v
```

Expected output:
```
origin    https://github.com/YOUR-USERNAME/darnit.git (fetch)
origin    https://github.com/YOUR-USERNAME/darnit.git (push)
upstream  https://github.com/kusari-oss/darnit.git (fetch)
upstream  https://github.com/kusari-oss/darnit.git (push)
```

## Install Dependencies

```bash
uv sync
```

This installs all packages in the workspace (darnit, darnit-baseline, darnit-testchecks) in development mode with all dependencies.

## Authenticate GitHub CLI

Many integration tests and audit commands use the GitHub API. Authenticate the CLI:

```bash
gh auth login
```

Follow the prompts to authenticate. You can verify with:

```bash
gh auth status
```

## Verify Your Setup

Run these commands to confirm everything works:

### Run all tests

```bash
uv run pytest tests/ --ignore=tests/integration/ -q
```

Expected: all tests pass.

### Run the linter

```bash
uv run ruff check .
```

Expected: no errors.

### Validate spec sync

```bash
uv run python scripts/validate_sync.py --verbose
```

Expected: all checks pass.

If any of these fail, see the [Troubleshooting Guide](troubleshooting.md).

## Staying Up to Date

Before starting new work, always sync with upstream:

```bash
git fetch upstream
git rebase upstream/main
```

This keeps your fork's history clean and avoids merge conflicts.

## Next Steps

- **Working on the framework?** Continue to [Framework Development](framework-development.md)
- **Working on an implementation?** Continue to [Implementation Development](implementation-development.md)
- **Need to understand the architecture first?** Read [Framework Development](framework-development.md) for architecture diagrams
- **Having issues?** Check the [Troubleshooting Guide](troubleshooting.md)
