# OpenSSF Baseline Attestation Specification

This document specifies how the OpenSSF Baseline MCP server generates in-toto attestations for compliance assessments and remediations.

## Overview

The MCP server produces signed in-toto attestations that cryptographically bind compliance assessment results to a specific repository state (git commit). These attestations can be verified by third parties to confirm that a repository met (or failed to meet) specific OpenSSF Baseline controls at a point in time.

## Attestation Types

### 1. Assessment Attestation

**Predicate Type**: `https://openssf.org/baseline/assessment/v1`

Generated when running `audit_openssf_baseline()`. This attestation captures:
- Which controls were checked
- Pass/fail/warning/N/A status for each control
- Evidence collected during the check
- Overall compliance level achieved

### 2. Remediation Attestation

**Predicate Type**: `https://openssf.org/baseline/remediation/v1`

Generated when automated or guided remediation is performed. This attestation captures:
- What was fixed
- Files created/modified
- Link to prior assessment
- Manual steps still required

## Statement Format

All attestations use the [in-toto Statement v1](https://github.com/in-toto/attestation/blob/main/spec/v1/statement.md) envelope:

```json
{
  "_type": "https://in-toto.io/Statement/v1",
  "subject": [...],
  "predicateType": "<predicate-type-uri>",
  "predicate": {...}
}
```

## Subject Identification

The subject identifies the repository state being attested:

```json
"subject": [{
  "name": "git+https://github.com/<owner>/<repo>",
  "digest": {
    "gitCommit": "<40-character-sha>"
  }
}]
```

| Field | Description |
|-------|-------------|
| `name` | Repository URL in purl-like format |
| `digest.gitCommit` | Full SHA-1 commit hash |

## Assessment Predicate Schema

```json
{
  "predicateType": "https://openssf.org/baseline/assessment/v1",
  "predicate": {
    "assessor": {
      "name": "openssf-baseline",
      "version": "<semver>",
      "uri": "https://github.com/darnitdevorg/darnit"
    },
    "timestamp": "<RFC3339>",
    "baseline": {
      "version": "2026.02.19",
      "specification": "https://baseline.openssf.org/versions/2026-02-19"
    },
    "repository": {
      "url": "https://github.com/<owner>/<repo>",
      "ref": "<branch-or-tag>",
      "commit": "<sha>"
    },
    "configuration": {
      "project_type": "software|specification|documentation|infrastructure|data",
      "project_config_path": "project.toml",
      "excluded_controls": ["<control-id>", ...],
      "adapters_used": ["builtin", ...]
    },
    "summary": {
      "level_assessed": 3,
      "level_achieved": 1,
      "total_controls": 65,
      "passed": 45,
      "failed": 15,
      "warnings": 3,
      "not_applicable": 2,
      "errors": 0
    },
    "levels": {
      "1": {
        "total": 19,
        "passed": 19,
        "failed": 0,
        "compliant": true
      },
      "2": {
        "total": 23,
        "passed": 18,
        "failed": 5,
        "compliant": false
      },
      "3": {
        "total": 23,
        "passed": 8,
        "failed": 10,
        "compliant": false
      }
    },
    "controls": [
      {
        "id": "OSPS-AC-01.01",
        "level": 1,
        "category": "AC",
        "status": "PASS|FAIL|WARN|NA|ERROR",
        "message": "Human-readable result description",
        "evidence": "Optional evidence or file path",
        "source": "builtin|kusari|<adapter-name>"
      }
    ]
  }
}
```

### Field Definitions

| Field | Type | Required | Description |
|-------|------|----------|-------------|
| `assessor.name` | string | Yes | Tool identifier |
| `assessor.version` | string | Yes | Semantic version of the tool |
| `assessor.uri` | string | No | URL to tool documentation |
| `timestamp` | string | Yes | RFC3339 timestamp of assessment |
| `baseline.version` | string | Yes | OSPS baseline version (e.g., "2026.02.19") |
| `repository.url` | string | Yes | Repository URL |
| `repository.commit` | string | Yes | Full commit SHA |
| `configuration.project_type` | string | Yes | Value of `ProjectConfig.type`; falls back to `"software"` when no project config is present |
| `configuration.excluded_controls` | array | No | Controls marked N/A in config |
| `summary.level_achieved` | int | Yes | Highest fully-compliant level (0-3) |
| `controls` | array | Yes | Individual control results |

## Remediation Predicate Schema

```json
{
  "predicateType": "https://openssf.org/baseline/remediation/v1",
  "predicate": {
    "remediator": {
      "name": "openssf-baseline",
      "version": "<semver>"
    },
    "timestamp": "<RFC3339>",
    "baseline_version": "2026.02.19",
    "repository": {
      "url": "https://github.com/<owner>/<repo>",
      "before_commit": "<sha-before>",
      "after_commit": "<sha-after>"
    },
    "prior_assessment": {
      "digest": "<sha256-of-assessment-attestation>",
      "level_achieved": 1
    },
    "remediations": [
      {
        "control_id": "OSPS-DO-01.01",
        "status": "remediated|partial|manual_required",
        "action": "Created SECURITY.md with vulnerability reporting policy",
        "automated": true,
        "changes": [
          {
            "type": "create|modify|delete",
            "path": "SECURITY.md",
            "description": "Created security policy file"
          }
        ]
      },
      {
        "control_id": "OSPS-AC-02.01",
        "status": "manual_required",
        "action": "Branch protection requires manual configuration",
        "automated": false,
        "manual_steps": [
          "Go to repository Settings > Branches",
          "Add branch protection rule for 'main'",
          "Enable 'Require pull request reviews before merging'",
          "Set 'Required approving reviews' to at least 1"
        ]
      }
    ],
    "summary": {
      "total_addressed": 5,
      "fully_remediated": 3,
      "partially_remediated": 1,
      "manual_required": 1,
      "files_created": ["SECURITY.md", "CONTRIBUTING.md"],
      "files_modified": ["README.md"],
      "files_deleted": []
    },
    "post_assessment": {
      "level_achieved": 2,
      "improvement": "+1 level"
    }
  }
}
```

## Signing with Sigstore

Attestations are signed using [Sigstore](https://sigstore.dev) keyless signing with DSSE (Dead Simple Signing Envelope).

### Dependencies

```toml
[project.dependencies]
sigstore = ">=3.0.0"
in-toto-attestation = ">=0.9.0"
```

### Signing Flow

```
┌─────────────────────────────────────────────────────────────────┐
│                      SIGNING FLOW                                │
├─────────────────────────────────────────────────────────────────┤
│                                                                  │
│  1. Generate Assessment/Remediation                              │
│         ↓                                                        │
│  2. Create in-toto Statement                                     │
│         ↓                                                        │
│  3. Authenticate via OIDC (GitHub, Google, Microsoft)           │
│         ↓                                                        │
│  4. Sigstore issues short-lived certificate                     │
│         ↓                                                        │
│  5. Sign Statement with DSSE                                     │
│         ↓                                                        │
│  6. Record signature in Rekor transparency log                  │
│         ↓                                                        │
│  7. Return signed bundle (.sigstore.json)                       │
│                                                                  │
└─────────────────────────────────────────────────────────────────┘
```

### Example Signing Code

```python
from sigstore.oidc import Issuer
from sigstore.sign import SigningContext
from in_toto_attestation.v1.statement import Statement
from in_toto_attestation.v1.resource_descriptor import ResourceDescriptor

def sign_assessment(assessment_result: dict, commit_sha: str, repo_url: str) -> bytes:
    """Sign an assessment result as an in-toto attestation."""

    # Create the in-toto statement
    stmt = Statement(
        subjects=[
            ResourceDescriptor(
                name=f"git+{repo_url}",
                digest={"gitCommit": commit_sha}
            ).pb,
        ],
        predicate=assessment_result,
        predicate_type="https://openssf.org/baseline/assessment/v1",
    )

    # Sign with Sigstore (keyless)
    ctx = SigningContext.production()
    with ctx.signer(identity_token=Issuer.production().identity_token()) as signer:
        result = signer.sign(stmt)

    return result.bundle.to_json()
```

### Output Format

The signed attestation is output as a Sigstore bundle (`.sigstore.json`):

```json
{
  "mediaType": "application/vnd.dev.sigstore.bundle+json;version=0.3",
  "verificationMaterial": {
    "certificate": {...},
    "tlogEntries": [...]
  },
  "dsseEnvelope": {
    "payload": "<base64-encoded-statement>",
    "payloadType": "application/vnd.in-toto+json",
    "signatures": [...]
  }
}
```

## Verification

To verify an attestation:

```bash
# Using sigstore-python
sigstore verify identity \
  --bundle attestation.sigstore.json \
  --cert-identity "user@example.com" \
  --cert-oidc-issuer "https://github.com/login/oauth"
```

Or programmatically:

```python
from sigstore.verify import Verifier, VerificationMaterials
from sigstore.verify.policy import Identity

verifier = Verifier.production()
materials = VerificationMaterials.from_bundle(bundle_path)

result = verifier.verify(
    materials,
    policy=Identity(
        identity="ci@example.com",
        issuer="https://token.actions.githubusercontent.com"
    )
)
```

## MCP Tool Interface

### `generate_attestation`

```python
@mcp.tool()
def generate_attestation(
    owner: str,
    repo: str,
    local_path: str = ".",
    attestation_type: str = "assessment",  # or "remediation"
    sign: bool = True,
    output_path: Optional[str] = None,
) -> dict:
    """
    Generate an in-toto attestation for baseline compliance.

    Args:
        owner: GitHub org/user
        repo: Repository name
        local_path: Path to local clone
        attestation_type: "assessment" or "remediation"
        sign: Whether to sign with Sigstore (requires OIDC auth)
        output_path: Where to write the attestation (default: stdout)

    Returns:
        The attestation (signed bundle if sign=True, raw statement if sign=False)
    """
```

### Usage Examples

```python
# Generate signed assessment attestation
result = generate_attestation(
    owner="my-org",
    repo="my-project",
    local_path="/path/to/repo",
    attestation_type="assessment",
    sign=True
)

# Generate unsigned statement (for testing)
result = generate_attestation(
    owner="my-org",
    repo="my-project",
    local_path="/path/to/repo",
    sign=False
)
```

## Storage Recommendations

| Location | Use Case |
|----------|----------|
| `.attestations/` directory | Store with repository |
| GitHub Release assets | Attach to releases |
| OCI registry | Store alongside container images |
| Sigstore Rekor | Automatically recorded during signing |

## Security Considerations

1. **Commit verification**: Always verify the git commit exists and matches the working directory before attesting
2. **OIDC identity**: The signer's identity is bound to the attestation; use CI service accounts for automation
3. **Timestamp accuracy**: Use server time; don't trust client-provided timestamps
4. **Evidence handling**: Sensitive evidence (API keys, internal paths) should be redacted

## Future Extensions

- **Batch attestations**: Multiple repositories in one attestation
- **Delta attestations**: Only include changed controls since last assessment
- **Policy attestations**: Attest that a policy was enforced, not just checked
- **Dependency roll-up**: Include attestation status of dependencies

## References

- [in-toto Attestation Framework](https://github.com/in-toto/attestation)
- [Sigstore Documentation](https://docs.sigstore.dev)
- [DSSE Specification](https://github.com/secure-systems-lab/dsse)
- [OpenSSF Baseline](https://baseline.openssf.org)
