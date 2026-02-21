## 1. Framework Code Changes

- [ ] 1.1 Implement `files_to_include` resolution in `llm_eval_handler` (`builtin_handlers.py`): resolve `$FOUND_FILE` from gathered evidence, read file contents (10KB limit, max 5 files), include `file_contents` in consultation request
- [ ] 1.2 Add `llm_enhance` propagation in `RemediationExecutor._execute_handler_invocations` (`executor.py`): after successful `file_create`, copy `llm_enhance` prompt and file path to result details
- [ ] 1.3 Update `RemediationResult.to_markdown()` to display "AI Enhancement Available" sections when `llm_enhance` metadata is present in handler results

## 2. Strengthen Regex Passes (TOML)

- [ ] 2.1 OSPS-DO-01.01 (README): replace `(?i)^#` with multi-pattern requiring heading + 200 chars of content
- [ ] 2.2 OSPS-VM-02.01 (Security): replace `security|contact` with 3 patterns: reporting process, contact method, response timeline
- [ ] 2.3 OSPS-GV-01.01 (Governance): replace `maintainer|governance` with 3 patterns: named maintainer, decision process, CODEOWNERS syntax
- [ ] 2.4 OSPS-GV-03.01 (Contributing): replace `contribut|pull request` with 3 patterns: steps with PR, PR guidelines, how to contribute
- [ ] 2.5 OSPS-LE-01.01 (License): replace `permission|license` with 3 patterns: copyright+grant, SPDX identifier, known license header
- [ ] 2.6 OSPS-GV-04.01 (CODEOWNERS): add CODEOWNERS path assignment syntax pattern `^\S+\s+@\S+`
- [ ] 2.7 OSPS-BR-07.01 (Gitignore): add credential file patterns (credentials.json, .secret)
- [ ] 2.8 OSPS-DO-02.01 (Bug Reports): replace weak single pattern with template structure markers and YAML template detection

## 3. Add llm_eval Passes (TOML)

- [ ] 3.1 OSPS-DO-01.01: add `llm_eval` pass evaluating README quality (project explanation, install steps, usage examples)
- [ ] 3.2 OSPS-VM-02.01: add `llm_eval` pass evaluating security policy (actionable reporting, contact method, timeline)
- [ ] 3.3 OSPS-GV-01.01: add `llm_eval` pass evaluating governance (real roles, decision process, not boilerplate)
- [ ] 3.4 OSPS-SA-01.01: add `llm_eval` pass evaluating architecture doc (real components, actors, data flows)
- [ ] 3.5 OSPS-SA-02.01: add `llm_eval` pass evaluating API documentation (actual endpoints, parameters, usage examples)

## 4. Rewrite Templates and Add llm_enhance (TOML)

- [ ] 4.1 Rewrite `readme_basic` template: replace 5 TODO comments with substantive sections (description, install, usage, contributing, license)
- [ ] 4.2 Rewrite `threat_model_basic` template: replace 8 TODO placeholders with STRIDE table containing example threats and mitigations
- [ ] 4.3 Rewrite `architecture_template`: replace TBD placeholders with example components table, actors table, data flow description, security boundaries
- [ ] 4.4 Create `api_documentation_template` for SA-02.01 remediation with interface table, config table, usage examples
- [ ] 4.5 Add `llm_enhance` prompts to `file_create` remediation handlers for DO-01.01, VM-02.01, GV-01.01, SA-01.01, SA-02.01
- [ ] 4.6 Add remediation section for SA-02.01 (was missing) using new `api_documentation_template`

## 5. Spec and Documentation Updates

- [ ] 5.1 Update framework spec Section 3.5: document `$FOUND_FILE` resolution and `file_contents` inclusion in consultation request
- [ ] 5.2 Update framework spec Section 4.2: add `llm_enhance` field to FileCreateRemediation fields table and add scenario
- [ ] 5.3 Regenerate docs from spec (`scripts/generate_docs.py`) and commit any changes to `docs/generated/`

## 6. Verification

- [ ] 6.1 Validate TOML syntax parses without errors
- [ ] 6.2 Run `ruff check .` — all checks pass
- [ ] 6.3 Run `pytest tests/ --ignore=tests/integration/` — no regressions
- [ ] 6.4 Run `validate_sync.py --verbose` — spec-implementation sync passes
- [ ] 6.5 Verify llm_eval handler tests pass (`TestLlmEvalHandler`)
- [ ] 6.6 Verify remediation executor tests pass (86 tests)
