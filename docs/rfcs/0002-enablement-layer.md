# RFC-0002: Darnit as an Enablement Layer -- Capabilities, Instrumentation, and Repository Snapshots

- **Status:** Draft -- open for community comment
- **Author:** Michael Lieberman (@mlieberman85)
- **Discussion:** (link to GitHub Discussion / issue)
- **Depends on:** RFC-0001 (including its September 2026 revision)
- **Target:** pre-1.0, after RFC-0001 Stage 2

## Summary

Darnit today behaves mainly as an auditor: it inspects a repository, reports control results, and optionally fixes some of them. This RFC proposes making darnit primarily an **enablement layer**: it helps a project *adopt capabilities* (signed releases, build provenance, private vulnerability reporting, pinned dependencies, reproducible builds), installs the upstream machinery that makes the project *produce its own evidence* continuously, and then reads that evidence cheaply and deterministically. Audit becomes the verification step of adoption rather than the product.

Five ideas, each usable on its own:

1. **Capabilities are the unit of work.** A capability has prerequisites, an install recipe, a verification, and a mapping to the controls it satisfies across standards.
2. **Instrument, don't inspect.** Once a capability is installed, the project's own CI produces evidence. Darnit's own scanning shrinks to bootstrap checks and the residual judgment.
3. **Install maintained upstream recipes.** Remediation mostly means adding and configuring existing reusable workflows and tools, pinned and kept current, rather than generating bespoke files.
4. **The LLM is an author, not a judge.** Spend model effort where a human review gate already exists (the pull request), and keep model judgment of compliance minimal.
5. **Repository snapshots.** A signed, out-of-repository, point-in-time attestation of observed repository facts, so point-in-time state has a home that is neither the source tree nor a verdict.

Supporting mechanisms: memoized judgments and confirmations keyed by evidence digest, incremental and pull-request-mode evaluation, and an organization-scoped question inbox.

## Motivation

- **Maintainers want outcomes, not control IDs.** "Pass OSPS-BR-06.01" is a means; "our releases are signed and verifiable" is the goal. The same capability often satisfies controls in several standards (OpenSSF Baseline, SLSA, Scorecard checks, regulatory control sets), and today each standard re-checks it independently.
- **Re-deriving facts on every run is expensive and fragile.** Darnit re-inspects repositories that could be producing attested evidence on their own. Every re-derivation is a chance to be wrong and costs API calls or model tokens.
- **Point-in-time facts have no home.** Repository settings, branch protection, organization policy, and similar state can change without a commit. They do not belong in the source tree, and today they appear only as evidence buried inside an assessment.
- **The model is most useful where it is least trusted to judge.** Model output is valuable for drafting project-specific content, where a human reviews the diff anyway, and risky when it decides whether a control passes (see RFC-0001, September 2026 revision).

## Goals

- A maintainer can ask for a capability, see a reviewable plan, and end with that capability installed, producing evidence, and verified.
- After adoption, repeat evaluations are mostly deterministic reads of evidence the project produced, and cost close to nothing.
- One capability definition serves every standard it satisfies.
- Point-in-time repository facts are published as signed, verifiable, supersedable records outside the source tree.

## Non-Goals

- Darnit producing SLSA provenance, SBOMs, or signatures about a project itself. Darnit installs the machinery; the project's own build produces those artifacts.
- Operating a hosted service. Publication targets are existing registries and attestation stores.
- Replacing `.project/` for durable, human-declared project metadata.

## Design

### Capabilities

A capability is declarative data, shipped in the same packs as standards:

```
capability:
  id                 # "signed-releases", "build-provenance", "private-vuln-reporting"
  prerequisites      # other capabilities or context keys (confirmed values only)
  recipe             # how to install: upstream workflow/action/tool + parameters
  verification       # the checks that show it is installed and working
  evidence_produced  # what the project will emit once installed (attestation types, files)
  satisfies          # control IDs across standards, each with the evidence that proves it
```

- Standards keep their control definitions. The `satisfies` mapping lets one installed capability discharge controls in several standards, and lets a report say "adopt build-provenance to close these five controls" instead of listing five failures.
- A control can be satisfied by more than one capability; the report proposes the smallest set.
- Capabilities never carry user-judgment values; recipes that need them (a security contact, maintainers) declare the context keys as prerequisites, which must be confirmed before a plan is produced.

**Example: build provenance.** The capability installs a maintained provenance generator into the project's release workflow, configured for the project's build. Verification confirms that the next release carries provenance that verifies against the expected builder identity. Darnit never generates provenance itself.

