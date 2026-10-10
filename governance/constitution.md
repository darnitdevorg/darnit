# Constitution

These are the non-negotiable rules for this repository. Every rule carries an
enforcement id that maps to a row in `ENFORCEMENT.md`. A rule with no
enforcing check is a wish, not a rule, and it will be ignored.

Changing a rule requires an ADR in `decisions/`. Do not edit a rule in place
without one.

This document is deliberately short. Every agent session imports it, so each
rule here costs context in every session, forever. Before adding anything,
read `where-decisions-live.md`: most decisions belong somewhere else.

What darnit is, and is not, is decided in
[ADR-0001](decisions/0001-what-darnit-is.md). The S rules below are the parts
of that decision a reviewer or a check can hold a change to.

This document sits under the project's [Technical Charter](../CHARTER.md) and
[GOVERNANCE.md](../GOVERNANCE.md), which govern who decides. This document
governs what a change must satisfy.

---

## 1. Scope

**S1.** A control MUST check or change the setup of the project it audits:
its files, its CI configuration, its platform settings and its declared
project data. A control MUST NOT run a tool to judge that tool's result, or
judge the project's runtime behavior. Out of scope, for example: whether
history satisfies a gittuf policy, whether recent commits are signed, whether
a scanner comes back clean, whether a build is hermetic or reproducible.
Whether gittuf is set up, a scanner is configured to run, or a lockfile and a
provenance step exist is in scope. `[ENF-S1]`

**S2.** Unverified is not compliant. A level is compliant only when every
applicable control at that level is PASS. WARN, ERROR, PENDING, an unhonored
claim and a control that failed to load all count against it. `[ENF-S2]`

**S3.** darnit MUST NOT conclude a value that needs a person's judgment
(`auto_detect = false`). Detection may propose a candidate. Only a person's
confirmation makes a value usable, and an unusable value MUST NOT reach a
verdict, a remediation input, an attestation or a write. `[ENF-S3]`

**S4.** Remediation MUST write only through the remediation executor, MUST
record every write in the run manifest, and MUST NOT write a path with
uncommitted user changes. `[ENF-S4]`

**S5.** The audited repository is untrusted input. Nothing in it, including its
own configuration files and its version-control remotes, configures darnit or
grants trust. Trust and tool configuration come only from operator
configuration or verified CI metadata. `[ENF-S5]`

**S6.** A step MUST conclude only an outcome in its effective set: its
registered ceiling, narrowed by `concludes`, widened only by a promotion that
the corpus backs with zero false PASS results. A model judgment MUST NOT
conclude PASS. No plugin MAY replace a core step type. `[ENF-S6]`

---

## 2. Framework shape

**F1.** The `darnit` package MUST NOT import an implementation package. The
framework reaches implementations only through plugin discovery and the
`ComplianceImplementation` protocol. `[ENF-F1]`

**F2.** Controls are defined in a framework's TOML. Python adds step types,
remediation handlers and tools; it does not define controls. `[ENF-F2]`

**F3.** No new extension point (a Protocol, entry-point group, registry, store
kind or plugin hook) until two implementations need it, or an ADR records why
the seam is needed before the second. `[ENF-F3]`

**F4.** Everything darnit accepts MUST have a reader: every field of the
framework TOML schema and of operator configuration, every step setting,
every CLI flag and every MCP tool parameter is read by production code. A
setting that changes nothing is removed, not documented. `[ENF-F4]`

**F5.** Every function in `packages/*/src` MUST be executed by a test, and
every shipped default implementation of a Protocol MUST be executed by a test
that reaches it through a real entry point (the CLI, an MCP tool or
`run_sieve_audit`), not through a test double. `[ENF-F5]`

**F6.** A change MUST NOT add a type error. An `attr-defined`, `call-arg` or
`name-defined` error MUST NOT be added even to the baseline. `[ENF-F6]`

---

## 3. Contracts

**C1.** darnit's public contracts are: the framework TOML schema, the operator
configuration schema, the plugin protocol, the CLI, the MCP tool surface and
the output formats (JSON, SARIF, attestation predicate). A change to one MUST
land its ADR or feature spec before or with the code, and a breaking change
MUST appear under a **BREAKING** entry in `CHANGELOG.md`. `[ENF-C1]`

---

## 4. Contributors and agents

**A1.** AI-assisted contributions follow [AI_POLICY.md](../AI_POLICY.md):
attribution by an `Assisted-by` trailer, never an AI `Co-authored-by` or
`Signed-off-by`, and disclosure in the pull request. `[ENF-A1]`

**A2.** `governance/` is tier-1. A change there MUST carry the `tier-1` label,
which records that a maintainer decided it, before it merges. An agent MUST NOT
change `governance/` unless a maintainer asked for that change. `[ENF-A2]`

**A3.** A contributor (person or agent) who cannot satisfy a rule MUST stop and
file an issue describing the conflict. They MUST NOT weaken a check, skip a
test or add a suppression to make a run pass. `[ENF-A3]`

**A4.** Every normative statement in `governance/` MUST carry an enforcement id
with a row in `ENFORCEMENT.md`. If you cannot name the check, you do not have a
rule. `[ENF-A4]`

**R1.** A change MUST reach `main` only through a pull request whose required
checks passed on its head. `[ENF-R1]`
