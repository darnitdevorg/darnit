# Where decisions live

Read this before writing a rule, a spec or a design doc. Without it, every
decision drifts into whichever document was open, the documents contradict
each other, and nobody, human or agent, can tell which one binds.

Adapted from swansong's `governance/where-decisions-live.md`.

## The first question: does it serve the scope?

Before deciding where a decision lives, apply
[ADR-0001](decisions/0001-what-darnit-is.md)'s admission test to what is being
decided:

1. Does it read or change a project's setup: files, CI configuration,
   platform settings or declared project data?
2. Would its answer stay the same across two runs with no change to that setup?
3. Does a control, a remediation or an interface that exists today need it?

A "no" to any of these means the work is out of scope, or premature. Stop,
and raise it in an issue before writing it down anywhere.

## The three questions

1. Is it a **rule** (something a change must satisfy) or a **decision**
   (a choice with reasons)?
2. Can you **name the check** that enforces it?
3. What must **already exist** for that check to mean anything, and what does
   the rule say before then?

| | Enforceable by a check | Not enforceable |
|---|---|---|
| **A rule for every change** | `constitution.md` rule plus an `ENFORCEMENT.md` row | ADR only; it creates no rule |
| **A choice for one feature** | That feature's tests | That feature's `specs/NNN/plan.md` |

## The fourth question: can it fail?

A check that cannot fail is a wish with a green tick. Before a check lands,
build the violation it claims to catch and watch the check fail on it. The
wiring audit of 2026-10-10 found this exact defect twice:

- CI's `Type Check` job runs with `|| true`;
- its `tools.py` call-argument check cannot see a single darnit signature.

Both looked like checks, and neither could fail.

## The precondition test

A rule that refers to something not yet built must say what it means until that
thing exists. Otherwise it either blocks work or quietly lies. Three shapes, in
order of preference:

- **Vacuous satisfaction**: the condition is trivially met until the
  precondition exists.
- **`dormant`**: the check runs, asserts nothing, and names what it waits for.
- **A named milestone**: `planned: scope-reset milestone`.

## The naming test

"Everything must be documented" fails, because there is no check for
"everything". Narrow the statement until a check exists ("every MCP tool
parameter is read by production code"), or move it down a row.

## The destinations

**Constitution rule.** It binds every change, it has a check, and violating it
matters. The bar is high, and the constitution should mostly stop growing. If
it keeps gaining rules, something that belongs in an ADR or a plan is leaking
upward.

**ADR** (`governance/decisions/`). It records the reasoning behind a choice.
ADRs are numbered and immutable: a decision that turns out wrong gets a new ADR
that supersedes it, never an edit in place. Most decisions are an ADR and no
rule. An RFC (`docs/rfcs/`) is a proposal under discussion; when it is
accepted, the decision becomes an ADR.

**Contract.** The framework TOML schema, the operator configuration schema,
the plugin protocol, the CLI, the MCP tool surface and the output formats.
The code that defines a contract (pydantic models, the Protocol, argparse,
the tool signatures) is normative, and prose describes it without superseding
it. A change follows C1.

**Feature spec** (`specs/NNN-*/`). Spec Kit's `spec.md`, `plan.md` and
`tasks.md` for one feature. Technology choices and the design of a single
feature belong in `plan.md`, where they stay revisable. A spec cites the ADRs
and rules it depends on by number. It does not restate them.

**Design note** (`design/`). Describes how a component works today. It is
descriptive: when it and the code disagree, the code is right and the note is
stale. A design note creates no obligation, so it uses no MUST or SHALL.

**User docs** (`docs/`). How to install, use, write a framework or write a
plugin. Every command, flag, key and API a user doc tells someone to use must
exist (F4). A doc that teaches a removed API is a bug.

## Exceptions

A change that cannot satisfy a rule gets an ADR that records the exception and
its reasoning. Never a silent suppression and never a weakened check (A3).

## Governance changes during feature work

`governance/` is tier-1 (A2). An agent whose task needs a governance change
stops and files an issue (A3). The work stays blocked until a maintainer makes
or approves the change. That is the design: a blocked task is visible, and a
rule quietly edited to fit is not.

At every milestone boundary, ask one standing question: does anything in
`governance/` contradict what we just built?
