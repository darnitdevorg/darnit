# Governance Documents Design

Design specification for governance documents needed before public release.

## Overview

Four documents are needed to establish proper open source governance:

| Document | Purpose | Priority |
|----------|---------|----------|
| `SECURITY.md` | Vulnerability reporting process | HIGH |
| `CONTRIBUTING.md` | Contributor guidelines | HIGH |
| `CHANGELOG.md` | Version history | MEDIUM |
| `GOVERNANCE.md` | Project governance | MEDIUM |

---

## 1. SECURITY.md

### Purpose
Define how security vulnerabilities should be reported and handled. Especially important for a compliance/security tool.

### Structure

```markdown
# Security Policy

## Supported Versions
- Table of versions receiving security updates

## Reporting a Vulnerability
- Contact method (GitHub Security Advisories preferred)
- What to include in report
- Response timeline expectations

## Security Measures
- How project maintains security (Dependabot, pinned deps, etc.)

## Disclosure Policy
- Coordinated disclosure timeline
- Credit for reporters
```

### Key Content

**Supported Versions:**
| Version | Supported |
|---------|-----------|
| 0.1.x   | Yes       |

**Reporting Method:** GitHub Security Advisories (private)
- Do NOT open public issues for vulnerabilities
- Email fallback: [maintainer email or security@domain]

**Response Timeline:**
- Acknowledgment: 48 hours
- Initial assessment: 7 days
- Fix timeline: Based on severity (Critical: 7d, High: 30d, Medium: 90d)

**Security Practices:**
- Dependabot for dependency updates
- GitHub Actions pinned to SHA hashes
- Sigstore for attestation signing
- No secrets in repository

---

## 2. CONTRIBUTING.md

### Purpose
Guide contributors on how to effectively contribute to the project.

### Structure

```markdown
# Contributing to Darnit

## Quick Start
- Fork, clone, setup instructions

## Development Setup
- Prerequisites (Python 3.11+, uv, gh CLI)
- Installation steps
- Running tests

## Code Organization
- Package structure explanation
- Where to add new features

## Making Changes
- Branch naming
- Commit message format
- PR process

## Adding New Controls
- How to implement OSPS controls
- Sieve verification phases
- Testing requirements

## Documentation
- When to update ARCHITECTURE.md
- Docstring requirements

## Code Style
- Type hints required
- Testing requirements
- Lint/format requirements
```

### Key Content

**Prerequisites:**
- Python 3.11+ (3.12 recommended)
- `uv` package manager
- `gh` CLI (for GitHub API features)
- Git

**Development Commands:**
```bash
# Setup
uv sync --all-extras

# Run tests
uv run pytest tests/ -v

# Type check
uv run mypy packages/darnit/src --ignore-missing-imports

# Run locally
uv run python main.py
```

**Package Structure:**
- `packages/darnit/` - Core framework (models, plugin system, sieve)
- `packages/darnit-baseline/` - OpenSSF Baseline implementation
- `main.py` - MCP server entry point

**Commit Message Format:**
```
type: short description

Longer description if needed

Co-Authored-By: Name <email>
```

Types: `feat`, `fix`, `docs`, `ci`, `refactor`, `test`, `deps`

**Adding New Controls:**
1. Add control spec to `controls.py`
2. Implement check function in appropriate level file
3. Add sieve adapter if needed
4. Register in rules catalog
5. Add remediation if applicable
6. Write tests
7. Update ARCHITECTURE.md

---

## 3. CHANGELOG.md

### Purpose
Track version history and notable changes.

### Structure

```markdown
# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.0] - 2024-12-XX

### Added
- Initial release features

### Security
- Security-related changes
```

### Initial Content (v0.1.0)

**Added:**
- Core darnit framework with plugin architecture
- OpenSSF Baseline (OSPS v2025.10.10) implementation
  - 62 controls across 3 maturity levels
  - 8 control domains (AC, BR, DO, GV, LE, QA, SA, VM)
- Progressive verification system (Sieve)
  - 4-phase verification: Deterministic → Pattern → LLM → Manual
- MCP server integration for AI assistants
- In-toto attestation generation with Sigstore signing
- STRIDE threat modeling (alpha)
- Automated remediation for 10 control categories
- Project configuration via `.project.yaml`
- SARIF output format support

**Security:**
- GitHub Actions pinned to SHA hashes
- Dependabot configuration for automated updates
- Least-privilege workflow permissions

---

## 4. GOVERNANCE.md

### Purpose
Define project governance, decision-making, and roles.

### Structure

```markdown
# Governance

## Project Structure
- Multi-package workspace explanation

## Roles
- Maintainer responsibilities
- Contributor expectations

## Decision Making
- How decisions are made
- RFC process for major changes

## Releases
- Release process
- Version numbering

## Code of Conduct
- Reference to CoC (or include inline)
```

### Key Content

**Project Structure:**
- Monorepo with `uv` workspace
- `darnit` - Core framework (maintained by core team)
- `darnit-baseline` - OpenSSF Baseline (maintained by core team)
- Future plugins can be external packages

**Roles:**

| Role | Responsibilities |
|------|------------------|
| Maintainer | Review PRs, merge, release, security |
| Contributor | Submit PRs, report issues, documentation |
| Baseline Implementer | Add/modify OSPS controls |

**Decision Process:**
- Minor changes: PR review and approval
- Major changes: Discussion in issue first
- Breaking changes: RFC process with community input

**Release Process:**
1. Update version in `pyproject.toml` files
2. Update CHANGELOG.md
3. Create GitHub release
4. Automated PyPI publish (when enabled)

---

## Implementation Order

1. **SECURITY.md** (highest priority - needed for responsible disclosure)
2. **CONTRIBUTING.md** (enables community contributions)
3. **CHANGELOG.md** (documents current state)
4. **GOVERNANCE.md** (establishes long-term structure)

## File Locations

All files go in repository root:
- `/SECURITY.md`
- `/CONTRIBUTING.md`
- `/CHANGELOG.md`
- `/GOVERNANCE.md`

## Estimated Effort

| Document | Lines | Time |
|----------|-------|------|
| SECURITY.md | ~80 | 15 min |
| CONTRIBUTING.md | ~200 | 30 min |
| CHANGELOG.md | ~60 | 15 min |
| GOVERNANCE.md | ~100 | 20 min |
| **Total** | ~440 | ~80 min |
