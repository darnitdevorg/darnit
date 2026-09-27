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

## Validation log

### T049: Baseline re-declaration, before and after (2026-09-27)

Method: `darnit audit -o json --no-fail` (deterministic, no model), built-in
operator configuration, isolated data directory, read-only platform calls
with the local `gh` login. "Before" ran from a worktree of `0c35bb3` (the
tip before feature 041); "after" ran from this branch with US5 applied. Each
run audited its own fresh clone of the same commit, so the repository content
was identical.

Repositories: this repository (`darnitdevorg/darnit` at `37a3896`, default
branch `main`) and `pypa/sampleproject` at `621e497`. 66 controls each.

| Repository | Run | PASS | FAIL | WARN | ERROR | PENDING |
|---|---|---|---|---|---|---|
| darnit | before | 61 | 2 | 3 | 0 | 0 |
| darnit | after | 14 | 3 | 18 | 0 | 31 |
| sampleproject | before | 22 | 25 | 19 | 0 | 0 |
| sampleproject | after | 11 | 8 | 18 | 5 | 24 |

PENDING here is `pending.kind = "llm_judgment"`: the control waits for a
model judgment, which can at most produce a PASS candidate.

Changed controls by cause (SC-006):

| Cause | darnit | sampleproject |
|---|---|---|
| A. Presence/keyword step no longer concludes PASS | 44 | 8 |
| B. Miss now inconclusive | 0 | 17 |
| C. Broken measurement now ERROR | 0 | 5 |
| D. Judgment now requested (PASS candidate at most) | 0 | 10 |
| E. Other (explained below) | 4 | 3 |
| Unchanged | 18 | 23 |

- A: PASS to WARN or PENDING. Concluded before by `file_exists`, `pattern`,
  or `regex`, or by an exec step that is a keyword scan or a presence check
  (BR-01.01 and BR-01.02 grep, BR-04.01 release-notes presence, VM-05.02 and
  VM-06.02 app installation or workflow keywords). Content controls now end
  PENDING; the rest end WARN.
- B: FAIL to WARN or PENDING. A pattern miss concluded FAIL before; it is now
  inconclusive (FR-004). BR-04.01 on sampleproject is the `file_exists`
  changelog step, narrowed to evidence because release notes also satisfy
  the requirement.
- C: WARN to ERROR on sampleproject for AC-03.01, AC-03.02, QA-03.01,
  QA-07.01 (branch protection answers 404 to a token without admin rights,
  which is ambiguous) and AC-01.01 (the organization 2FA field and the
  `/user` 2FA field are not visible to the token).
- D: WARN to PENDING for content controls that gained an `llm_eval` step
  (T047).
- E, both repositories: AC-02.01, BR-03.01, VM-04.01 PASS to WARN or
  PENDING. Their platform checks read a setting that does not measure the
  requirement (`allow_forking`, `html_url`, `has_issues`); the checks were
  removed or narrowed to FAIL only (T046). This is the platform analogue of
  cause A.
- E, darnit only: one organization-settings control WARN to FAIL. `gh_api`
  concludes FAIL from the settings response, where the former `exec` step
  could only reach INCONCLUSIVE when its expression disagreed with a zero
  exit code.

No control went from anything to PASS. Every PASS after is concluded by a
step allowed to conclude it: `gh_api`, `github_branch_protection`, an
existence step (LE-03.01, QA-02.01, QA-05.01, QA-05.02), `inferred_from`
(LE-02.02, LE-03.02), or zizmor (`exec`, BR-01.01 on sampleproject).

Corpus (`uv run python scripts/corpus_report.py --format markdown`): 10
fixtures, 88 labels; false PASS by a step allowed to conclude PASS: 0;
`known_false_pass.toml` has no entries; control verdicts: 21 correct, 0
incorrect, 0 false PASS, 67 undetermined (WARN, PENDING, or ERROR).

### T054: Quickstart run, sections 1-5 (2026-09-27)