### Instrument, don't inspect

Once installed, a capability makes the project's CI emit evidence on its own schedule: provenance on release, scanner results on push, a repository snapshot (below) on a schedule. Darnit's evaluation then prefers, in order:

1. evidence the project produced, verified by signature and identity;
2. platform state read directly (APIs), for facts the project cannot attest about itself;
3. darnit's own inspection;
4. model judgment, then a human, as in RFC-0001.

Evidence produced by the project's own CI is attributed to that identity. Whether it can conclude a control follows the per-claim authority rules in RFC-0001; a signature proves who produced a statement, not that the statement is complete.

### Upstream recipes and their lifecycle

- Recipes reference maintained upstream building blocks (reusable workflows, composite actions, tools) by pinned version and digest.
- Installing a recipe records what was installed and at which version in darnit's extension data, so later runs can detect removal, drift, or a stale pin, and propose an update the way dependency-update tools do.
- Recipes that need project-specific edits beyond parameters are the exception and go through the same plan/apply/re-check loop (RFC-0001) with the change visible in the pull request.
- Darnit does not fork or vendor upstream recipes. Gaps are fixed upstream.

### The LLM as author, not judge

Two uses of a model carry different risk:

| Use | Output lands in | Human gate | Risk of a wrong result |
|---|---|---|---|
| Author (draft SECURITY.md, governance docs, threat-model prose, recipe parameters, fixes) | A pull request diff | Review of the diff | Visible and revertible |
| Judge (does this document satisfy the control?) | A verdict and an attestation | None unless routed to a human | Invisible |

Darnit's model budget should go mostly to authoring. Judging stays minimal and follows RFC-0001: an LLM never concludes PASS on its own. Authored content never contains unconfirmed user-judgment values.

### Memoized judgments and confirmations

Every model judgment and human confirmation is stored with a digest of the evidence it was based on and an expiry. On the next run:

- If the evidence digest is unchanged and the record has not expired, the prior judgment or confirmation stands without re-asking or re-spending.
- If the evidence changed, only that judgment re-runs, and a human reconfirming sees what changed since they last confirmed.

This makes repeat runs cheap and stable, which matters for fleets and for attestations that should not flip between runs.

### Incremental and pull-request-mode evaluation

Controls and capability verifications declare their inputs (file globs, API fields, attestation types). The engine fingerprints inputs and re-evaluates only what changed. This enables a pull-request check that reports regressions introduced by the change ("this removes a required status check", "this adds an unpinned action"). Pull-request mode depends on RFC-0001's trust boundary: nothing in the pull request may change what darnit runs or how it concludes.

### Organization-scoped question inbox

Human questions from many repositories are batched and deduplicated by scope (organization or repository). An answer is stored once, as an attributed assertion with an expiry, at the scope it applies to, and inherited by every repository in that scope unless overridden. This builds on RFC-0001's fleet mode and treats the inbox as a primary product surface rather than a side effect of batch runs.

### Repository snapshots

**Gap.** Existing formats cover adjacent needs but not this one:

- SLSA source-track attestations describe change-management properties of a revision, not a catalog of repository and organization state.
- Tools that sign raw platform API responses capture state but without normalized keys, per-value metadata, or human assertions.
- Attribute-assertion predicates can encode properties but have no field for when a value was observed or whether it could not be observed.
- Scorecard output is a scanner's result set, best referenced by digest rather than duplicated.

What is missing is a record of "what was observed about repository R at time T", with each value carrying when it was observed, its source and evidence digest, its authority, an honest status, and a validity window.

**Proposed shape (working name `repo-snapshot`).** Facts only, never verdicts:

```
subjects:   repository identity (digest of the platform's immutable repository ID),
            observed revision (commit / tree)
predicate:
  repository, revision, window{start, end}, validUntil, producer{tool, version, identity},
  vocabulary{uri, version}, coverage, supersedes (digest of previous snapshot), references[]
  properties[]:
    key, scope (org | repo | branch | release),
    status (observed | absent | unobservable | unconfirmed | error),
    value?, observedAt, validUntil?,
    authority (dispositive | suggestive | asserted),
    source{kind, uri, digest}, evidence[], reason?
```

Rules:

