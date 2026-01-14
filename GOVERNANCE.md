# Governance

This document describes the governance model for the darnit project.

## Project Structure

Darnit is organized as a monorepo using `uv` workspace:

| Package | Purpose | Maintainer |
|---------|---------|------------|
| `darnit` | Core framework (models, plugin system, sieve) | Core team |
| `darnit-baseline` | OpenSSF Baseline implementation | Core team |

Future plugins can be developed as external packages following the plugin architecture.

## Roles and Responsibilities

### Maintainers

Maintainers have write access to the repository and are responsible for:

- Reviewing and merging pull requests
- Managing releases and versioning
- Responding to security vulnerabilities
- Setting project direction and priorities
- Enforcing the Code of Conduct

### Contributors

Contributors are community members who:

- Submit pull requests with bug fixes or features
- Report issues and bugs
- Improve documentation
- Participate in discussions

### Baseline Implementers

A specialized contributor role for those who:

- Add or modify OSPS controls
- Implement sieve verification adapters
- Write remediation functions

## Decision Making

### Minor Changes
- Standard PR review and approval process
- One maintainer approval required

### Major Changes
- Open a GitHub Issue for discussion first
- Allow community input before implementation
- Document rationale in the PR

### Breaking Changes
- Require RFC (Request for Comments) process
- Minimum 7-day comment period
- Requires consensus from maintainers

## Release Process

1. Update version in `pyproject.toml` files
2. Update CHANGELOG.md with release notes
3. Create GitHub Release with tag
4. Automated PyPI publish via CI (when enabled)

Releases follow [Semantic Versioning](https://semver.org/):
- MAJOR: Breaking changes
- MINOR: New features (backwards compatible)
- PATCH: Bug fixes (backwards compatible)

## Code of Conduct

All participants are expected to uphold a welcoming, harassment-free environment. Be respectful, constructive, and inclusive in all interactions.

## Contact

- **Issues**: [GitHub Issues](https://github.com/kusari-oss/darnit/issues)
- **Discussions**: [GitHub Discussions](https://github.com/kusari-oss/darnit/discussions)
- **Security**: See [SECURITY.md](SECURITY.md) for vulnerability reporting
