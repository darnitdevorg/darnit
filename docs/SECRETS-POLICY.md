# Secrets Management Policy

## Credential Handling

- **No secrets in source**: Secrets, API keys, tokens, and credentials MUST NOT be
  committed to version control, even temporarily.
- **Environment-based injection**: All secrets are injected at runtime via environment
  variables or mounted secret volumes.
- **Automated detection**: Monitoring for accidentally committed credentials
  is performed by Kusari Inspector.

## CI/CD Secrets

- GitHub Actions secrets or an external vault service (e.g., HashiCorp Vault) are used
  for all CI/CD credentials.
- Secrets are scoped to the minimum required environment (repository, environment, or
  organization level).

## Rotation & Revocation

- **Rotation schedule**: Long-lived credentials are rotated at least every 90 days.
- **Incident response**: Compromised credentials are revoked immediately and rotated
  before re-use.
- **Short-lived tokens**: Prefer OIDC tokens and short-lived credentials over long-lived
  secrets wherever supported.

## Review

This policy is reviewed annually or when a security incident involving credentials occurs.