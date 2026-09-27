# Adversarial fixture corpus

Small repositories with human-labelled expected outcomes per control. The
corpus measures every verification step and gates when a step may conclude
PASS (feature 041, `docs/architecture/framework-design.md` section 5.5).

## Running it

```text
uv run pytest tests/darnit_baseline/corpus/ -v             # the gate and runner self-tests
uv run python scripts/corpus_report.py --format markdown   # the report (or --format json)
```

Both run offline and deterministically. The report script exits 1 when the
gate fails.

## Layout

```text
tests/darnit_baseline/corpus/
|-- README.md
|-- runner.py               # loads fixtures, runs the sieve, measures steps
|-- test_corpus.py          # the gate for openssf-baseline
|-- test_runner.py          # runner self-tests on a synthetic framework
|-- known_false_pass.toml   # tolerated false PASS results (empty since US5)
`-- <fixture>/
    |-- labels.toml         # expected outcomes and platform recordings (required)
    `-- <repository files>  # the fixture's file tree, as a plain directory
```

A fixture is a plain directory; it does not need to be a git repository.
Adding a fixture requires only its files and its `labels.toml`; no code
change.

| Fixture | Represents |
|---|---|
| `empty` | Missing everything |
| `placeholder-docs` | README, CONTRIBUTING, SECURITY, SUPPORT that say only TODO |
| `placeholder-governance` | GOVERNANCE, MAINTAINERS, CODEOWNERS, CONTRIBUTING, LICENSE that say only TODO |
| `policy-denies-process` | A SECURITY.md stating there is no policy, process, or contact |
| `write-all-workflow` | A workflow granting `permissions: write-all` |
| `reference-good` | A small well-formed repository |
| `platform-no-protection` | Classic protection 404, no rulesets |
| `platform-ruleset-protection` | Protection only through an active ruleset |
| `platform-permission-denied` | 403 and 401 from the platform |
| `platform-rate-limited` | 429, and a 403 whose message is a rate limit |
| `platform-org-2fa-hidden` | Org hides its 2FA requirement; the auditor has 2FA |

## labels.toml

```toml
[fixture]
description = "README contains only TODO"

# Optional recorded platform responses, keyed by API path. $OWNER is
# "corpus", $REPO is the fixture directory name, $BRANCH is "main".
[fixture.platform."/repos/$OWNER/$REPO/branches/$BRANCH/protection"]
status = 404
error = "HTTP 404: Branch not protected"
body = { message = "Branch not protected" }

[fixture.platform."/repos/$OWNER/$REPO"]
status = 200
body = { private = false, has_issues = true }
jq = { ".has_issues" = "true" }

[labels."OSPS-DO-01.01"]
expected = "NOT_PASS"
why = "A README that says only TODO does not explain how to use the project."

[labels."OSPS-LE-03.01"]
expected = "FAIL"
why = "No LICENSE file."
```

| Field | Type | Notes |
|---|---|---|
| `[fixture].description` | str | What the fixture represents. |
| `[fixture.platform."<path>"]` | table | Recorded response: `status` (int), `body`, optional `error` (the `gh` error text), optional `jq` (output of `gh api --jq <expr>` keyed by expression). |
| `[labels."<control_id>"].expected` | str | `PASS`, `FAIL`, `NOT_PASS`, or `N/A`. |
| `[labels."<control_id>"].why` | str | Short rationale against the upstream requirement text. |

Label against the upstream OSPS requirement text
(`tests/darnit_baseline/fixtures/osps-baseline/`), not against what darnit
checks today:

- `PASS`: the fixture clearly satisfies the requirement.
- `FAIL`: the fixture clearly violates it.
- `NOT_PASS`: anything but PASS is acceptable (the requirement needs a human
  judgment, depends on a condition the fixture cannot show, or cannot be
  measured, as in the permission-denied and rate-limited scenarios).
- `N/A`: the requirement does not apply to the fixture.

Controls without a label are not measured on that fixture.

Keep fixtures tiny and text-only: no binaries (they would change this
repository's own audit), no `.env` files (ignored by the root `.gitignore`),
no Python files. Workflow files under `tests/` are never run by GitHub, which
runs only the repository root's `.github/workflows/`.

## How a fixture runs

`runner.py` copies the fixture (without `labels.toml`) into a scratch
directory and runs `run_sieve_audit` with the framework's controls, built-in
operator configuration, not-applicable claims ignored, and no model
(a control waiting for a judgment is PENDING, which is not PASS). Platform
calls through `gh_api_with_status` are served by `RecordedGhApi`; `gh`
subprocesses from `exec` steps are served the same recordings by a stub
first on a `PATH` that otherwise holds only `/usr/bin` and `/bin`. An
unrecorded path answers as a transport failure. `HOME` and the XDG
directories point into the scratch directory.

## What a run reports

- **Steps by outcome**: for every step of a labelled control that ran, and
  every raw handler outcome it produced, the times it was observed, the
  times it concluded the control, and the correct and incorrect conclusions
  against the label. A raw PASS is correct only on a `PASS` label; a raw
  FAIL or WARN is correct on `FAIL` or `NOT_PASS`. INCONCLUSIVE and ERROR
  are not conclusions. A raw PASS on a `FAIL` or `NOT_PASS` label is a false
  PASS, whether or not the step was allowed to conclude it.
- **Eligible for a PASS promotion**: a step that may not yet conclude PASS,
  produced at least one correct PASS, and no false PASS across the corpus.
  A maintainer may then record a `promotion` on the step, with `corpus` set
  to the report's corpus version.
- **Control results**: per fixture and labelled control, the final status,
  the step that concluded it, and a verdict (`correct`, `incorrect`,
  `false_pass`, or `undetermined` when no step concluded).
- **Corpus version**: a SHA-256 digest over every fixture file and label, in
  path order.

## The gate

A run fails if any step allowed to conclude PASS produces a false PASS,
naming the framework, control, step, and fixture. `known_false_pass.toml`
lists tolerated false PASS results, each with the task that removes it. An
entry that no longer occurs also fails the gate, so the list only shrinks.
User Story 5 emptied it, and `tests/darnit_baseline/test_baseline_authority.py`
keeps it empty for `openssf-baseline` (SC-001).
