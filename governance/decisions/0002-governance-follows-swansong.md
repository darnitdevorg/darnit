# ADR-0002: Governance is a short enforced constitution, ADRs and an enforcement table

- Status: proposed
- Date: 2026-10-10
- Rule impact: creates `governance/` and rules A1-A4 and R1. Retires the Spec
  Kit constitution as a separately edited document.

## Context

darnit's rules live in several places that disagree:

- **The Spec Kit constitution** (`.specify/memory/constitution.md`, version
  1.3.2, 347 lines).
- **`CLAUDE.md`** (415 lines, about half of it feature changelog).
- **`docs/architecture/framework-design.md`** (2,369 lines, titled "the
  authoritative specification").
- **About 22,000 lines of docs**, many of which still describe removed or
  never-built behavior.
- **`AI_POLICY.md`.**

None of these documents says which of its statements a check enforces. The
wiring audit found rules that nothing enforced: dead code, single writer,
confirmation. It also found a CI type check that could not fail.

The swansong project governs itself with a short constitution in which every
rule carries an enforcement id, an `ENFORCEMENT.md` that records each check's
honest status, immutable ADRs for reasoning, and a document that says where
each kind of decision lives. The maintainers asked darnit to follow it.

## Decision

1. **`governance/` is normative and tier-1.** It holds:
   - `constitution.md`: the rules;
   - `ENFORCEMENT.md`: one row per rule;
   - `where-decisions-live.md`;
   - `decisions/`: the ADRs.
2. **Every rule has an enforcement id and a row.** A statement no check can
   enforce is an ADR, not a rule.
3. **The Spec Kit constitution becomes a pointer to `governance/`,** so
   `/speckit.*` commands read the same rules. Nobody edits it directly, and
   nobody runs `/speckit.constitution`. Its principles map to rules:
   - Plugin Separation becomes F1.
   - Conservative-by-Default becomes S2.
   - TOML-First becomes F2.
   - Never Guess User Values becomes S3.
   - Sieve Pipeline Integrity becomes S6, the authority ceiling. Its
     "4-phase ordering MUST be respected" clause is dropped: the spec already
     says the framework enforces no phase order, and RFC-0001 replaces
     phases.
   - New rules not in the Spec Kit constitution: S1 (scope), S4 (remediation
     does no harm, from framework-design section 15) and S5 (the audited
     repository is untrusted, from section 14).
4. **`framework-design.md` stops being "authoritative".**
   - Its normative content becomes rules, ADRs or the contracts (C1).
   - Its descriptive content becomes design notes under `design/`.
   - Content about removed or out-of-scope features is deleted.
   - The docs consolidation plan (a later ADR) says where each section goes.
   - Until that plan lands, `scripts/validate_sync.py` keeps reading the
     handler-name registry from it.
5. **`CLAUDE.md` imports the constitution.** It keeps routing ("read X before
   touching Y") and a short "never" list. The feature changelog
   ("Active Technologies", "Recent Changes") is removed, because git and
   `CHANGELOG.md` already record it.
6. **`governance/` is not a Spec Kit feature.** It is plain files changed by
   tier-1 pull requests, with no `specs/NNN` folder, no tasks and no feature
   number. This follows swansong's ADR-0006. Spec Kit organizes work that
   ships behavior, as specify, plan, tasks, implement. Governance changes when
   a rule turns out wrong, or a feature needs a decision. It has no backlog of
   its own, and a feature stream would invent one. A feature that needs a
   rule or ADR records the need in its own spec, and the rule lands here.
   Building an enforcement check is code: a plain pull request that cites
   its `ENF-` row and shows the check failing on a built violation. It becomes
   a Spec Kit feature only if it is large enough to need a plan.
7. **RFCs stay where they are.** An RFC (`docs/rfcs/`) is a proposal under
   discussion; once accepted, it is recorded as an ADR.
8. **Project governance is unchanged.** `CHARTER.md`, `GOVERNANCE.md` and the
   TSC process keep deciding who decides. Adopting this ADR is an operational
   change made by maintainer consensus under `GOVERNANCE.md`.

## Alternatives

- **Keep the Spec Kit constitution as the rule source and add enforcement ids
  to it.** It stays the place Spec Kit's own commands rewrite, it is 347
  lines, and it mixes rules with process and history. Rejected.
- **Make `framework-design.md` the rule source.** At 2,369 lines it is the
  wallpaper a short constitution exists to avoid, and much of it describes
  code that no longer exists. Rejected.

## Consequences

- **Many current statements stop being rules.** A MUST in a design doc or a
  spec no longer binds; only a rule with a row does. That is the point, but it
  means reading `ENFORCEMENT.md` honestly. Most of darnit's checks are
  `planned` or `unbuilt` today, and CI blocks no merge until ENF-R1 is
  enforced.
- **The work is real.** Building checks F4, F5 and F6, consolidating the docs,
  and requiring CI on `main` are each more than a day of work.
- **Speed changes.** Agents that need a governance change stop and file an
  issue instead of editing the rule. That is slower, and the slowdown is
  deliberate.

## Enforcement

- **This ADR creates A1-A4 and R1.** Their rows are in `ENFORCEMENT.md`.
- **The Spec Kit pointer is planned under ENF-A4.** `governance_lint` will
  check that `.specify/memory/constitution.md` contains only the pointer.
