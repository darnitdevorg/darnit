# Governance

The darnit Project is governed by a Technical Steering Committee (TSC). The binding rules for membership, voting, and amendments live in the Project's [Charter](./CHARTER.md); the current voting members of the TSC are listed in [TECHNICAL-STEERING-COMMITTEE.md](./TECHNICAL-STEERING-COMMITTEE.md).

This document describes the operational layer below the Charter: how the Project is organized, what roles contributors fill, and how routine activities (PR review, releases) are run on a day-to-day basis. The Charter is the authority on governance decisions; this document is operational guidance and may be revised by maintainer consensus without a TSC vote.

## Project Structure

Darnit is organized as a monorepo using `uv` workspace:

| Package | Purpose | Maintainer |
|---------|---------|------------|
| `darnit` | Core framework (models, plugin system, sieve) | Core team |
| `darnit-baseline` | OpenSSF Baseline implementation | Core team |

Future plugins can be developed as external packages following the plugin architecture.

## Roles and Responsibilities

The TSC sets policy. The roles below operate under that policy and are responsible for day-to-day execution. TSC members are typically also maintainers, but the two roles are distinct: TSC authority comes from the [Charter](./CHARTER.md); maintainer authority comes from commit access granted by the TSC.

### Maintainers

Maintainers have write access to the repository and are responsible for:

- Reviewing and merging pull requests
- Managing releases and versioning
- Responding to security vulnerabilities
- Day-to-day technical direction within policy set by the TSC
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

## Day-to-Day PR Process

The following thresholds apply to routine PR activity. Changes to *governance itself* -- this document, the [Charter](./CHARTER.md), or the [TSC roster](./TECHNICAL-STEERING-COMMITTEE.md) -- follow the TSC voting rules in the Charter instead.

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
- Approval by maintainer consensus

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

All participants are expected to uphold a welcoming, harassment-free environment. Be respectful, constructive, and inclusive in all interactions. The Project intends to adopt a project-specific Code of Conduct; until then, the LF Projects Code of Conduct applies per the [Charter](./CHARTER.md), Section 4.1.

## Contact

- **Issues**: [GitHub Issues](https://github.com/kusari-oss/darnit/issues)
- **Discussions**: [GitHub Discussions](https://github.com/kusari-oss/darnit/discussions)
- **Security**: See [SECURITY.md](SECURITY.md) for vulnerability reporting
