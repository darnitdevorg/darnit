# Implementation Plan: Operator Configuration and Trust Model

**Branch**: `040-operator-config-trust` | **Date**: 2026-09-26 | **Spec**: [spec.md](spec.md)

**Input**: Feature specification from `/specs/040-operator-config-trust/spec.md`

**Note**: This template is filled in by the `/speckit-plan` command; its definition describes the execution workflow.

## Summary

Give tool configuration a home owned by whoever runs darnit (user-level operator configuration found identically by the CLI, MCP server, and harness), move project assertions from the repository-level `.baseline.toml` into `.project/darnit.yaml`, and retire `.baseline.toml` after one deprecation release. Project-asserted not-applicable results -- explicit claims or applicability-changing project data -- count only for repositories the operator trusts and only when no declared evidence contradicts them; otherwise they are pending and non-compliant until the operator confirms them. Trust identity comes from the operator's target or CI metadata, never from the checkout's own remotes; confirmations are stored on the operator side. Reports and attestations label every assertion-backed N/A. Design decisions are in [research.md](research.md).

## Technical Context

**Language/Version**: Python 3.11/3.12 (workspace targets)

**Primary Dependencies**: `tomllib` (stdlib), `pydantic >= 2` (existing; `extra="forbid"` for the new models). No new runtime dependencies: per-user config location extends the existing `darnit/stores/defaults/platform_paths.py`; repository-identity normalization is a small in-tree helper.

**Storage**: Filesystem only. Operator configuration: one TOML file per user (research R1). Confirmations: a file under the existing darnit data root, keyed by canonical repository identity (research R6). Project assertions: `.project/darnit.yaml` in the audited repository (read-only input).

**Testing**: pytest (`uv run pytest tests/ --ignore=tests/integration/ -q`); CI-event simulation via environment variables and event-payload fixtures; scratch-repository end-to-end tests per [quickstart.md](quickstart.md).

**Target Platform**: Linux, macOS, Windows (permission check is POSIX-only; Windows warns, strict mode refuses).

**Project Type**: Library + CLI + MCP server + headless harness (single Python workspace).

**Performance Goals**: Operator configuration resolution, containment and permission checks add negligible time per audit (single file read and stat calls).

**Constraints**: No environment variable may grant trust (FR-008). Operator configuration is never read from inside the audited repository (FR-004). ASCII-only documentation. Changes to framework behavior update `docs/architecture/framework-design.md` first (constitution Development Workflow).

**Scale/Scope**: About 8 fixture `.baseline.toml` files and 17 test modules migrate; the parity-test corpus needs a new fixture marker; every audit-running driver path gains the trust decision and assertion evaluation.

## Constitution Check

*GATE: Must pass before Phase 0 research. Re-check after Phase 1 design.*

| Principle | Assessment | Status |
|---|---|---|
| I. Plugin Separation | All new code is in `packages/darnit` (core). Framework TOMLs gain an optional `contradicted_by` field; no implementation is imported by core. | Pass |
| II. Conservative-by-Default | Pending and unobtainable-evidence claims count as non-compliant; untrusted repositories cannot reduce the compliance denominator; unknown CI events are untrusted. | Pass |
| III. TOML-First Architecture | Contradicting evidence is declared in framework TOML; operator configuration is TOML. | Pass |
| IV. Never Guess User Values | Assertions are labelled with their origin and asserter; confirmations record who, when, and evidence; a repository-supplied claim is never treated as confirmed. | Pass |
| V. Sieve Pipeline Integrity | Pass ordering and conclusion rules are unchanged; operator pass overrides replace a mechanism rather than adding a new one; an assertion can only produce N/A, never PASS. | Pass |
| Architecture constraints | Changes span Layer 1 (applicability and N/A evaluation) and Layer 3 (MCP tool arguments and confirmation tool) without conflating them. | Pass |
| Development workflow | `framework-design.md` updated first; lint, tests, spec-sync validation required. | Pass (planned) |

Post-design re-check (after Phase 1): unchanged -- all gates pass. No complexity-tracking entries.

## Project Structure

### Documentation (this feature)

