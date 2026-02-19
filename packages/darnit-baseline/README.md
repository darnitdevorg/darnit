# darnit-baseline

OpenSSF Baseline (OSPS v2025.10.10) compliance implementation for the [darnit](../darnit) framework — **62 controls** across **8 domains** and **3 maturity levels** (25 L1, 17 L2, 20 L3).

## How Controls Are Verified

Each control runs through a **sieve pipeline** — a sequence of passes that stops at the first conclusive result:

```
file_exists  →  exec / pattern  →  manual
     ↓              ↓                 ↓
File presence   Commands (gh api)   Human review
checks          & regex patterns    (fallback)
```

**Pass types:**

- **file_exists** — checks for specific files (README.md, SECURITY.md, LICENSE, etc.)
- **exec** — runs a command (typically `gh api`) and evaluates output with a CEL expression
- **pattern** — searches file contents with regex, optionally evaluates with CEL
- **manual** — fallback steps for human verification

**Conservative by default:** A control that hasn't been explicitly verified as passing reports WARN (needs verification). The system never assumes compliance.

## Control Reference

Controls gated by `platform = "github"` require the GitHub CLI (`gh`). Additional conditions are noted inline.

### OSPS-AC — Access Control (6 controls)

| Control | Lvl | What It Checks | How | Auto-Remediation |
|---------|-----|----------------|-----|------------------|
| AC-01.01 | 1 | MFA required for org members | `exec` gh api | API: enable org MFA |
| AC-02.01 | 1 | Repository allows forking | `exec` gh api | API: enable forking |
| AC-03.01 | 1 | PRs required for primary branch | `exec` gh api | API: branch protection |
| AC-03.02 | 1 | Primary branch deletion blocked | `exec` gh api | API: branch protection |
| AC-04.01 | 2 | Workflows declare `permissions:` *(GitHub Actions)* | `pattern` workflows | Manual |
| AC-04.02 | 3 | Permissions scoped to least privilege *(GitHub Actions)* | `pattern` workflows | Manual |

### OSPS-BR — Build & Release (11 controls)

| Control | Lvl | What It Checks | How | Auto-Remediation |
|---------|-----|----------------|-----|------------------|
| BR-01.01 | 1 | Workflows handle untrusted inputs safely *(GitHub Actions)* | `exec` zizmor / `pattern` | `exec` zizmor --fix |
| BR-01.02 | 1 | Branch names handled safely in workflows *(GitHub Actions)* | `pattern` workflows | Manual |
| BR-02.01 | 2 | Unique version IDs per release *(if has_releases)* | `exec` gh release list | Manual |
| BR-02.02 | 3 | Assets clearly linked to release IDs | `exec` gh release list | Manual |
| BR-03.01 | 1 | Repository URL uses HTTPS | `exec` gh api | — |
| BR-03.02 | 1 | Distribution channels use HTTPS | `pattern` README, INSTALL.md | — |
| BR-04.01 | 2 | Releases include change log *(if has_releases)* | `exec` gh api / `file` CHANGELOG | Manual |
| BR-05.01 | 2 | Uses standard dependency tooling | `file` package.json, pyproject.toml, etc. | Manual |
| BR-06.01 | 2 | Releases are cryptographically signed *(if has_releases)* | `pattern` workflows, docs | Creates release-signing.yml |
| BR-07.01 | 1 | Secret files are gitignored | `file` + `pattern` .gitignore | Creates .gitignore |
| BR-07.02 | 3 | Secrets management policy documented | `pattern` SECURITY.md, docs | Manual |

### OSPS-DO — Documentation (7 controls)

| Control | Lvl | What It Checks | How | Auto-Remediation |
|---------|-----|----------------|-----|------------------|
| DO-01.01 | 1 | Repository has a README | `file` README.md | Creates README.md |
| DO-02.01 | 1 | Bug reporting process documented | `file` issue template / `pattern` | Creates bug_report.md template |
| DO-03.01 | 3 | Support documentation available | `file` SUPPORT.md | Creates SUPPORT.md |
| DO-03.02 | 3 | Release author verification instructions | `pattern` docs | Creates RELEASE-VERIFICATION.md |
| DO-04.01 | 3 | Support scope and duration documented | `pattern` SUPPORT.md, docs | Creates SUPPORT.md |
| DO-05.01 | 3 | End-of-support policy documented | `pattern` SUPPORT.md, docs | Creates SUPPORT.md |
| DO-06.01 | 2 | Dependency management documented | `pattern` README, docs | Creates docs/DEPENDENCIES.md |

### OSPS-GV — Governance (6 controls)

