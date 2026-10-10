# Enforcement

Every normative rule in `governance/` maps to a row here. Once ENF-A4's check
exists, CI fails when a MUST or MUST NOT carries an enforcement id with no row
here, or when a row names a check that does not exist.

Status values (the same as swansong's):

- `enforced`: the check exists and runs in CI. The row says in its text what the
  check does not yet cover.
- `dormant`: the check exists and runs, but its precondition is unmet, so it
  asserts nothing yet. The row names the precondition. The row becomes
  `enforced` on its own once the precondition is met.
- `planned`: agreed but not yet written. The row names the milestone it lands
  in. A row planned for two milestones is either written or struck.
- `unbuilt`: no check exists, and nobody has started one.
- `manual`: enforced by human review, and the row names who is responsible.

**A caveat that applies to every row today.** `main`'s branch protection
requires a pull request but requires no status checks and no approvals. Until
ENF-R1 is enforced, an `enforced` row below means the check runs in CI and is
visible. It does not mean a failing run blocks a merge.

| ID | Rule | Check | Failure mode | Status |
|----|------|-------|--------------|--------|
| ENF-S1 | Controls check setup, not outcomes | Manual: the reviewer of any pull request that adds or changes a control or step type in a shipped framework TOML or plugin applies ADR-0001's admission test. Planned check: every `exec` step and plugin step type in a shipped framework is listed in a reviewed inventory that records the setup it reads, and a step not in the inventory fails. | A control that runs a tool and grades its result, which brings false PASS risk and the tool's trust roots into darnit | manual (maintainers); check planned for the scope-reset milestone |
| ENF-S2 | Unverified is not compliant | CI `Test` job: `tests/darnit/tools/test_compliance_errors.py`, `tests/darnit/assertions/test_compliance_effects.py`, `tests/darnit/harness/test_harness_compliance.py`, and the adversarial corpus gate (`tests/darnit_baseline/corpus/`, `known_false_pass.toml`). Does not cover: a control dropped at load time while its level is still reported compliant (wiring audit W-18), or a list-valued `when` that makes a control N/A (W-05). | A false PASS, or a level reported compliant with an unverified control | enforced, with known gaps |
| ENF-S3 | Judgment values are never concluded | CI `Test` job: `tests/darnit/context_integrity/` (`test_consumers_use_usable`, `test_accept_candidates`, `test_confirmation_records`, `test_reads_do_not_write`). Does not cover: raw `.project/project.yaml` values satisfying a remediation `when` guard, or the `project.*` template namespace (W-09). | A guessed maintainer, contact or license used as if confirmed | enforced, with known gaps |
| ENF-S4 | Remediation writes only through the executor | CI `Test` job: `tests/darnit/context_integrity/test_single_writer.py`, `test_user_files_survive.py`. Does not cover: plugin remediation handlers registered with `supports_plan=False` that write for themselves (W-08). | A user's uncommitted work overwritten; files changed that the run manifest does not list | enforced, with known gaps |
| ENF-S5 | The audited repository is untrusted | CI `Test` job: `tests/darnit/config/operator/test_repository_cannot_configure.py`, `test_baseline_toml_removed.py`, and the trust tests under `tests/darnit/trust/`. Does not cover: `remediate_audit_findings` building its trust target from the checkout's origin remote (W-07). | A repository that configures its own audit, or grants itself trust | enforced, with known gaps |
| ENF-S6 | Steps conclude only within their effective set | CI `Test` job: `tests/darnit/config/test_strict_framework_loading.py`, the orchestrator dispatch tests, and the corpus gate (`plugin-redefines-manual` among its cases). Does not cover: the shared-handler cache (W-04), `gh_api` and `mcp` expressions decided by truthiness (W-16), or a plugin registering without its plugin context (W-17). | A PASS no step was allowed to give | enforced, with known gaps |
| ENF-F1 | Framework does not import implementations | Planned: an import check over `packages/darnit/src` that fails on `import darnit_<implementation>` or `from darnit_<implementation>`. | The framework works only with in-tree plugins | unbuilt |
| ENF-F2 | Controls live in TOML | CI `Spec Sync`: `scripts/validate_sync.py` (TOML schema, pass types, SARIF reads TOML). Strict loading rejects unknown control keys. | Control metadata or logic split between Python and TOML | enforced |
| ENF-F3 | No premature extension points | Manual: the reviewer asks for the second implementation or the ADR. | A seam with one implementation and no caller; the stores, adapters and pass registries found in the wiring audit | manual (maintainers) |
| ENF-F4 | Everything accepted has a reader | Planned: a test that walks the framework-schema and operator-config models, the declared step settings, the argparse tree and the registered MCP tool signatures, and requires each field, setting, flag and parameter to be read in `packages/*/src` outside its declaring module, against a reviewed allow-list that gives a reason for each entry. | A documented setting that silently does nothing (W-10, W-13, W-14, W-24, W-29 in the wiring audit) | planned: scope-reset milestone |
| ENF-F5 | Every function runs in a test; default implementations run end to end | Planned: per-function coverage from the CI test run, failing on any function in `packages/*/src` with no executed line unless it is in a reviewed allow-list; plus a test that lists each Protocol's shipped default implementation and requires a test through a real entry point. On 2026-10-10, 129 functions had no executed line. | Code nobody runs; a default implementation that has never worked (#574) | planned: scope-reset milestone |
| ENF-F6 | No new type errors | Planned: whole-repo mypy (`mypy_path` over every `packages/*/src`, pydantic plugin) against a committed baseline file, failing on any new error and on any `attr-defined`, `call-arg` or `name-defined` error. Validated locally on 2026-10-10: 193 baseline entries, about 7 seconds warm, and it fails when a real defect is taken out of the baseline. Today's CI `Type Check` job checks two files with `|| true` and gates nothing. | Missing methods and wrong call signatures shipping (#574, the attestation predicate, the CEL `except` clause) | planned: scope-reset milestone |
| ENF-C1 | Contracts change spec-first; breaking changes are listed | CI `Spec Sync` covers handler names and the TOML schema. The rest is manual: the reviewer checks that the ADR or spec landed with or before the code, and that the BREAKING entry is present. | A contract that changes with no recorded decision; a user broken with no notice | manual (maintainers), partly enforced |
| ENF-A1 | AI attribution | DCO check requires the human submitter's `Signed-off-by`. The rest is manual: the reviewer checks the `Assisted-by` trailer, the absence of AI co-author or sign-off lines, and the PR's AI disclosure. Planned: a commit-message check that fails on an AI `Co-authored-by` or `Signed-off-by`. | AI attribution that misstates who certified the change | manual, partly enforced |
| ENF-A2 | Governance changes are labelled | Planned: a workflow that fails any pull request touching `governance/` unless it carries the `tier-1` label, plus a CODEOWNERS entry naming both maintainers for `governance/`. | Rules changed by whoever was editing nearby | unbuilt |
| ENF-A3 | No weakening checks | Planned: a diff check that fails on an added `# noqa`, `# type: ignore`, `pytest.mark.skip` or `continue-on-error` outside a `tier-1` pull request. | A green build bought by lowering the bar | unbuilt |
| ENF-A4 | Every rule has a row | Planned: `scripts/governance_lint.py`, which requires every MUST in `governance/*.md` to carry an id, every id to have a row here, and every row to be cited by a rule. | Governance drifting back into prose | unbuilt |
| ENF-R1 | Merges go through required checks | `main` branch protection. Today it requires a pull request with zero approvals and no required status checks. Planned: require `Test`, `Lint`, `Spec Sync`, `DCO` and, once built, the ENF-F6 type gate. | A red pull request merged | unbuilt (protection exists, but requires no checks) |

## Build order

1. ENF-R1. Nothing else gates until the checks are required.
2. ENF-F6, ENF-A4 and ENF-A2. These are small and already designed, and the
   first two stop new defects of the kind the wiring audit found.
3. ENF-F4 and ENF-F5. They will fail on day one; start them with the current
   failures as their allow-list and burn it down.
4. ENF-F1 and ENF-A3.
5. ENF-S1's inventory check, once the scope-reset classification has decided
   which steps stay.

Prove each new check the way swansong does: open a pull request built to
violate it, watch the check fail, and close that pull request unmerged.
