# ADR-0003: Consolidate the docs into governance, contracts, design notes and user docs

- Status: proposed
- Date: 2026-10-10
- Rule impact: none directly. It moves normative text under A4, so every MUST
  that survives carries an enforcement id.

## Context

The repository has about 28,500 lines of active documentation in more than 100
files:

- root documents: 4,469 lines;
- `docs/`: 22,691 lines;
- package READMEs and skills: about 1,000 lines;
- the Spec Kit constitution: 347 lines.

Separately, `specs/` holds about 44,700 lines of Markdown.

Normative statements (MUST, SHALL, "authoritative") are spread across about 30
files, and three of those files call themselves authoritative:

- the Spec Kit constitution;
- `docs/architecture/framework-design.md`, which alone has 265 normative
  statements;
- `docs/architecture/README.md`.

An inventory on 2026-10-10 found nine places where these documents contradict
each other or the code:

- the phase ordering;
- whether unknown step keys load;
- whether WARN is remediated;
- a deleted `rules/catalog.py` described as live;
- stale handler lists;
- `.baseline.toml` compatibility;
- `[plugins]` placement;
- `[framework]` versus `[metadata]`;
- a stale Spec Kit pointer.

Many user docs still teach removed APIs. Some examples: `DeterministicPass`,
`main.py`, `baseline-mcp`, `PENDING_LLM`, and "62 controls / v2025.10.10"
(the baseline now has 66 controls, at v2026.02.19).

## Decision

### Layout

```
governance/            normative, tier-1
  constitution.md
  ENFORCEMENT.md
  where-decisions-live.md
  contracts/           behavior every implementation and plugin must keep
    results-and-authority.md     outcomes, ceilings, disposition, compliance, corpus
    framework-toml.md            schema, strict loading, step and remediation fields, CEL, when
    context-values.md            standing, confirmation, lapse, single writer
    remediation-safety.md        plan/apply, approval, platform engine, outcomes, manifest, VCS
    operator-config-and-trust.md operator config, trust, claims, plugin trust
    plugin-protocol.md           protocol members, registration, module-path policy, packaging
  decisions/           ADRs
design/                descriptive notes on how components work today; no MUST
  overview.md, sieve.md, audit-pipeline.md, context.md, reporting.md,
  remediation-engine.md, stores.md, agent-graph.md, workflow.md
docs/                  user and author docs; every command and key they name exists (F4)
  install/  user/  plugin-authoring/  contributing/  archive/
```

### Rules for this layout

- **Contracts.** A contract keeps only statements that carry an enforcement
  id (A4). An unenforced MUST becomes either a row with status `planned` or
  `unbuilt`, or descriptive text in `design/`. That keeps the contracts from
  regrowing into another 2,369-line specification.
- **Specs.** `specs/NNN-*/` folders become implementation records. A spec's
  open tasks are either finished or closed with a note. Specs are not
  rewritten.
- **Dogfood files stay where they are.** These files are darnit's own
  compliance evidence:
  - in `docs/`: `DEPENDENCIES.md`, `SAST-POLICY.md`, `SCA-POLICY.md`,
    `SECRETS-POLICY.md`, `SECURITY-ASSESSMENT.md`, `TEST-REQUIREMENTS.md`, and
    `threatmodel/`;
  - at the root: `SECURITY.md`, `THREAT_MODEL.md`, `CONTRIBUTING.md`,
    `GOVERNANCE.md`, `README.md`, `SUPPORT.md`.

  `openssf-baseline.toml` and `.project/project.yaml` look for them at these
  exact paths.
- **LF documents are unchanged.** `CHARTER.md`, `GOVERNANCE.md`,
  `TECHNICAL-STEERING-COMMITTEE.md`, `AI_POLICY.md` and `CHANGELOG.md` stay as
  they are. The one change is that GOVERNANCE.md's "breaking changes require an
  RFC" now points at the RFC-then-ADR flow.

### `framework-design.md`

The specification is about 75% contract, 15% description and 10% history or
out-of-scope material. Its section numbers survive as anchors in the new
contracts, because test docstrings cite them.

| Sections | Goes to |
|---|---|
| 1 Purpose, philosophy | replaced by ADR-0001 and the constitution |
| 1.3 diagram, 5.1 and 5.3 execution model, 11.1-11.3, 12, 13 | `design/` |
| 2 schema, 3.2-3.8 field and ceiling tables, 4.3, 4.4, 4.6, 4.7 | `contracts/framework-toml.md` |
| 3.0-3.1 outcomes, ceilings, disposition, order; 5.2, 5.4, 5.5 | `contracts/results-and-authority.md` (without the Witness passages) |
| 4.1, 4.2, 4.5, 15 | `contracts/remediation-safety.md` |
| 6.3-6.5, 10.1-10.3, 10.5 | `contracts/plugin-protocol.md` |
| 6.6, 14 | `contracts/operator-config-and-trust.md` |
| 7.4-7.11 | `contracts/context-values.md` |
| 7.1-7.3, 4.8, 6.1-6.2, Appendix A | `docs/plugin-authoring/` |
| 8 SARIF mapping | `design/reporting.md` |
| 9 sync enforcement | `ENFORCEMENT.md`. Its check finds 8 hard-coded handler names in the file, so it enforces almost nothing. |
| Appendix B (rules catalog migration) | deleted; the catalog no longer exists |
| Appendix C, version history | context for the ADRs below; otherwise removed (git keeps it) |

### Everything else

