# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### Security

- Platform remediation reads the current settings first, changes only what a
  control requires, and never weakens a setting already in place (fewer
  required approvals, removed status checks or push restrictions, code-owner
  review or linear history turned off). If the settings cannot be read,
  nothing is written. Platform changes need a person's approval of the exact
  change by default, and the result is read back from the platform rather
  than taken from response text.
- A step whose `expr` cannot be evaluated (it does not compile, reads data
  that is missing, or is not boolean) is `ERROR`, class `evaluation`, never
  the handler's PASS or FAIL. Before, the handler's verdict stood: OpenSSF
  Baseline OSPS-BR-01.01 and OSPS-AC-04.02 passed when zizmor exited with an
  accepted code and printed no findings.
- Plugins cannot redefine a step type. A plugin registering a name that core
  or another plugin already registered (for example `manual` with a PASS
  ceiling) is refused, logged at WARNING naming both registrants, and listed
  by `darnit list` and in the warnings of an audit of that plugin's framework
  (or a framework composing it); the existing step type is unchanged.

### Removed

- Python helpers that read or wrote raw context values: `load_context`,
  `load_stored_context`, `flatten_user_context`, `get_context_value`,
  `get_raw_value`, `is_context_confirmed`, `save_context_value`, and
  `save_context_values` (`darnit.config.context_storage`), and
  `darnit.context.detectors.detect_ci`. Use
  `darnit.config.context_resolve.resolve_context` (read) and
  `darnit.config.context_writes` (write); `detect_ci_provider` is the one CI
  detector.

### Added

- Operator configuration: a user-level TOML file found the same way by the
  CLI, MCP server, and harness (`--operator-config PATH`, else
  `$XDG_CONFIG_HOME/darnit/config.toml` or `~/.config/darnit/config.toml`,
  else built-in defaults). It is the only source of tool settings: plugins,
  MCP servers, pass overrides, custom controls, stores, LLM settings, trusted
  repositories, CI trust rules, and policy. Unknown keys stop the run, a path
  inside the audited repository is refused, and a file writable by others is
  refused under `--strict-operator-config` (on by default in recognized CI).
  Reports record its source and digest.
- `darnit config show` (resolved operator configuration, digest, permission
  check, and redacted settings), `darnit config trust add|list|remove`
  (edits `[trust].repos`), and `darnit config migrate [REPO] [--force]`
  (writes `.baseline.toml` claims to `.project/darnit.yaml` and prints a
  proposed operator configuration fragment; it never writes operator
  configuration).
