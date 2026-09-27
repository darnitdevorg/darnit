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
# Framework TOML shipped in your plugin package
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

darnit separates two kinds of configuration:

- **Operator configuration** is tool configuration owned by whoever runs darnit. It is the only place tool settings come from.
- **Project claims** in `.project/` are statements a repository makes about itself. They are reported, and they count only under the trust and evidence rules below.

Nothing in an audited repository can add to, override, or select operator configuration.

### Operator Configuration

Operator configuration is a TOML file found the same way by every driver (CLI, MCP server, headless harness):

1. `--operator-config PATH` given at launch (`darnit audit`, `darnit run`, `darnit harness`, `darnit serve`, `darnit config show`).
2. Otherwise the per-user location: `$XDG_CONFIG_HOME/darnit/config.toml` when `XDG_CONFIG_HOME` is set and absolute, else `~/.config/darnit/config.toml` (Linux and macOS), or `%APPDATA%\darnit\config.toml` (Windows).
3. Otherwise built-in defaults.

It holds allowed plugins and trusted publishers, MCP servers, per-control pass overrides and custom controls, storage backends, LLM settings, trusted repositories, CI trust rules, and policy defaults:

```toml
schema_version = 1

[plugins]
allowed = ["openssf-baseline"]
trusted_publishers = ["https://github.com/darnitdevorg"]
allow_unsigned = false

[mcp_servers.scanner]
command = ["scanner-mcp", "--stdio"]
env = { SCANNER_TOKEN = "$SCANNER_TOKEN" }   # substituted from the environment at launch

[trust]
repos = ["github.com/example/project"]
ci = [ { event = "push-default-branch" } ]

[policy]
confirmation_expiry_days = 180
```

`darnit config show` prints the file in use, its SHA-256 digest, the permission-check result, and the effective settings with secrets redacted. Every audit report records the same source and digest, so reference secrets as `$VAR` rather than writing them into the file.

Safeguards:

- **Validation**: unknown keys and invalid values stop the run with an error naming the file and key.
- **Containment**: an operator configuration path inside the audited repository is refused, and the refusal is reported. A repository cannot supply operator configuration by passing a path into itself.
- **Permission check (POSIX)**: the file and each parent directory up to your home directory must be owned by you (or root) and not group- or world-writable. A failing file is loaded with a warning, or refused in strict mode.
- **Strict mode**: enabled by `--strict-operator-config`, automatically in recognized CI, or by `policy.strict_permissions = true` in the file. The file can only turn strict mode on, never off.

### Trusted Repositories and CI

A repository's claims can only be honored when the operator trusts that repository for the run.

- **Local runs**: a repository is trusted when the identity you name (`--repo HOST/NAMESPACE/NAME` on the CLI and harness, or the `owner`/`repo` arguments of an MCP tool) is listed in `[trust].repos`. Identities are compared in canonical form, so SSH and HTTPS URLs, a trailing `.git`, and host case all match. A checkout's own remotes are never trusted; a mismatch between your target and the checkout's `origin` is reported.
- **CI**: trust comes from CI metadata and an opt-in rule. The only rule is `push-default-branch`: a push to the repository's default branch (GitHub Actions or GitLab CI) of a listed repository, with the checked-out commit matching the one CI reports. Pull requests, merge requests (from forks or not), `workflow_run`, merge-queue events, and unrecognized CI environments are untrusted.

Manage the list with `darnit config trust add|list|remove`, which edits only `[trust].repos` in the operator configuration file. Reports record the trust decision, its reason, and the CI facts used.

### Project Claims in `.project/`

A repository records that a control does not apply in `.project/darnit.yaml`:

```yaml
controls:
  OSPS-BR-02.01:
    status: n/a
    reason: "Pre-1.0 project with no releases yet. Tracked in issue #123."
    asserted_by: "@maintainer"   # optional
```

Project data in `.project/` that makes a control not applicable (for example a value its applicability condition reads) is a claim too. Every claim has one outcome, shown in the report:

| Outcome | When | Effect |
|---------|------|--------|
| `honored` | The repository is trusted, an explicit claim gives a reason, and no evidence the control declares contradicts it; or an operator confirmed the claim | Control is `N/A`, labelled asserted |
| `pending` | Anything else, including untrusted repositories, claims without a reason, and evidence that could not be obtained | Control is evaluated normally and counts as non-compliant |
| `contradicted` | Evidence contradicts the claim (for example a release exists) | Claim is ignored; control is evaluated normally |

An operator can confirm a pending claim through the `confirm_project_data` MCP tool (`confirm_not_applicable`). Confirmations are stored on the operator side, never in the repository, and lapse when they expire or when the claim's reason or evidence changes. An agent must only confirm a claim when the operator explicitly asks it to.

### Deprecated: `.baseline.toml`

`.baseline.toml` is deprecated. In this release darnit reads its per-control `status` and `reason` and treats them exactly like `.project/` claims; it also still honors `extends` naming a registered framework (use `--framework` instead). Every audit warns for each setting in the file, naming where it now belongs. Tool settings in it are not applied. A later release will ignore the file.

Run `darnit config migrate [REPO]` to write its claims to `.project/darnit.yaml` (existing claims are kept unless you pass `--force`) and print a proposed operator configuration fragment for its tool settings. The command never writes operator configuration. Review both, then delete `.baseline.toml`.

### Configuration Review Checklist

When reviewing changes to `.project/`:

1. **Verify N/A justifications** are legitimate and each claim has a `reason`
2. **Check the audit report** for pending and contradicted claims, and for ignored repository settings, which indicate configuration that belongs in operator configuration

---

## MCP Server Security

When running Darnit as an MCP server with AI assistants, consider these security aspects.

### Access Control

The MCP server has access to:

- **File system** (read for auditing, write for remediation)
- **GitHub API** (via configured token)
- **Network** (for external tool integrations)

### Register darnit at User Scope

Register darnit's MCP server in your own (user-scope) agent configuration, not in a configuration file committed to a repository. `darnit install` writes user-scope registrations by default; `--project` writes a repository-scoped one and is not recommended.

A repository-scoped registration lets the repository decide how darnit is launched: its command, arguments, and environment. For example, a repository-scoped `uv run darnit serve` runs the repository's own copy of darnit, not the one you installed. Do not approve repository-scoped darnit servers in repositories you do not control. When darnit's own code is running from inside the audited repository, audit results include a warning recommending user-scope registration (expected only when developing darnit itself).

```json
{
  "mcpServers": {
    "darnit": {
      "command": "darnit",
      "args": ["serve"],
      "env": {
        "GITHUB_TOKEN": "${GITHUB_TOKEN}",
        "DARNIT_LOG_LEVEL": "INFO"
      }
    }
  }
}
```

Pass `--operator-config PATH` and `--strict-operator-config` in `args` if you keep operator configuration somewhere other than the per-user location.

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

### Current Status

> **Note:** The Sigstore verification module (`darnit.core.verification`) is fully
> implemented and tested, but it is **not yet integrated into plugin discovery**.
> Currently, `discover_implementations()` loads all entry-point plugins
> unconditionally. The verification infrastructure is ready to be wired in — see
> the TODO in `packages/darnit/src/darnit/core/discovery.py`.
>
> In practice this means:
> - **Local development**: All plugins load without verification (expected behavior).
> - **Published releases**: The GitHub Actions publish workflow supports Sigstore
>   attestations (`attestations: true`), but the release trigger is not yet active.
> - **Production hardening**: Once verification is integrated into discovery and
>   packages are published with attestations, set `allow_unsigned = false` to
>   enforce signed-only plugins.

### Plugin Verification with Sigstore

Darnit supports [Sigstore](https://www.sigstore.dev/)-based plugin verification to ensure plugins come from trusted sources.

#### Configuration

```toml
# Operator configuration (for example ~/.config/darnit/config.toml)
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
[[controls."MY-01.01".passes]]
handler = "my_custom_check"  # Short name from registry
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