- **Verdicts live elsewhere.** An assessment cites a snapshot by digest; the snapshot itself makes no compliance claim.
- **Honest unknowns.** "Could not observe" (for example, a token that cannot read an admin-only setting) is `unobservable`, never `false` or `absent`. An expired value is unknown.
- **Candidates carry no value.** An unconfirmed user-judgment key appears as `unconfirmed`. Human-asserted values reference the confirmed record in `.project/` by content digest.
- **No personal data.** Nothing about the operator or auditor appears, and values are projected to what a consumer needs.
- **One statement per run,** kept small enough to store in common attestation stores.

**Production and distribution.**

- The preferred producer is the project's own CI, running a darnit-provided reusable workflow on a schedule. Keyless signing then binds each snapshot to both the workflow and the project. Installing that workflow is itself a capability.
- Fleet operators can also produce snapshots under their own identity; consumers decide which identities they trust.
- Publication uses existing stores: the platform's attestation store keyed by the repository-identity subject, release assets, or an OCI registry. A transparency log is used for timestamping where appropriate. Private repositories must not be published to public logs.
- `.project/` can carry a pointer to where snapshots are published. Consumers take the newest valid snapshot, apply their own maximum age, and follow `supersedes` to detect drift.

**Before committing to a new predicate,** a short spike models about ten Baseline facts for one repository three ways (signed raw API responses, an attribute-assertion profile, and the draft above) and writes the same policies against each. A new predicate is warranted only if the existing forms cannot cleanly express unknown versus false, asserted versus observed, and per-value freshness.

### Standards and capabilities as data packs

This RFC assumes RFC-0001 Stage 2: integrations are the only code, and standards are data. Capabilities follow the same rule. A new standard or capability should ship as TOML plus existing integrations and recipes; custom code is an integration, not a special path.

## Relationship to RFC-0001

RFC-0001 defines how darnit reaches trustworthy verdicts (authority, drivers, evidence, remediation safety). This RFC changes what darnit is for and what it spends its effort on. It relies on RFC-0001 for: per-claim authority and the rule that a model never concludes PASS; engine-held run state and typed pending tasks; the candidate/confirmed context envelope; the audited-repository trust boundary; and the plan/apply/re-check remediation loop, which capability installation uses directly.

## Staged Plan

| Stage | Work | Acceptance gate |
|---|---|---|
| A | Capability schema; `satisfies` mapping for the Baseline implementation; reports grouped by capability | A Baseline report on a real repository proposes a capability set that covers its failures, with no change to verdicts |
| B | Three reference capabilities installed via upstream recipes through the RFC-0001 remediation loop, with recipe records and drift detection | Each installs via pull request, verifies after merge, and is detected when removed or stale |
| C | Evidence-first evaluation: prefer project-produced, identity-verified evidence; memoized judgments and confirmations by evidence digest | A second run on an unchanged repository makes no model calls and asks no questions |
| D | Repository-snapshot spike, then (if warranted) the predicate, the scheduled workflow capability, and a verifier | Snapshots produced by a project's CI verify, supersede correctly, and express unobservable values distinctly |
| E | Incremental and pull-request mode; organization question inbox | A pull request that weakens a protected setting is flagged; an organization-scoped answer clears the same question across repositories |

## Alternatives Considered

- **Stay an auditor and improve accuracy only.** Necessary (RFC-0001) but not sufficient: every run keeps re-deriving facts, and maintainers are left with a list of failures rather than a path to adoption.
- **Generate bespoke workflows and files per project.** Maximum flexibility, but darnit then owns maintenance of everything it wrote, across every repository, forever. Pinned upstream recipes move that burden to the projects that specialize in it.
- **Store point-in-time facts in the repository.** Simple to read, but commits become a noisy proxy for settings changes, the file goes stale between commits, and nothing binds it to the time and identity that observed it.
- **Embed observed facts only inside assessments.** Current behavior. It couples observation to judgment, cannot be re-evaluated under a different policy, and gives organization- and branch-scoped state a commit as its subject.

## Open Questions

1. **Capability granularity.** How fine-grained should capabilities be, and should standards packs or a shared capability pack own them?
2. **Recipe trust.** What trust and pinning policy applies to upstream recipes, and how are recipe updates reviewed?
3. **Snapshot vocabulary.** Who owns the property key vocabulary, and how is it versioned across standards?
4. **Snapshot identity.** How should consumers weigh project-produced snapshots against fleet-operator snapshots for the same repository?
5. **Where the predicate lives.** Keep it darnit-owned, or propose it to an existing attestation or OpenSSF working group once it has proven itself? Naming, including its relationship to existing discovery work such as `chainsights`, is open.
6. **Expiry defaults.** Per-property validity windows for snapshots and per-key expiry for memoized confirmations: shared defaults or per-standard?
