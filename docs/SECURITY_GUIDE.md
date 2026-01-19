# Darnit Security Guide

This document describes security considerations, best practices, and configuration options for using Darnit securely.

## Table of Contents

- [Dynamic Module Loading Security](#dynamic-module-loading-security)
- [GitHub Token Security](#github-token-security)
- [Custom Adapter Security](#custom-adapter-security)
- [Configuration Security](#configuration-security)
- [MCP Server Security](#mcp-server-security)
- [Attestation Security](#attestation-security)
- [Remediation Security](#remediation-security)

---

## Dynamic Module Loading Security

Darnit uses dynamic module loading to instantiate adapters defined in configuration files. To prevent arbitrary code execution, **module paths are validated against a whitelist** before loading.

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

For enterprise deployments, you can subclass `AdapterRegistry` or `PluginRegistry` to extend the whitelist:

```python
from darnit.core.registry import PluginRegistry

class EnterprisePluginRegistry(PluginRegistry):
    ALLOWED_MODULE_PREFIXES = PluginRegistry.ALLOWED_MODULE_PREFIXES + (
        "mycompany.",
        "mycompany_compliance.",
    )
```

> **Warning**: Extending the whitelist increases your attack surface. Only add trusted module prefixes.

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
| Custom adapters loading malicious code | Module whitelist prevents arbitrary loading |
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
