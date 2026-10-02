# Implementation Plan: Remediation Safety

**Branch**: `043-remediation-safety` | **Date**: 2026-10-02 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/043-remediation-safety/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Make every remediation path plan before it acts, act only on what it planned, and report only what it verified. Platform settings change through one core engine that reads the current state, plans the minimal non-weakening change against a declared requirement, binds approval to a digest of that change and the observed state, applies under an operator policy (`prompt` default, `manual`, `auto`; high-impact changes configured separately), and reads back. The broken `api_call` handler and its full-object payloads are removed; `enable_branch_protection` becomes a thin tool over the engine. Remediation handlers get a plan/apply mode in which they return `FileChange`s and `ChangeSet`s; the executor is the single writer, so preview equals apply and every write lands in an operator-side run manifest. Git tools commit only manifest files, never stash, and refuse unsafe repository states. Outcomes are typed, derived from changes plus a cache-neutral re-check, and drive the report and the commit/PR gates; project references are declared next to the file they describe. Decisions are in [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.11/3.12 (workspace targets)

**Primary Dependencies**: existing only -- `pydantic >= 2` (`extra="forbid"` models), `gh` CLI for platform calls (JSON bodies via `--input -`), `git` CLI, `jinja2` (templates), `ruamel.yaml` (round-trip `.project/` writes, feature 042). No new runtime dependencies; run ids use a small in-tree ULID helper or `uuid4`.

**Storage**: Filesystem. Remediation policy in the feature 040 operator configuration. Run manifests operator-side under the darnit data root (`remediation/<repository-identity>/<run_id>.json`, 0600, never in the checkout). No new repository files; commit messages carry a `Darnit-Remediation-Run` trailer.

**Testing**: pytest. Platform: `RecordedGhApi` extended to writes (method, endpoint, body) with request-body capture. Git: scratch repositories with dirty trees, untracked secrets, stashes, detached HEAD, merges in progress, and a bare remote. Filesystem snapshots for plan-mode contract tests across every shipped remediation. Existing autouse operator-config and data-root isolation.

**Target Platform**: Linux, macOS, Windows (unchanged). Platform remediation: GitHub only; other forges get manual steps.

**Project Type**: Library + MCP server + CLI + skills.

**Performance Goals**: A preview adds at most 3 GET calls per platform target (repo or branch, protection, rules). A re-check runs only the affected controls. Scratch-copy previews apply only to exec steps declared offline.

**Constraints**:
- Principle II (a fix is claimed only when a re-check passes).
- Principle III (requirements, references, `effects` and `safe` live in TOML).
- Principle I: the engine and handlers are in darnit-core. Baseline and CSL change only their TOML and their own tool modules.
- Principle V (the sieve is unchanged; the re-check is a subset audit).
- Feature 040: policy comes from operator config only.
- Feature 042: only usable context values reach remediation, and `.project/project.yaml` is patched only by an applied remediation.
- `framework-design.md` is updated first.
- ASCII only; no reference to unpublished advisories.

**Scale/Scope**:

| Item | Count |
|---|---|
| Platform remediations moved to the engine | 7 |
| Moved to manual | 2 (AC-01.01, AC-02.01) |
| Platform targets | 3 |
| Remediation handlers given plan mode | 6 (`file_create`, `yaml_inject`, `project_update`, `exec`, `platform_setting`, `manual`), plus the plugin `generate_threat_model` |
| MCP tools changed | 6 |
| CLI paths | 1 (`darnit run`) |
| Skills | 2 |
| Existing test files pinning current behavior | about 20 (research "Current state"; the codebase map lists them) |

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment | Status |
|---|---|---|
| I. Plugin Separation | Engine, targets, policy, manifest, plan protocol, outcomes, git rules in darnit-core. Baseline: TOML requirements, `project_reference`, removal of payload templates and `CONTROL_REFERENCE_MAPPING`, its own `tools.py`/orchestrator wiring. CSL: its own `mcp_tools.py`. No core import of implementations. | Pass |
| II. Conservative-by-Default | "Fixed" requires a passing re-check; INCONCLUSIVE/skip never counts as success; unreadable state means no write; unknown protection fields refuse rather than risk loss; context guard fails closed. | Pass |
| III. TOML-First Architecture | Platform fixes declared as requirements in TOML; references, `effects`/`offline`, and `safe` in TOML; removed schema properties cannot be declared. | Pass |
| IV. Never Guess User Values | Unchanged from 042: remediation still consumes only usable values; approvals are not context confirmations and are not stored as such. Policy `auto` concerns platform changes, not user-judgment values. | Pass |
| V. Sieve Pipeline Integrity | Sieve unchanged; re-check is a subset audit with cache writes disabled. | Pass |
| Development workflow | `framework-design.md` sections 4 and a new remediation-policy section first; lint, tests, `validate_sync` (extended for removed properties and exec platform commands). | Pass (planned) |

Post-design re-check: unchanged. `auto` is an operator decision recorded in every report, and still does read-first, minimal changes and read-back (FR-026). It does not relax Principle II, because outcomes still need a re-check.

## Project Structure

### Documentation (this feature)

```text
specs/043-remediation-safety/
|-- plan.md
|-- research.md          # R1-R14
|-- data-model.md        # policy, target, change set, file change, outcome, run, manifest
|-- quickstart.md        # V1-V7
|-- contracts/
|   `-- remediation-interfaces.md
|-- checklists/
|   `-- requirements.md
`-- tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
packages/darnit/src/darnit/
|-- config/
|   |-- operator/schema.py        # RemediationSettings (platform, high_impact)
|   |-- framework_schema.py       # platform_setting schema; exec effects/offline; file_create project_reference;
|   |                             # remove api_call, requires_confirmation, dry_run_supported, dry_run_command
|   `-- resolver.py               # update_config_after_file_create: record only if empty or equal (or replaced by writer)
|-- core/utils.py                 # gh_api_write; responder (method, endpoint, body)
|-- remediation/
|   |-- platform/                 # NEW
|   |   |-- engine.py             # read -> plan -> policy/approval -> apply -> read back
|   |   |-- targets.py            # branch_protection (GET->PUT translator, granular endpoints), repository, vulnerability_reporting
|   |   |-- model.py              # PlatformTarget, ObservedState, ChangeOperation, ChangeSet, digests
|   |   `-- policy.py             # resolve policy from operator config; approval check
|   |-- plan.py                   # NEW: FileChange, PlanItem, RemediationRun, RemediationOutcome
|   |-- manifest.py               # NEW: operator-side run manifest
|   |-- executor.py               # plan/apply modes; single writer; conflict and ignore checks; outcomes
|   `-- github.py                 # enable_branch_protection -> engine wrapper
|-- sieve/
|   |-- handler_registry.py       # HandlerContext.mode; supports_plan flag
|   `-- builtin_handlers.py       # file_create/yaml_inject/project_update/exec plan mode; platform_setting; api_call removed
|-- tools/audit.py                # run_sieve_audit(write_cache=False) for re-checks
|-- server/tools/git_operations.py  # run_id; manifest-only staging; no stash; state refusals; trailer
|-- cli.py                        # darnit run: policy, /dev/tty approval
`-- skills/darnit-remediate/SKILL.md, skills/darnit-comply/SKILL.md  # preview with digests; pass only approved digests

packages/darnit-baseline/src/darnit_baseline/
|-- openssf-baseline.toml         # platform_setting requirements; AC-01.01/AC-02.01 manual; project_reference; safe/effects
|-- templates/*_payload.tmpl      # removed (7)
|-- config/mappings.py            # CONTROL_REFERENCE_MAPPING removed
|-- remediation/orchestrator.py   # typed RemediationRun; re-check; fail-closed guard; approvals
`-- tools.py                      # remediate_audit_findings(approve), enable_branch_protection(dry_run=True, branch=None, approve)

packages/darnit-csl/src/darnit_csl/mcp_tools.py   # dry_run=True; README edit as FileChange
packages/darnit-reproducibility/.../reproducibility.toml  # uv lock: effects/offline declaration (not offline -> not previewable)

docs/architecture/framework-design.md   # updated first
scripts/validate_sync.py                # removed properties; exec platform-command check
```

**Structure Decision**: Single Python workspace. New logic concentrates in `remediation/platform/` (one engine for every platform write), `remediation/plan.py` + `manifest.py` (one change model and one record of writes), and the executor as the single writer. Everything else is rewiring writers and reporters onto them.

## Sequencing and dependencies

1. `framework-design.md`: plan/apply protocol, `platform_setting`, requirements per target, exec `effects`/`offline`, removed properties, remediation policy and approval, outcomes, git rules.
2. Platform engine (US1, P1):
   1. `gh_api_write` and the write responder;
   2. targets with readers and comparators;
   3. the branch-protection translator and planner;
   4. digests, policy and approval;
   5. read-back;
   6. `enable_branch_protection` and the TOML moved onto it;
   7. remove `api_call` and the payload templates; AC-01.01 and AC-02.01 become manual.
3. Version-control safety (US2, P1): the run manifest; the git tools rewritten (`run_id`, staging, no stash, refusals, trailer); the PR tool pushes only the branch.
4. Plan/apply protocol and the single writer (US5): `HandlerContext.mode`; handler plan outputs; the executor writes and checks for conflicts and ignore rules; exec `effects`/`offline` with a scratch-copy preview; the contract test over every shipped remediation.
5. Outcomes and re-check (US4): typed outcomes; `run_sieve_audit(write_cache=False)`; orchestrator and tool output from outcomes; commit and PR gates on outcomes; fail-closed guard.
6. Project references (US3): `project_reference` in TOML; mapping table removed; record only on create, when empty or equal; Baseline validation test.
7. Schema cleanup and entry points:
   - remove `requires_confirmation`, `dry_run_supported` and `dry_run_command`;
   - enforce `safe`;
   - CSL `dry_run`;
   - `darnit run` approval;
   - `create_security_policy` through the writer;
   - skills;
   - `validate_sync` checks.
8. Update tests that pin current behavior; quickstart V1-V7.

Steps 2 and 3 are independent and can proceed in parallel; 4 precedes 5; 6 depends on 3 (manifest) and 4 (single writer).

## Follow-ups (out of scope)

- Atomic rollback across the handlers of one remediation (#420).
- What AC-02.01, LE-01.01, DO-03.01 and other controls measure (#508, #511, #513, the catalog refresh). This feature only stops their remediations from claiming unrelated fixes.
- Platform remediation for forges other than GitHub (#155 is related).
- Rendered-template validation (#152). It touches the same executor, so sequence it after this feature.

## Complexity Tracking

No constitution violations; no entries.
