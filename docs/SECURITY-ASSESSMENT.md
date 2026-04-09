# Security Assessment Process

## Pre-Release Security Review

Before each major release, the following security assessment steps are performed:

### Security Audit Checklist

- [ ] Review all dependencies for known vulnerabilities
- [ ] Run static analysis security testing (SAST) tools
- [ ] Check for hardcoded credentials or secrets
- [ ] Review access control and authentication changes
- [ ] Verify input validation on new endpoints or user inputs

### Security Review Process

1. A security review issue is created for each major release
2. At least one maintainer reviews security-relevant changes
3. All critical and high severity findings must be resolved before release
4. Security review sign-off is documented in the release notes

### Vulnerability Reporting

See [SECURITY.md](../SECURITY.md) for responsible disclosure instructions.