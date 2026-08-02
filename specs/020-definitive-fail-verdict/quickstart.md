# Quickstart: preserve handler-conclusive FAIL through the CEL post-step

Three verification layers, in order from smallest to fullest. Layer 3 is the actual product test per [[feedback_darnit_testing_framing]] and is mandatory for sign-off.

## Layer 1: orchestrator unit tests (deterministic)

**Command:**

```sh
uv run pytest tests/darnit/sieve/test_orchestrator_cel.py -v
```

**Expected:** all 8 transition-table cases pass. The two new-behavior cells are:

- Handler FAIL + CEL true + expr present -> INCONCLUSIVE (new; was PASS)
- Handler FAIL + CEL false + expr present -> FAIL (new; was INCONCLUSIVE)

Old-behavior cells preserved:

- Handler PASS + CEL true + expr -> PASS
- Handler PASS + CEL false + expr -> INCONCLUSIVE
- Handler INCONCLUSIVE + any CEL + expr -> INCONCLUSIVE (pass-through)
- Handler ERROR + any CEL + expr -> ERROR (pass-through)
- Any handler status + no expr -> unchanged
- Any handler status + CEL evaluation error -> unchanged

## Layer 2: branch-protection integration tests (deterministic, stubbed API)

**Command:**

```sh
uv run pytest tests/darnit_baseline/controls/test_branch_protection.py -v
```

**Expected:** for each of `OSPS-AC-03.01`, `OSPS-AC-03.02`, `OSPS-QA-03.01`, `OSPS-QA-07.01`:

- **FAIL case:** subprocess stubbed to return `returncode=1` + `stdout=b'{"message": "Branch not protected", ...}'` -> control resolves FAIL with a message string containing "Branch not protected".
- **PASS case:** subprocess stubbed to return `returncode=0` + a healthy branch-protection body -> control resolves PASS (regression guard).

Also runs the full non-integration sweep to confirm no unrelated regressions:

```sh
uv run pytest tests/ --ignore=tests/integration/ -m "not upstream" -q
```

Any test that fails here should be one of the ones flagged by the R7 grep in `research.md` (i.e., testing the buggy behavior). Un-flagged failures mean a real regression.

## Layer 3: audit skill against a real repo (nondeterministic, mandatory)

**Setup:** use the test project created for feature 019 verification:

```sh
ls /tmp/darnit-test-repo   # created previously; recreate if gone
```

Point `/tmp/darnit-test-repo` at itself (it has no branch protection since it is a local scratch repo, but the audit tool queries GitHub via `gh api` which will fail cleanly with 404 or auth-scoped error). For a real 404 signal, point at any pushed GitHub repo you own whose default branch is unprotected.

**Command via the skill:**

Invoke `/darnit-audit` from within Claude Code, targeted at the repo, at each level. Compare the reported verdict for the four named branch-protection controls (`OSPS-AC-03.01`, `OSPS-AC-03.02`, `OSPS-QA-03.01`, `OSPS-QA-07.01`) against the following expectation:

- With no branch protection: all four MUST report FAIL, with a message referencing "Branch not protected".
- With authenticated `gh` but unreachable network: WARN (unchanged).
- With branch protection enabled and healthy: PASS.

**Comparison against previous behavior:**

Before this feature ships, `/darnit-audit` on an unprotected repo reports the four controls as WARN ("needs verification"). After, they report FAIL. This qualitative shift is the entire user-visible outcome of the feature and is what the reader will see in an audit report.

## Layer 4 (optional): live GitHub audit

If you have a GitHub repo whose default branch is unprotected AND you have `gh auth status` returning authenticated:

```sh
uv run darnit audit /path/to/unprotected-repo -t level=1 --show-all --no-fail -o json | \
  jq '[.controls[] | select(.id | test("OSPS-AC-03|OSPS-QA-03.01|OSPS-QA-07.01")) | {id, status}]'
```

Expected: all four report `"status": "FAIL"`.

Note: the CLI `darnit audit` runs deterministically without LLM consultation (per its own docstring). This layer exercises the real `gh api` path but not the LLM-mediated report interpretation — that is layer 3's job.
