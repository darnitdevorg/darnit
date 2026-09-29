# Implementation Plan: Candidate Integrity for Project Values

**Branch**: `042-candidate-integrity` | **Date**: 2026-09-29 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/042-candidate-integrity/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Make project context values carry their standing (confirmed, candidate, concluded, unknown) from storage to every consumer, and make reads side-effect free. A single resolver produces a `ResolvedContext` whose `usable()` mapping (confirmed values plus concluded values of detectable keys) is the only thing verification, remediation, the harness, and attestations may read. Detection only proposes candidates for judgment keys; auto-accept never writes. Confirmations are recorded with who, when, basis, last-validated, and optional expiry: in `.project/darnit.yaml` for trusted repositories, operator-side (feature 040 store) otherwise. Values stored by earlier versions without a record load as candidates and can be confirmed or rejected in one review call. Prompts carry candidates as labelled data and accept them by digest, never by echoing the value into an executable call. Detection fallbacks apply only to genuine negatives, the CI provider has one name and vocabulary, and writers never replace or reformat a user-authored project file. Design decisions are in [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.11/3.12 (workspace targets)

**Primary Dependencies**: existing only -- `pydantic >= 2`, `ruamel.yaml` (already a darnit-core dependency, for round-trip writes), `PyYAML`, `jinja2` (remediation templates), `cel-python` (detect filters). No new runtime dependencies.

**Storage**: Filesystem. Context values and in-repository confirmation records in `.project/darnit.yaml`; the project's `.project/project.yaml` is read and, only by applied remediation, patched in place; operator-side records in the feature 040 store (`trust/confirmations.json`, claim `context_value`).

**Testing**: pytest with scratch repositories built per test (the issue reproductions), tree snapshots to assert no writes, isolated operator config and data root (existing autouse fixtures), recorded platform responses for release detection (feature 041 `RecordedGhApi`).

**Target Platform**: Linux, macOS, Windows (unchanged).

**Project Type**: Library + MCP server + headless harness (+ test CLI).

**Performance Goals**: Resolving context adds no platform calls beyond today's detection; `get_pending_data` stays a single detection pass per call.

**Constraints**: Principle IV (candidates never consumed; confirmations recorded with who, when, basis; optional expiry); Principle II (unconfirmed counts as unverified); Principle I (framework never imports implementations -- the Baseline and CSL changes are TOML and their own tool modules); `framework-design.md` first; ASCII-only; the upstream `.project/project.yaml` format stays conformant (darnit data only in `darnit.yaml`).

**Scale/Scope**: 9 Baseline context keys and 8 CSL keys; 4 read paths made side-effect free; 3 explicit write paths routed through one writer; ~6 consumers moved to `ResolvedContext`; prompt builders in `darnit_baseline/tools.py`, the remediation orchestrator, and the context validator; roughly 25 existing test files pin current behaviour (see research "Current state").

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment | Status |
|---|---|---|
| I. Plugin Separation | Resolver, writer, record format, and review live in darnit-core; Baseline changes are its TOML flags and its own `tools.py`; CSL changes are its own `mcp_tools.py`. No core import of implementations. | Pass |
| II. Conservative-by-Default | Unconfirmed and unknown keys are unverified; failed detection yields no value (no silent N/A); legacy stored values drop to candidates. | Pass |
| III. TOML-First Architecture | Judgment flags, vocabularies, and `validity_days` are TOML; tool parameters for context keys are generated from TOML definitions. | Pass |
| IV. Never Guess User Values | This feature enforces it end to end: detection proposes only; confirmation records who, when, and basis; optional expiry with reversion to candidate; prompts never contain candidates in executable form. | Pass |
| V. Sieve Pipeline Integrity | Unchanged; `when` and CEL inputs come from `usable()` only. | Pass |
| Development workflow | `framework-design.md` updated first; lint, tests, `validate_sync`. | Pass (planned) |

Post-design re-check: unchanged. The operator-side context record uses an explicit expiry instead of the operator policy default (research R4), so no operator-local setting changes a repository's reading.

## Project Structure

### Documentation (this feature)

```text
specs/042-candidate-integrity/
|-- plan.md
|-- research.md          # R1-R14
|-- data-model.md        # ResolvedValue, ResolvedContext, ConfirmationRecord, transitions
|-- quickstart.md
|-- contracts/
|   `-- context-confirmation-tools.md
|-- checklists/
|   `-- requirements.md
`-- tasks.md             # /speckit-tasks
```

### Source Code (repository root)

```text
packages/darnit/src/darnit/
|-- config/
|   |-- context_schema.py      # ResolvedValue, Origin, standing; ContextSource kept for storage parsing only
|   |-- context_resolve.py     # NEW: resolve_context -> ResolvedContext (usable, pending, stored_unconfirmed)
|   |-- context_writes.py      # NEW: the only writer of project context and in-repo confirmation records
|   |-- context_keys.py        # NEW: canonical names and vocabularies, legacy mapping, value digest
|   |-- context_storage.py     # get_pending_context pure; auto-accept write removed; strict detect only
|   |-- loader.py              # load_project_config_checked (absent | valid | invalid); round-trip writes
|   `-- framework_schema.py    # ContextDefinitionConfig.validity_days
|-- trust/confirmations.py     # record_confirmation(expires_at=...), context_bases section
|-- context/
|   |-- detectors.py           # detect_ci removed (detect_ci_provider is canonical)
|   `-- auto_detect.py         # collect_auto_context reads via resolver
|-- tools/audit.py             # applicability from ResolvedContext.usable(); next steps read-only
|-- harness/answer_sources.py, harness/driver.py   # usable() only; collect never persists
|-- server/tools/project_data.py, harness_loop.py, agent/graph.py  # writes via context_writes
|-- remediation/
|   |-- executor.py            # guarded context mapping -> ConfirmationRequired
|   |-- context_validator.py   # standing-based checks; placeholder-only prompts
|   `-- (orchestrator in baseline)
`-- skills/darnit-data/SKILL.md  # accept by digest; review flow; correct file locations

packages/darnit-baseline/src/darnit_baseline/
|-- openssf-baseline.toml      # maintainers, security_contact auto_detect = false; tool descriptions
|-- tools.py                   # get_pending_data payload; confirm_project_data params; no truncation
`-- remediation/orchestrator.py  # preflight: candidates as data; resolver-based template context

packages/darnit-csl/src/darnit_csl/mcp_tools.py  # no defaults for judgment parameters

docs/architecture/framework-design.md  # updated first
```

**Structure Decision**: Single Python workspace. New logic concentrates in three small darnit-core modules (resolve, write, keys) so the safety property has one read boundary and one write boundary; everything else is rewiring consumers onto them.

## Sequencing and dependencies

1. `framework-design.md`: context standing, confirmation records and locations, `validity_days`, review and accept-by-digest parameters.
2. Keys and digests (`context_keys.py`), then the resolver (`context_resolve.py`) reading storage, records (both locations), and per-run detection with strict fallbacks.
3. Loader tri-state and the single writer (`context_writes.py`) with round-trip YAML; remove the auto-accept write; route `confirm_project_data`, ActionPlan `collect_context`, and CLI collect through the writer.
4. Consumers onto `ResolvedContext`: audit applicability and 040 context-value assertions, harness answer source, remediation (guarded mapping, `when`), context validator, CSL tool defaults.
5. Prompts: `get_pending_data` payload, accept-by-digest, review lists, enum reachability, placeholder-only templates; generated `confirm_project_data` parameters; skill text.
6. Baseline TOML flags; test updates for pinned behaviours; quickstart validation.

## Follow-ups (out of scope)

- `attestation/predicate.py` reads `project_config.project_type` (not defined on `ProjectConfig`).
- CSL `coc_policy='org'` in tool text versus the `[csl, umbrella]` enum.
- Full upstream `.project/` schema conformance (#498).
- Remediation safety (#472-#475, #483, #420) is feature 043.

## Complexity Tracking

No constitution violations; no entries.
