# Adversarial fixture corpus

Small repositories with human-labelled expected outcomes per control. The
corpus measures every verification step and gates when a step may conclude
PASS (feature 041, `docs/architecture/framework-design.md` section 5.5).

## Layout

```text
tests/darnit_baseline/corpus/
|-- README.md
|-- <fixture>/
|   |-- labels.toml        # expected outcomes (required)
|   `-- <repository files> # the fixture's file tree, as a plain directory
```

A fixture is a plain directory; it does not need to be a git repository.
Adding a fixture requires only its files and its `labels.toml`; no code
change.

## labels.toml

```toml
[fixture]
description = "README contains only TODO"

# Optional recorded platform responses for gh_api steps, keyed by API path.
# Offline and deterministic: no network access during a corpus run.
[fixture.platform."/repos/$OWNER/$REPO/branches/main/protection"]
status = 404
body = { message = "Branch not protected" }

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
| `[fixture.platform."<path>"]` | table | Recorded response: `status` (int) and `body`. |
| `[labels."<control_id>"].expected` | str | `PASS`, `FAIL`, `NOT_PASS` (anything but PASS is correct), or `N/A`. |
| `[labels."<control_id>"].why` | str | Short rationale. |

Controls without a label are not measured on that fixture.

## What a run reports

For every (framework, control, step index, outcome): correct and incorrect
conclusions against the labels, false PASS count, and whether a step not yet
allowed to conclude PASS is eligible for a promotion (zero false PASS). A run
fails if any step allowed to conclude PASS produces a false PASS, naming the
step and the fixture.