Run from this branch after the Polish changes (T050-T053). Sections 1-4 are
offline: corpus fixtures were audited through the corpus runner's isolated
audit (`run_fixture`: fixture copy, scratch `HOME`/XDG directories, `gh`
served from the fixture's recorded responses, no model). Section 3 used a
scratch script, not the test suite, on a copy of `corpus/reference-good/`
with an origin of `github.com/example/reference-good`, `--repo`-style target
`github.com/example/reference-good`, scratch `HOME`/XDG directories, a `gh`
stub that always fails, an empty `RecordedGhApi`, and `HarnessRun` with
`MockLLMStep` (placeholder API key; no model is called). The same steps are
also encoded, on a synthetic operator-defined control, in
`tests/darnit/harness/test_harness_compliance.py`,
`tests/darnit/server/test_submit_judgment.py`, and
`tests/darnit/trust/test_judgments.py`.

1. Weak evidence does not PASS.
   - `placeholder-docs`: DO-01.01 and GV-03.01 PENDING (`llm_judgment`),
     `concluded_by = none`. GV-01.01 is FAIL by `file_exists`: this fixture
     has no governance file (the placeholder governance files are in
     `placeholder-governance`, where GV-01.01, GV-01.02, and GV-03.01 are
     PENDING (`llm_judgment`) and DO-01.01 is FAIL, no README). No control
     in either fixture is PASS by `file_exists`, `regex`, or `pattern`
     except existence steps (QA-05.01, QA-05.02).
   - `empty`: DO-01.01, GV-01.01, GV-03.01 FAIL by `file_exists`.
   - `reference-good`: LE-03.01 PASS by the existence `regex` step (license
     grant).
   - Level compliance false at levels 1-3 in all three.
2. Broken measurements are ERROR. Platform controls checked: AC-03.01,
   AC-03.02, QA-03.01, QA-07.01, QA-01.01, QA-01.02, GV-02.01.
   - `platform-permission-denied`: all seven ERROR, `error.class = auth`;
     no FAIL.
   - `platform-rate-limited`: all seven ERROR, `error.class = rate_limit`;
     no FAIL.
   - `platform-no-protection`: the four branch-protection controls FAIL,
     concluded by `github_branch_protection` (the plugin handler proves
     failure from the 404 "Branch not protected" answer; the quickstart's
     "via `fail_on_status`" describes the `gh_api` equivalent). QA-01.01,
     QA-01.02, GV-02.01 PASS by `gh_api`.
   - Not compliant at any level in all three.
3. Judgments become PASS candidates.
   1. Harness, positive judgment citing "widget is a command-line tool that
      prints ASCII widgets.": DO-01.01 PENDING (`confirmation`), authority
      `suggestive`, candidate from `harness`, model
      `anthropic:claude-sonnet-5`, 1 cited excerpt; level 1 not compliant,
      exit class 1. The mock returns the same judgment for every pending
      control, so five other controls whose model step also reads the
      README became candidates too.
   2. `confirm_project_data(confirm_pass_candidate=["OSPS-DO-01.01"],
      owner, repo)`, re-audit: PASS, `authority: asserted`,
      `concluded_by: confirmation`, confirmation block with `confirmed_by`,
      `confirmed_at`, `expires_at`.
   3. README edited, re-audit: PENDING (`llm_judgment`), "the evidence
      changed since its PASS candidate was confirmed"; level 1 not
      compliant.
   4. `submit_judgment` citing text not in the README: `rejected`, naming
      the missing excerpt; candidate store unchanged.
   5. Negative judgment: `finding`, FAIL, `authority: suggestive`,
      `concluded_by: llm_judgment`; store unchanged.
4. Corpus measurement.
   1. `uv run python scripts/corpus_report.py --format markdown`: 10
      fixtures, 88 labels, 90 of 176 declared steps observed; a row per
      (control, step, outcome) with observed, concluded, correct,
      incorrect, and false-PASS counts; gate PASS, 0 violations.
   2. Temporary `promotion = { outcome = "pass", ... }` on VM-02.01's
      `regex` step: exit 1, gate FAIL, one unexpected false PASS naming
      fixture `policy-denies-process`, control VM-02.01, step `pass[1]
      regex`. Promotion removed; the TOML is unchanged.
   3. Temporary fixture directory with only a `labels.toml` (one LE-03.01
      FAIL label): measured with no code change (11 fixtures, 89 labels,
      verdict correct); directory removed.
5. Baseline re-declaration.
   1. Corpus: zero false PASS (4.1).
   2. Real repositories, "after" rerun with the T049 method (fresh clones of
      the same commits, `darnit audit -o json --no-fail`, built-in operator
      configuration, isolated data directory, read-only platform calls with
      the local `gh` login), 66 controls each:

      | Repository | PASS | FAIL | WARN | ERROR | PENDING |
      |---|---|---|---|---|---|
      | darnit | 14 | 3 | 18 | 0 | 31 |
      | sampleproject | 11 | 8 | 18 | 5 | 24 |

      Both match the T049 "after" counts, so T050-T053 changed no result.
      No PASS is concluded by a presence or pattern step other than the
      existence steps; every ERROR carries `error.class`; every PENDING is
      `llm_judgment`. A first darnit run from a local clone whose
      `origin/HEAD` pointed at this feature branch (not on the platform)
      turned four branch-protection controls into ERROR (`unavailable`,
      "Branch not found"), as the rules require for an undeclared 404;
      setting `origin/HEAD` to `main` reproduced the T049 counts.

Checks (T055): `uv run ruff check .` clean;
`uv run python scripts/validate_sync.py --verbose` passed;
`uv run pytest tests/ --ignore=tests/integration/ -q -p no:randomly`:
3990 passed, 18 skipped, and the known local-only failure
`tests/darnit/parity/tier1/test_no_product_changes.py` (unmerged prerequisite
commits on this stacked branch).