- CI trust decisions: in CI a repository is trusted only under the opt-in
  `push-default-branch` rule (GitHub Actions, GitLab CI); pull requests,
  merge requests, and unrecognized CI are untrusted. Locally, `--repo
  HOST/NAMESPACE/NAME` (or an MCP tool's `owner`/`repo`) names the audited
  repository; a checkout's own remotes are never trusted. Reports record the
  decision, its reason, and the CI facts used.
- Assertion outcomes for not-applicable claims from `.project/darnit.yaml`
  (with optional `asserted_by`) and from `.project/` context values that make
  a control not applicable: each claimed control reports `honored`,
  `pending`, or `contradicted`. Operators can confirm a pending claim with
  `confirm_project_data` (`confirm_not_applicable`); confirmations are stored
  operator-side and lapse on expiry or when the claim or its evidence
  changes. Framework controls can declare `contradicted_by` evidence.
- Per-step conclusions (feature 041). Each step type registers a ceiling of
  outcomes it may conclude for its control: `file_exists` and `regex` /
  `pattern` steps may conclude only FAIL, `exec`, `gh_api`, and
  `github_branch_protection` may conclude PASS or FAIL, and `llm_eval` and
  `manual` conclude nothing. A step outcome outside its effective set is
  evidence only and evaluation continues. New step fields in framework TOML:
  `existence` (presence or pattern step whose requirement is literally
  existence; allows PASS), `concludes` (narrows the ceiling), `fail_on_miss`
  (a pattern miss proves failure; otherwise a miss is inconclusive),
  `fail_on_status` (`gh_api` HTTP statuses that prove failure), and
  `promotion` (`{outcome = "pass", corpus, note}`, permission to conclude
  PASS beyond the ceiling, justified by a corpus measurement). A declaration
  that widens a ceiling without a promotion fails when controls load. Plugin
  handlers declare their ceiling at registration; one that declares none is
  evidence only.
- Result statuses `ERROR` and `PENDING`. `ERROR` is a broken measurement
  (platform authorization or rate-limit error, unavailable service, missing
  tool, evaluation error) and carries `error: {class, cause}`; it never
  concludes FAIL, and a later step that concludes still wins. `PENDING`
  carries `pending.kind`: `llm_judgment` (awaiting a model judgment) or
  `confirmation` (a PASS candidate awaiting an operator). Results also carry
  `concluded_by`, and `candidate` / `confirmation` blocks where they apply.
  Level compliance treats FAIL, WARN, ERROR, and PENDING, including a PASS
  candidate, as non-compliant in every driver, report, and attestation.
- `gh_api` step: a status-aware platform API check. Only statuses declared in
  `fail_on_status` prove failure; 401/403 are `ERROR` (`auth`), 429 or a
  rate-limit 403 is `ERROR` (`rate_limit`) even when declared, 5xx,
  transport failures, and undeclared statuses are `ERROR` (`unavailable`),
  and a missing `gh` is `ERROR` (`missing_tool`). Recorded responses let
  tests and the corpus run platform checks offline. A missing `exec` binary
  and a required MCP server that is missing or unusable are now `ERROR`
  instead of FAIL.
- PASS candidates from model judgments. A model judgment never concludes
  PASS. A positive judgment whose cited excerpts all appear verbatim in the
  content the step read becomes a PASS candidate (`PENDING`, kind
  `confirmation`), stored operator-side for an operator- or CI-named
  repository; it counts as non-compliant until the operator confirms it with
  the new `confirm_pass_candidate` MCP tool (every framework server; OpenSSF
  Baseline also accepts `confirm_project_data(confirm_pass_candidate=...)`).
  A confirmed candidate
  reports PASS with `authority: asserted`, `concluded_by: confirmation`, and
  the confirmer, time, and expiry, and lapses when the judged content or the
  control's rubric changes or the confirmation expires. A negative judgment
  is a suggestive FAIL (`concluded_by: llm_judgment`); a judgment citing text
  that is not there leaves the control WARN; a model-service failure is
  `ERROR`.
- `submit_judgment` MCP tool on every framework server: a coding agent
  submits a judgment for a `PENDING` (`llm_judgment`) control with verbatim
  excerpts; darnit re-gathers the evidence, verifies the excerpts, and
  returns a PASS candidate, a model finding, or a rejection naming the
  excerpts not found. The audit and comply skills use it and never state a
  verdict or confirm a candidate without the operator's instruction.
- Reports show an ERROR's class and cause, a PENDING result's kind, and a
  PASS candidate as "not compliant until confirmed" with its model and number
  of cited excerpts. The Baseline attestation predicate adds, within v1,
  `concluded_by`, `pending.kind`, `candidate` (with `confirmed`; a candidate
  keeps status `PENDING` and carries no verdict), `confirmation`, and
  `error: {class, cause}` per control, and `pending`, `pass_candidates`,
  `warnings`, and `errors` counts in the summary and per level.
- Adversarial fixture corpus under `tests/darnit_baseline/corpus/`: small
  repositories with per-control labels (placeholder docs and governance, a
  policy denying any process, a write-all workflow, an empty repository, a
  well-formed reference, and recorded platform scenarios). It measures every
  executed step per control and outcome, fails on any false PASS by a step
  allowed to conclude PASS, and reports promotion eligibility.
  `scripts/corpus_report.py` writes the report (Markdown or JSON); CI runs
  the gate and adds the report to the job summary. A new fixture needs only
  its files and a `labels.toml`.
- Context value standing (feature 042). Every context key resolves to one
  standing: `confirmed` (a person confirmed this exact value), `concluded`
  (an `auto_detect = true` key detected in this run; never persisted),
  `candidate` (a value with an origin that no person confirmed), or
  `unknown`. Only confirmed values and concluded values of `auto_detect =
  true` keys reach control applicability, compliance, remediation,
  attestations, and the harness; a candidate is shown labelled with its
  origin and never consumed.
- Context confirmation records: who (`confirmed_by`), when
  (`confirmed_at`), the candidate value and origin it was based on
  (`basis`, absent when the person typed the value), `last_validated`, and
  an optional `expires_at`. A record applies only to the value it confirmed;
  a hand edit makes the key a candidate again. Records go in
  `.project/darnit.yaml` under `confirmations:` when the operator trusts the
  repository, otherwise in the operator-side store, and nothing is written
  into the repository. In-repository records count whether or not the
  operator trusts the repository. Context definitions accept
  `validity_days`; a confirmation lapses at the earliest of its `expires_at`
  and `last_validated + validity_days`, and operator expiry policy does not
  apply to it.
- `confirm_project_data(confirm_stored=[...], reject_stored=[...])`
  reviews stored values in one call: a rejected `.project/darnit.yaml` value
  is deleted, and a rejected `.project/project.yaml` value is reported with
  its file and field for the person to edit (the file is not changed).
  `get_pending_data` lists these values under `stored_unconfirmed` with
  their locations. `confirm_project_data` also accepts `expires_at`
  (`{key: date}`).
- Frameworks that define context keys but no `confirm_project_data` tool
  (for example Community Specification) get a framework-neutral
  `confirm_project_data` that records context values for that framework's
  keys.
- Remediation policy in operator configuration: `[remediation]` with
  `platform` and `high_impact`, each `prompt` (default; darnit asks and, on
  approval, makes the change), `manual` (darnit only reports the steps), or
  `auto` (darnit applies without asking, still reading first, changing only
  what is needed, and reading back). High-impact changes are repository
  visibility and organization-wide settings. The policy comes only from
  operator configuration, and every remediation report records it.
- `platform_setting` remediation handler: a control declares a requirement on
  a target (`branch_protection`, `repository`, `vulnerability_reporting`), not
  a payload. One platform engine reads the target, plans the minimal change
  without weakening anything, writes under the policy, and reads back. Branch
  protection uses the repository's default branch unless one is named, and a
  requirement already met by classic protection or an active ruleset writes
  nothing.
- Approval by digest. A preview returns a digest for every platform change
  set and plan item; `remediate_audit_findings` and
  `enable_branch_protection` take `approve` with the digests the person
  approved. A change set's digest is bound to the settings it was computed
  from, so a change in between writes nothing and needs a new preview. A batch approval
  never covers a high-impact change, and `dry_run=False` alone approves
  nothing. Remediations marked `safe = false` and steps that cannot be
  previewed exactly need their own approval under every policy.
- Run ids. Every apply records an operator-side run manifest of the files it
  wrote (never inside the checkout). `create_remediation_branch`,
  `commit_remediation_changes`, and `create_remediation_pr` take `run_id`
  (default: the repository's latest run), and every remediation commit
  carries a `Darnit-Remediation-Run: <run_id>` trailer.
- Remediation outcome kinds, one per control: `fixed`, `changed_not_passing`,
  `changed_not_verified`, `unchanged` (with the reason, for example
  `already_exists`), `needs_approval`, `needs_confirmation`, `manual`, and
  `error`. `fixed` requires that something changed and that a re-check of the
  control passes; the re-check does not replace the audit cache. Summaries
  and the commit and pull request steps are derived from these outcomes,
  never from words or symbols in report text. `remediate_audit_findings`
  returns the run as a fenced JSON block after its Markdown report.
- `project_reference` on a `file_create` remediation step names the
  `.project/` field that describes the created file. The reference is
  recorded only for a file created in this run and only into an empty field.
  It replaces the fixed control-to-field table, which recorded some files
  under unrelated fields (a bug report template as the security policy) and
  replaced existing references.
- Exec remediation steps declare `effects = "working_tree"` and `offline =
  true` to be previewed in a scratch copy of the working tree; other exec
  steps are labelled "cannot be previewed exactly".
- `expr_decides` step field: on a handler PASS the step's `expr` alone
  decides, true PASS and false FAIL, within the step's effective set. It is
  accepted only on `exec`, `regex`, and `pattern` steps that have an `expr`.
  The OpenSSF Baseline zizmor steps (OSPS-BR-01.01, OSPS-AC-04.02) set it, so
  a matching finding is FAIL.
- `evidence_fields` on `gh_api` steps: the response body keys kept in the
  step's evidence, and so in reports and attestations; `expr` still sees the
  full response. A step reading a person's account (`/user`, `/user/...`,
  `/users/...`) must declare it.
- Expressions on `exec`, `regex`, and `pattern` steps can read `project`
  (the usable project context values; reading an unconfirmed one is an
  evaluation error), and `file_exists(path)` answers for the audited
  repository (it always answered false). Each step type declares the names
  its expressions may use, and a reference to any other name fails loading.
- Step types declare the settings they read (`settings`) and the names their
  expressions may use (`expression_names`) when they register. A plugin step
  type that declares no settings loads with one warning per step type.

### Changed

- **BREAKING:** framework loading is strict. An unknown control key, a step
  key that is neither a common step field nor a setting its step type
  declares (a misspelled `fail_on_mis`, for example), an `expr` its step
  type cannot take, and a step naming a step type that is not registered
  fail loading, naming the framework file, control, step, and key. Before,
  they were ignored, or the step was skipped. A pass override or custom
  control in operator configuration that names the step type of a plugin
  that is not installed still loads, and the control is `ERROR`, class
  `missing_tool`.
- **BREAKING:** reproducibility controls no longer PASS from text or
  file-presence signals. The five reproducibility step types may conclude
  only FAIL; the signals they find are evidence for the control's later
  steps, so such a control ends WARN unless a person or a corpus-backed
  promotion concludes it. A workflow mentioning `cosign sign` in a comment
  no longer passes RE-02.02.
- **BREAKING:** an unreadable `requirements.txt`, or one whose include
  cannot be resolved, no longer fails RE-01.01: it shows nothing about
  pinning, so it decides nothing and another manifest may still fail the
  control. This supersedes feature 037 FR-007 for that case.
- OSPS-AC-01.01 keeps only `login` and `two_factor_authentication` from the
  auditor's `/user` record; email, location, company, and biography no
  longer appear in evidence, JSON output, or attestations.
- The `darnit-hello` and `darnit-example` file controls now FAIL when the
  file is missing: they named the unregistered `file_must_exist`, so the
  step was skipped and the control could never fail.
- A repository that builds with a Nix flake in CI and also fetches over the
  network in CI now FAILs RE-02.01. The Nix signal counts only when RE-01.02
  passed, and RE-01.02 no longer concludes PASS on its own, so the fetch is
  no longer outweighed.
- Per-control `status` and `reason` in a repository's `.baseline.toml`, ignored
  since 0.1.1, are read during the deprecation release as not-applicable
  claims under the trust rules: a claim counts only for a repository the
  operator trusts, or after the operator confirms it; otherwise the control
  is evaluated and counts as non-compliant. `darnit config migrate` moves
  them to `.project/darnit.yaml`.
- **BREAKING:** `PENDING_LLM` is removed; `PENDING` with
  `pending.kind = "llm_judgment"` replaces it in every output, including MCP
  tool results and JSON reports.
- **BREAKING:** the ActionPlan audit step (`submit_action_result`) no longer
  accepts client-supplied per-control results; the engine records only
  results it produced. MCP clients submit an empty result for the audit step
  and send judgments through `submit_judgment`.
- **BREAKING:** OpenSSF Baseline results change. The controls are
  re-declared under the per-step rules: many controls no longer PASS from a
  file-presence or keyword step and now end WARN or `PENDING`; pattern misses
  are inconclusive instead of FAIL; platform checks use `gh_api`, so token
  and rate-limit problems are `ERROR` instead of FAIL; settings that do not
  measure a requirement (`allow_forking`, `has_issues`, `html_url`) no longer
  conclude PASS; 21 content controls gain an `llm_eval` step. Only license
  presence (LE-03.01), QA-02.01, QA-05.01, and QA-05.02 keep existence steps
  that conclude PASS. The corpus reports zero false PASS.
- **BREAKING:** a context value stored in `.project/` without a matching
  confirmation record, including every value written by an earlier darnit
  version, is a candidate (origin `stored_unconfirmed`) and is no longer
  used. Review them with `confirm_project_data(confirm_stored=[...],
  reject_stored=[...])`.
- **BREAKING:** `confirm_project_data` requires `owner` and `repo` for
  context values (they decide where the record is written) and accepts a
  detected candidate only by digest (`accept_candidates={key: digest}`);
  detection runs again and a digest that no longer matches is refused. Its
  per-key parameters are generated from the server's own framework
  definitions (the Baseline server gains `platform`), and enum parameters
  accept only the key's `values`.
- **BREAKING:** `remediate_community_spec` judgment parameters
  (`code_license`, `governance_mode`, `coc_policy`, `scope`, `coc_contacts`,
  and the other `csl_*` values) no longer default (the code license used to
  default to MIT). An omitted parameter is taken from confirmed context
  only; otherwise the tool writes nothing and reports `confirmation
  required: <key>`.
- **BREAKING:** answers a coding agent submits to an ActionPlan
  `collect_context` step over MCP are used for that run only and are no
  longer saved. Answers a person types into `darnit run` are recorded as
  confirmations.
- **BREAKING:** OpenSSF Baseline `maintainers` and `security_contact` are
  user-judgment keys (`auto_detect = false`): detection only proposes a
  candidate, and they require a person's confirmation. A remediation
  template or `when` clause that reads a context key without a usable value
  stops that control with `confirmation required: <key>` and writes
  nothing, whether or not the control lists the key in `requires_context`
  and whatever `default()` the template uses.
- **BREAKING:** `enable_branch_protection` previews by default
  (`dry_run=True`); applying needs `dry_run=False` and, under the default
  policy, the change set's digest in `approve`. Its branch defaults to the
  repository's default branch (was `main`). Its parameters only tighten
  protection; existing settings are never lowered or removed.
- **BREAKING:** the `api_call` remediation handler is removed, with its
  full-object payload templates. A framework TOML that declares it fails to
  load, naming `platform_setting`.
- **BREAKING:** the remediation properties `requires_confirmation`,
  `dry_run_supported`, and `dry_run_command` are removed; a framework TOML
  that declares one fails to load, naming the replacement (`safe = false`,
  or plan mode with exec `effects`/`offline`). A remediation's preview now
  runs the same handler logic as the apply against the current state and
  writes nothing; it no longer lists the handlers that would be called.
- **BREAKING:** `commit_remediation_changes` stages only the files the
  remediation run wrote, and only while they are unchanged since; ignored
  files are never staged. `add_all` is removed. Remediation never writes a
  file with uncommitted user changes (the preview reports it as
  `user_changes_present`), and `create_remediation_branch` never stashes and
  refuses a detached HEAD, a merge or rebase in progress, or an existing
  branch holding commits without the run trailer. `create_remediation_pr`
  pushes only the remediation branch.
- **BREAKING:** the OpenSSF Baseline OSPS-AC-01.01 (organization two-factor
  authentication, which has no API) and OSPS-LE-01.01 (contributor sign-off,
  DCO or CLA) remediations are manual steps; the OSPS-AC-02.01 remediation,
  which enabled forking, is removed and its manual check steps are the
  guidance. OSPS-LE-01.01 no longer creates or replaces a LICENSE file.
- **BREAKING:** OpenSSF Baseline OSPS-LE-02.01 and OSPS-LE-03.01 create a
  LICENSE only for a confirmed `license_type` (`mit`, `apache-2.0`,
  `bsd-3-clause`, or `other` for manual steps), a new user-judgment context
  key; MIT is no longer a default, and an existing license file is never
  replaced.
- **BREAKING:** `remediate_community_spec` previews by default
  (`dry_run=True`); its README edit appears in the preview and the run
  manifest. CSL-02.01 and CSL-03.01 replace an existing scope or notices
  document, so they are `safe = false` and are written only when the person
  approves the previewed content (`approve=[digest]`).
- **BREAKING:** `darnit run` previews remediation by default and writes files
  or platform settings only with `--apply`. Items that need individual
  approval are asked for on the terminal by digest, and otherwise end as
  `needs_approval`.
- `create_security_policy` writes through the remediation executor and the
  run manifest, never replaces an existing SECURITY.md, and reports the
  control's outcome.
- If the check for unconfirmed project context cannot complete, remediation
  does not run and the error is returned (it used to proceed).
- Reads never write. Audits (every driver), `get_pending_data`, report
  generation, `remediate_audit_findings` in dry run, and the harness collect
  phase no longer create or modify files in the audited repository; the
  write of high-confidence detections from pending-data listing is removed.
  A control's `on_pass` project update (explicit or auto-derived) is no
  longer applied during an audit and is reported as evidence
  `proposed_project_update`. `init_project_config` no longer seeds detected
  values; over MCP it only creates an empty `.project/darnit.yaml` when
  `.project/` is absent.
- `get_pending_data` questions carry a detected value only as a labelled
  `candidate` (`value`, `origin`, `digest`, `label`); command templates and
  answer mappings hold placeholders only. Enum questions list every allowed
  value (no longer truncated to four), and configuration `examples` appear
  only as `format_hint`, never as answer options. Remediation prompts follow
  the same rules.
- A detection step that errored or could not decide produces no value;
  `value_if_fail` applies only to a completed negative answer. A failing
  `gh release list` leaves `has_releases` unknown instead of storing
  `false`, so release-gated controls stay applicable.
- Each context key has one canonical name and vocabulary. The CI provider is
  read and written as `github`, `gitlab`, `azure`, or `other`; stored legacy
  spellings are read canonically (`github_actions` -> `github`, `unknown`
  -> no value).
- darnit writes context values only to `.project/darnit.yaml`, keeps
  comments and sections it does not change, and patches only targeted
  fields when a remediation updates `.project/project.yaml`. It no longer
  replaces an invalid `.project/project.yaml` with a scaffold: when either
  `.project/` file is present but invalid, writes are refused with the
  validation errors, and audit reports list them as warnings.
- `.baseline.toml` is deprecated. In this release darnit reads its
  per-control `status`/`reason` as not-applicable claims under the same rules
  as `.project/` claims, still honors `extends` naming a registered framework,
  ignores its tool settings (see Security above), and warns once per setting
  in the file with the setting's new home. A later release will ignore the
  file with a notice. `darnit init` no longer creates `.baseline.toml`; it
  explains `.project/` claims and operator configuration.
- A not-applicable claim makes a control `N/A` (excluded from the level's
  denominator) only when it is honored: the repository is trusted, an
  explicit claim gives a reason, and no declared evidence contradicts it, or
  an operator confirmed it. Pending claims count as non-compliant and
  contradicted claims have no effect. Remediation skips only honored claims.
- Attestation level compliance uses the same rule as audit reports: WARN,
  ERROR, PENDING, and pending claims are non-compliant. Assertion-backed
  `N/A` results carry `authority: asserted` and `asserted_by`.
- `darnit install --project` warns that a repository-scoped registration lets
  the repository control how darnit is launched; user scope remains the
  default.
- The built-in audit tool's JSON output is now an object (`metadata`,
  `operator_config`, `trust`, `ignored_repository_settings`,
  `unknown_assertions`, `summary`, `results`, and `warnings` when present)
  instead of a bare list of results.