| Disposition | Files |
|---|---|
| Into `governance/contracts/` | `docs/architecture/`: `cel-expressions`, `conditional-controls`, `control-dependencies`, `external-templates`, `shared-handlers` (if shared handlers survive), `remediation-manual-guidance`, `github-api-remediation`, `remediation-audit-filtering` (after the WARN contradiction is decided), and the rule from `implementation-provided-tools` |
| Into `design/` | `ARCHITECTURE.md` (as `overview.md`); `docs/architecture/`: `audit-pipeline`, `audit-context-collection`, `context-collection`, `dot-project-integration`, `org-project-resolution`, `repo-identity-resolution`, `framework-agnostic-reporting`; `docs/`: `WORKFLOW.md`, `agent-graph.md`, a short version of `design/CONTEXT_SIEVE_DESIGN.md` |
| Into the darnit-baseline package docs | `ci-workflow-templates`, `declarative-file-templates`, `policy-doc-templates`, and `ATTESTATION_SPEC.md` (refreshed as the predicate contract) |
| Merged into `docs/plugin-authoring/` | `IMPLEMENTATION_GUIDE.md` (cut by about half), `HANDLER_AUTHORING.md`, `CEL_CONTEXT.md` together with `getting-started/cel-reference.md`, `getting-started/implementation-development.md`, both tutorials, `packaging-plugins.md` (the entry point), `plugin-authoring/stores.md` |
| Merged into `docs/contributing/` | `GETTING_STARTED.md`, `getting-started/{README,framework-development,development-workflow,environment-setup,testing,troubleshooting}`, the MCP development section of CONTRIBUTING.md |
| Into `docs/user/` | `using-skills`, `SECURITY_GUIDE.md` (linking the contracts instead of restating them), `MIGRATION_GUIDE.md`, `CNCF_METADATA.md`, `CSL_ONBOARDING.md` |
| Recorded as ADRs | `docs/decisions/cel-library-evaluation.md`; the accepted parts of RFC-0001; and `docs/design/builtin-tool-factories.md` as a proposed ADR once its owner wants it reviewed |
| `docs/archive/` (excluded from `test_doc_step_examples`) | `DECISION_FLOWS.md`, `ARCHITECTURE_RESEARCH_BRIEF.md`, `TEST_REPO_DESIGN.md`, `plugin-discovery-design.md`, `SARIF_DESIGN.md`, `design/CONTEXT_PROMPTS.md`, `design/cncf-project-spec-analysis.md` |
| Deleted | `design/reproducibility-attestation-system.md` (2,131 lines; out of scope under ADR-0001); `USAGE_GUIDE.md`; `GOVERNANCE_DOCS_DESIGN.md`; `TODO.md` (its items move to issues); `docs/examples/`; `docs/architecture/`: `context-documentation`, `sieve-handler-authoring`, `handler-pipeline`, `plugin-registry`, `README` |
| Rewritten in place | `README.md` (to about 300 lines, describing the scope as ADR-0001 states it); `CLAUDE.md` (to about 100 lines: import the constitution, routing, AI rules, test and lint commands); the package READMEs (control counts; the gittuf and reproducibility scope) |

Estimated result: about 12,700 lines of active docs, down from about 28,500,
with about 2,950 of them normative and in one place, instead of about 5,800
spread across 30 files.

### Decisions needed before contract text is written

1. Is phase ordering enforced? The proposal is no: dispatch follows the
   step list. Constitution V asserted otherwise.
2. Do unknown step keys load? They fail loading since feature 044.
   `handler-pipeline.md` is stale.
3. Is WARN remediated? `framework-design.md` 10.4 says only FAIL is.
   `remediation-audit-filtering.md` says everything not PASS. The proposal
   is FAIL only, which is what the code does.
4. Does `[plugins]` belong in framework TOML at all? The proposal is no: it
   moves to operator config, and the unused framework-schema field is
   removed (wiring audit CONFIG-18).
5. RFC-0001 promises that `.baseline.toml` keeps loading. That was superseded
   by #556, and is recorded as such in the ADR that records RFC-0001's
   accepted parts.

### ADRs to backfill

These record decisions that already shipped, so that the contracts can cite
them instead of restating the reasoning:

- CEL via cel-python
- authority per claim (RFC-0001 stages 0-1, features 041 and 044)
- propose-only judgment keys (features 018 and 042)
- the audited repository is untrusted, and `.baseline.toml` is removed (040, #556)
- remediation plan/apply and `platform_setting` replacing `api_call` (043)
- removal of dead subsystems and the protocol trim (#487, #451)
- PENDING and ERROR statuses (036, 041)

### Order of work

1. ADR-0001, ADR-0002 and this ADR are accepted, after the maintainers decide
   the open items.
2. CLAUDE.md is rewritten and the Spec Kit constitution becomes a pointer.
   This is small, and it stops agents from reading stale rules.
3. The contracts are written from `framework-design.md`, one file per pull
   request. `validate_sync.py`, the PR template and the test docstrings
   follow.
4. `design/` notes are written and moved.
5. The user docs are merged, archived, deleted and rewritten. The doc-example
   test is extended so that it also runs over the merged docs.

## Alternatives

**Keep `framework-design.md` and fix it.** It would keep being the place where
every feature appends a section. Rejected for the reasons in ADR-0002.

**Treat the tests as the only contract and make all prose descriptive.** This
is honest, but plugin authors and reviewers then have no readable statement of
the behavior they must keep. Rejected in favor of contracts restricted to
enforced statements.

## Consequences

- **Links break.** Many links and test-docstring citations change. Keeping the
  section numbers as anchors limits the breakage, but some will still be
  missed.
- **Removed docs lose history in place.** Their history stays in git and
  `docs/archive/`.
- **The work is large.** About five pull requests for the contracts, and two
  or three for the user docs.

## Enforcement

None new. Contracts are subject to A4 (`ENF-A4`) and user docs to F4
(`ENF-F4`).
