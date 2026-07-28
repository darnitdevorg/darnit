# Phase 0 Research: Propose-Only Auto-Detection for User-Judgment Keys

The spec left no NEEDS CLARIFICATION markers, so this phase did the one piece
of genuine research the feature requires: build the FR-010 inventory of every
location that restates, documents, or enforces the previous wording. Building
it surfaced three findings, the first of which changes how the amendment should
be argued.

## Finding 1: Propose-only already ships

**Decision**: Frame the amendment as reconciling the constitution with existing
behavior, not as authorizing future behavior.

**Rationale**: The mechanism the RFC proposes to introduce is already built,
documented, and enabled in production configuration.

- `packages/darnit/src/darnit/config/framework_schema.py:802,807` defines both
  `hint_sources: list[str]` and `allow_sieve_hints: bool = False` on the
  context definition model.
- `packages/darnit-baseline/openssf-baseline.toml:287-289,300-301` sets
  `allow_sieve_hints = true` with `hint_sources` for `maintainers` and
  `security_contact` -- two of the three keys the constitution names as
  requiring human judgment.
- `packages/darnit/src/darnit/context/collection.py:264-271` resolves
  `hint_sources` by reading those files and returning a value tagged
  `file:<name>`. This runs with **no `auto_detect` gate**. The function's own
  docstring lists auto-detection as step 3 "if definition.auto_detect is true",
  but `hint_sources` is step 3.5 and carries no such condition.
- `packages/darnit/src/darnit/remediation/context_validator.py:219-258`
  presents whatever was found as a labelled suggestion carrying its source and
  confidence, and requires an explicit `confirm_project_data(...)` call with a
  `<user-confirmed values>` placeholder rather than a pre-filled guess.
- `docs/architecture/framework-design.md:838-840`, which CLAUDE.md names as the
  authoritative framework specification, shows `auto_detect = false` alongside
  `hint_sources` and `allow_sieve_hints = true` on the same key.

So the shipped behavior is: candidate produced, labelled, never auto-applied,
confirmation required. That is precisely propose-only, and it is precisely what
the constitution's "the sieve MUST NOT run for that key. No exceptions." reads
as forbidding.

Two consequences. First, FR-013 (no observable behavior change) is satisfied by
construction rather than by care -- there is no behavior to hold still, because
the amendment only changes prose. Second, the argument to reviewers is stronger
than the spec currently frames it: this is not loosening a safety rule to
enable future work, it is correcting a governing document that misdescribes the
system today, in the direction the design already went.

**Alternatives considered**: Treating the finding as out of scope and amending
on the RFC's forward-looking rationale alone. Rejected because a reviewer who
finds `allow_sieve_hints` during review will reasonably ask why the PR did not
mention it, and because leaving the contradiction unstated means the next
person to read Principle IV literally may "fix" working code to match it.

## Finding 2: The naming debt in FR-014 may not exist

**Decision**: Recommend relaxing FR-014's debt clause. Flagged for user
confirmation rather than applied, since it edits a clarified answer.

**Rationale**: The Q3 clarification assumed that after this amendment
`auto_detect = false` would misdescribe its own behavior, because detection
would run. Finding 1 shows the project already separates the two axes across
two flags:

| Flag | Governs | Default |
|---|---|---|
| `auto_detect` | whether a value may be concluded without a person | `false` |
| `allow_sieve_hints` | whether a detected value may be shown as a suggestion | `false` |

Read that way, `auto_detect = false` accurately means "may not conclude," which
is exactly what the amendment preserves. The name is fine. What is missing is
not a rename but an explanation: nothing near the constitutional rule mentions
that a second flag governs proposing, so a reader of Principle IV alone cannot
tell that the safety property is enforced by the pair rather than by the ban.

**Alternatives considered**: Keeping the debt clause as written, on the grounds
that `auto_detect` still reads as being about detection generally. Rejected as
recording debt that no future work would act on. Renaming was already rejected
at Q3 for compatibility reasons and remains rejected.

## Finding 3: A fourth normative restatement exists

**Decision**: Add `ARCHITECTURE.md:29` to the change set.

