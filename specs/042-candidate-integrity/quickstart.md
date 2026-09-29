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