```text
specs/040-operator-config-trust/
|-- plan.md              # This file
|-- research.md          # Phase 0 decisions (R1-R8)
|-- data-model.md        # Phase 1 entities and assertion state machine
|-- quickstart.md        # Phase 1 validation guide
|-- contracts/
|   |-- operator-config.md   # File location, format, guarantees, permission check
|   |-- drivers-and-cli.md   # Flags, target identity, report fields, MCP behavior
|   `-- asserted-results.md  # Assertion sources, result fields, compliance math
|-- checklists/
|   `-- requirements.md
`-- tasks.md             # Phase 2 output (/speckit-tasks)
```

### Source Code (repository root)

```text
packages/darnit/src/darnit/
|-- config/
|   |-- operator/                 # NEW
|   |   |-- __init__.py
|   |   |-- schema.py             # OperatorConfig models (extra="forbid", schema_version)
|   |   |-- loader.py             # resolution order, containment + permission checks, digest
|   |   `-- migrate.py            # .baseline.toml -> .project/darnit.yaml + proposed fragment
|   |-- merger.py                 # deprecation-period reading of assertions only; ignored-settings report
|   `-- schema.py                 # .project/darnit.yaml controls: add optional asserted_by
|-- trust/                        # NEW
|   |-- identity.py               # canonical repository identity (host/ns/name), identity sources
|   |-- ci.py                     # CI platform/event detection, push-default-branch rule
|   |-- decision.py               # TrustDecision for a run
|   |-- assertions.py             # ProjectAssertion collection and outcome evaluation
|   `-- confirmations.py          # operator-side confirmation store (data root)
|-- tools/audit.py                # applying assertion outcomes to results and compliance; N/A labelling
|-- tools/audit_org.py            # operator configuration and trust decision per enumerated repository
|-- stores/defaults/platform_paths.py  # user config dir (XDG rules, absolute-only)
|-- server/ (factory, tools)      # --operator-config, per-call containment check, confirmation tool,
|                                 # ActionPlan tools (harness_loop.py)
|-- harness/driver.py             # --operator-config, trust decision in report
`-- cli.py                        # --operator-config, `config show|migrate|trust`, `install` scope

packages/darnit-baseline/src/darnit_baseline/
|-- openssf-baseline.toml         # contradicted_by on release-dependent controls; affects-list fixes
|-- tools.py                      # baseline audit and attestation tools pass operator config
|-- remediation/orchestrator.py   # uses assertion outcomes instead of raw N/A overrides
`-- attestation/predicate.py      # authority/asserter fields for assertion-backed N/A

docs/
|-- architecture/framework-design.md   # updated first: operator config, trust, assertions
|-- SECURITY_GUIDE.md                  # operator config replaces repository config guidance
`-- (skills) darnit-* SKILL.md         # user-scope registration guidance

tests/
|-- darnit/config/operator/       # loader, schema, containment, permissions, precedence
|-- darnit/trust/                 # identity normalization, CI rules, decisions, confirmations
|-- darnit/assertions/            # outcome state machine, context-value assertions, labelling
`-- darnit/parity/fixtures/       # new fixture marker replacing .baseline.toml
```

**Structure Decision**: Single Python workspace. New core modules under `darnit/config/operator/` and `darnit/trust/`; existing modules are modified in place. The baseline implementation changes only its TOML and attestation labelling.

## Sequencing and dependencies

1. **Prerequisite**: the change restricting what a repository's own configuration may set lands first (it provides the `trusted` parameter this feature feeds from operator configuration).
2. `framework-design.md` update (constitution workflow).
3. Operator configuration: schema, location, loader, checks, `config show` (User Story 1).
4. Repository identity and CI trust decisions (User Story 4, and prerequisite for 5).
5. Assertions in `.project/`, outcome state machine, context-value assertions, labelling, confirmations (User Stories 2 and 3).
6. Deprecation reading of `.baseline.toml`, `config migrate`, docs and skills (User Story 5).
7. Attestation labelling; coordinate with #492 so pending results are non-compliant in the attestation as well as the report.

## Follow-ups (out of scope)

- Organization-level policy source (#503).
- Upstream `.project/` proposal for an exemption/applicability field.
- Optional pinning of numeric platform repository IDs in `trust.repos`.
- Trust rules beyond `push-default-branch` (for example same-repository pull requests).

## Complexity Tracking

No constitution violations; no entries.
