# ADR-0001: darnit aligns a project's setup with a hygiene goal

- Status: proposed
- Date: 2026-10-10
- Rule impact: creates S1. Restates the existing conservative, trust and
  authority principles as S2, S3, S5 and S6.

## Context

The maintainers have described darnit's purpose many times, but never in one
place a change could be held to. Without that statement, two kinds of work
kept entering the project, each reasonable on its own.

The first kind is runtime verification: checks that run a tool and grade what
it says.

- `gittuf_commits_signed` parses `git log %G?`. It turned a fabricated
  signature into a dispositive PASS (wiring audit W-01).
- Witness runtime traces were Sigstore-verified to decide whether a build
  touched the network (#553).
- Reproducibility checks infer hermeticity and bit-for-bit output.
- zizmor findings decide CI controls.

Each brings that tool's trust roots and failure modes into darnit, and each is
a place where darnit can say PASS about something it cannot know.

The second kind is generic interfaces ahead of any user: check and remediation
adapters, a locator, a storage backend, four store protocols, pass and template
registries, shared handlers, budgets, enhancers. The 2026-10-10 wiring audit
found 149 defects, most of them in exactly this kind of code. It had been
declared, documented and validated, but never connected. #487 removed about
8,000 lines of it, and more remains.

darnit is an LF project with a [Technical Charter](../../CHARTER.md). This ADR
is not a charter. It decides what the software is for.

## Decision

**darnit is a framework for aligning a project's setup with a hygiene goal.**

A hygiene goal is a published set of practices a project should have in place:
OpenSSF Baseline, the Community Specification, "use gittuf", "be reproducible".
darnit reads a project's **setup**, reports where it falls short of the goal,
and helps set up what is missing.

Setup means:

- **Files:** SECURITY.md, LICENSE, CODEOWNERS, lockfiles, a gittuf policy.
- **CI configuration:** which workflows run, what they run, and with what
  permissions.
- **Platform settings:** branch protection, required reviews, 2FA
  requirements, read through the platform API.
- **Declared project data:** `.project/`, confirmed by a person where a value
  needs judgment (S3).

**darnit does not verify runtime behavior or tool outcomes.** It checks that a
mechanism is set up and in use. Whether the mechanism produces the right
answer at any given moment is the job of the mechanism.

| Goal | In scope: setup | Out of scope: outcome |
|------|-----------------|-----------------------|
| gittuf | gittuf is initialized; a policy exists with a root of trust; the policy is well formed; CI runs gittuf verification | whether history satisfies the policy; whether recent commits are signed |
| OpenSSF Baseline | SECURITY.md, LICENSE and contribution docs exist; branch protection and review settings are configured; security testing and dependency scanning run in CI | whether today's scan results are clean; whether the security tests pass |
| Reproducibility | dependencies are pinned in lockfiles; the build environment is declared; CI produces signed provenance | whether a build is hermetic at runtime; whether two builds are bit-for-bit identical |

### The framework

To serve that purpose, the framework provides:

- **Evidence readers**: repository files, parsed CI configuration, platform
  settings (read-only) and confirmed project data.
- **Checks**: declarative, defined in framework TOML. They produce PASS, FAIL,
  or a result that is not yet known together with the reason it is not known.
- **Remediation**: a plan that is previewed, approved and then applied by a
  single writer, which sets up what is missing.
- **Plugins**: hygiene goals (frameworks), and integrations that teach darnit
  how to read and set up one tool's configuration.
- **Interfaces**: the CLI, MCP tools and agent skills, as thin shells over one
  execution path.

### The admission test

A control, step type, interface, configuration key or subsystem is admitted only
if all three answers are yes:

1. Does it read or change a project's setup?
2. Would its answer stay the same across two runs with no change to that setup?
3. Does something that exists today need it?

Question 2 catches outcome checks: the answer to "are the scans clean" changes
without anyone touching the setup. Question 3 catches premature interfaces (F3).

## Alternatives

**darnit as a verifier.** It would run gittuf verification, scanners,
reproducibility builds and Witness, and grade the results. This was rejected
for four reasons:

- It duplicates tools that already do this and do it better.
- It makes darnit trust what those tools trust, which brings in signing keys,
  Sigstore roots, monitors and network access.
- Its answers change without the project changing.
- It is where false PASS results come from. W-01 is a dispositive PASS for a
  forged signature.

**Keep outcome checks, but as advisory evidence.** Feature 044 took this route
for the reproducibility checks, and #565 did for Witness. It was rejected:

- An advisory check still has to be maintained, tested and kept correct.
- It still shows up in reports.
- It still invites the next change that promotes it to deciding.

**No written scope; rely on review.** This is the status quo, and the audit
measured its result.

## Consequences

- **Some controls are cut or reframed.** A scope-reset classification will
  mark every control, step type and subsystem as keep, reframe or cut, for the
  maintainers to decide. Expected outcomes:
  - gittuf GT-02.01 is cut.
  - GT-01.02 is reframed from "policy passes verification" to "the policy is
    well formed and CI runs gittuf verification".
  - Witness verification and RE-03.01 are cut.
  - RE-02.01 is reframed to the parts that read build configuration.
  - The Baseline controls that grade zizmor findings need a decision. Reading
    a workflow file for a dangerous trigger is setup; running a scanner and
    grading its findings is an outcome.
  - Two areas are borderline and need a decision:
    - The threat-model analysis engine (features 006, 010, 011 and 014:
      tree-sitter discovery and opengrep taint analysis). Producing a threat
      model document as a remediation is setup. An analysis engine that grades
      code is not.
    - Feature 023's Scorecard wiring, because several Scorecard checks are
      outcome checks.
- **Some audit findings close by deletion, not repair.** W-01 is one; several
  P1s about unused interfaces are others.
- **Some OSPS controls are phrased as outcomes.** For those, darnit reports
  whether the practice is set up. Reports and the attestation predicate must
  say "set up for", not "compliant with", wherever that is the truth. That is
  a wording and predicate change, decided separately.
- **Fewer features.** Some contributions that work and were tested will be
  declined because they verify an outcome. The PR template and the S1 review
  make that visible before the work is done, not after.
- **Model judgments (`llm_eval`) are still allowed,** for a narrow use: whether
  a file's content says what a setup practice requires, for example whether
  SECURITY.md names a reporting channel. They remain PASS candidates that a
  person confirms. That is still setup.

## Enforcement

- **S1 (`ENF-S1`):** manual review now. A planned inventory check covers every
  `exec` step and plugin step type in a shipped framework.
- **S2 and S3:** restate existing tested rules (`ENF-S2`, `ENF-S3`).
- **F3, F4, F5:** cover question 3 of the admission test.