### Fixed

- The `darnit-hello` and `darnit-example` templates and the documentation
  use the registered `file_exists` step type instead of `file_must_exist`
  (#501).
- The OpenSSF Baseline OSPS-LE-02.01 regex step runs: it set `patterns`
  where the handler read `pattern`, so it recorded "Missing pattern" instead
  of the SPDX evidence. The control's outcome is unchanged.

## [0.1.1] - 2026-10-03

### Security

- A repository's own `.baseline.toml` is now treated as untrusted input. By
  default only `version`, `settings`, and `extends` naming a registered
  framework are honored; everything else is ignored with a warning: settings
  that could change what darnit executes or trusts (control `passes`,
  `check`, `remediation`, and `config` overrides, custom controls,
  `control_groups`, `adapters`, `mcp_servers`, `stores`, plugin trust
  settings, and `extends` file paths) and per-control `status`/`reason`
  exclusions, which would let the audited party remove controls from its own
  compliance result. These settings are moving to operator
  configuration that lives outside the audited repository.
  See GHSA-96qw-w4fw-5hcm.

### Removed

- Top-level `openspec/` directory. The 25 architectural specs that lived under
  `openspec/specs/<topic>/spec.md` were rehomed; the 12 archived proposals
  under `openspec/changes/archive/` were dropped (history preserved in `git log`).
- `scripts/generate_docs.py` and the `docs/generated/` output directory.
- The `doc-generation` job in `.github/workflows/ci.yml` and the
  "Generated docs are up to date" step in `.github/workflows/release.yml`.
- The "Generated docs" gate (item 4) from the Development Workflow in the
  project constitution.
- Pre-commit hook patterns referencing the openspec path.

### Added

- `docs/architecture/` directory containing the 25 rehomed architectural reference
  specs (including the authoritative `framework-design.md`), plus a one-screen
  `README.md` index. These are static reference documentation, not in-flight
  feature specs (those live in `specs/`).
- `specs/017-org-wide-audit-pipeline/` containing the previously in-flight
  openspec proposal, migrated to the speckit spec/plan/tasks layout, with the
  two openspec spec-delta files preserved under `specs/017-org-wide-audit-pipeline/deltas/`.
- This `CHANGELOG.md` file.

### Changed

- The authoritative location of the framework-design specification has moved
  from `openspec/specs/framework-design/spec.md` to
  `docs/architecture/framework-design.md`. The project constitution,
  PR template, `.pre-commit-config.yaml`, `scripts/validate_sync.py`, and
  every reference in `ARCHITECTURE.md`, `CLAUDE.md`, the `docs/` tree, and
  `packaging/README.md` are updated accordingly.
- `scripts/validate_sync.py` was trimmed: the two openspec-dependent checks
  ("Spec Exists" and "Docs Freshness") were removed; the three
  openspec-independent checks (TOML Schema, Pass Types Sync against
  `docs/architecture/framework-design.md`, SARIF Source) are retained.
- The project constitution is bumped to v1.2.0 with a Sync Impact Report
  block documenting the Workflow gate changes and the spec relocation.
- The `_PRUNE_DIRS` set in `packages/darnit-baseline/src/darnit_baseline/remediation/scanner.py`
  no longer lists `"openspec"`.

> **For downstream integrators:** Any tooling that referenced `openspec/...`
> paths will need to update. The constitution's "spec sync" Workflow gate
> continues to apply but is now scoped to TOML schema, handler-name registry,
> and SARIF-from-TOML invariants only -- the openspec-specific "Spec Exists"
> and "Docs Freshness" checks have been removed. See the feature documents
> under `specs/016-openspec-migration/` for the full migration record.
