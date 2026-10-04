# Quickstart: Validating the Closed False-PASS Paths

**Feature**: 044-false-pass-paths | **Date**: 2026-10-04

Run these from the repository root after `uv sync`. Platform calls use `RecordedGhApi`, so none of these scenarios touch the network.

## V1. A failed expression is ERROR (US1, SC-001)

```bash
uv run pytest tests/darnit/sieve/test_expr_failure.py -v
```

**Shipped controls.** Use a zizmor stand-in on `PATH` that exits 0 and prints nothing.

| Control | Stand-in output | Expected |
|---|---|---|
| OSPS-BR-01.01, OSPS-AC-04.02 | Nothing | ERROR (`evaluation`), not PASS |
| Same | JSON with the control's finding (`template-injection`, `excessive-permissions`) | FAIL: the steps set `expr_decides` (FR-015); without it the step was INCONCLUSIVE and the control WARN |
| Same | JSON with only other findings | PASS |
| Same | Empty JSON list | PASS |

**Other cases:**
- A step whose `expr` evaluates to a string gives ERROR.
- `project.ci_provider == "github"`:
  - with a confirmed `ci_provider = github`, the expression evaluates true;
  - with an unconfirmed candidate, the step is ERROR.
- `file_exists("README.md")` is true in a repository that has `README.md`.
- With `expr_decides = true` and a handler PASS: true is PASS, false is FAIL, a broken expression is ERROR; a handler FAIL, WARN, INCONCLUSIVE, or ERROR is unchanged. A FAIL outside the step's effective set does not conclude.
- `expr_decides` without `expr`, on `file_exists`, or on `gh_api` fails loading.

## V2. Load-time checks (US1 scenario 6, US2, SC-003)

```bash
uv run pytest tests/darnit/config/test_strict_framework_loading.py -v
uv run python scripts/validate_sync.py --verbose
```

Each of these fails loading, and the error names the location:

| Input | Error names |
|---|---|
| Control key `nmae` | File and control |
| Step key `fail_on_mis` | File, control, step, and key |
| `handler = "file_must_exst"` | Control and step type |
| `expr = 'response.body.x'` on an `exec` step | Control and the name |
| Expression with a syntax error | Control and step |

**Other cases:**
- Every shipped framework, `darnit-hello` and `darnit-example` included, loads.
- An operator custom control naming a missing plugin step type audits as ERROR `missing_tool`.

## V3. Plugins cannot replace step types (US2, SC-002)

```bash
uv run pytest tests/darnit/sieve/test_registration_collisions.py -v
```

- A plugin that registers `manual` with ceiling `{"pass"}`:
  - the registration is refused;
  - a WARNING is logged;
  - `refused_registrations` lists it;
  - a control whose only automated step is `manual` still does not PASS.
- Two plugins registering the same name: the second is refused, and both plugins are named.

## V4. Reproducibility text signals (US3, SC-004)

```bash
uv run pytest tests/darnit_reproducibility/test_no_pass_from_signals.py -v
```

| Repository | Expected |
|---|---|
| Workflow with only a comment mentioning `cosign sign` | RE-02.02 is not PASS; the signal appears in evidence |
| Python manifest without a lockfile | `repro_deps_pinned` still FAILs |

## V5. No auditor profile in output (US4, SC-005)

```bash
uv run pytest tests/darnit_baseline/test_user_evidence_redaction.py -v
```

The recorded `/user` response includes email, location, company, and bio.

| Output | Expected |
|---|---|
| AC-01.01 evidence | Only `login` and `two_factor_authentication` |
| JSON report and attestation predicate | None of the other values |

## V6. Corpus and regression

```bash
uv run pytest tests/darnit_baseline/corpus/ tests/darnit_reproducibility/test_repro_corpus_gate.py -v
uv run ruff check .
uv run pytest tests/ -q
```

The corpus has cases for each path closed here, with 0 false PASSes:
- `zizmor-no-findings-document` (Baseline corpus): an exec step whose expression cannot evaluate;
- `plugin-redefines-manual` (Baseline corpus): a plugin redefining `manual`;
- `text-signals-only` (`tests/darnit_reproducibility/corpus/`): reproducibility text signals.

## Validation log

Run on 2026-10-04 on branch `044-false-pass-paths` after T024a-T027 and T030, offline, with `uv run` and `-p no:cacheprovider`.

| Scenario | Command | Result |
|---|---|---|
| V1 | `pytest tests/darnit/sieve/test_expr_failure.py` | 34 passed. The zizmor stand-in printing nothing gives ERROR (`evaluation`) for OSPS-BR-01.01 and OSPS-AC-04.02; a matching finding gives FAIL (`expr_decides`); other findings and an empty list give PASS. |
| V2 | `pytest tests/darnit/config/test_strict_framework_loading.py` | 19 passed. |
| V2 | `python scripts/validate_sync.py --verbose` | PASSED: TOML schema (66 controls), pass types (8 handlers), SARIF source, context keys (17 fields), remediation properties (78 remediations). |
| V3 | `pytest tests/darnit/sieve/test_registration_collisions.py` | 9 passed. |
| V4 | `pytest tests/darnit_reproducibility/test_no_pass_from_signals.py` | 17 passed. |
| V5 | `pytest tests/darnit_baseline/test_user_evidence_redaction.py` | 17 passed. |
| V6 | `pytest tests/darnit_baseline/corpus/ tests/darnit_reproducibility/test_repro_corpus_gate.py` | 23 passed. Baseline corpus: 13 fixtures, 94 labelled control results, 0 false PASS, 0 gate violations. With the registry's refusal bypassed, `plugin-redefines-manual` produces 3 false PASSes, so the case detects the regression. |
| V6 | `ruff check .` | All checks passed. |
| V6 | `pytest tests/ -q` | 5083 passed, 26 skipped. |
| CI identity | `pytest tests/ -m integration -q` with `CI=true GITHUB_ACTIONS=true GITHUB_EVENT_NAME=pull_request GITHUB_REPOSITORY=darnitdevorg/darnit GITHUB_SERVER_URL=https://github.com GITHUB_REF=refs/pull/1/merge GITHUB_SHA=0000000000000000000000000000000000000000` | 340 passed, 2 skipped. |
