# Phase 0 Research: Candidate Integrity for Project Values

Decisions, rationale, and alternatives. Codebase references are to the `042-candidate-integrity` branch (stacked on features 040 and 041).

## Current state (measured)

- `get_pending_context` (`config/context_storage.py:541-693`) auto-accepts any detection with confidence >= `auto_accept_confidence` (0.8) and calls `save_context_value(..., source=AUTO_DETECTED)`. It is called from the audit report's next-steps section (`tools/audit.py:1665`), `get_pending_data` (`darnit_baseline/tools.py:755`), the `remediate_audit_findings` guard before its dry-run branch (`tools.py:1318`), and the harness collect phase (`harness/driver.py:521`). Every one of those is a read path.
- `save_context_value` stores the 11 typed `ProjectContext` fields as bare primitives (`context_storage.py:404-409`); `_parse_context_value` wraps any bare value as `USER_CONFIRMED` at confidence 1.0 (`:45-62`). Provenance survives only for dynamic keys (for example the CSL `csl_*` keys).
- `_run_detect_pipeline` (`:747-892`) applies `value_if_fail` on FAIL, INCONCLUSIVE, or ERROR in its default mode, with confidence 0.8, which meets the threshold. Feature 040 added a `strict=True` mode used only by `observe_context_evidence`.
- `confirm_project_data_impl` (`server/tools/project_data.py:26-253`) writes bare typed fields with no record of who confirmed, and both it and `save_context_value` do `load_project_config() or init_project_config()`, so an invalid `project.yaml` is replaced by a scaffold (`loader.py:145-190`). `init_project_config` seeds `ci_provider` from `detect_ci` (`github_actions`, `gitlab_ci`, ...), a vocabulary no control condition uses.
- Prompt builders embed candidates in executable calls: `_build_context_question` (`darnit_baseline/tools.py:915-922`), `answer_mapping.value_map["Yes"]` (`:815-833`), `_format_preflight_prompt` (`remediation/orchestrator.py:787-813`), and `context_validator.format_context_prompt` (`remediation/context_validator.py:284-286`, which embeds `examples[0]`). `_build_ask_user_params` truncates enums to 4 options and turns free-text `examples` into options (`tools.py:1002-1042`).
- Consumers never consult provenance: audit applicability (`tools/audit.py:306-363`), the remediation template context (`remediation/orchestrator.py:425-560`, `remediation/executor.py:175-234`), and `ProjectYamlAnswerSource` (`harness/answer_sources.py:109-157`). `context_validator` checks `source == AUTO_DETECTED`, which the typed-field collapse defeats.
- `remediate_community_spec` defaults `code_license="MIT"`, `governance_mode="csl"`, `coc_policy="csl"` (`darnit_csl/mcp_tools.py:60-71`).
- Explicit write paths that remain legitimate: `confirm_project_data`, the CLI `darnit run` collect step (`agent/graph.py:156`), and ActionPlan `collect_context` answers submitted over MCP (`server/tools/harness_loop.py:146`).

## R1. Reads have no side effects

- **Decision**: `get_pending_context` becomes a pure function returning pending requests with candidates; it never writes. The auto-accept branch is removed from it. Concluded values for keys that do not require judgment are computed per run (R2) and held in memory, never persisted by a read. `remediate_audit_findings` (any mode), the audit report, `get_pending_data`, and harness collect call only read functions. A single writer module (`config/context_writes.py`) is the only code that writes project context, and it is called only from explicit confirmation paths and applied remediation.
- **Rationale**: FR-001/FR-002. One writer makes "who can write" auditable and testable (a test asserts no other module imports the YAML writers for `.project/`).
- **Alternatives**: keep auto-accept but write provenance (still writes on read; still persists guesses as data); gate auto-accept behind a flag (the flag is the bug surface).

## R2. Standing of every value: confirmed, candidate, concluded

- **Decision**: One resolver, `resolve_context(local_path, definitions, *, target, operator) -> ResolvedContext`, returns, per key, a `ResolvedValue` with `standing` in {`confirmed`, `candidate`, `concluded`, `unknown`}, the value (if any), origin, and (for confirmed) the confirmation record. `ResolvedContext.usable()` returns a mapping of only confirmed values plus concluded values of keys that do not require judgment. Consumers (audit applicability, remediation template context and `when`, harness answer source, context validator, attestation) take `ResolvedContext` or its `usable()` mapping and nothing else. This is the typed model #358 proposes; bare dicts from storage are no longer passed to consumers.
- A key requires judgment when its definition has `auto_detect = false`. `concluded` is possible only for `auto_detect = true` keys whose detection ran to completion (R8) with confidence >= `auto_accept_confidence`.
- **Rationale**: FR-003 to FR-006; Principle IV ("a stored candidate MUST remain distinguishable from a confirmed value on every later read"). A single choke point replaces per-consumer checks that drifted.
- **Alternatives**: add a `source` check in each consumer (the status quo pattern, which already failed); separate pydantic generics `ConfirmedValue[T]`/`CandidateValue[T]` for every field (heavier; the standing enum on one model gives the same guarantee at the `usable()` boundary).

