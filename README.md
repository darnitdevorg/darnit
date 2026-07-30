# Darnit

> *"Darnit patches holes in your software - like darning a sock, but for code."*

**Darnit** is a pluggable compliance audit framework that helps projects conform to software engineering best practices. It provides infrastructure for running compliance audits, generating cryptographic attestations, and automating remediation workflows.

While security is a key focus, Darnit covers the full spectrum of software quality:
- **Security posture** - vulnerability management, access controls, threat modeling
- **Testing practices** - code review requirements, CI/CD quality gates, test coverage
- **Build reproducibility** - artifact signing, dependency pinning, release processes
- **Project governance** - maintainer documentation, contribution guidelines, response times
- **Documentation standards** - READMEs, changelogs, support information

This repository includes an MCP (Model Context Protocol) server for AI assistant integration, plus the OpenSSF Baseline implementation as the first supported standard.

## Features

- **Plugin Architecture**: Implement any compliance standard as a darnit plugin
- **Composition**: Assemble your organization's posture as a TOML-only mix of slices from other installed implementations — no forking, no Python ([quickstart](specs/013-plugin-composition/quickstart.md))
- **MCP Server**: Integrates with AI assistants (Claude, etc.) for interactive auditing
- **Automated Remediation**: Generate fixes for compliance gaps with dry-run support
- **Project Configuration**: Canonical `.project.yaml` for project metadata and documentation locations
- **Attestation Generation**: Create cryptographically signed in-toto attestations
- **STRIDE Threat Modeling**: (Alpha) Built-in security threat analysis — works best on Python web services (Flask, FastAPI, Django, MCP servers); Go/JavaScript and CLI tools have limited coverage today. See [Coverage scope](#threat-model-coverage-scope) below. To be used for basic drafting only.
- **CEL Expressions**: Flexible pass logic using Common Expression Language
- **Plugin Verification**: Sigstore-based plugin signing and verification

## Included Implementation: OpenSSF Baseline

This repository includes `darnit-baseline`, an implementation of the [OpenSSF Baseline](https://baseline.openssf.org/) (OSPS v2025.10.10). The Baseline defines best practices for open source projects across security, quality, and governance:

- **62 Controls** across 3 maturity levels
- **8 Control Categories**: Access Control, Build & Release, Documentation, Governance, Legal, Quality, Security Architecture, Vulnerability Management
- **Automated Remediation** for common compliance gaps

The Baseline isn't just about security—it covers testing requirements, build processes, documentation standards, and project governance practices that make software more reliable and maintainable.

## Installation

> [!NOTE]
> PyPI, pipx, `uv tool install`, container, Homebrew, and standalone-binary
> channels are not published yet - tracked in
> [#229](https://github.com/kusari-oss/darnit/issues/229) (which depends on
> PyPI publishing, [#228](https://github.com/kusari-oss/darnit/issues/228)).
> Until those land, install from source with [`uv`](https://docs.astral.sh/uv/):

```bash
git clone https://github.com/kusari-oss/darnit
cd darnit
uv sync

uv run darnit audit /path/to/repo
uv run darnit serve --framework openssf-baseline   # MCP server mode
```

Once [#229](https://github.com/kusari-oss/darnit/issues/229) lands, `pipx install darnit-mcp`
and `uv tool install darnit-mcp` will become the recommended end-user paths, with
container, Homebrew, standalone-binary, and Claude Code plugin channels documented in
[`docs/install/README.md`](docs/install/README.md).
### Optional: Opengrep for taint analysis

The threat model generator can use [Opengrep](https://github.com/opengrep/opengrep)
(or Semgrep) to perform intra-procedural taint analysis, producing higher-confidence
findings with data-flow traces. Without it, the generator uses tree-sitter structural
analysis only — accurate but without taint confirmation.

Install via your platform's package manager (recommended — gets you a signed,
checksummed artifact rather than piping an unverified script into your shell):

```bash
# macOS / Linux with Homebrew
brew install opengrep

# Or pin a specific release directly from GitHub:
#   https://github.com/opengrep/opengrep/releases
# Download, verify the SHA-256 against the release notes, then place
# the binary on your PATH.

# Verify the install succeeded
opengrep --version
```

If you'd rather use Semgrep (also supported by darnit): `pipx install semgrep`.

### Threat-model coverage scope

The tree-sitter discovery pipeline is tuned for **web-service shapes**. What works well today:

| Project shape | Coverage |
|---|---|
| Python web service (Flask, FastAPI, Django, MCP server) | Best path — full STRIDE: routes, data stores, sinks, info-disclosure, elevation-of-privilege |
| JavaScript/Node service (Express-style) | Moderate — route registration + basic sink set |
| Go HTTP service (`net/http`, chi, gorilla) | Thin — HTTP route registration + `sql.Open` only |
| Go CLI built on [`spf13/cobra`](https://github.com/spf13/cobra) | Moderate — command families discovered, STRIDE assigned heuristically by import set; `needs reviewer attention` marker on every finding ([feature 014](specs/014-cobra-threat-model/spec.md)) |
| YAML / GitHub Actions workflows | Some — overly-broad permissions and similar config issues |
| Python CLI frameworks (argparse, click, typer) | Not modeled — sibling to the Go cobra work ([#264](https://github.com/kusari-oss/darnit/issues/264)) |
| Other Go CLI frameworks (urfave/cli, kingpin) / message handlers / gRPC | Not modeled — out of scope for the cobra pass ([#262](https://github.com/kusari-oss/darnit/issues/262)) |
| Crypto/signing **client** libraries (sigstore-python, in-toto) | Out of scope — these call out rather than receive; entry-point queries don't fire |
| ML pipelines (PyTorch, Transformers, ONNX, Safetensors) | Modeled — mapped to TAMPERING and ELEVATION_OF_PRIVILEGE |
| Systems software, daemons, libraries | Not modeled |

If your project doesn't match a supported shape, the generator will still write a report — but it will likely show "Total findings: 0" because no entry points were discovered. That's a coverage gap on our side, not a clean bill of health. Expanding the query set is [tracked in our issue tracker](https://github.com/kusari-oss/darnit/issues?q=is%3Aissue+threat-model+coverage).

## Quick Start

### Run an Audit

```python
# Audit a repository against OpenSSF Baseline
audit_openssf_baseline(
    local_path="/path/to/repo",
    level=3  # Check all maturity levels
)
```

### Generate Attestation

```python
# Create a signed compliance attestation
generate_attestation(
    local_path="/path/to/repo",
    sign=True
)
```

### Remediate Issues

```python
# Preview what would be fixed
remediate_audit_findings(
    local_path="/path/to/repo",
    categories=["security_policy", "contributing"],
    dry_run=True  # Preview changes
)

# Apply fixes
remediate_audit_findings(
    local_path="/path/to/repo",
    categories=["security_policy", "contributing"],
    dry_run=False
)
```

## Architecture

For a detailed architecture overview with diagrams, see the [Framework Development Guide](docs/getting-started/framework-development.md).

The project uses a plugin architecture with two main packages:

| Package | Description |
|---------|-------------|
| `darnit` | Core framework — plugin system, sieve pipeline, configuration, MCP server |
| `darnit-baseline` | OpenSSF Baseline implementation — 62 controls across 3 maturity levels |

## Project Configuration

The `.project.yaml` file is the canonical source of truth for your project's metadata and documentation locations.

**NOTE:** This is a stopgap solution untile CNCF's `.project/` specification is fleshed out a bit more. This `.project.yaml` is based on what has been made available for `.project/` along with additional information for Baseline conformance.

### Example `.project.yaml`

```yaml
schema_version: "0.1"

project:
  name: my-project
  type: software

# Security
security:
  policy:
    path: SECURITY.md
  threat_model:
    path: docs/THREAT_MODEL.md

# Governance
governance:
  maintainers:
    path: MAINTAINERS.md
  contributing:
    path: CONTRIBUTING.md

# Legal
legal:
  license:
    path: LICENSE
  contributor_agreement:
    type: dco

# CI/CD and Quality
ci:
  provider: github
  github:
    workflows:
      - .github/workflows/ci.yml
      - .github/workflows/release.yml

# Build & Release
build:
  reproducible: true
  signing:
    enabled: true
```

### Configuration Tools

```python
# Initialize configuration by discovering existing files
init_project_config(local_path="/path/to/repo")

# Get current configuration
get_project_config(local_path="/path/to/repo")

# Confirm project context for accurate audit results
confirm_project_context(
    local_path="/path/to/repo",
    has_releases=True,
    ci_provider="github"
)
```

## Creating a Plugin

To create a new compliance implementation, start with the [**third-party plugin packaging guide**](docs/packaging-plugins.md) — it walks through `pyproject.toml`, entry points, the `ComplianceImplementation` protocol, the TOML control schema, signing, and distribution end-to-end. A minimal worked example lives at [`packages/darnit-hello/`](packages/darnit-hello/); copy it as a starting point.

For implementation-level details (Python control handlers, custom MCP tools, remediation patterns), see the [Implementation Development Guide](docs/getting-started/implementation-development.md) and the [step-by-step tutorial](docs/tutorials/create-new-implementation.md).

**If your "implementation" is really a curated mix of existing ones** — e.g., "OpenSSF Baseline levels 1–2 + three named SLSA controls + four of our own" — see the [composition quickstart](specs/013-plugin-composition/quickstart.md). Composition is TOML-only; you don't write Python composition code, and upstream sources stay upgrade-current automatically.

## Available MCP Tools

### Audit Tools
- `audit_openssf_baseline` - Run compliance audit
- `list_available_checks` - List all available controls
- `generate_attestation` - Create signed attestation

### Configuration Tools
- `init_project_config` - Initialize `.project.yaml`
- `get_project_config` - Get current configuration
- `confirm_project_context` - Record project context

### Remediation Tools
- `remediate_audit_findings` - Auto-fix compliance gaps
- `create_security_policy` - Generate SECURITY.md
- `enable_branch_protection` - Configure branch protection

### Git Workflow Tools
- `create_remediation_branch` - Create a branch for fixes
- `commit_remediation_changes` - Commit changes
- `create_remediation_pr` - Open a pull request
- `get_remediation_status` - Check git status

### Analysis Tools
- `generate_threat_model` - STRIDE threat analysis

### Testing Tools
- `create_test_repository` - Create a repo that fails all controls (for testing)

## OSPS Control Categories

| Prefix | Category | Focus Area |
|--------|----------|------------|
| OSPS-AC | Access Control | Branch protection, authentication, authorization |
| OSPS-BR | Build & Release | Reproducible builds, artifact signing, CI/CD pipelines |
| OSPS-DO | Documentation | README quality, changelogs, support information |
| OSPS-GV | Governance | Maintainer documentation, contribution guidelines, response times |
| OSPS-LE | Legal | Licensing, contributor agreements (DCO/CLA) |
| OSPS-QA | Quality | Code review requirements, testing, static analysis |
| OSPS-SA | Security Architecture | Threat modeling, secure design principles |
| OSPS-VM | Vulnerability Management | Dependency scanning, CVE handling, security advisories |

## Using with Claude Code

Darnit provides an MCP (Model Context Protocol) server that integrates with AI assistants like Claude Code. This allows Claude to run compliance audits, generate attestations, and apply remediations directly.

### Quick Setup

Add the darnit MCP server to your Claude Code settings:

**Option 1: Global settings** (`~/.claude/settings.json`):

```json
{
  "mcpServers": {
    "openssf-baseline": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/baseline-mcp", "darnit", "serve", "--framework", "openssf-baseline"]
    }
  }
}
```

**Option 2: Project settings** (`.claude/settings.json` in your repo):

```json
{
  "mcpServers": {
    "openssf-baseline": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/baseline-mcp", "darnit", "serve", "--framework", "openssf-baseline"]
    }
  }
}
```

**Option 3: Using uvx** (if published to PyPI):

```json
{
  "mcpServers": {
    "openssf-baseline": {
      "command": "uvx",
      "args": ["darnit", "serve", "--framework", "openssf-baseline"]
    }
  }
}
```

### Verifying the Connection

After adding the configuration, restart Claude Code. You should see darnit tools available:

```
/mcp
```

This will show available MCP servers including `darnit` with tools like:
- `audit_openssf_baseline`
- `remediate_audit_findings`
- `generate_attestation`
- etc.

### Example Usage in Claude Code

Once configured, you can ask Claude to:

```
Audit this repository for OpenSSF Baseline compliance
```

```
Fix the failing security controls
```

```
Generate a signed attestation for this project
```

### Creating Custom Frameworks

You can create your own compliance framework by:

1. **Create a framework package** with entry points (see [Creating a Plugin](#creating-a-plugin))

2. **Define your framework in TOML** (`my-framework.toml`):

```toml
[framework]
name = "my-framework"
version = "1.0.0"

[mcp]
name = "my-framework"
description = "My compliance framework"

[mcp.tools.audit_my_framework]
handler = "my_package.tools:audit"
description = "Run compliance audit"

[controls."MY-01.01"]
name = "MyFirstControl"
description = "Description of the control"
level = 1
```

3. **Configure Claude Code to use your framework**:

```json
{
  "mcpServers": {
    "my-framework": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/my-framework", "darnit", "serve", "/path/to/my-framework.toml"]
    }
  }
}
```

### Environment Variables

The MCP server respects these environment variables:

| Variable | Description | Default |
|----------|-------------|---------|
| `GITHUB_TOKEN` | GitHub API token for repo checks | From `gh auth` |
| `DARNIT_LOG_LEVEL` | Logging level (DEBUG, INFO, WARN) | INFO |
| `DARNIT_CACHE_TTL` | Cache time-to-live in seconds | 300 |

## Security

Darnit is designed with security in mind. Key security features include:

- **Module Whitelist**: Dynamic adapter loading is restricted to trusted module prefixes (`darnit.*`, `darnit_baseline.*`, `darnit_plugins.*`, `darnit_testchecks.*`)
- **Dry-Run Mode**: All remediation actions support dry-run to preview changes before applying
- **Sigstore Attestations**: Cryptographically signed compliance attestations with transparency logging
- **Plugin Verification**: Sigstore-based verification of plugin packages

### Plugin Security

Configure trusted publishers in `.baseline.toml`:

```toml
[plugins]
allow_unsigned = false
trusted_publishers = [
    "https://github.com/kusari-oss",
    "https://github.com/my-org",
]
```

Default trusted publishers: `kusari-oss`, `kusaridev`

### Quick Security Checklist

- [ ] Use fine-grained GitHub tokens with minimal permissions
- [ ] Always use `dry_run=True` first when remediating
- [ ] Review `.baseline.toml` changes in pull requests
- [ ] Name custom adapter packages with `darnit_` prefix
- [ ] Enable plugin verification in production (`allow_unsigned = false`)

For comprehensive security guidance, see [docs/SECURITY_GUIDE.md](docs/SECURITY_GUIDE.md).

To report security vulnerabilities, see [SECURITY.md](SECURITY.md).

## Development

For contributor setup and development workflow, see the [Getting Started Guide](GETTING_STARTED.md).

## Governance

The darnit Project is governed by a Technical Steering Committee (TSC). See the [Charter](CHARTER.md) for the binding governance rules, the [TSC roster](TECHNICAL-STEERING-COMMITTEE.md) for current voting members, and [GOVERNANCE.md](GOVERNANCE.md) for operational guidance (roles, release process, contact).

## License

Apache-2.0
