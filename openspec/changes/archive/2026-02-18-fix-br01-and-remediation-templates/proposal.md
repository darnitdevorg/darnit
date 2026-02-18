## Why

The remediation tool can worsen compliance scores: running `remediate_audit_findings()` against kusaridev/kusari-cli generated `sast.yml` for OSPS-VM-06.02, which caused BR-01.01 to report "3 of 3 pattern checks failed" instead of "2 of 2" — the tool's own output added a file that increased the failure count. While the core BR-01.01 checking logic is now correct (the universal CEL expr fix + zizmor integration work properly), the remediation templates need hardening so generated files don't introduce cross-control regressions.

## What Changes

- Audit all CI workflow templates for cross-control safety: verify that remediation-generated files don't trigger failures in other controls (e.g., templates should avoid `${{ }}` expressions in `run:` blocks that could trip BR-01.01)
- Add a "do no harm" spec requirement: remediation outputs for one control MUST NOT cause regressions in other controls
- Fix the zizmor exec pass to handle exit codes properly — zizmor returns exit code 14 for findings, but the pass doesn't declare `pass_exit_codes`, so it falls through as INCONCLUSIVE instead of being evaluated by the CEL expression

## Capabilities

### New Capabilities

(none)

### Modified Capabilities

- `ci-workflow-templates`: Add requirement that generated workflow files must not introduce failures for other controls (do-no-harm principle). Add requirement for zizmor pass exit code handling.

## Impact

- `packages/darnit-baseline/openssf-baseline.toml` — BR-01.01 zizmor pass needs `pass_exit_codes` and `fail_exit_codes`; workflow template content audit
- `openspec/specs/ci-workflow-templates/spec.md` — new "do no harm" requirement