**Rationale**: The spec was written against two governing documents. The
inventory found a third file stating the rule normatively rather than as an
example: `ARCHITECTURE.md:29` reads "When `auto_detect = false` in TOML, the
sieve must not run for that key," inside a Conservative-by-Default section that
mirrors the constitution's structure. Under the Q5 answer (all prose updated),
it is in scope. It is also the file a new contributor is most likely to read
first, which makes leaving it stale worse than leaving a deep reference stale.

**Alternatives considered**: None; this is a straightforward inventory result.

## The inventory (FR-010)

Disposition per the Q5 answer: prose is updated in this feature; code,
configuration, and their comments are recorded as deferred; historical records
are left alone.

### Updated by this feature

| Location | What it says | Disposition |
|---|---|---|
| `.specify/memory/constitution.md:102-103` | "the sieve MUST NOT run for that key. No exceptions." | Rewrite to propose-only |
| `.specify/memory/constitution.md:106-107` | "acceptable ONLY for keys where `auto_detect = true`" | Rewrite; this is the sentence that forbids proposing |
| `.specify/memory/constitution.md:108-113` | confidence threshold provision, currently unscoped | Scope to non-user-judgment keys per FR-004 |
| `CLAUDE.md:170` | "MUST NOT run for that key. No exceptions." | Rewrite to match the constitution |
| `CLAUDE.md:172` | "acceptable only for keys where `auto_detect = true`" | Rewrite to match |
| `ARCHITECTURE.md:29` | "the sieve must not run for that key" | Rewrite; see Finding 3 |
| `ARCHITECTURE.md:441` | "Values with `auto_detect = false` require explicit user confirmation" | Accurate but incomplete; extend to mention proposing |
| `docs/design/CONTEXT_PROMPTS.md:201` | schema table: "Whether value can be auto-detected" | Clarify to "whether a value may be concluded without confirmation" |
| `docs/IMPLEMENTATION_GUIDE.md:707` | `auto_detect = false` example with no surrounding rule text | Add a sentence on what the flag now means |
| `docs/rfcs/0001-core-rearchitecture.md:247` | Stage 0 row | Mark satisfied and link the PR (FR-012) |
| `docs/rfcs/0001-core-rearchitecture.md:153` | "The project's current rule is absolute: the sieve MUST NOT run..." | Found during implementation, not Phase 0. Present-tense assertion of the old rule that the amendment falsifies. Rewritten to past tense. |
| `docs/rfcs/0001-core-rearchitecture.md:280` | Governance dependency: "Recommend landing that as its own small PR through the TSC before Stage 1 begins" | Found during implementation. Dependency is discharged by this change; rewritten to record that, and to carry Finding 1 forward for Stage 1. |

### Deferred (recorded, not changed)

| Location | Why deferred |
|---|---|
| `packages/darnit/src/darnit/config/framework_schema.py:792,807` | Code. Field definitions and docstrings; changing them risks behavior. |
| `packages/darnit/src/darnit/context/collection.py:233` | Code. The docstring understates what the function does (Finding 1); correcting it is a code change. |
| `packages/darnit-baseline/openssf-baseline.toml:284` | Configuration comment. |
| `packages/darnit-baseline/src/darnit_baseline/tools.py:796-819` | Code. Reads the flag to choose prompt shape. |
| `docs/architecture/framework-design.md:838` | Already consistent with propose-only; no change needed. Listed so the inventory is complete. |

### Left alone (historical records)

| Location | Why |
|---|---|
| `specs/001-tiered-control-automation/` (spec, plan, contracts, tasks, data-model) | Frozen record of a completed feature. Rewriting history would misrepresent what was decided then. |
| `specs/003-auto-context-inference/` | Same. Also mostly refers to the unrelated `context/auto_detect.py` module. |
| `docs/design/CONTEXT_SIEVE_DESIGN.md`, `docs/DECISION_FLOWS.md` | Refer to `prompt_if_auto_detected` and `auto_detected` source labels, which are different concepts. |
| `docs/threatmodel/findings/` | Generated output referencing the unrelated `context/auto_detect.py` module path. |

**Naming hazard for whoever implements this**: `packages/darnit/src/darnit/context/auto_detect.py`
is a module about detecting context generally. It is not the TOML flag. Several
inventory hits are that module and must not be touched.
