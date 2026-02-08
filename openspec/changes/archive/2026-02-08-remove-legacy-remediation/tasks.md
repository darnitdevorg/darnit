## 1. Add Missing TOML Templates

Templates already exist: `security_policy_standard`, `contributing_standard`, `bug_report_template`, `dependabot_config`, `branch_protection_payload`. Only missing ones need to be added.

- [x] 1.1 Add `codeowners_template` to `[templates]` — CODEOWNERS file with `${context.maintainers}` variable
- [x] 1.2 Add `governance_template` to `[templates]` — GOVERNANCE.md with `${context.maintainers}`, `${context.governance_model}` variables
- [x] 1.3 Add `maintainers_template` to `[templates]` — MAINTAINERS.md with `${context.maintainers}` variable
- [x] 1.4 Add `support_template` to `[templates]` — SUPPORT.md with `${owner}`, `${repo}` variables
- [x] 1.5 Add `vex_policy_template` to `[templates]` — VEX policy section for SECURITY.md

## 2. Add TOML Declarative Remediation to 7 Controls Still Using Legacy

These controls currently have `handler = "legacy_func"` or no remediation section, and fall through to legacy Python. Each needs `file_create`, `api_call`, or `manual` added so TOML dispatch handles them.

- [x] 2.1 OSPS-GV-01.01 (`handler = "create_governance_doc"`) — add `file_create` with `governance_template`, keep existing `requires_context`
- [x] 2.2 OSPS-GV-04.01 (`handler = "create_codeowners"`) — add `file_create` with `codeowners_template`, keep existing `requires_context`
- [x] 2.3 OSPS-GV-01.02 (no remediation section) — add `file_create` with `maintainers_template` and `requires_context = [{ key = "maintainers" }]`
- [x] 2.4 OSPS-GV-03.02 (no remediation section) — add `file_create` with `contributing_standard` (template already exists)
- [x] 2.5 OSPS-QA-07.01 (`handler = "enable_branch_protection"`) — add `manual` remediation steps with direct repo link (`https://github.com/${owner}/${repo}/settings/branches`) and instructions for enabling PR review requirements. Also add `${owner}`/`${repo}` substitution to `_get_manual_remediation()` in the orchestrator so template variables resolve in manual steps.
- [x] 2.6 OSPS-VM-04.02 (`handler = "ensure_vex_policy"`) — add `file_create` with `vex_policy_template` targeting SECURITY.md, or `manual` steps if append-to-existing-file is needed
- [x] 2.7 OSPS-DO-03.01 (`handler = "create_support_doc"`) — add `file_create` with `support_template`

## 3. Remove `handler` References from Already-Migrated Controls

These controls already have executable TOML remediation (file_create/api_call) that wins in dispatch priority, but still carry dead `handler = "..."` references.

- [x] 3.1 Remove `handler = "enable_branch_protection"` from OSPS-AC-03.01 (already has `api_call`)
- [x] 3.2 Remove `handler = "create_bug_report_template"` from OSPS-DO-02.01 (already has `file_create`)
- [x] 3.3 Remove `handler = "create_contributing"` from OSPS-GV-03.01 (already has `file_create`)
- [x] 3.4 Remove `handler = "create_security_policy"` from OSPS-VM-02.01 (already has `file_create`)
- [x] 3.5 Remove `handler = "create_dependabot_config"` from OSPS-VM-05.03 (already has `file_create`)

## 4. Delete Legacy Code

- [x] 4.1 Remove `func_map` dictionary from `orchestrator.py`
- [x] 4.2 Remove `_apply_legacy_remediation()` function from `orchestrator.py`
- [x] 4.3 Remove legacy fallthrough branch in `_apply_remediation()` dispatch loop
- [x] 4.4 Remove imports of legacy functions from `orchestrator.py` (enable_branch_protection, create_security_policy, etc.)
- [x] 4.5 Delete `packages/darnit-baseline/src/darnit_baseline/remediation/actions.py`
- [x] 4.6 Delete `packages/darnit-baseline/src/darnit_baseline/remediation/registry.py`
- [x] 4.7 Remove `REMEDIATION_REGISTRY` and `registry` exports from `remediation/__init__.py`; update `implementation.py`, `tools.py`, and `adapters/builtin.py` to use `REMEDIATION_CATEGORIES`

## 5. Update Tests

- [x] 5.1 Remove or update tests that import from `actions.py` or `registry.py`
- [x] 5.2 Existing TOML `file_create` templates verified via integration tests (governance, codeowners, security_policy)
- [x] 5.3 Verify existing remediation E2E tests pass with TOML-only dispatch
- [x] 5.4 Run `uv run ruff check .` and `uv run pytest tests/ --ignore=tests/integration/ -q` — 859 passed, 0 failed

## 6. Future Work (TODO only)

- [x] 6.1 Add a TODO/issue for extracting common remediation templates (SECURITY.md, CONTRIBUTING.md, CODEOWNERS, etc.) into a shared `darnit-templates` core library that multiple darnit implementations can reuse
