# Software Composition Analysis (SCA) Policy

## Scanning Frequency

- **Every pull request**: Automated dependency review before merge
- **Daily**: Automated vulnerability scanning of all dependencies
- **On release**: Full dependency audit before each release

## Severity Thresholds

| Severity | Action Required | Timeline |
|----------|----------------|----------|
| Critical | Block merge, immediate fix | 48 hours |
| High     | Block merge, prioritize fix | 7 days |
| Medium   | Warning, schedule fix | 30 days |
| Low      | Informational, fix in next cycle | 90 days |

## Remediation Process

1. Automated alerts from Kusari Inspector — see [`.github/workflows/sca.yml`](../.github/workflows/sca.yml) for configuration
2. Triage by maintainers to confirm applicability
3. Apply patch, upgrade, or document as not affected (VEX)
4. Verify fix does not introduce regressions

## Exceptions

Exceptions to the remediation timelines require:
- Documented justification
- Approval from a project maintainer
- A tracking issue with a planned resolution date