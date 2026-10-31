# ADR-0002: Governance is a short constitution whose rules name their enforcement

- Status: proposed
- Date: 2026-10-12
- Decided by: the TSC, because the Charter (2.g.vii) gives it policies and
  processes for contributing.
- Rule impact: creates `governance/` and the rules in `constitution.md`.
  Retires the Spec Kit constitution as a separately edited document.

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

None of these documents says which of its statements anything enforces, and
the gaps showed.

- The 2026-10-10 wiring audit found rules that nothing enforced, and a CI type
  check that could not fail.
- Two days later, CI turned out to have been running only 2,390 of 5,164
  tests (#591). It selected tests by markers that most tests did not carry, so
  none of the safety suites behind features 040-044 had ever run in CI.
- `main` requires no status checks, so even the checks that did run blocked
  nothing.

darnit's contributors use several coding agents (Claude, Gemini, Grok,
OpenAI Codex), and most of the code is written with one. A rule that only a
person remembers does not reach the agent writing the change. A rule that
only an agent applies can be skipped by the next agent.

## Decision

1. **`governance/` holds the rules.** It contains:
   - `constitution.md`: the rules;
   - `ENFORCEMENT.md`: one row per rule;
   - `where-decisions-live.md`;
   - `decisions/`: the ADRs.

   A change to it needs a code owner's approval, and the TSC's approval where
   the Charter gives the TSC the decision (A3).
2. **Every rule names how it is enforced, and tests come first.**
   - **test:** a deterministic CI check, preferred wherever one is possible.
   - **agent:** the rule is in every agent's instructions, applied with a
     yes/no review question.
   - **human:** a maintainer applies it in review.

   A rule enforced only by agents or humans needs a stated reason why a test
   is impossible or disproportionate, a review question and an owner, and it
   is reviewed for deletion if it catches nothing for two milestones. Most
   rules that look like they need judgment have a deterministic part (an
   inventory, a count that only shrinks, a snapshot diff), and that part is
   built as a test.
3. **A row says `enforced` only when it is proven.** A row is `enforced` only
   when its check runs in CI and a pull request built to violate it was shown
   to fail. A check that runs but has not been shown to fail is `running`. The
   #591 gap is the reason: tests that were assumed to run did not.
4. **Every agent reads the same rules.** `AGENTS.md` at the repository root is
   the agent instruction file, because Codex, Cursor, Copilot and others read
   it, and Gemini can be pointed at it. It carries:
   - a copy of the constitution between markers, which a test keeps identical
     to `governance/constitution.md`;
   - where to read before touching what;
   - the test and lint commands;
   - the stop-and-file protocol (A1);
   - the attribution lines from AI_POLICY.

   `CLAUDE.md` becomes a short file that imports `AGENTS.md` and adds only
   Claude-specific notes. The Spec Kit constitution becomes a pointer to
   `governance/`, and nobody runs `/speckit.constitution`.
5. **The pull request template asks questions that can be checked:**
   - which rules the change could affect;
   - where a new flag, parameter or setting is read;
   - whether a contract snapshot changed, and its BREAKING entry;
   - the issue behind any new suppression or allow-list entry;
   - the AI tool and model used, and the parts it wrote.
6. **An agent review is a required check, but never an approval.**
   - An independent agent reviews each pull request against the
     constitution's review questions, and reports possible violations citing
     the rule, file and line. It runs in a fresh session the author cannot
     steer, under its own identity. It treats pull request text as untrusted,
     and never reads secrets from a fork's code.
   - Its findings are claims, like a model judgment in darnit. A blocking
     finding stops the merge until a maintainer other than the author resolves
     it. A clean review lets the author merge only on paths that CODEOWNERS
     does not own.
   - On owned paths, a code owner other than the author always approves. An
     agent's review is never enough on its own where a wrong merge is
     expensive. This mirrors darnit's rule that a model judgment never
     concludes PASS by itself.
