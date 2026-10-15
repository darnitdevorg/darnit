# Enforcement

Every rule in `constitution.md` has a row here. A row records:

- **Mode**: test, agent or human (see the constitution's "How rules are
  enforced").
- **Check**: the CI check, plus a yes/no review question for any part a test
  cannot reach.
- **Today**: what the check finds on `main`, measured. The measurements below
  were taken on `f9bfd08` (2026-10-12).
- **Status**.

Status values:

- `enforced`: the check runs in CI on every pull request, and a pull request
  built to violate it was shown to fail. The row links that demonstration.
- `running`: the check runs in CI, but no failure demonstration is recorded
  yet.
- `dormant`: the check runs but asserts nothing until a named precondition is
  met. It becomes `enforced` on its own when the precondition holds.
- `planned`: agreed, not yet written. The row names the milestone it lands in.
  A row planned for two milestones is either built or struck.
- `unbuilt`: no check exists, and nobody has started one.
- `manual`: enforced by agent or human review only, with the review question
  and the owner named.

A new check starts from today's findings as an allow-list. Each entry links an
issue, and the list can only shrink (A1).

**No check blocks a merge yet.** `main` requires a pull request, but no status
checks and no approvals, and `enforce_admins` is off (see ENF-R1). Until R1 is
in place, every row below is visible in CI but does not stop a merge.

| ID | Mode | Check | Today | Status |
|----|------|-------|-------|--------|
| ENF-S1 | test + human | Planned: a committed inventory of every `exec` command, plugin step type and `gh_api` method in a shipped framework, each recorded as reading setup. A step not in the inventory fails. `gh_api` steps must be GET. Adding a row needs maintainer review against the question "Could this step's answer change while nothing in the repository or its platform settings changes (tool version, network, time, history)?" | About 15-20 rows. 5 outcome uses: `zizmor` ×2 (BR-01.01, AC-04.02), `gittuf_verify_policy`, `gittuf_commits_signed`, `repro_witness_attestation`. 2 borderline: `repro_hermetic_build`, `repro_bit_for_bit`. These are cut or reframed per ADR-0001. | planned: scope-reset milestone |
| ENF-S2 | test | CI `Test` job: `tests/darnit/tools/test_compliance_errors.py`, `tests/darnit/assertions/test_compliance_effects.py`, `tests/darnit/harness/test_harness_compliance.py`, `tests/darnit/config/test_strict_framework_loading.py`, and the adversarial corpus gate (`tests/darnit_baseline/corpus/`, including `plugin-redefines-manual`). Planned: a test that every shipped `promotion` matches corpus eligibility. | Known gaps from the wiring audit: the shared-handler cache, list-valued `when` (N/A), `gh_api`/`mcp` truthiness, a plugin registering without its plugin context, a dropped control leaving its level compliant. 0 promotions are shipped. | running (only the corpus gate has a failure demonstration) |
| ENF-S3 | test | CI `Test` job: `tests/darnit/context_integrity/`. | Known gap: raw `.project/project.yaml` values satisfy a remediation `when` guard, and the `project.*` template namespace is unguarded. | running |
| ENF-S4 | test | CI `Test` job: `tests/darnit/context_integrity/test_single_writer.py`, `test_user_files_survive.py`. Planned: an allow-list of filesystem write sites in `packages/*/src`, so a new write site outside the executor fails. | Write sites outside the executor are reachable from remediation: `darnit_baseline/threat_model/remediation.py` (5 sites; overwrites uncommitted user files), `remediation/helpers.py:53`, `darnit_baseline/tools.py:1144-1145`. | running, with known gaps |
| ENF-S5 | test | CI `Test` job: `tests/darnit/config/operator/test_repository_cannot_configure.py`, `test_baseline_toml_removed.py`, `tests/darnit/trust/`. | Known gap: `remediate_audit_findings` builds its trust target from the checkout's origin remote. | running, with known gaps |
| ENF-F1 | test | Planned: an AST check over `packages/darnit/src` that fails on an import of an implementation package, a framework-name literal outside the one default constant, and a `register_control` call outside the control loader. | 0 imports. 5 framework-name literals in 4 files: `agent/graph.py:402,416`, `cli.py:504`, `config/merger.py:691`, `config/context_schema.py:350`. `register_control` is called only by the loader, but CLAUDE.md shows it as a plugin API. | planned: first checks milestone |
| ENF-F2 | test | Today: tier-1 parity tests (`tests/darnit/parity/tier1/`) compare `audit_openssf_baseline` with `HarnessRun` only. Planned: a parity matrix of entry points (CLI, MCP, builtin, harness, `darnit run`) × options over the parity fixtures, plus an AST check that profile, tags and default-framework resolution happen in one module. | Profile resolution happens in 3 places and is absent from the CLI; tags are parsed in 3 places; the default framework is set in 4. CLI `audit` has no `--level`; MCP audit has no include/exclude; the harness has no tags or profile. | planned: second checks milestone |
| ENF-F3 | test + agent | Planned, three ratchets:<br>(1) Every MCP tool parameter and CLI flag is read (AST); configuration fields later.<br>(2) Whole-repo mypy against a baseline generated in CI's environment. Any `attr-defined`, `call-arg` or `name-defined` error fails outright.<br>(3) The set of shipped functions with no executed line, from CI's coverage run, may only shrink. Protocol stubs and test-fixture packages are excluded.<br>Agent question: "Does a test reach each new or changed default implementation through a real entry point?" | (1) 6 unread: `auto_init_config`, `template`, `get_pending_data` `level` and `profile`, `--profile` on `audit` and `plan`. (2) 201 errors, 21 in the always-fail tier. (3) 101 functions. Today's CI `Type Check` job checks 2 files with `\|\| true` and gates nothing. | planned: first checks milestone |
| ENF-F4 | test | CI `Non-dev install smoke` job (#575, extended by #596): builds every published wheel, installs it without development dependencies, runs one audit, and fails on a control that could not be evaluated or on more than one wheel per package. | Passes on `main`. Shown to fail when `packaging` is removed from darnit-core (#575 review). Plugins loaded only through registration (gittuf, reproducibility) are not imported in full. | running (a failure demonstration exists in review; link it from a closed pull request to mark `enforced`) |
| ENF-C1 | test + human | Planned: committed snapshots of each contract surface: MCP tool schemas, the argparse tree, `model_json_schema()` of both configuration schemas, and JSON/SARIF/predicate output for one fixture. A removal or rename in a snapshot diff requires a BREAKING line. Human question: "Did the ADR or spec that decides this change land with or before it?" | Today's `Spec Sync` check finds 8 hard-coded handler names in a document and enforces almost nothing. | manual (maintainers); snapshots planned |
| ENF-R1 | test + human | `main` branch protection:<br>- required checks `Test`, `Lint`, `Spec-Implementation Sync`, `Build`, `DCO` and `agent-review`;<br>- required code-owner review, with CODEOWNERS listing only the owned paths, so a pull request touching them needs an owner other than its author;<br>- administrators included.<br><br>The `agent-review` check runs a fresh agent session that the author cannot steer. It has its own identity, takes the constitution's review questions as input, treats pull request text as untrusted, and reads no secrets from a fork's code. It passes when it raises no blocking finding, or when a maintainer other than the author has approved the pull request.<br><br>Human part: a weekly digest of pull requests merged without a second person goes to the maintainers, and anything doubtful becomes an issue.<br><br>Planned:<br>- a scheduled job that fails when protection drifts from this declaration;<br>- a test that the CI test command has no marker, `-k`, `--deselect` or `--ignore` selection;<br>- a hermetic job that runs the suite with an empty HOME, CI variables set and the network blocked, and fails if anything is written under HOME. | Protection requires a PR only: 0 approvals, no required checks, `enforce_admins` off. No `agent-review` check exists. CODEOWNERS owns everything (`*`) and names only one maintainer. CI has run the whole suite since #592. With an empty HOME, the suite writes 377 files there, including `~/.darnit/verification_cache`, a pip cache, tree-sitter grammars and sigstore TUF metadata (a network fetch). | unbuilt (settings change pending) |
| ENF-A1 | test + agent | Planned: a committed file of ratchet counts and sets, compared on every pull request:<br>- suppressions by kind;<br>- the mypy baseline;<br>- the unexecuted-function set;<br>- reader allow-lists;<br>- the inventory of Protocols, entry-point groups and registries;<br>- CI's test selection.<br>An increase fails unless the pull request links an issue and a maintainer approves.<br>Agent question: "Did this change weaken, skip or suppress anything to make a run pass?" | Baseline: 85 `# noqa` (47 of them `BLE001`), 54 `# type: ignore`, 41 test skips (`mark.skip`/`skipif`, `pytest.skip(`, `importorskip`), 5 `pragma: no cover`, 2 `continue-on-error` and 10 `\|\| true` in workflows and scripts, 3 ruff per-file-ignores. 17 extension points (9 Protocols, 3 entry-point groups, 5 registries). | planned: first checks milestone |
| ENF-A2 | test + human | `DCO` check (not yet required; it cannot tell an agent-added sign-off from a person's). Planned:<br>- a check that fails on an AI `Co-authored-by` or `Signed-off-by` line, on a PR body without exactly one AI-assistance box ticked, or on AI use declared without an `Assisted-by` trailer;<br>- a check that fails on a local home-directory path in a tracked file;<br>- an output test that an audit report contains no home path or user profile.<br>Human question: "Can the author explain this change?" | Since AI_POLICY landed (38 commits): 1 AI co-author line, 6 AI-disclosed PRs without `Assisted-by`, 6 PRs with no AI box ticked. 21 home-directory paths in tracked files, mostly Spec Kit `tasks.md`. | planned: first checks milestone |
| ENF-A3 | test + agent | CODEOWNERS entry for `governance/` naming the maintainers, and required code-owner review on `main`. Planned: `scripts/governance_lint.py`, which requires every MUST in `governance/` to carry an id, every id to have a row here, and every row to be cited by a rule. Agent question: "Did a maintainer ask for this change to `governance/`?" | CODEOWNERS lists only `@mlieberman85`, plus a stale `/main.py` line. Code-owner review is not required. | unbuilt |

## Build order

1. ENF-R1 settings (no code) and a CODEOWNERS pull request that owns only
   the expensive paths and names both maintainers. Nothing gates until these
   land. Until the `agent-review` check exists, R1 falls back to a second
   maintainer's approval on every pull request.
2. ENF-F3 (1), the reader check for MCP parameters and CLI flags, starting
   with 6 allow-list entries linked to #528, #541 and #576.
3. ENF-F3 (2), the mypy gate, replacing today's `Type Check` job.
4. ENF-F1, the AST check, either fixing the 5 framework-name literals or
   starting with them allow-listed.
5. ENF-A2, the attribution and home-path checks.
6. ENF-A1, the ratchet file.
7. ENF-F4: record the failure demonstration (#575 merged).
8. ENF-R1's hermetic job. The writes to HOME are fixed first, or allow-listed.
9. ENF-F2, the parity matrix and the single-resolver check.
10. ENF-F3 (3), the coverage ratchet.
11. ENF-C1, the contract snapshots.
12. ENF-S1, the inventory, after the scope-reset classification.
13. ENF-A3, governance_lint.

Prove each new check: open a pull request built to violate it, watch the check
fail, close that pull request unmerged, and link it from the row. That link is
what moves a row from `running` to `enforced`.
