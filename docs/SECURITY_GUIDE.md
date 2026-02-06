# Darnit Security Guide

This document describes security considerations, best practices, and configuration options for using Darnit securely.

## Table of Contents

- [Dynamic Module Loading Security](#dynamic-module-loading-security)
- [GitHub Token Security](#github-token-security)
- [Custom Adapter Security](#custom-adapter-security)
- [Configuration Security](#configuration-security)
- [MCP Server Security](#mcp-server-security)
- [Plugin Security Model](#plugin-security-model)
- [Attestation Security](#attestation-security)
- [Remediation Security](#remediation-security)

---

## Dynamic Module Loading Security

Darnit uses dynamic module loading to instantiate adapters defined in configuration files. To prevent arbitrary code execution, **module paths are validated against a allowlist** before loading.

### Allowed Module Prefixes

By default, only modules from these prefixes can be dynamically loaded:

```python
ALLOWED_MODULE_PREFIXES = (
    "darnit.",
    "darnit_baseline.",
    "darnit_plugins.",
    "darnit_testchecks.",
)
```

### Security Implications

- **Configuration-defined adapters** must reference modules within the allowed prefixes
- **Malicious configurations** cannot load arbitrary Python code
- **Custom adapters** must be installed as proper Python packages with `darnit_` prefix

### Extending the Whitelist

If you need to use custom adapters from your own packages, you have two options:

#### Option 1: Use the `darnit_` Prefix Convention (Recommended)

Name your custom adapter package with the `darnit_` prefix:

```
darnit_mycompany/
├── adapters/
│   └── custom.py
└── __init__.py
```

This automatically allows your module to be loaded:

```toml
# .baseline.toml
[adapters.mycompany]
type = "python"
module = "darnit_mycompany.adapters.custom"
class = "MyCustomAdapter"
```

#### Option 2: Modify the Whitelist (Advanced)

For enterprise deployments, you can subclass `AdapterRegistry` or `PluginRegistry` to extend the allowlist:

```python
from darnit.core.registry import PluginRegistry

class EnterprisePluginRegistry(PluginRegistry):
    ALLOWED_MODULE_PREFIXES = PluginRegistry.ALLOWED_MODULE_PREFIXES + (
        "mycompany.",
        "mycompany_compliance.",
    )
```

> **Warning**: Extending the allowlist increases your attack surface. Only add trusted module prefixes.

---

## GitHub Token Security

Darnit requires GitHub API access for many checks (branch protection, workflows, etc.).

### Token Sources

Darnit obtains GitHub tokens in this order:

1. `GITHUB_TOKEN` environment variable
2. `gh auth token` (GitHub CLI authentication)

### Required Permissions

For read-only auditing, your token needs:

| Permission | Scope | Purpose |
|------------|-------|---------|
| `repo` | Read | Access repository metadata, branch protection |
| `read:org` | Read | Check organization settings (if applicable) |

For remediation (creating files, enabling branch protection):

| Permission | Scope | Purpose |
|------------|-------|---------|
| `repo` | Write | Create/modify files, enable branch protection |
| `workflow` | Write | Modify GitHub Actions workflows |

### Best Practices

1. **Use fine-grained tokens** with minimal permissions
2. **Never commit tokens** to version control
3. **Rotate tokens regularly** especially for CI/CD
4. **Use short-lived tokens** in automated pipelines
5. **Audit token usage** via GitHub's security log

### CI/CD Configuration

```yaml
# GitHub Actions example
jobs:
  audit:
    runs-on: ubuntu-latest
    permissions:
      contents: read
      security-events: write
    steps:
      - uses: actions/checkout@v4
      - name: Run Darnit Audit
        env:
          GITHUB_TOKEN: ${{ secrets.GITHUB_TOKEN }}
        run: |
          uv run python main.py audit_openssf_baseline
```

---

## Custom Adapter Security

When creating custom adapters, follow these security guidelines.

### Adapter Development Checklist

- [ ] **Validate all inputs** from configuration and control definitions
- [ ] **Sanitize file paths** to prevent path traversal attacks
- [ ] **Avoid shell injection** when executing external commands
- [ ] **Handle secrets securely** - never log credentials
- [ ] **Implement timeouts** for external calls
- [ ] **Use least privilege** - request only necessary permissions

### Secure Command Execution

For command-based adapters, use safe execution patterns:

```python
import subprocess
import shlex

class SecureCommandAdapter(CheckAdapter):
    def check(self, control_id, owner, repo, local_path, config):
        command = config.get("command", "")

        # NEVER do this - shell injection vulnerability
        # subprocess.run(f"tool {local_path}", shell=True)

        # DO this - use list arguments, no shell
        subprocess.run(
            ["tool", "--path", local_path],
            shell=False,
            timeout=300,
            capture_output=True,
        )
```

### Input Validation

```python
from pathlib import Path

def validate_path(path: str, allowed_base: str) -> Path:
    """Validate path is within allowed directory."""
    resolved = Path(path).resolve()
    allowed = Path(allowed_base).resolve()

    if not str(resolved).startswith(str(allowed)):
        raise ValueError(f"Path {path} is outside allowed directory")

    return resolved
```

---

## Configuration Security

### `.baseline.toml` Security

The `.baseline.toml` file in your repository can override framework behavior. Consider these risks:

| Risk | Mitigation |
|------|------------|
| Disabling security controls | Review `.baseline.toml` changes in PRs |
| Custom adapters loading malicious code | Module allowlist prevents arbitrary loading |
| Marking controls as N/A inappropriately | Require justification in `reason` field |

### Secure Configuration Example

```toml
# .baseline.toml
version = "1.0"
extends = "openssf-baseline"

# Document why controls are disabled
[controls."OSPS-BR-02.01"]
status = "n/a"
reason = "Pre-1.0 project with no releases yet. Tracked in issue #123."

# Use only trusted adapters
[adapters.scanner]
type = "python"
module = "darnit_mycompany.adapters.scanner"  # Must have darnit_ prefix
```

### Configuration Review Checklist

When reviewing `.baseline.toml` changes:

1. **Verify N/A justifications** are legitimate
2. **Check adapter modules** use allowed prefixes
3. **Review custom control definitions** for appropriate security levels
4. **Audit control overrides** that reduce security requirements

---

## MCP Server Security

When running Darnit as an MCP server with AI assistants, consider these security aspects.

### Access Control

The MCP server has access to:

- **File system** (read for auditing, write for remediation)
- **GitHub API** (via configured token)
- **Network** (for external tool integrations)

### Recommended Configuration

```json
{
  "mcpServers": {
    "darnit": {
      "command": "uv",
      "args": ["run", "--directory", "/path/to/baseline-mcp", "python", "main.py"],
      "env": {
        "GITHUB_TOKEN": "${GITHUB_TOKEN}",
        "DARNIT_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

### Security Recommendations

1. **Run with minimal permissions** - Use read-only tokens when only auditing
2. **Use dry-run mode** - Always preview remediation changes before applying
3. **Review AI-suggested changes** - Don't blindly apply remediation recommendations
4. **Isolate sensitive repositories** - Consider separate MCP server instances
5. **Monitor MCP server logs** - Track what operations are being performed

### Dry-Run Mode

Always use dry-run mode first to preview changes:

```python
# Preview what would be changed
remediate_audit_findings(
    local_path="/path/to/repo",
    categories=["security_policy", "contributing"],
    dry_run=True  # Preview only
)
```

---

## Plugin Security Model

Darnit's plugin system allows extending functionality through third-party packages. This section describes the security model for plugins.

### Plugin Verification with Sigstore

Darnit supports [Sigstore](https://www.sigstore.dev/)-based plugin verification to ensure plugins come from trusted sources.

#### Configuration

```toml
# .baseline.toml
[plugins]
allow_unsigned = false          # Reject unsigned plugins (use true for local dev)
trusted_publishers = [          # Trust plugins signed by these OIDC identities
    "https://github.com/kusari-oss",
    "https://github.com/openssf",
]
```

#### Trusted Publisher Formats

The `trusted_publishers` list supports multiple identity formats:

| Format | Example | Matches |
|--------|---------|---------|
| Full GitHub URL | `https://github.com/kusari-oss` | Any repo in that org |
| GitHub org name | `kusari-oss` | Substring match in identity |
| Specific repo | `https://github.com/kusari-oss/darnit` | Exact repo match |
| Email identity | `security@example.com` | Email-based OIDC |

**Example with multiple formats:**

```toml
[plugins]
allow_unsigned = false
trusted_publishers = [
    "https://github.com/kusari-oss",     # Trust all repos in org
    "https://github.com/openssf",         # Trust OpenSSF org
    "mycompany",                          # Trust by org name substring
]
```

#### Verification Modes

| Mode | `allow_unsigned` | Behavior |
|------|------------------|----------|
| Strict | `false` | Only signed plugins from trusted publishers load |
| Permissive | `true` | All plugins load, warnings for unsigned |

#### Using the Verifier

```python
from darnit.core.verification import PluginVerifier, VerificationConfig

# Production mode: require signed plugins from trusted publishers
config = VerificationConfig(
    allow_unsigned=False,
    trusted_publishers=[
        "https://github.com/kusari-oss",
        "https://github.com/openssf",
    ],
)
verifier = PluginVerifier(config)

result = verifier.verify_plugin("darnit-baseline")
if result.verified:
    if result.signed:
        print(f"Plugin verified (signed by {result.publisher})")
    else:
        print(f"Plugin allowed (unsigned): {result.warning}")
elif result.error:
    print(f"Verification failed: {result.error}")

# Development mode: allow all plugins with warnings
dev_config = VerificationConfig(allow_unsigned=True)
dev_verifier = PluginVerifier(dev_config)
```

### Handler Registration Security

Plugins register handlers using the `@register_handler` decorator. Only modules matching the allowlist can register handlers.

#### Allowlist

```python
ALLOWED_MODULE_PREFIXES = (
    "darnit.",           # Core framework
    "darnit_baseline.",  # OpenSSF Baseline implementation
    "darnit_plugins.",   # Official plugins
    "darnit_testchecks.",# Test utilities
)
```

#### Registering Handlers

```python
from darnit.core.handlers import register_handler

@register_handler("my_custom_check")
def my_custom_check(context):
    """Custom check implementation."""
    # Check logic here
    return PassResult(outcome=PassOutcome.PASS, ...)
```

The handler can then be referenced in TOML by short name:

```toml
[controls."MY-01.01".passes.deterministic]
config_check = "my_custom_check"  # Short name from registry
```

Or by full module path (must match allowlist):

```toml
[controls."MY-01.01".passes.deterministic]
config_check = "darnit_baseline.controls.level1:_create_mfa_check"
```

### Security Recommendations

1. **Enable strict verification** in production (`allow_unsigned = false`)
2. **Verify trusted publishers** match expected identities
3. **Review plugin code** before adding to trusted list
4. **Use short names** when possible for better auditability
5. **Monitor verification cache** at `~/.darnit/verification_cache/`

### Verification Cache

Verification results are cached to handle Sigstore service unavailability:

- **Cache location**: `~/.darnit/verification_cache/`
- **TTL**: 24 hours by default
- **Format**: JSON files keyed by package name and version

To clear the cache:

```bash
rm -rf ~/.darnit/verification_cache/
```

### Graceful Degradation

When Sigstore services are unavailable:

1. **Cached results** are used if available
2. **Warning logged** if no cached result exists
3. **Behavior depends on `allow_unsigned`**:
   - `true`: Plugin loads with warning
   - `false`: Plugin rejected

### Signing Plugins with Sigstore

Plugin authors can sign their packages using Sigstore for trusted distribution.

#### GitHub Actions Workflow (Recommended)

The easiest way to sign plugins is via GitHub Actions with OIDC:

```yaml
# .github/workflows/release.yml
name: Release

on:
  release:
    types: [published]

permissions:
  id-token: write  # Required for Sigstore OIDC
  contents: read
  attestations: write

jobs:
  publish:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4

      - name: Set up Python
        uses: actions/setup-python@v5
        with:
          python-version: "3.12"

      - name: Install build tools
        run: pip install build twine

      - name: Build package
        run: python -m build

      - name: Publish to PyPI with attestations
        uses: pypa/gh-action-pypi-publish@release/v1
        with:
          attestations: true
```

#### Manual Signing

For local signing:

```bash
# Install sigstore
pip install sigstore

# Sign a distribution file
python -m sigstore sign dist/my_plugin-1.0.0-py3-none-any.whl

# This creates:
# - dist/my_plugin-1.0.0-py3-none-any.whl.sigstore
```

#### Verification by Users

Users can verify signed plugins:

```bash
python -m sigstore verify identity \
  --cert-identity your-email@example.com \
  --cert-oidc-issuer https://github.com/login/oauth \
  dist/my_plugin-1.0.0-py3-none-any.whl
```

### Arbitrary Code Execution Warning

> **⚠️ Security Warning**: Plugins can execute arbitrary code in your environment.

Darnit plugins have full Python execution capabilities and can:

- **Read and write files** on your filesystem
- **Make network requests** to any host
- **Execute system commands** via subprocess
- **Access environment variables** including secrets

**Before installing any plugin:**

1. **Review the source code** or trust the publisher
2. **Check the publisher identity** via Sigstore signature
3. **Use `allow_unsigned = false`** to require signed plugins
4. **Run in isolated environments** (containers, VMs) for untrusted plugins

**For plugin authors:**

- Follow secure coding practices (input validation, no shell injection)
- Sign your releases with Sigstore
- Document required permissions clearly
- Avoid hardcoded secrets or credentials

---

## Attestation Security

Darnit can generate cryptographically signed attestations for compliance status.

### Sigstore Integration

Attestations are signed using [Sigstore](https://www.sigstore.dev/) for keyless signing:

- **No key management** required
- **Transparency log** provides tamper evidence
- **OIDC identity** ties signatures to verifiable identities

### Verification

To verify an attestation:

```bash
# Install cosign
brew install cosign

# Verify the attestation
cosign verify-attestation \
  --type https://in-toto.io/Statement/v1 \
  --certificate-identity-regexp '.*' \
  --certificate-oidc-issuer-regexp '.*' \
  attestation.json
```

### Attestation Security Considerations

| Aspect | Recommendation |
|--------|---------------|
| Storage | Store attestations separately from code |
| Retention | Keep attestations for audit trail |
| Verification | Verify attestations in CI/CD pipelines |
| Trust | Configure allowed OIDC issuers for your organization |

---

## Remediation Security

Remediation actions modify your repository. Follow these safety practices.

### Safe Remediation Workflow

1. **Create a branch** for remediation changes
2. **Run in dry-run mode** first to preview
3. **Apply changes** to the branch
4. **Review the diff** carefully
5. **Create a PR** for team review
6. **Merge after approval**

### Using MCP Tools Safely

```python
# 1. Create a branch
create_remediation_branch(
    local_path="/path/to/repo",
    branch_name="fix/openssf-baseline-compliance"
)

# 2. Preview changes (dry-run)
remediate_audit_findings(
    local_path="/path/to/repo",
    categories=["all"],
    dry_run=True
)

# 3. Apply changes
remediate_audit_findings(
    local_path="/path/to/repo",
    categories=["security_policy", "contributing"],
    dry_run=False
)

# 4. Commit and create PR
commit_remediation_changes(local_path="/path/to/repo")
create_remediation_pr(local_path="/path/to/repo")
```

### Remediation Categories

| Category | Risk Level | Review Priority |
|----------|------------|-----------------|
| `branch_protection` | High | Requires admin review |
| `security_policy` | Low | Standard review |
| `contributing` | Low | Standard review |
| `codeowners` | Medium | Team lead review |
| `dependabot` | Medium | Security team review |

---

## Reporting Security Issues

If you discover a security vulnerability in Darnit:

1. **DO NOT** create a public GitHub issue
2. See [SECURITY.md](../SECURITY.md) for reporting instructions
3. Email security concerns to the maintainers listed there

---

## Additional Resources

- [OpenSSF Baseline Specification](https://baseline.openssf.org/)
- [Sigstore Documentation](https://docs.sigstore.dev/)
- [GitHub Token Permissions](https://docs.github.com/en/authentication/keeping-your-account-and-data-secure/managing-your-personal-access-tokens)
- [OWASP Secure Coding Practices](https://owasp.org/www-project-secure-coding-practices-quick-reference-guide/)
