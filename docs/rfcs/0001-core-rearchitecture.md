# RFC-0001: Darnit Core Rearchitecture -- Integration-First Modules, Evidence Authority, and Dual Harness Drivers

- **Status:** Draft -- open for community comment
- **Author:** Michael Lieberman (@mlieberman85)
- **Discussion:** (link to GitHub Discussion / issue)
- **Target:** pre-1.0; staged landing beginning after 0.1

## Summary

Darnit helps code projects adopt best practices and meet published criteria (OpenSSF Baseline, SLSA, reproducible builds) through a three-phase pipeline: **Check** (verify against a standard's rules), **Collect** (gather the project-specific data needed to close gaps), and **Remediate** (apply fixes). Fully deterministic automation is impossible in practice -- real projects have quirks (docs under `docs/` vs `documentation/`, bespoke build layouts) that make purely rule-based remediation a combinatorial dead end -- so Darnit escalates from deterministic techniques through heuristics to LLM assistance and, finally, explicit human input.

This RFC proposes restructuring Darnit's core before 1.0 around four ideas:

1. **Integration-first modules.** Darnit should carry almost no check logic of its own. Existing scanners and services -- OpenSSF Scorecard, Zizmor, Opengrep, Frizbee, the GitHub API -- are the check and remediation logic; Darnit wraps each behind a small **Integration** plugin contract and expresses standards as **declarative Controls** (TOML + CEL) over normalized findings.
2. **Evidence authority as a first-class attribute.** Every step declares not just how expensive and deterministic it is, but whether its output *proves* a control or merely *suggests* an answer. Safety rules key on authority; cost rules key on cost. Conflating the two is what makes escalation ladders unsafe.
3. **Strategy lists instead of a fixed phase enum.** Escalation becomes an ordered, user-configurable list of steps per control, governed by a small set of load-time invariants rather than a hardcoded four-rung ladder baked into an enum.
4. **One core, two drivers.** The pipeline, escalation runner, and evidence model live in a harness-agnostic core exposing an ActionPlan protocol. A **coding-agent driver** (MCP server + agent skill) serves single-project and interactive use; a **custom-harness driver** serves fleet-scale use where the entire flow must be machine-controlled. Both drive identical module code.

Nothing is removed in this proposal. Existing TOML control definitions, CEL evaluation, per-run attestation, the shared-handler cache, the `darnit run` pipeline loop, and the MCP server all survive; they are re-seated behind explicit contracts.

## Motivation

Darnit's current design (pre-0.1) proved the concept but entangles concerns the project now needs separated. Each item below is stated against the code as it exists today.

**The pipeline loop exists, but only in the CLI.** `darnit/tools/audit.py:run_sieve_audit()` is already the single shared check function -- its docstring states that all code paths that run audits MUST delegate to it, and both `cli.py:cmd_audit` and the MCP tool in `darnit_baseline/tools.py` do. That part is healthy. The problem is one level up: the *pipeline* loop (Check -> Collect -> re-Check -> Remediate) exists only as inline orchestration inside `cli.py:cmd_run`, with a local `route()` call, a local iteration ceiling, and a local feedback handler. The MCP surface has no access to it, so a coding agent driving Darnit must improvise the loop out of skills and one-shot tool calls. There is one loop, and it is the wrong shape: batch where it needs to be resumable, and CLI-private where it needs to be driver-agnostic.

**Check logic and tool invocation are coupled.** A control today bundles what a standard requires with how a specific tool is run. This makes adding standards harder than it should be and invites Darnit to accumulate custom check logic -- an explicit non-goal.

**Escalation is structural, not declarative.** `sieve/models.py` defines `VerificationPhase` as a fixed enum (`DETERMINISTIC`, `PATTERN`, `LLM`, `MANUAL`). Within a phase, a control's pass list is already an ordered, TOML-authored list that users can extend and reorder -- so "many deterministic layers before any heuristic" works today. What does not work is reordering *across* the phase boundary, and, more importantly, the enum conflates two unrelated properties: how expensive and repeatable a step is, and how much authority its output carries. See "Two axes, not one" below.

**The shared-execution cache is name-keyed and run-scoped.** `[shared_handlers]` already implements run-once-and-fan-out (`sieve/orchestrator.py`, `docs/architecture/shared-handlers.md`), so an expensive invocation consumed by many controls executes once. Two limits remain: the cache key is an author-declared name rather than a value derived from the invocation, so correctness depends on humans never reusing a name with different parameters; and the cache is explicitly scoped to a single audit run, with no persistence or replay across runs.

**Evidence is untyped and unattributed.** Check results and collected data flow through loosely-typed project state. `HandlerResult` carries a `confidence` float that nothing consults, and records no tool name, tool version, or invocation. Nothing anywhere records *how much authority* a result carries -- whether a control passed because an API reported ground truth or because a heuristic guessed well. For a project whose lineage is supply-chain attestation, that distinction is the whole product.

## Goals

- A single module implementation serves Check, Collect, and Remediate, and runs identically under both drivers.
- Adding a new standard requires, in the common case, **only TOML + existing integrations**. This is the project's fitness function as a *strong default*: when a standard needs new code, that should be a deliberate, reviewed exception (no upstream tool exists, or the case is genuinely complex) -- not the path of least resistance.
- End users can reorder, insert, and tune escalation steps in configuration without forking, without being able to configure their way into a false compliance claim.
- Every finding and phase transition carries provenance (tool, version, invocation) and evidence authority, and is attestable.
- The LLM is a **typed, fallible step** -- structured output, validation, bounded retry, verification -- never the control flow, and never the sole basis for asserting compliance.

## Non-Goals

- Becoming a policy engine (CEL remains an evaluation convenience, not a policy language product).
- Maintaining first-party check logic that duplicates existing scanners.
- Owning bespoke remediation scripts per project.
- Coupling to a single LLM vendor or coding agent. Both a subscription-based coding agent and an API-billed harness must work.

## Design

### Two-layer module model

**Integrations** are the only place code lives. One plugin per external tool/service, including trivial built-ins:

```
Integration:
  id            # "scorecard", "zizmor", "gh_api", "file_exists", "glob"
  version_pin   # pinned tool version -- see "Version pinning" below
  cost_class    # free | subprocess | network | paid_tokens
  deterministic # bool: same inputs produce same output
  authority     # dispositive | suggestive  (see below)
  side_effects  # none | writes_repo | mutates_external
  cache_key(ctx, params)             # derived, not author-declared
  run(ctx, params) -> NormalizedFindings
```

**Controls** are pure declaration -- TOML + CEL over normalized findings:

```toml
[control."OSPS-BR-06.01"]
spec_refs = ["OSPS-BR-06.01"]
check = 'findings.scorecard.probes["pinnedDependencies"].outcome == "true"'
```

Properties:

- Built-ins (`file_exists`, `glob`, `gh_api`) implement the same contract, as do **shell/command hook integrations** (run a user-supplied command, capture and normalize its output) for gaps no packaged tool covers. Custom check logic in Python is legitimate when no upstream tool exists or the case is genuinely complex -- it just implements the same Integration contract rather than living as a special path. Python integrations are expected to remain first-class for much of **Collect** and **Remediate**, where the work is inherently procedural (API orchestration, template generation, repo mutation) rather than scan-shaped.
- **Run-once, fan-out, with derived keys.** The existing `[shared_handlers]` behavior is preserved and generalized: `cache_key(ctx, params)` is computed from the invocation rather than declared by the author, which removes the name-collision failure mode. Cache scope remains a single run by default; cross-run replay is deferred (see Open Questions).
- **Owned findings model, external formats at the edges.** SARIF (Zizmor, Opengrep), Scorecard JSON, and OSV are *importers* into a typed `NormalizedFindings` predicate; SARIF remains an output formatter. Darnit's internal model is never a third-party schema.
- **Provenance by construction.** Every finding records tool, version, invocation, and authority, making results ingestible by transparency/graph tooling (e.g. GUAC) and evaluable by attestation policy engines (e.g. AMPEL).

### Two axes, not one

The current `VerificationPhase` enum conflates two independent properties. Separating them is the load-bearing change in this RFC.

- **Cost and determinism** describe what running the step costs and whether it repeats. These drive *scheduling*: parallelize free steps, batch paid ones, decide what to cache.
- **Evidence authority** describes whether the step's output settles the question. These drive *safety*.

They are independent, and the cases that break a single-axis model are common:

| Step | Deterministic | Authority |
|---|---|---|
| `gh_api` reading branch protection | yes | dispositive -- it is the ground truth |
| `git_history_infer` guessing a security contact | yes | suggestive -- a perfectly repeatable guess |
| `llm_extract` reading a contact out of docs | no | suggestive |
| Human confirmation | n/a | asserted |

A single confidence scalar cannot express the second row: the step is completely deterministic and completely unauthoritative. This is precisely the case a compliance tool must not get wrong, and it is why the previous draft's `confirm_threshold` was doing safety work a number cannot do.

Authority values:

- **dispositive** -- the output settles the question. Only dispositive steps may conclude a control.
- **suggestive** -- the output is a candidate. It attaches as evidence and never concludes anything.
- **asserted** -- a human stated it. May conclude a control, and is recorded and reported distinctly.

### Strategy lists and the execution rule

Each control phase declares an ordered list of steps:

```toml
[control."OSPS-GV-03.01".collect]        # e.g. security contact
steps = [
  { integration = "file_exists",  params = { path = "SECURITY.md" } },
  { integration = "gh_api",       params = { endpoint = "security_contacts" } },
  { integration = "codeowners_parse" },
  { integration = "git_history_infer" },                                # suggestive
  { integration = "llm_extract",  params = { globs = ["docs/**"] } },   # suggestive, paid
  { kind = "manual" },                                                  # terminal
]
```

The execution rule differs per phase, because the consequence of being wrong differs per phase.

**Check.** Confidence is not a decision input at all.

- A **dispositive** PASS or FAIL is terminal.
- A **suggestive** result never terminates the list. It attaches as a candidate and execution continues.
- **ERROR is terminal and does not escalate.** If `gh api` fails on a rate limit, Darnit surfaces the failure. It does not substitute a guess for ground truth that was merely unavailable. (This is why the result model stays four-state -- `pass | fail | inconclusive | error` -- rather than collapsing to tri-state. An error is not an absence of knowledge; it is a broken measurement, and the two must not be handled alike.)
- If the list is exhausted with only suggestive results, the control is **inconclusive**, with the best candidate and its evidence attached for a human.
- `manual` is terminal.

**Collect.** Confidence survives here, demoted to a presentation filter: it decides whether a candidate is good enough to be worth showing a human, and nothing else. A suggestive step produces a **proposal**; a proposal becomes a value only on human confirmation.

**Remediate.** See "Remediation trust boundary" below. Confidence may participate in decisions here, but never alone.

Because a suggestive step can never terminate the list, its *position* no longer affects correctness -- only cost. This simplifies the invariant machinery substantially: ordering invariants only need to do cost work.

**Invariants, split by kind:**

- **Cost invariants** (no paid-token step before free steps are exhausted; batch network steps) are **user-overridable**. It is the user's money and latency, and getting them wrong is not a safety event.
- **Safety invariants** are **framework-enforced and not overridable**: only dispositive or asserted steps may conclude a control; no step with side effects may run during Check or Collect; `manual` is terminal; the remediation denylist (below) holds regardless of configuration.

### Confirmation, persistence, and expiry

When a human confirms a proposed value, that confirmation persists to `.project/` so subsequent runs resolve the step deterministically and never re-ask. This converts one-time human effort into permanent determinism and is the mechanism that makes fleet operation tractable at all.

Two rules keep the ratchet honest:

1. **Persistence does not launder authority.** A confirmed value retains authority `asserted` forever, along with the evidence it was based on -- including whether an LLM proposed it. Writing a guess into a file does not make it ground truth, and a later run must not report it as though a tool observed it.
2. **Confirmations age.** Each stored value records `confirmed_at`, `confirmed_by`, and its basis. Past a configurable period it downgrades back to a candidate requiring re-confirmation. This gives staleness handling without requiring a bespoke drift signal per key. Proposed default: per-key, 180 days, with facts that rarely change (governance model) configured longer than facts that rot (security contact).

**Change to `auto_detect = false`.** The project's rule was absolute until constitution 1.3.0: the sieve MUST NOT run for a key marked `auto_detect = false`, "no exceptions." That amendment, the Stage 0 gate below, narrowed it to **propose-only**: steps may run and produce a candidate for human confirmation, but may never conclude the key on their own. The safety property is preserved in full -- no guessed value is ever *used* unconfirmed -- while the user gets a pre-filled answer to accept instead of a blank field to research. This is a governance change to CLAUDE.md and the project constitution, not merely an RFC decision; see "Governance dependency."

### Remediation trust boundary

Remediation can be far more aggressive than Check, and the reason is not that the model is more trustworthy there. It is that **the failure modes differ in detectability and reversibility**:

- A wrong remediation is a visible artifact in a diff, reviewable and revertible.
- A wrong PASS is invisible and unrevertible. Nobody finds out, because the entire premise of the check was that no one was looking.

So Darnit can rationally gamble on Remediate and cannot rationally gamble on Check, independent of model quality. The resulting tiering:

| Phase | Role of confidence |
|---|---|
| Check | Not a decision input |
| Collect | Presentation filter only |
| Remediate | May be a decision input, subject to mechanical gates |

**Default boundary: the pull request.** Remediation writes to a branch and lands as a PR. Human review of the diff is the confirmation step, so LLM generation can be creative within it.

**Auto-merge** exists for the case that motivates it: large legacy fleets where per-repo human review by people unfamiliar with the code costs more than Darnit occasionally being wrong. It is gated on mechanical, non-introspective properties -- never on a model's self-reported confidence, which is both poorly calibrated and the one signal an attacker can influence:

- content was template-generated, or the diff is confined to the file scope the control declared;
- CI is green on the branch;
- the diff touches nothing on the denylist.

**The denylist is not overridable**: `.github/` in its entirety, CI and workflow definitions, and dependency manifests. Rationale under "Adversarial inputs."

**API-mutating remediations** (for example enabling branch protection) produce no diff and no PR, and take effect immediately on state shared by every contributor. They are handled by **capturing prior state as evidence before mutating**. This makes the change revertible and auditable, places it in the same reversibility class as a diff, and therefore lets one set of gating rules cover both kinds of remediation rather than leaving the API class ungoverned.

### Adversarial inputs

Fleet mode gives Darnit write access to many repositories. Collect reads repository content -- READMEs, docs, issue text, dependency metadata -- and feeds it to an LLM. **That content is untrusted input**, particularly across repositories the operator does not control.

The complete attack chain is short: prompt injection in a documentation file steers a generated remediation; confidence-gated auto-merge accepts it; the diff modifies a workflow file; the attacker now executes code in CI across the org. Darnit would become a delivery mechanism for exactly the class of compromise it exists to prevent.

Mitigations, stated as requirements rather than guidance:

- Collect inputs are untrusted. Content read from a repository is data, never instruction, and integrations that pass repository content to a model must isolate it as such.
- The auto-merge denylist above is non-overridable. An org that wants unattended workflow remediation does not get it; the residual risk is not the operator's alone to accept, because it propagates to everyone who consumes the affected artifacts.
- Shell and command hook integrations inherit the plugin trust boundary. Because RFC-adjacent work (spec 013) permits recursive composition from third-party implementations, a composed-in command hook is arbitrary code execution sourced transitively. Command hooks introduced through composition from an unsigned source are refused under the existing `allow_unsigned` / `trusted_publishers` policy.

### Evidence, attestation, and compliance math

`NormalizedFindings`, `CheckResult`, `Evidence`, and `RemediationPlan` are schema-typed structures serialized as in-toto predicates in DSSE envelopes. Each carries the authority of the evidence that produced it.

**Compliance is reported as one number plus a breakdown**: "Level 1 compliant, of which N controls rest on human assertion." A single number keeps the common case readable; the breakdown means the distinction is visible where people actually look, not buried in an envelope. Attestations record authority per control so a downstream policy engine can reject assertion-backed passes for high-assurance use without re-deriving anything.

**Signing scope.** Not every intermediate structure needs a signature. All four types are *attestable* -- deterministically serializable and hashable -- but signing every phase transition puts DSSE and Sigstore in the inner loop and produces a transparency-log entry per intermediate result per repo across a fleet. Default to signing the final `CheckResult` set and the `RemediationPlan`; leave the rest attestable-but-unsigned.

**Relationship to today's attestation.** Attestation currently lives in `darnit-baseline` with a baseline-specific predicate type (`https://openssf.org/baseline/assessment/v1`) over a flatter schema. Moving Evidence types into core means defining and versioning new predicate types publicly. The existing predicate remains emitted and verifiable across the transition.

**Version pinning.** `version_pin` is only meaningful if enforced, and provenance is only worth attesting if the pin holds. Proposed rule: Darnit resolves the tool, compares against the pin, and **fails closed** on mismatch, with an explicit per-integration opt-out that is recorded in the evidence so a consumer can see the pin was not honored.

**Caching and non-determinism.** `cache_key` for a non-deterministic integration is replay, not reproduction. LLM steps are cached, if at all, under (prompt, model, version) with replay semantics stated explicitly, so that reproducibility claims elsewhere in the project are not quietly weakened.

**Disagreement is signal.** When a dispositive step and a suggestive step reach different answers, "stop at the first conclusive result" discards information a compliance operator wants. The dispositive result stands, and the disagreement is recorded in evidence.

### One core, two drivers

`darnit-core` (the existing distribution; this RFC *shrinks* it rather than creating it) owns the module contracts, strategy runner, phase pipeline, `ExecutionContext`, and the ActionPlan protocol. Drivers are thin:

- **`darnit-agent`** -- MCP server plus a packaged agent skill that teaches any MCP-capable coding agent to walk the ActionPlan loop. Best for single projects, interactive use, and development; token-heavy work rides the user's existing agent subscription.
- **`darnit-harness`** -- deterministic orchestration whose nodes call the same core functions the MCP tools wrap. The harness owns the loop; LLM calls are validated, retried, verified steps. Best for operating across many repositories, where relying on a coding agent's best-effort behavior is not acceptable.

**The ActionPlan protocol already has an ancestor in the tree.** `cli.py:cmd_run` calls `route(state)`, which returns the next node (`audit` | `collect_context` | `remediate` | `end`). Extracting and generalizing that function *is* the protocol; this is not green-field work.

**Agent trust boundary.** ActionPlan reveals one step at a time. The calling agent may decide *whether* to proceed and may supply *user input*. It may not choose ordering, skip steps, or fabricate results. Enforcement is mechanical: core validates that the result submitted for step N matches step N's declared schema and refuses out-of-order submission. The agent is therefore trusted with pacing and human interaction, and with nothing else.

**On orchestration libraries.** The previous draft named LangGraph. The codebase has already been there: `cmd_run` carries the comment "Inline orchestration (replaces LangGraph)." This RFC does **not** propose returning to it. The harness driver owns a loop whose shape is now specified by the ActionPlan protocol; whether that loop is hand-rolled or library-backed is an implementation choice for the driver, and the current inline implementation is evidence that hand-rolled is sufficient. A durable-execution backend (Temporal-style: crash-safe resumption, long-running remediation such as open-PR, await-CI, verify) remains an anticipated evolution, to be proposed separately when fleet-scale demand is concrete.

### Fleet mode and the manual queue

A human cannot be asked per-repo per-control at scale. Manual and unconfirmed items batch into a **review queue, deduped across repositories** by (collect key, scope), where each collect key declares whether the fact it gathers is org-scoped or repo-scoped. Answering "who is the security contact for this org" once clears the item for every repository that shares the scope.

Repositories stay non-compliant until their items clear. Fleet runs therefore do not reach "compliant" unattended, which is the honest outcome: an unattended run cannot produce an assertion, and assertions are the only way some controls can ever pass.

This makes the deduped queue and org-level confirmation the same mechanism rather than competing ones, and it lands the answers exactly where spec 017 already puts org-level data -- the org-level `.project` repository. Spec 017 is therefore the fleet driver's storage layer, not a parallel effort.

## Relationship to in-flight work

| Work | Relationship |
|---|---|
| `specs/013-plugin-composition` | Composition resolves control sets; this RFC changes what a control's steps look like. Composition must run before strategy-list validation so invariants are checked against the resolved set. Open item: whether a composed-in control may drag in an Integration the composing plugin did not declare. Security-relevant for command hooks (see Adversarial inputs). |
| `specs/017-org-wide-audit-pipeline` | Becomes the fleet driver's enumeration and storage layer. Not a competing path. |
| `darnit/agent/` (`graph.py`, `state.py`, `feedback.py`) | The harness seed. `route()` becomes the ActionPlan protocol; `AuditState` becomes the typed Evidence carrier; the noninteractive feedback mode that queues unanswered questions is the manual queue in embryo. Retained and promoted, not replaced. |
| `[shared_handlers]` | Retained; generalized to derived cache keys. |
| `darnit-baseline` attestation | Retained and kept verifiable; core Evidence predicates added alongside. |

## Staged Plan

Each stage lands as its own scoped spec/PR series with an executable acceptance gate. Later stages do not begin until the prior gate passes.

| Stage | Work | Acceptance gate |
|---|---|---|
| 0 | Governance: narrow `auto_detect = false` to propose-only in CLAUDE.md and the constitution | **Satisfied** by constitution 1.3.0 (spec `018-auto-detect-propose-only`), landed as its own PR. Principle IV now permits proposing a candidate for a user-judgment key and forbids concluding one without human confirmation. Phase 0 research for that feature also established that the mechanism already ships via `allow_sieve_hints`, so Stage 1 inherits a rule that matches the code rather than one it must first argue around. |
| 1 | Add `authority` to results and handlers; implement the per-phase execution rule; extract `route()` from `cmd_run` into the public ActionPlan protocol; expose the pipeline loop over MCP | One reference control (SECURITY.md) runs the full Check/Collect/Remediate loop through the same protocol from both `darnit run` and a coding agent over MCP, with an LLM step demonstrably unable to produce a PASS |
| 2 | Carve down `darnit-core`: Integration contract, `NormalizedFindings` + Scorecard/SARIF importers, derived cache keys, strategy-list runner, cost/safety invariant split; re-express existing controls over normalized findings | One full standard's controls run identically under both drivers; a control whose only evidence is suggestive reports inconclusive rather than pass; legacy phase-keyed TOML loads through the compatibility path with a lossless-translation test |
| 3 | `darnit-agent` packaging (MCP + skill); `darnit-harness` driver with the deduped manual queue; confirmation persistence and expiry; remediation gating incl. denylist and prior-state capture | Reference suite green under both drivers; fitness test below passes; an injection-attempt fixture in repo content fails to influence an auto-merge decision |

**Fitness gate (replaces "ship a second standard").** Darnit already ships several implementations, so shipping another proves nothing. The gate is instead: **take an existing implementation that carries Python check logic today, re-express it as TOML plus existing integrations, and report the deleted line count.** That is a measurable claim about the contract rather than a restatement of the status quo.

**Compatibility commitments.** Existing `.baseline.toml` and framework TOML continue to load through the config resolver during the transition; phase-keyed tables (`deterministic = [...]`, `llm = [...]`) are translated into strategy lists by the loader, and the translation is covered by a lossless-round-trip test rather than asserted. Existing MCP tool names remain (deprecated aliases where renamed). Attestation output remains verifiable across the boundary. No stage deletes functionality; each re-seats it behind a contract.

## Alternatives Considered

- **Minimal refactor only** (expose the existing loop over MCP, keep entangled controls): fastest, but preserves the coupling that blocks TOML-only standards and a real scale harness. Rejected as insufficient, though its steps are subsumed by Stage 1.
- **Keeping the `VerificationPhase` enum as the escalation model:** simpler to explain and already implemented, but it conflates cost with authority, which means no configuration of it can express "deterministic but unauthoritative" -- the exact case that produces false compliance claims. Rejected on safety grounds, not ergonomics.
- **A single confidence scalar as the decision lever** (the previous draft's `confirm_threshold`): one dial operators understand, but a number cannot distinguish "I observed this" from "I am confident I guessed correctly," and it is the one input an attacker can influence. Retained only as a presentation filter in Collect and as one gate among mechanical ones in Remediate.
- **Adopting a third-party findings schema (SARIF/OSV) as the internal model:** avoids an importer layer but binds core semantics to formats that do not cover all sources (Scorecard probes are not SARIF) and do not carry the authority and provenance fields the strategy runner needs.
- **Returning to LangGraph for the harness:** already tried and reverted in `cmd_run`. The ActionPlan protocol specifies the loop's shape; the library choice is a driver implementation detail.
- **Durable execution (Temporal) as the immediate harness:** strongest determinism and scale story, but a heavy operational dependency to impose on a pre-0.1 community project. Deferred to a follow-up RFC gated on demonstrated fleet-scale need.

## Open Questions (feedback requested)

Closed in this draft, recorded for reviewers who saw the previous version: findings-normalization depth is answered by the fitness function (controls asserting over tool-specific payloads become tool-coupled and break when the tool is swapped, so core normalizes a closed predicate set plus an explicitly-flagged, fitness-excluded escape hatch); invariant overridability is answered by the cost/safety split; the agent trust boundary is answered by mechanical ActionPlan validation.

Still open:

1. **Confidence semantics within Collect.** Confidence is now only a presentation filter, but is it a property of the step, the finding, or the candidate -- and how should two suggestive steps proposing different values be ranked for the human?
2. **Evidence source of truth.** Signed predicate chain versus persisted `.project/` file as projection -- how are user hand-edits to confirmed values reconciled, and does a hand-edit carry authority `asserted` with an unknown basis?
3. **Cross-run cache and replay.** The shared cache is run-scoped today. Is persistent replay worth the staleness risk, and does it interact with confirmation expiry?
4. **Expiry defaults.** Is per-key expiry with a 180-day default right, and should authority `asserted` expire differently for slow-changing facts?
5. **Integration contract stability.** Integrations are the primary contribution ramp. What deprecation policy applies pre-1.0 so early plugin authors are not burned by churn?
6. **LLM vendor neutrality.** Model-agnostic client layer versus a single SDK, given both subscription-agent and API-billed paths must work.

## Governance dependency

Narrowing `auto_detect = false` from "the sieve MUST NOT run" to "steps may propose, never conclude" changed a rule the project constitution stated with "no exceptions." The safety property is preserved in full -- no unconfirmed guess is ever used. **This dependency is now discharged**: the amendment landed as its own PR (constitution 1.3.0, spec `018-auto-detect-propose-only`) before Stage 1 begins, as recommended here.

Phase 0 research for that amendment turned up something that strengthens the rest of this RFC: propose-only was already implemented. `allow_sieve_hints` and `hint_sources` exist in the framework schema and are enabled for `maintainers` and `security_contact` in the OpenSSF Baseline configuration, with `hint_sources` resolution running un-gated by `auto_detect`. The constitution had been describing a system the project no longer had. Stage 1 therefore inherits a written rule that matches the code, rather than one it must argue around.

## How to Participate

- Comment on this RFC in the linked Discussion; substantive design objections are most useful on the two-axis attribute model and the safety invariants.
- Stage 2 creates the project's primary contribution ramps: **Integration plugins** (small, well-bounded, one external tool each) and **TOML-only standards**. Both will be labeled `good-first-issue` as contracts stabilize.
- Reference-module implementations double as documentation and acceptance tests; adopting one is a self-contained contribution.

## Appendix: Fitness Function

> **Default:** adding a new standard (e.g., a CRA control set, the SLSA source track) should require only TOML control definitions plus existing integrations. If common cases cannot ship this way, that is a contract defect to be fixed in core.
>
> **Legitimate exceptions:** custom check logic is appropriate when no existing tool covers the requirement, or the case is genuinely complex or unusual. Such logic implements the standard Integration contract (or a shell/command hook) so it remains cacheable, attributable, and reusable -- the exception is in *what* the code does, never in *how* it plugs in.
>
> **Expected, not regretted:** Python integrations are anticipated to remain first-class for significant portions of Collect and Remediate, which are procedural by nature. The aspiration is that the ecosystem grows enough scanners and services to keep shrinking Darnit's custom-check surface -- but realistically there will always be something to support via existing shell/command hooks or a new custom hook, and the architecture treats that as a supported case rather than a failure.
