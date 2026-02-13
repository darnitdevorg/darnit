## 1. Context Definitions

- [x] 1.1 Add `[context.sbom_tool]` enum definition (syft, cyclonedx, trivy, other) with `store_as = "tooling.sbom_tool"` and `affects = ["OSPS-QA-02.02"]`
- [x] 1.2 Add `[context.sast_tool]` enum definition (codeql, semgrep, sonarqube, other) with `store_as = "tooling.sast_tool"` and `affects = ["OSPS-VM-06.02"]`
- [x] 1.3 Add `[context.preferred_license]` string definition with `store_as = "legal.license"`, `auto_detect = true`, and `affects = ["OSPS-LE-01.01", "OSPS-LE-02.01"]`

## 2. API Payload Templates

- [x] 2.1 Add `[templates.mfa_enforcement_payload]` — JSON payload for org MFA enforcement
- [x] 2.2 Add `[templates.allow_forking_payload]` — JSON payload for enabling repo forking
- [x] 2.3 Add `[templates.branch_deletion_protection_payload]` — JSON payload for branch deletion protection
- [x] 2.4 Add `[templates.repo_visibility_payload]` — JSON payload for making repo public
- [x] 2.5 Add `[templates.status_checks_payload]` — JSON payload for required status checks
- [x] 2.6 Add `[templates.pr_review_payload]` — JSON payload for required PR reviews
- [x] 2.7 Add `[templates.vulnerability_reporting_payload]` — JSON payload for enabling private vulnerability reporting

## 3. CI Workflow Templates

- [x] 3.1 Add `[templates.ci_test_workflow]` — generic CI test workflow with checkout + placeholder test command
- [x] 3.2 Add `[templates.sbom_workflow]` — SBOM generation workflow defaulting to syft, supporting `$SBOM_TOOL` substitution
- [x] 3.3 Add `[templates.sast_workflow]` — SAST scanning workflow defaulting to CodeQL, supporting `$SAST_TOOL` substitution
- [x] 3.4 Add `[templates.sca_workflow]` — SCA dependency scanning workflow for pull requests
- [x] 3.5 Add `[templates.release_signing_workflow]` — release signing workflow using GitHub artifact attestation

## 4. Policy Document Templates

- [x] 4.1 Add `[templates.support_template]` — SUPPORT.md with getting help, reporting bugs, community sections (already existed)
- [x] 4.2 Add `[templates.support_scope_template]` — support scope section with supported versions and duration
- [x] 4.3 Add `[templates.end_of_support_template]` — end-of-support policy with notification and migration
- [x] 4.4 Add `[templates.dependency_management_template]` — dependency policy, update cadence, vulnerability response
- [x] 4.5 Add `[templates.vex_policy_template]` — VEX statement format, assessment criteria, publication process (already existed)
- [x] 4.6 Add `[templates.sca_policy_template]` — scanning frequency, severity thresholds, remediation timelines
- [x] 4.7 Add `[templates.sast_policy_template]` — scanning triggers, severity handling, exception process

## 5. Access Control Domain (AC) — Remediations

- [x] 5.1 OSPS-AC-01.01: Add `api_call` remediation for MFA enforcement (`PUT /orgs/$OWNER`), `safe = false`
- [x] 5.2 OSPS-AC-02.01: Add `api_call` remediation for enabling forking (`PATCH /repos/$OWNER/$REPO`), `safe = true`
- [x] 5.3 OSPS-AC-03.02: Add `api_call` remediation for branch deletion protection, `safe = false`

## 6. Vulnerability Management Domain (VM) — Checks and Remediations

- [x] 6.1 OSPS-VM-01.01: Add `manual` remediation with steps to add disclosure process to SECURITY.md (already existed)
- [x] 6.2 OSPS-VM-03.01: Add `api_call` remediation for enabling private vulnerability reporting (`PUT /repos/$OWNER/$REPO/private-vulnerability-reporting`), `safe = true`
- [x] 6.3 OSPS-VM-04.01: Add `manual` remediation with steps for creating security advisories (already existed)
- [x] 6.4 OSPS-VM-04.02: Add `file_create` remediation for VEX policy (`docs/VEX-POLICY.md`)
- [x] 6.5 OSPS-VM-05.01: Add `file_create` remediation for SCA policy (`docs/SCA-POLICY.md`)
- [x] 6.6 OSPS-VM-05.02: Add `file_create` remediation for SCA workflow (`.github/workflows/sca.yml`)
- [x] 6.7 OSPS-VM-06.01: Add `file_create` remediation for SAST policy (`docs/SAST-POLICY.md`)
- [x] 6.8 OSPS-VM-06.02: Add `file_create` remediation for SAST workflow (`.github/workflows/sast.yml`) (pattern check already existed)

## 7. Quality Assurance Domain (QA) — Checks and Remediations

- [x] 7.1 OSPS-QA-01.01: Add `api_call` remediation for making repo public, `safe = false` (exec check already existed)
- [x] 7.2 OSPS-QA-02.02: Add `file_create` remediation for SBOM workflow (`.github/workflows/sbom.yml`)
- [x] 7.3 OSPS-QA-03.01: Add `api_call` remediation for required status checks, `safe = false`
- [x] 7.4 OSPS-QA-06.01: Add `file_create` remediation for CI workflow (pattern check already existed)
- [x] 7.5 OSPS-QA-07.01: Add `api_call` remediation for required PR reviews, `safe = false`

## 8. Build & Release Domain (BR) — Remediations

- [x] 8.1 OSPS-BR-06.01: Add `file_create` remediation for release signing workflow (`.github/workflows/release-signing.yml`)

## 9. Documentation Domain (DO) — Remediations

- [x] 9.1 OSPS-DO-03.01: Add `file_create` remediation for SUPPORT.md (already existed)
- [x] 9.2 OSPS-DO-04.01: Add `file_create` remediation for support scope documentation
- [x] 9.3 OSPS-DO-05.01: Add `file_create` remediation for end-of-support policy
- [x] 9.4 OSPS-DO-06.01: Add `file_create` remediation for dependency management (`docs/DEPENDENCIES.md`)

## 10. Validation

- [x] 10.1 Run `uv run ruff check .` — all linting passes
- [x] 10.2 Run `uv run pytest tests/ --ignore=tests/integration/ -q` — 847 passed, 1 skipped
- [x] 10.3 Run `uv run python scripts/validate_sync.py --verbose` — spec sync passes
- [x] 10.4 Automated remediation coverage: 32/62 controls (52%, up from ~22%). Remaining 11 controls without any remediation are hard-to-automate (license detection, encrypted distribution, design/API docs, security assessments)