| Control | Lvl | What It Checks | How | Auto-Remediation |
|---------|-----|----------------|-----|------------------|
| GV-01.01 | 2 | Governance documentation exists | `file` GOVERNANCE.md, MAINTAINERS.md, etc. | Creates GOVERNANCE.md *(needs: maintainers)* |
| GV-01.02 | 2 | Roles and responsibilities documented | `pattern` governance docs | Creates MAINTAINERS.md *(needs: maintainers)* |
| GV-02.01 | 1 | Issues or Discussions enabled | `exec` gh api | — |
| GV-03.01 | 1 | Contributing guidelines exist | `file` CONTRIBUTING.md | Creates CONTRIBUTING.md |
| GV-03.02 | 2 | Contribution requirements documented | `pattern` CONTRIBUTING.md | Creates CONTRIBUTING.md |
| GV-04.01 | 3 | Collaborator review policy documented | `file` CODEOWNERS / `pattern` | Creates CODEOWNERS *(needs: maintainers)* |

### OSPS-LE — Legal (5 controls)

| Control | Lvl | What It Checks | How | Auto-Remediation |
|---------|-----|----------------|-----|------------------|
| LE-01.01 | 1 | Repository has a license file | `file` LICENSE | Creates LICENSE (MIT) |
| LE-02.01 | 1 | License is OSI-approved | `exec` gh api | — |
| LE-02.02 | 1 | Releases include license info | `exec` gh release view | — |
| LE-03.01 | 1 | License file present in repository root | `file` LICENSE | — |
| LE-03.02 | 1 | License included in release archives *(if has_releases)* | `exec` gh release view | — |

### OSPS-QA — Quality Assurance (13 controls)

| Control | Lvl | What It Checks | How | Auto-Remediation |
|---------|-----|----------------|-----|------------------|
| QA-01.01 | 1 | Repository is publicly accessible | `exec` gh api | API: make repo public |
| QA-01.02 | 1 | Commit history is publicly visible | `exec` gh api | Manual |
| QA-02.01 | 1 | Dependency manifest exists | `file` package.json, pyproject.toml, etc. | Manual |
| QA-02.02 | 3 | SBOM delivered with compiled assets *(if has_compiled_assets)* | `pattern` workflows | Creates sbom.yml |
| QA-03.01 | 2 | Status checks required before merge | `exec` gh api | Manual |
| QA-04.01 | 1 | Subprojects are documented *(if has_subprojects)* | `pattern` README, docs | Manual |
| QA-04.02 | 3 | Subprojects enforce equal security *(if has_subprojects)* | `pattern` security files | Manual |
| QA-05.01 | 1 | No generated executables in repo | `pattern` absence check | Manual |
| QA-05.02 | 1 | No unreviewable binary artifacts | `pattern` absence check | Manual |
| QA-06.01 | 2 | CI includes automated tests | `pattern` workflows | Creates ci.yml |
| QA-06.02 | 3 | Testing instructions documented | `pattern` README, docs | Manual |
| QA-06.03 | 3 | Test requirements for contributions | `pattern` CONTRIBUTING.md | Manual |
| QA-07.01 | 3 | PRs require approval before merge | `exec` gh api | API: require PR reviews |

### OSPS-SA — Security Assessment (4 controls)

| Control | Lvl | What It Checks | How | Auto-Remediation |
|---------|-----|----------------|-----|------------------|
| SA-01.01 | 2 | Design docs show actions and actors | `pattern` architecture docs | Creates ARCHITECTURE.md |
| SA-02.01 | 2 | API/interface documentation available | `pattern` API docs, README | — |
| SA-03.01 | 2 | Security assessment before releases *(if has_releases)* | `manual` / `pattern` | Creates SECURITY-ASSESSMENT.md |
| SA-03.02 | 3 | Threat model documentation available | `file` THREAT_MODEL.md / `pattern` | Creates THREAT_MODEL.md |

### OSPS-VM — Vulnerability Management (10 controls)

| Control | Lvl | What It Checks | How | Auto-Remediation |
|---------|-----|----------------|-----|------------------|
| VM-01.01 | 2 | Security policy includes disclosure process | `pattern` SECURITY.md | Manual |
| VM-02.01 | 1 | Repository has a security policy | `file` SECURITY.md | Creates SECURITY.md |
| VM-03.01 | 2 | Private vulnerability reporting enabled | `exec` gh api / `pattern` | API: enable private reporting |
| VM-04.01 | 2 | Repository supports security advisories | `exec` gh api | Manual |
| VM-04.02 | 3 | VEX policy documented | `pattern` SECURITY.md, docs | Creates docs/VEX-POLICY.md |
| VM-05.01 | 3 | SCA remediation policy documented | `pattern` docs | Creates docs/SCA-POLICY.md |
| VM-05.02 | 3 | Pre-release SCA workflow configured | `pattern` workflows | Creates sca.yml |
| VM-05.03 | 3 | Automated dependency scanning configured | `file` dependabot.yml, renovate.json | Creates dependabot.yml |
| VM-06.01 | 3 | SAST remediation policy documented | `pattern` docs | Creates docs/SAST-POLICY.md |
| VM-06.02 | 3 | Automated SAST in CI pipeline | `pattern` workflows | Creates sast.yml |

