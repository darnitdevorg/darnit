# Getting Started with Darnit

Welcome to darnit! This guide helps you start contributing to the project.

**Darnit** is a pluggable compliance audit framework. It provides infrastructure for running compliance audits, generating attestations, and automating remediation. The project uses a plugin architecture that separates the core framework from compliance implementations.

## Prerequisites

- Python 3.11+
- [uv](https://docs.astral.sh/uv/) (dependency management)
- [Git](https://git-scm.com/)
- [GitHub CLI](https://cli.github.com/) (`gh`)

## Quick Setup

```bash
# 1. Fork the repo on GitHub, then clone your fork
git clone https://github.com/YOUR-USERNAME/darnit.git
cd darnit

# 2. Add upstream remote
git remote add upstream https://github.com/kusari-oss/darnit.git

# 3. Install all dependencies
uv sync

# 4. Authenticate GitHub CLI
gh auth login

# 5. Verify everything works
uv run pytest tests/ --ignore=tests/integration/ -q
```

Full setup details: [Environment Setup](docs/getting-started/environment-setup.md)

## Choose Your Path

### I want to work on the framework

The core plugin system, sieve pipeline, configuration, and MCP server.

- [Framework Development](docs/getting-started/framework-development.md) — Architecture, separation rules, diagrams
- [Testing Guide](docs/getting-started/testing.md) — Running and writing tests
- [Development Workflow](docs/getting-started/development-workflow.md) — Pre-commit checklist, PRs

### I want to create or modify an implementation

Compliance framework plugins — TOML controls, CEL expressions, remediation.

- [Implementation Development](docs/getting-started/implementation-development.md) — TOML controls, pass types, handlers
- [CEL Reference](docs/getting-started/cel-reference.md) — CEL syntax and pitfalls
- [Tutorial: Add a New Control](docs/tutorials/add-new-control.md) — Step-by-step walkthrough
- [Tutorial: Create a New Implementation](docs/tutorials/create-new-implementation.md) — Build a plugin from scratch

## All Guides

See the [full getting started index](docs/getting-started/README.md) for a complete list of guides.

## Troubleshooting

Having issues? Check the [Troubleshooting Guide](docs/getting-started/troubleshooting.md).

## Contributing Policy

See [CONTRIBUTING.md](CONTRIBUTING.md) for our Code of Conduct and contribution policy.