## R3. Where confirmations live (clarification 2 and 3)

- **Decision**:
  - The value stays where it is stored today (typed and dynamic keys in `.project/darnit.yaml` `context:`; `security_contact` may also come from `project.yaml` `security.contact`). darnit writes confirmed values only to `.project/darnit.yaml`.
  - A confirmation record is stored in `.project/darnit.yaml` under a new top-level `confirmations:` map when the target repository is trusted by the operator (feature 040 `decide_trust(...).trusted`). Otherwise it is stored operator-side in the feature 040 store (`trust/confirmations.py`), claim `context_value`, `control_id` = the context key, `evidence_digest` = the value digest, and nothing is written to the repository. An untrusted target requires a trusted-eligible identity (operator-named or CI), the same rule as 040 claims.
  - A value is confirmed if an in-repository record or (for this operator) an operator-side record matches the current value digest and has not lapsed. In-repository records count whether or not the operator trusts the repository (clarification: operators run darnit against trusted repositories).
- **Value digest**: `sha256:` over the canonical JSON of the normalized value (R9), so reordering a list does not change it but any content change does.
- **Rationale**: FR-009, FR-011, FR-012; matches the 040 split (repository data in `.project/`, operator decisions operator-side).
- **Alternatives**: records beside each value inline in `context:` (breaks the typed-field shape and mixes data with metadata); records only operator-side (teammates and CI never see confirmations).

## R4. Expiry (clarification 2)

- **Decision**: Each record has `last_validated` (set on confirm and re-confirm) and optional `expires_at`. Framework TOML gains an optional per-key `validity_days` on `[context.<key>]`. A record lapses at the earliest of `expires_at` and `last_validated + validity_days`; with neither, it never lapses. Operator-side context records set `expires_at` only from those two sources; the operator policy `confirmation_expiry_days` (used for 040 claims and 041 PASS candidates) does not apply to context confirmations. `record_confirmation` gains an explicit `expires_at` parameter so the context path does not inherit the operator policy.
- A project may set `expires_at` in its own in-repository records by hand; darnit preserves it on re-confirmation unless the person supplies a new one.
- **Rationale**: FR-022; a repository reads the same for every operator.

## R5. Values without a record (clarification 1)

