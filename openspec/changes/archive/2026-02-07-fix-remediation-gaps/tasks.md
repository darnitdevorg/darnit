## 1. Framework: Manual Remediation Type

- [x] 1.1 Add `ManualRemediationConfig` model to `packages/darnit/src/darnit/config/framework_schema.py` with fields: `steps` (list[str]), `docs_url` (str | None), `context_hints` (list[str], default empty)
- [x] 1.2 Add `manual: Optional[ManualRemediationConfig]` field to `RemediationConfig` in `framework_schema.py`
- [x] 1.3 Add `manual` dispatch branch to `execute()` in `packages/darnit/src/darnit/remediation/executor.py` — after `api_call`, before `handler` fallback. Return `RemediationResult(success=True, remediation_type="manual", details={steps, docs_url, context_hints})`
- [x] 1.4 Write unit tests for manual remediation executor: basic dispatch, dry_run returns same result, context_hints in details, coexistence with automated types (automated wins)

## 2. Framework: Improve file_create Existing-File Messaging

- [x] 2.1 Change `_execute_file_create` in `executor.py` to return `success=True` with `remediation_type="file_create_skipped"` and message "File already exists — control may already be satisfied" when file exists and `overwrite=false`
- [x] 2.2 Update existing unit tests for file_create to expect `success=True` for the file-exists case
- [x] 2.3 Add test confirming overwrite=true still overwrites (unchanged behavior)

## 3. TOML: New Templates

- [x] 3.1 Add `[templates.readme_basic]` to `openssf-baseline.toml` — minimal README.md with `$REPO` name, description placeholder, install/usage/contributing/license sections as `<!-- TODO -->` stubs
- [x] 3.2 Add `[templates.license_mit]` to `openssf-baseline.toml` — standard MIT license text with `$YEAR` and `$OWNER` substitution
- [x] 3.3 Add `[templates.threat_model_basic]` to `openssf-baseline.toml` — minimal STRIDE-based template with sections for assets, threats, mitigations as `<!-- TODO -->` stubs
- [x] 3.4 Add `[templates.gitignore_secrets]` to `openssf-baseline.toml` — `.env`, `*.pem`, `*.key`, `*.p12`, `credentials.json`, `.secret*` patterns with comments

## 4. TOML: New file_create Remediation Blocks

- [x] 4.1 Add `[controls."OSPS-DO-01.01".remediation]` with `file_create` referencing `readme_basic` template, path `README.md`, and `project_update` setting `documentation.readme`
- [x] 4.2 Add `[controls."OSPS-LE-01.01".remediation]` with `file_create` referencing `license_mit` template, path `LICENSE`, and `project_update` setting `legal.license`
- [x] 4.3 Add `[controls."OSPS-SA-03.02".remediation]` with `file_create` referencing `threat_model_basic` template, path `THREAT_MODEL.md`, and `project_update` setting `security.threat_model`
- [x] 4.4 Add `[controls."OSPS-BR-07.01".remediation]` with `file_create` referencing `gitignore_secrets` template, path `.gitignore`

## 5. TOML: Status Checks api_call Remediation

- [x] 5.1 Add `[controls."OSPS-QA-03.01".remediation]` with `api_call` block targeting `/repos/$OWNER/$REPO/branches/$BRANCH/protection` to set required status checks, plus `requires_context` for `ci.required_checks`
- [x] 5.2 Add `[templates.status_checks_payload]` with the GitHub API payload structure referencing context-provided check names

## 6. Baseline: generate_threat_model File Writing

- [x] 6.1 Add `output_path: str | None = None` parameter to `generate_threat_model()` in `packages/darnit-baseline/src/darnit_baseline/tools.py`
- [x] 6.2 After content generation, if `output_path` is provided, write content to `os.path.join(local_path, output_path)` and return confirmation message
- [x] 6.3 Update `generate_threat_model` MCP tool schema in `openssf-baseline.toml` to include the `output_path` parameter description

## 7. TOML: Manual Remediation Blocks for Non-Automatable Controls

- [x] 7.1 Add `manual` remediation blocks for AC domain controls (MFA, workflow permissions) with steps explaining org-admin requirements and links to GitHub docs
- [x] 7.2 Add `manual` remediation blocks for BR domain controls (release signing, SBOM generation) with steps for toolchain setup and `context_hints` for future automation
- [x] 7.3 Add `manual` remediation blocks for QA domain controls (automated tests, subproject security) with project-specific guidance
- [x] 7.4 Add `manual` remediation blocks for VM domain controls (private reporting, security advisories) with GitHub security feature setup steps

## 8. Verification

- [x] 8.1 Run `uv run ruff check .` — all linting passes
- [x] 8.2 Run `uv run pytest tests/ --ignore=tests/integration/ -q` — all tests pass (800 passed, 1 skipped)
- [x] 8.3 Verified: 46/62 controls now have remediation blocks (74%, up from 19%); 31 manual remediation blocks added