7. **The Spec Kit constitution's principles become rules:**
   - Plugin Separation and TOML-First become F1.
   - Conservative-by-Default and Sieve Pipeline Integrity become S2. The
     latter's "4-phase ordering MUST be respected" clause is dropped: the
     framework enforces no phase order, and RFC-0001 replaces phases.
   - Never Guess User Values becomes S3.

   New rules not in the Spec Kit constitution:
   - S1, scope;
   - S4, remediation does no harm;
   - S5, the audited repository is untrusted;
   - F2, one execution path;
   - F3, shipped code can run;
   - F4, declared dependencies;
   - R1, merge gate;
   - A1, ratchets.
8. **`framework-design.md` stops being "authoritative".** A later ADR on
   consolidating the docs moves its normative content into rules, ADRs or
   contract documents, its descriptive content into design notes, and deletes
   what describes removed or out-of-scope features. Until then,
   `scripts/validate_sync.py` keeps reading it.
9. **`governance/` is not a Spec Kit feature.**
   - It is plain files, changed by pull requests, with no `specs/NNN` folder,
     tasks or feature number. Spec Kit organizes work that ships behavior;
     governance changes when a rule is wrong or a feature needs a decision,
     and a feature stream would invent a backlog for it.
   - A feature that needs a rule or an ADR records the need in its own spec,
     and the rule lands here.
   - Building a check is a plain pull request that cites its `ENF-` row and
     links the pull request that shows it failing.
10. **RFCs and project governance are unchanged.** An RFC (`docs/rfcs/`) is a
    proposal under discussion, and an accepted RFC becomes an ADR.
    `CHARTER.md`, `GOVERNANCE.md` and the TSC process still decide who
    decides.

## Open question for the TSC

R1 lets an author merge a change to a path CODEOWNERS does not own, after the
required checks and an independent agent review pass. GOVERNANCE.md says "one
maintainer approval required" for every pull request. The TSC decides between:

- **R1 as written.** GOVERNANCE.md is amended to match.
- **A second maintainer on every pull request.** The agent review stays
  advisory.

Whichever it chooses, R1 falls back to a second maintainer on every pull
request until the `agent-review` check exists.

## Alternatives

**Keep the Spec Kit constitution as the rule source, and add enforcement ids
to it.** It is the file Spec Kit's commands rewrite, it is 347 lines, and it
mixes rules with process and history.

**Make `framework-design.md` the rule source.** At 2,369 lines it is the
wallpaper a short constitution exists to avoid, and much of it describes code
that no longer exists.

**Allow only tested rules.** That is the cleanest version, but some rules have
a judgment part no test reaches. Two examples: whether a new step's answer can
change without the setup changing, and whether a decision landed before the
change. Leaving those unwritten would leave them to memory. The agent and
human modes, with their conditions, keep them written down and small.

**Instruct agents in `CLAUDE.md` only.** Contributors use agents that do not
read it.

## Consequences

- **Statements stop binding.** A MUST in a design doc or a spec no longer
  binds; only a rule with a row does.
- **The table is mostly `planned`.** That is honest, but it means the rules
  bind review now and CI later.
- **The first checks find real defects.** On `main` today, the planned checks
  would flag:
  - 6 unread parameters and flags;
  - 201 type errors;
  - 101 functions no test executes;
  - 5 framework-name literals in core;
  - a test suite that writes 377 files to HOME.

  Each check starts with today's findings as an allow-list that can only
  shrink. That is work, spread over the build order in `ENFORCEMENT.md`.
- **Nobody merges their own change unreviewed.**
  - On paths where a wrong merge is expensive, R1 requires the other
    maintainer, and includes administrators. With two maintainers, that is a
    real constraint on speed.
  - Elsewhere, an independent agent review stands in for the second person,
    and a weekly digest lets the maintainers check its calls after the
    fact.
- **Blocked work stays visible.** Agents stop and file instead of editing a
  rule, so some work waits for a person.

## Enforcement

This ADR creates the rules in `constitution.md`. Their rows are in
`ENFORCEMENT.md`. The `AGENTS.md` copy test and the Spec Kit pointer check are
part of ENF-A3's governance_lint.
