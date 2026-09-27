# Quickstart: Validating the Result and Authority Contract

Prerequisites: `uv sync`; feature 040 in place; an isolated operator configuration and data root (as the test suite's shared fixtures provide). Contracts: [step-declarations.md](contracts/step-declarations.md), [results-and-judgments.md](contracts/results-and-judgments.md). Entities: [data-model.md](data-model.md).

## 1. Weak evidence does not PASS (User Story 1)

1. Audit `tests/darnit_baseline/corpus/placeholder-docs/` (README "TODO", placeholder governance files).
   Expected: DO-01.01, GV-01.01, GV-03.01 are not PASS (WARN or PENDING); none has `concluded_by` equal to `file_exists` or `pattern` with status PASS.
2. Audit `tests/darnit_baseline/corpus/empty/`.
   Expected: the same controls are FAIL, concluded by the presence step.
3. Audit a fixture with a LICENSE file. Expected: LE-03.01 PASS (existence step).

## 2. Broken measurements are ERROR (User Story 2)

Run the corpus platform scenarios `platform-permission-denied`, `platform-rate-limited`, and `platform-no-protection` (recorded responses).
Expected: the first two produce ERROR with `error.class` `auth` / `rate_limit` for platform controls and no FAIL; the third produces FAIL for branch-protection controls via `fail_on_status`. The level is not compliant in all three.

## 3. Judgments become PASS candidates (User Story 3)

1. Run the harness with a mock LLM step returning a positive judgment with a verbatim excerpt for DO-01.01 on `corpus/reference-good/`.
   Expected: DO-01.01 is PENDING (confirmation) with a candidate; level non-compliant.
2. Confirm the candidate through the confirmation tool. Re-audit.
   Expected: PASS, `authority: asserted`, confirmation block present.
3. Edit README; re-audit. Expected: confirmation lapses; back to PENDING (llm_judgment).
4. Submit a positive judgment citing text not in the README via `submit_judgment`. Expected: rejection naming the excerpt; nothing stored.
5. Submit a negative judgment. Expected: suggestive FAIL.

## 4. Corpus measurement (User Story 4)

1. `uv run python scripts/corpus_report.py --format markdown`.
   Expected: a row per (control, step, outcome) with correct/incorrect counts; zero violations.
2. Add a temporary promotion on a pattern step for a content control; rerun.
   Expected: the run fails, naming the step and the fixture that produced a false PASS. Remove the promotion.
3. Add a new fixture directory with `labels.toml` only. Expected: it is measured with no code change.

## 5. Baseline re-declaration (User Story 5)

1. Run the corpus. Expected: zero false PASS across all fixtures.
2. Audit this repository and one other real repository before and after (JSON). Expected: every changed control falls into one of: presence/keyword step no longer concludes PASS, miss now inconclusive, failure now ERROR, judgment now candidate.

## Checks

```
uv run pytest tests/ --ignore=tests/integration/ -q
uv run ruff check .
uv run python scripts/validate_sync.py --verbose
```
