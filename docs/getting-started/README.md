# Getting Started with Darnit Development

Welcome to the darnit contributor documentation. Choose your path below based on what you want to work on.

## Choose Your Path

### I want to work on the framework

The core darnit framework — plugin system, sieve pipeline, configuration, MCP server.

1. [Environment Setup](environment-setup.md) — Prerequisites, fork, clone, install
2. [Framework Development](framework-development.md) — Architecture, separation rules, sieve pipeline (with diagrams)
3. [Testing Guide](testing.md) — Running and writing tests
4. [Development Workflow](development-workflow.md) — Pre-commit checklist, branching, PRs

### I want to create or modify an implementation

Compliance framework plugins — TOML controls, CEL expressions, remediation, custom handlers.

1. [Environment Setup](environment-setup.md) — Prerequisites, fork, clone, install
2. [Implementation Development](implementation-development.md) — TOML controls, pass types, handlers, entry points
3. [CEL Reference](cel-reference.md) — CEL expression syntax and common pitfalls
4. [Testing Guide](testing.md) — Running and writing tests
5. [Development Workflow](development-workflow.md) — Pre-commit checklist, branching, PRs

**Tutorials** (complete copy-paste walkthroughs):
- [Add a New Control](../tutorials/add-new-control.md) — Add a control to the OpenSSF Baseline
- [Create a New Implementation](../tutorials/create-new-implementation.md) — Build a plugin from scratch

## Quick Reference

| Guide | What it covers |
|-------|---------------|
| [Environment Setup](environment-setup.md) | Prerequisites, fork/clone, install, verify |
| [Framework Development](framework-development.md) | Package structure, separation rules, sieve pipeline, Mermaid diagrams |
| [Implementation Development](implementation-development.md) | TOML controls, pass types, handlers, entry points, MCP tools |
| [CEL Reference](cel-reference.md) | CEL syntax, context variables, escaping rules, pitfalls |
| [Testing Guide](testing.md) | Running tests, test structure, writing new tests |
| [Development Workflow](development-workflow.md) | Pre-commit checklist, branching, commits, PRs |
| [Troubleshooting](troubleshooting.md) | Common issues and solutions |

## Having Issues?

Check the [Troubleshooting Guide](troubleshooting.md) first. If that doesn't help, [open an issue](https://github.com/kusari-oss/darnit/issues).
