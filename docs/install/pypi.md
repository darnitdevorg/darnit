# Install darnit from PyPI

This is the recommended install path for users who have **Python 3.11 or 3.12** already installed. Examples assume version `0.1.0` — substitute the version you want.

## Pick an install command

```bash
# pipx — isolated install, recommended for end users
pipx install darnit-mcp==0.1.0

# uv — fastest, modern
uv tool install darnit-mcp==0.1.0

# pip — works in any virtualenv
pip install darnit-mcp==0.1.0
```

After install, `darnit --version` should print `0.1.0`.

## Pre-releases (TestPyPI)

Pre-releases (`rcN` suffix) are published to TestPyPI only. To install one:

```bash
pip install \
  --index-url https://test.pypi.org/simple/ \
  --extra-index-url https://pypi.org/simple/ \
  --pre \
  darnit-mcp==0.1.0rc1
```

The `--extra-index-url` is required so dependencies of darnit that exist only on PyPI (e.g. `tree-sitter`, `mcp`, `pydantic`) can still be resolved.

## Verify the Sigstore attestation

Every release attaches a [PEP 740](https://peps.python.org/pep-0740/) Sigstore attestation. The signing identity is the GitHub Actions workflow that produced the wheel; you can verify the chain back to the canonical repository without trusting anything in between.

### One-step verification with pip

If your pip is 25.0 or newer, `--verify-attestations` does the whole thing automatically:

```bash
pip install --verify-attestations darnit-mcp==0.1.0
```

pip refuses to install if the attestation is missing or fails to verify against PyPI's public certs.

### Manual verification with `sigstore`

If you need to verify outside an install context (security scanning, attestation archives, etc.):

```bash
# Install the verifier
pip install 'sigstore>=3.0.0'

# Download the wheel
pip download --no-deps darnit-mcp==0.1.0

# Fetch the PEP 740 attestation bundle from PyPI's provenance API
curl -fsSL \
  "https://pypi.org/integrity/darnit-mcp/0.1.0/darnit_mcp-0.1.0-py3-none-any.whl/provenance" \
  -o provenance.json

# Extract the first attestation as a sigstore-readable bundle
python -c "
import json
with open('provenance.json') as f:
    data = json.load(f)
with open('attestation.sigstore.json', 'w') as out:
    json.dump(data['attestation_bundles'][0]['attestations'][0], out)
"

# Verify against the canonical kusari-oss/darnit identity
python -m sigstore verify identity \
  --bundle attestation.sigstore.json \
  --cert-identity-regexp '^https://github\.com/kusari-oss/darnit/\.github/workflows/release\.yml@' \
  --cert-oidc-issuer https://token.actions.githubusercontent.com \
  darnit_mcp-0.1.0-py3-none-any.whl
```

A passing verification proves:

- The wheel bytes match exactly what was signed.
- The signer was the `release.yml` workflow in `kusari-oss/darnit`.
- The OIDC issuer was GitHub Actions (not some other identity provider).

For TestPyPI pre-releases, substitute `test.pypi.org` for `pypi.org` in the provenance URL.

## Public package set

Each release publishes four packages in lockstep:

| Package | Purpose |
|---|---|
| `darnit` | Core framework (you'll usually install `darnit-mcp`, which pulls this in) |
| `darnit-baseline` | OpenSSF Baseline compliance implementation |
| `darnit-gittuf` | Gittuf policy plugin |
| `darnit-mcp` | The MCP server entry point — installs the `darnit` CLI |

For most users, `pip install darnit-mcp` is the right command. The other packages exist for users who want only the framework, only a specific implementation, or who are writing their own implementation plugin (see [`docs/packaging-plugins.md`](../packaging-plugins.md)).

## Prerequisites

- **Python 3.11 or 3.12** — older Python versions are not supported and will fail to install
- **Network access to pypi.org** (or test.pypi.org for pre-releases)
- Some darnit controls invoke `git` and the `gh` CLI at audit time. If you only `pip install`, you'll need to install those separately. The [container image](container.md) bundles them.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `ERROR: Package requires a different Python` | Host Python is older than 3.11. Install Python 3.11+ or use [pipx](https://pipx.pypa.io/) with an explicit `--python` flag. |
| `Could not find a version that satisfies the requirement` (for a pre-release) | Missing `--pre` flag or wrong `--index-url`. |
| Sigstore verification fails with "no attestation bundles" | The release was published before PEP 740 attestations existed, or the attestation hasn't propagated yet (rare; retry in a few minutes). |
| Sigstore verification fails with "identity mismatch" | The wheel was not signed by `kusari-oss/darnit`'s release workflow. **Do not trust this artifact.** Report it via the project's security policy. |
