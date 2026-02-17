# darnit-baseline

OpenSSF Baseline (OSPS v2025.10.10) compliance implementation for the darnit framework.

## Overview

**darnit-baseline** is a plugin for the [darnit](../darnit) compliance framework that implements the [OpenSSF Baseline](https://baseline.openssf.org/) security controls.

This package provides:
- **61 Controls** across 3 maturity levels
- **8 Control Categories**: Access Control, Build & Release, Documentation, Governance, Legal, Quality, Security Architecture, Vulnerability Management
- **Automated Remediation** actions for common compliance gaps
- **SARIF Output** for integration with security tools

## Installation

```bash
pip install darnit-baseline
```

This will automatically install `darnit` as a dependency.

## External Tool Dependencies

Some controls use external tools for deeper analysis. These are **optional** — controls gracefully fall back to built-in pattern matching when a tool is unavailable.

| Tool | Controls | Purpose | Install |
|------|----------|---------|---------|
| [zizmor](https://docs.zizmor.sh/) | OSPS-BR-01.01 | GitHub Actions static analysis (template injection detection) | `cargo install zizmor` or `brew install zizmor` |
| [gh](https://cli.github.com/) | BR-02.*, LE-02.*, LE-03.02, QA-01.02 | GitHub API queries (releases, commits) | `brew install gh` |
| [jq](https://jqlang.github.io/jq/) | — | JSON processing (used internally by some exec passes) | `brew install jq` |

## Usage

The implementation registers automatically via Python entry points:

```python
from darnit.core.discovery import discover_implementations

implementations = discover_implementations()
baseline = implementations.get("openssf-baseline")

# Get all controls
controls = baseline.get_all_controls()

# Get controls by level
level1_controls = baseline.get_controls_by_level(1)
```

## Control Categories

| Prefix | Category | Description |
|--------|----------|-------------|
| OSPS-AC | Access Control | Authentication, authorization, branch protection |
| OSPS-BR | Build & Release | CI/CD security, artifact signing |
| OSPS-DO | Documentation | README, SECURITY.md, changelog |
| OSPS-GV | Governance | Maintainer documentation, response times |
| OSPS-LI | Legal | Licensing, contributor agreements |
| OSPS-QA | Quality | Testing, code review, static analysis |
| OSPS-SA | Security Architecture | Threat modeling, security design |
| OSPS-VM | Vulnerability Management | CVE handling, SCA, dependency scanning |

## Maturity Levels

| Level | Description | Controls |
|-------|-------------|----------|
| **Level 1** | Basic security hygiene | 24 controls |
| **Level 2** | Intermediate security practices | 19 controls |
| **Level 3** | Advanced security measures | 18 controls |

## Available Remediations

The following remediation categories are available:

- `security_policy` - Create SECURITY.md
- `contributing` - Create CONTRIBUTING.md
- `governance` - Create GOVERNANCE.md
- `codeowners` - Create CODEOWNERS file
- `branch_protection` - Enable branch protection rules
- `status_checks` - Configure required status checks
- `dco_enforcement` - Configure DCO enforcement
- `bug_report_template` - Create issue templates
- `dependabot` - Configure Dependabot
- `support_doc` - Create SUPPORT.md

## Package Structure

```
darnit_baseline/
├── controls/      # Control definitions (levels 1-3)
├── checks/        # Check implementations (legacy)
├── rules/         # OSPS rules catalog
├── remediation/   # Baseline-specific remediations
├── formatters/    # SARIF output formatting
└── config/        # Control-to-reference mappings
```

## License

Apache-2.0
