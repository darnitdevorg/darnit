# Constitution

These are the non-negotiable rules for this repository. Every rule carries an
enforcement id that maps to a row in `ENFORCEMENT.md`. Each row says how the
rule is enforced and how far that enforcement reaches today.

Changing a rule requires an ADR in `decisions/`. Do not edit a rule in place
without one.

This document is deliberately short. Every agent session loads it, so each
rule costs context in every session, forever. Before adding a rule, read
`where-decisions-live.md`: most decisions belong somewhere else.

What darnit is, and is not, is decided in
[ADR-0001](decisions/0001-what-darnit-is.md). This document sits under the
project's [Technical Charter](../CHARTER.md) and
[GOVERNANCE.md](../GOVERNANCE.md), which decide who decides. This document
decides what a change must satisfy.

## How rules are enforced

Every rule names one or more enforcement modes. A deterministic check is
always preferred.

- **test**: a check in CI that fails on a violation, and has been shown to.
- **agent**: the rule is in every agent's instructions (`AGENTS.md`), and the
  agent applies it while writing and reviewing, using the yes/no question in
  the rule's row.
- **human**: a maintainer applies it in review, and is accountable for it.

A rule may rely on agent or human enforcement alone only if its row says why a
test is impossible or disproportionate, gives the yes/no question a reviewer
answers from the diff, and names an owner. A rule enforced that way that
catches nothing for two milestones is reviewed for deletion. A rule whose
check cannot fail is not enforced.

---

## 1. Scope and correctness

**S1.** A control's result MUST depend only on the audited project's setup:
its files, its CI configuration, its platform settings (read, never changed by
a check) and its confirmed project data. The same setup MUST give the same
result on any machine, at any time, with any tool version darnit supports. A
PASS states that a practice is set up, never that its outcome holds: for
example, that gittuf is set up, not that history satisfies the policy; that a
scanner runs in CI, not that its findings are clean. `[ENF-S1]`

**S2.** No false PASS. A step MUST conclude only an outcome in its effective
set: its registered ceiling, narrowed by `concludes`, widened only by a
promotion that the corpus backs with zero false PASS results. A model judgment
MUST NOT conclude PASS. No plugin MAY replace a core step type. A level is
compliant only when every applicable control at that level is PASS. WARN,
ERROR, PENDING, an unhonored claim and a control that failed to load all count
against it. `[ENF-S2]`

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

---

## 2. Framework shape

**F1.** The core (`packages/darnit`) MUST NOT import or name an implementation
package or a framework. The default framework is one named constant. Controls
are data: only a framework's TOML defines them, and Python adds step types,
remediation handlers and tools. `[ENF-F1]`

**F2.** There is one execution path. Every entry point that audits or
remediates (the CLI, each framework's MCP tools, the builtin tools, the
harness, `darnit run`) MUST resolve framework, level, tags, profile,
include/exclude and output format through one shared resolver, and MUST give
the same controls and statuses on the parity fixtures. `[ENF-F2]`

**F3.** Shipped code can run. Everything darnit accepts MUST have a production
reader: every CLI flag, MCP tool parameter, step setting and configuration
field. Every function in a shipped package MUST be executed by a test, and a
shipped default implementation of a Protocol by a test that reaches it through
a real entry point. A change MUST NOT add a type error. `[ENF-F3]`

**F4.** Each published package, installed from its built wheel without
development dependencies, MUST run an audit with no import error. `[ENF-F4]`

---

## 3. Contracts

**C1.** darnit's public contracts are: the CLI, the MCP tool surface, the
framework TOML schema, the operator configuration schema, the plugin protocol
and the output formats (JSON, SARIF, attestation predicate). A change to a
contract MUST be visible in review, MUST land with or after its ADR or feature
spec, and, when it breaks a user, MUST appear under a **BREAKING** entry in
`CHANGELOG.md`. Breaking changes also follow GOVERNANCE.md's RFC process.
`[ENF-C1]`

---

## 4. Process

**R1.** A change MUST reach `main` only through a pull request. The required
checks MUST pass on its head, and they include the whole test suite, run
hermetically: no real HOME, no network, no dependence on CI environment
variables. The pull request MUST be approved by a maintainer other than its
author, and administrators are not exempt. The one exception is a merge from
a GitHub security advisory, which is recorded in the advisory. `[ENF-R1]`

**A1.** Every ratchet only tightens: suppressions, skips, baselines,
allow-lists, the extension-point inventory and CI's test selection. Loosening
one requires a maintainer-approved pull request that links an issue. A
contributor (person or agent) who cannot satisfy a rule MUST stop and file an
issue that names the rule and the conflict, and MUST NOT weaken a check to
make a run pass. `[ENF-A1]`

**A2.** Contributions follow [AI_POLICY.md](../AI_POLICY.md). Committed files,
pull request and issue text, and darnit's own output MUST NOT contain local
filesystem paths, an auditor's personal data, credentials, or the names of
private projects. `[ENF-A2]`

**A3.** A change to `governance/` MUST be approved by a code owner of
`governance/`. Where the Charter gives the decision to the TSC (scope, and
contribution policy), the change MUST be approved by a majority of the TSC's
voting members, recorded as pull request approvals as GOVERNANCE.md
describes. Every MUST in `governance/` carries an enforcement id with a row in
`ENFORCEMENT.md`. An agent MUST NOT change `governance/` unless a maintainer
asked it to. `[ENF-A3]`