## Project Context

Context values serve two purposes: **(1)** they gate which controls apply to your project via `when` clauses, and **(2)** they populate templates during remediation. Controls gated by context that hasn't been set show as N/A.

Set context via the `confirm_project_context` MCP tool or by editing `.project/project.yaml`.

| Key | Type | Auto-Detect | Controls | Usage |
|-----|------|-------------|----------|-------|
| `maintainers` | list or path | Yes | GV-01.01, GV-01.02, GV-04.01 | Template variable in GOVERNANCE.md, MAINTAINERS.md, CODEOWNERS. Remediation blocks until provided. |
| `security_contact` | string | No | VM-01.01, VM-02.01, VM-03.01 | Populates SECURITY.md template |
| `governance_model` | enum | No | GV-01.01, GV-01.02 | Selects governance template variant |
| `has_subprojects` | boolean | No | QA-04.01, QA-04.02 | When-clause: controls only run if `true` |
| `has_releases` | boolean | Yes | BR-02.01, BR-04.01, BR-06.01, LE-03.02, SA-03.01 | When-clause: controls only run if `true` |
| `is_library` | boolean | No | DO-04.01, BR-01.01 | Audit hints for accuracy |
| `has_compiled_assets` | boolean | No | QA-02.02 | When-clause: control only runs if `true` |
| `ci_provider` | enum | Yes | BR-01.01, BR-01.02, AC-04.01, AC-04.02 | When-clause: controls only run if `"github"` |

## Automated Remediation Summary

The implementation provides **35 automated remediation actions** across three categories:

**27 file_create actions** — generates project files from templates:
- Root files: README.md, SECURITY.md, CONTRIBUTING.md, GOVERNANCE.md, MAINTAINERS.md, CODEOWNERS, LICENSE, .gitignore, SUPPORT.md, ARCHITECTURE.md, THREAT_MODEL.md
- CI workflows: ci.yml, sca.yml, sast.yml, sbom.yml, release-signing.yml
- GitHub config: .github/dependabot.yml, .github/ISSUE_TEMPLATE/bug_report.md
- Policy docs: docs/DEPENDENCIES.md, docs/VEX-POLICY.md, docs/SCA-POLICY.md, docs/SAST-POLICY.md, docs/SECURITY-ASSESSMENT.md, docs/RELEASE-VERIFICATION.md

**7 api_call actions** — GitHub API settings changes:
- Enable org MFA (AC-01.01)
- Enable forking (AC-02.01)
- Enable branch protection with PR requirements (AC-03.01)
- Disable branch deletion (AC-03.02)
- Make repository public (QA-01.01)
- Require PR reviews (QA-07.01)
- Enable private vulnerability reporting (VM-03.01)

**1 exec action** — `zizmor --fix` for GitHub Actions template injection remediation (BR-01.01)

All remaining controls provide manual guidance steps as fallback.

## External Tool Dependencies

Some controls use external tools for deeper analysis. These are **optional** — controls gracefully fall back to built-in pattern matching when a tool is unavailable.

| Tool | Controls | Purpose | Install |
|------|----------|---------|---------|
| [zizmor](https://docs.zizmor.sh/) | BR-01.01 | GitHub Actions static analysis (template injection) | `cargo install zizmor` or `brew install zizmor` |
| [gh](https://cli.github.com/) | AC-*, BR-02/03/04, LE-02/03, QA-01/03/07, GV-02, VM-03/04 | GitHub API queries | `brew install gh` |
| [jq](https://jqlang.github.io/jq/) | — | JSON processing (used internally by some exec passes) | `brew install jq` |

## Package Structure

```
darnit_baseline/
├── attestation/     # In-toto attestation support
├── config/          # Project context configuration
├── formatters/      # Output formatting (Markdown, JSON, SARIF)
├── remediation/     # Remediation orchestration
├── rules/           # SARIF rule definitions (from TOML)
└── threat_model/    # Threat model generation
```

## Installation

```bash
pip install darnit-baseline
```

This automatically installs `darnit` as a dependency.

## License

Apache-2.0
