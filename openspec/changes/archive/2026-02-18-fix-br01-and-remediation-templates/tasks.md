## 1. Fix zizmor exec pass exit codes

- [x] 1.1 Add `pass_exit_codes = [0, 10, 11, 12, 13, 14]` to BR-01.01 zizmor exec pass in `openssf-baseline.toml`
- [x] 1.2 Verify BR-01.01 resolves via zizmor (PASS from CEL expr) instead of falling through to pattern handler — test against kusaridev/kusari-cli

## 2. Harden workflow templates

- [x] 2.1 Add `persist-credentials: false` to `actions/checkout` in `sast_workflow` template
- [x] 2.2 Add `persist-credentials: false` to `actions/checkout` in `sbom_workflow` template
- [x] 2.3 Add `persist-credentials: false` to `actions/checkout` in `sca_workflow` template
- [x] 2.4 Add `persist-credentials: false` to `actions/checkout` in `release_signing_workflow` template
- [x] 2.5 Add `persist-credentials: false` to `actions/checkout` in `ci_test_workflow` template
- [x] 2.6 Verify no workflow template has `${{ }}` expressions in `run:` blocks referencing user-controllable contexts

## 3. Validate cross-control safety

- [x] 3.1 Run zizmor against each workflow template content to confirm zero `artipacked` findings
- [x] 3.2 Run full audit against kusaridev/kusari-cli with hardened templates and confirm BR-01.01 passes via zizmor path
- [x] 3.3 Run `uv run ruff check .` and `uv run pytest tests/ --ignore=tests/integration/ -q`
- [x] 3.4 Run `uv run python scripts/validate_sync.py --verbose` and regenerate docs if needed