- **Decision**: Any stored value of any context key with no matching record loads as `candidate`, origin `stored_unconfirmed` (with its file and field). For keys that do not require judgment, a fresh per-run detection that concludes (R2) is used instead; if none concludes, the key is `unknown`. This also neutralizes values that earlier versions stored from failed detection (for example `has_releases: false` from a `gh` error, #470).
- **Review**: `get_pending_data` returns a `stored_unconfirmed` list (key, value, file, field). `confirm_project_data` gains `confirm_stored=[keys]` and `reject_stored=[keys]`: confirming records a confirmation for the current stored value (basis origin `stored_unconfirmed`); rejecting deletes the value from `.project/darnit.yaml`, and for a value in `project.yaml` returns the exact file and field for the person to edit, changing nothing (clarification 3).
- **Rationale**: FR-010; one action repairs a repository written by earlier versions.
- **Alternatives**: migrate by treating stored values as confirmed once (keeps every past guess); per-key prompts only (dozens of calls for existing repositories).

## R6. Accepting a candidate without echoing it

- **Decision**: Questions carry the candidate as data: `candidate: {value, origin, digest}`, labelled unconfirmed. `confirm_project_data` gains `accept_candidates={key: candidate_digest}`: the server re-runs detection, confirms the candidate only if its digest still matches, and records the basis (candidate value and origin). Command templates (`command_template`, preflight prompts, context-validator prompts) contain only placeholders (`<your answer>`), never a detected value or a configuration example. `answer_mapping.value_map["Yes"]` becomes the `accept_candidates` form with the digest, not the value.
- **Rationale**: FR-013 and User Story 3 scenario 4 (a yes records acceptance of that specific candidate); an agent never types a guessed value into an executable call.
- **Alternatives**: keep value-embedding and add a warning (agents execute regardless); require the person to retype the value (error-prone for lists).

## R7. Enum reachability and examples

- **Decision**: `_build_ask_user_params` stops truncating: when an enum has more than the selector's option limit (4), it returns no options and a question whose text lists every allowed value, with `allowed_values` in the payload; answers are validated against the enum. Configuration `examples` are shown only as format hints, never as options. `confirm_project_data` gains parameters for every context key the framework defines (including `platform` and the CSL keys), generated from the framework's context definitions rather than a fixed list.
- **Rationale**: FR-014, FR-015; the fixed parameter list already drifted (`platform`, `csl_*` missing).

## R8. Detection failures

- **Decision**: `_run_detect_pipeline` keeps only the strict semantics from feature 040: `value_if_fail` applies only when the handler concluded negatively and no earlier handler was incomplete; ERROR and INCONCLUSIVE yield no value. The non-strict mode is removed. Release status additionally requires a successful platform answer to conclude `false` (a `gh` error is ERROR).
- **Rationale**: FR-016, FR-017; one semantics, already implemented and tested for 040.

## R9. One name and vocabulary per key

- **Decision**: The framework TOML definition is the vocabulary. A single normalizer (`config/context_keys.py`) maps legacy storage (`ci.provider`, bare `provider`) to `ci_provider` and legacy values (`github_actions` -> `github`, `gitlab_ci` -> `gitlab`, `azure_pipelines` -> `azure`, `bitbucket_pipelines` -> `other`, `unknown` -> no value) on read; darnit writes only canonical names and values. `detectors.detect_ci` is removed in favour of `detect_ci_provider`; `init_project_config` no longer seeds detected values. `collect_auto_context` and the remediation orchestrator read through the resolver, so they see canonical names.
- **Rationale**: FR-018 (#476).

## R10. Never destroy a user-authored file

- **Decision**: `load_project_config` returns a tri-state result (absent, valid config, invalid with errors) through a new `load_project_config_checked`; the old function stays as a thin wrapper for read-only callers. Every writer refuses when the result is invalid and reports the errors. Writes to `project.yaml` (only applied remediation such as `apply_project_update` writes there) go through `ruamel.yaml` round-trip (already a darnit-core dependency) and change only the targeted fields, preserving comments, order, and unknown fields. Writes to `.project/darnit.yaml` also use round-trip and preserve sections darnit does not change (notably feature 040 `controls:` claims). An unparseable `darnit.yaml` blocks writes instead of being skipped and rewritten.
- **Rationale**: FR-019 to FR-021 (#463).
- **Alternatives**: continue whole-file rewrites through pydantic dumps (loses comments and unknown fields).

## R11. Remediation uses only usable values

- **Decision**: The template context exposes `context` as a guarded mapping built from `ResolvedContext`: reading a key whose standing is not usable raises `ConfirmationRequired(key)`, which the executor turns into a "confirmation required" result naming the key, regardless of `requires_context`. Template `default()` filters therefore never paper over an unconfirmed key. Remediation `when` clauses evaluate against `usable()`. MCP remediation tools stop defaulting judgment parameters: `remediate_community_spec` parameters that map to CSL context keys default to None and fall back to confirmed context only.
- **Rationale**: FR-007, FR-008 (#465).
- **Alternatives**: parse templates for `context.*` references (misses computed access; the guarded mapping catches every access).

## R12. Harness and ActionPlan

- **Decision**: `ProjectYamlAnswerSource` supplies only `usable()` values. Harness collect never persists (answers from `--answers` or interactive resolvers stay in-run, as feature 027 `asserted` answers). ActionPlan `collect_context` answers submitted over MCP and CLI `darnit run` answers are persisted only through the R1 writer as confirmations (confirmed_by = operator identity, basis origin `answer`), with the same trust-based location as R3.
- **Rationale**: FR-001, FR-002; edge case on harness answers.

## R13. Framework configuration changes

- **Decision**: OpenSSF Baseline sets `auto_detect = false` on `maintainers` and `security_contact` (keeping `allow_sieve_hints = true` and `hint_sources`). `validity_days` is added to the context definition schema. `framework-design.md` is updated first (context standing, confirmations, `validity_days`, the review parameters).
- **Rationale**: FR-005, Principle IV, spec-first rule.

## R14. Out of scope, noted

- `predicate.py:147` reads `project_config.project_type`, which `ProjectConfig` does not define (latent error when a config is passed); separate issue.
- CSL `coc_policy='org'` in tool descriptions versus the enum `[csl, umbrella]`; separate issue.
- `audit_openssf_baseline(auto_init_config=...)` and `get_pending_context(level=...)` are unused parameters; removed only where this feature touches the signature.
