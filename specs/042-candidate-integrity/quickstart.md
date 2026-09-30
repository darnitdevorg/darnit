# Quickstart: Validating Candidate Integrity

Prerequisites: `uv sync`; features 040 and 041 in place; isolated operator configuration and data root (the test suite's shared fixtures provide them). Contract: [contracts/context-confirmation-tools.md](contracts/context-confirmation-tools.md). Entities: [data-model.md](data-model.md).

Scratch repositories used below (from the issue reproductions):

- `R-maint`: `MAINTAINERS.md` with `- Alice Example <alice@realcorp.io> @alice`, `SECURITY.md` with a contact, no `.project/`.
- `R-rel`: a repository whose origin publishes releases, with `GH_TOKEN=invalid`.
- `R-ci`: `.github/workflows/ci.yml`, no `.project/`.
- `R-hand`: a hand-written `.project/project.yaml` with a header comment, `social` as a list, and a `maturity_log` (fails darnit's schema).
- `R-legacy`: `.project/darnit.yaml` written by an earlier darnit version (bare `maintainers`, `has_releases: false`, `ci_provider: github_actions`).

## 1. Reads write nothing (User Story 1)

For each scratch repository: snapshot the tree, then run `audit_openssf_baseline`, `get_pending_data`, `remediate_audit_findings(dry_run=True)`, and a harness run with `MockLLMStep`. Expected: the tree is byte-identical; `maintainers` and `security_contact` are pending with candidates and origins.

## 2. Judgment keys are only proposed (User Story 2)

On `R-maint`, run an applied remediation for the governance category. Expected: `confirmation required: maintainers`; no CODEOWNERS written. Generate an attestation. Expected: no maintainers value in it. Call `remediate_community_spec` without `code_license`. Expected: `confirmation required: csl_code_license`.

## 3. Questions carry candidates as data (User Story 3)

On `R-maint`, a single-commit repository, and an empty repository, inspect `get_pending_data` and the remediation preflight. Expected: no command template contains a detected value or an example; `governance_model` and `ci_provider` list every allowed value. Answer "Yes" through `accept_candidates` with the returned digest. Expected: confirmed, record basis shows the candidate and its origin. Repeat after editing `MAINTAINERS.md`. Expected: digest mismatch, nothing written.

## 4. Confirmations are recorded (User Story 4)

1. Trusted target (`trust.repos` includes it): confirm `maintainers`. Expected: `.project/darnit.yaml` has `confirmations.maintainers` with confirmed_by, confirmed_at, last_validated, basis.
2. Untrusted target: confirm `maintainers`. Expected: nothing written to the repository; an operator-side record exists.
3. Edit the maintainers value by hand. Expected: candidate, origin `stored_unconfirmed`, `lapsed` shows the old record.
4. Set `validity_days = 1` for the key and move the clock two days. Expected: candidate, origin `expired_confirmation`.
5. On `R-legacy`: `get_pending_data` lists every value under `stored_unconfirmed`; `confirm_project_data(confirm_stored=[...], reject_stored=[...])` confirms and rejects them in one call; a rejected `project.yaml` value returns the field to edit and the file is unchanged.

## 5. Failed detection and canonical names (User Story 5)

- `R-rel` with a bad token: `has_releases` is `unknown`; release-gated controls match an audit where the key is simply unknown.
- `R-ci`: confirm `governance_model` only. Expected: stored CI provider (if any) is `github`; CI controls stay applicable.
- `R-legacy`: `ci_provider: github_actions` reads as `github`.

## 6. User-authored files survive (User Story 6)

On `R-hand`, run an audit and `confirm_project_data(governance_model="bdfl", ...)`. Expected: `project.yaml` byte-identical; the confirm call returns the validation errors and writes nothing. On a valid hand-written `project.yaml`, run an applied remediation that updates one field. Expected: comments, order, and other fields preserved.

## Checks

```
uv run pytest tests/ --ignore=tests/integration/ -q
uv run ruff check .
uv run python scripts/validate_sync.py --verbose
```

## Validation log

2026-09-29, branch `042-candidate-integrity` at 8433bac plus the Polish changes (T047-T052). Sections 1-6 were run in one process against scratch repositories built by `tests/darnit/context_integrity/conftest.py` (`R-maint`, `R-rel`, `R-ci`, `R-hand`, `R-legacy`, and an empty repository; origins `https://github.com/example-org/<name>`), calling the tool functions directly (`audit_openssf_baseline`, `get_pending_data`, `remediate_audit_findings`, the remediation orchestrator, `HarnessRun` with `MockLLMStep`, `confirm_project_data`, `generate_attestation`, `remediate_community_spec`). Operator configuration and the data root were scratch directories; trust lists named only the scratch identities. `gh` was a stub on `PATH`: failing (`false`) by default, with `GH_TOKEN=invalid`, and for one comparison a stub that answers `gh release list` with no releases and fails everything else. No network and no real organization's settings were used. Result: 36 of 36 checks passed.

1. Reads write nothing: PASS. For each of `R-maint`, `R-rel`, `R-ci`, `R-hand`, `R-legacy`, the tree (excluding `.git/`) was byte-identical after an audit, `get_pending_data(limit=0)`, `remediate_audit_findings(dry_run=True)`, an orchestrator dry run over all categories, and a harness run. On `R-maint`, `maintainers` and `security_contact` are pending with candidates, origin `sieve_hint` (`context_sieve (2 signals)`).
2. Judgment keys are only proposed: PASS. An applied governance remediation on `R-maint` is blocked by the preflight with `Context confirmation required: maintainers` (the candidate shown as data with its digest and placeholder-only commands); no CODEOWNERS written. An unsigned attestation carries no maintainers value (SECURITY.md text appears only as file-content evidence). `remediate_community_spec` without `code_license` returns `confirmation required: csl_code_license` and writes nothing.
3. Questions carry candidates as data: PASS. On `R-maint`, a single-commit repository (`R-rel`), and an empty repository, no command template or answer mapping contains a candidate value or a string example (boolean keys' `true`/`false` appear only as the mapping of the person's Yes/No); `governance_model` lists all 7 allowed values and `ci_provider` all 8. Accepting by digest (trusted target) records `basis.value` and `basis.origin` (`sieve_hint`). After editing `MAINTAINERS.md`, the old digest is refused (`digest mismatch`) and nothing is written.
4. Confirmations are recorded: PASS. (1) Trusted: `confirmations.maintainers` has `confirmed_by`, `confirmed_at`, `last_validated`, `value_digest` (no `basis` for a typed answer). (2) Untrusted: repository unchanged; a `context_value` record in the scratch data root's `trust/confirmations.json`. (3) Hand edit: candidate, origin `stored_unconfirmed`, `lapsed` holds the old record. (4) `validity_days = 1`: confirmed now, candidate with origin `expired_confirmation` two days later. (5) `R-legacy`, with `security.contact` added to its `project.yaml` so a project-file value exists: `stored_unconfirmed` lists `maintainers`, `has_releases`, `ci_provider` (in `darnit.yaml`) and `security_contact` (`project.yaml:security.contact`); one call confirmed `maintainers` and `ci_provider`, deleted `has_releases` from `darnit.yaml`, returned `edit required` for `project.yaml:security.contact` with the file unchanged, and kept the `controls:` claim.
5. Failed detection and canonical names: PASS. `R-rel` with a failing `gh`: `has_releases` is `unknown` and pending (control: an empty release list concludes `false`). The 9 release-gated controls have identical statuses in both cases and none is N/A. `R-ci`, confirming only `governance_model`: no CI provider is stored; BR-01.01, BR-01.02, AC-04.01, AC-04.02 stay applicable (WARN). `R-legacy`: `ci_provider: github_actions` reads as `github` (candidate).
6. User-authored files survive: PASS. `R-hand`: the audit and `confirm_project_data(governance_model="bdfl", ...)` leave the tree byte-identical; the confirmation is refused with the validation errors; the audit reports 2 warnings. A valid hand-written `project.yaml` with comments: an applied documentation remediation added only `documentation.readme.path` and `documentation.support.path`, keeping comments, order, and other fields.

Observed, not a failure: on `R-maint` the maintainers candidate is `["@realcorp", "@alice", "Alice Example"]`; the email domain in `alice@realcorp.io` is read as a handle. It stays a candidate that a person must accept or correct (tracked in #464).

Checks: `uv run ruff check .` clean; `uv run python scripts/validate_sync.py --verbose` passed (TOML schema, 66 controls; handler names; SARIF source; context keys); `uv run pytest tests/ --ignore=tests/integration/ -q -p no:randomly`: 4235 passed, 18 skipped, 1 failed (`tests/darnit/parity/tier1/test_no_product_changes.py`, which compares against the merge base and fails on any feature branch that changes product code; known local-only); corpus report gate PASS (0 false PASS, 11 fixtures, 89 labels).
