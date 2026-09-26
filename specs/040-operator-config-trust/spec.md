# Feature Specification: Operator Configuration and Trust Model

**Feature Branch**: `040-operator-config-trust`

**Created**: 2026-09-26

**Status**: Draft

**Input**: User description: "Operator configuration and trust model. darnit separates configuration owned by whoever runs darnit (the operator) from content of the repository being audited, which is untrusted input (RFC-0001 September 2026 revision, 'Trust boundaries'). This feature defines user-level operator configuration and retires the repository-level .baseline.toml."

## Background

darnit has three kinds of input that are easy to conflate:

- **Tool configuration** -- what darnit runs and what it trusts: which checks and commands execute, which plugins and MCP servers are trusted, where results are stored, which model is used and how much it may spend.
- **Project facts and assertions** -- what a project says about itself: maintainers, security contact, "this control does not apply to us because we publish no releases".
- **Run parameters** -- what to audit this time: target, framework, level, output format.

Tool configuration belongs to the **operator**: whoever runs darnit (a maintainer on a laptop, a CI job, a fleet harness, a person using a coding agent). The audited repository's content belongs to whoever can write to that repository, which in general is not the operator. RFC-0001 (September 2026 revision) states the design principle this feature implements: **the audited repository is untrusted input in its entirety, including any configuration it contains; it may supply assertions about itself, which are recorded and reported as its own, but it may not change what darnit executes, how steps conclude, or which plugins and servers are trusted.**

Today the repository-level `.baseline.toml` file mixes project assertions with tool configuration. This feature gives tool configuration its own home owned by the operator, moves project assertions into `.project/`, and retires `.baseline.toml`.

Constitution alignment: Principle II (Conservative-by-Default) governs how project-asserted "not applicable" claims count toward compliance; Principle IV (Never Guess User Values) governs how claims and confirmations are recorded.

## User Scenarios & Testing *(mandatory)*

### User Story 1 - Operator configures darnit once, outside any repository (Priority: P1)

A maintainer uses darnit across several of their own repositories. They want one place to set how darnit runs for them -- which plugins and MCP servers they trust, their model and budget, custom checks they rely on, where reports go -- without copying settings into every repository and without any repository being able to change those settings.

**Why this priority**: Every other story depends on operator configuration existing. It is also the direct replacement for settings that can no longer come from the audited repository.

**Independent Test**: Create a user-level operator configuration with a custom check and a trusted MCP server, audit two different repositories with each driver (CLI, MCP server, headless harness), and confirm the same settings apply in every case and that nothing in either repository changes them.

**Acceptance Scenarios**:

1. **Given** an operator configuration in the standard per-user location, **When** the operator runs an audit from the CLI, the MCP server, or the harness without extra flags, **Then** all three load the same operator configuration.
2. **Given** an operator configuration and an explicit configuration path passed at launch, **When** an audit runs, **Then** the explicit path is used instead of the per-user file.
3. **Given** a per-run flag that sets a value also present in operator configuration, **When** an audit runs, **Then** the flag wins for that run only.
4. **Given** an audited repository that contains files attempting to set tool configuration (plugins, servers, commands, checks, storage, budgets, trust lists), **When** the audit runs, **Then** none of those settings take effect, and the report lists what was ignored.
5. **Given** no operator configuration exists, **When** an audit runs, **Then** darnit uses built-in defaults and says where it looked for operator configuration.

---

### User Story 2 - Project assertions live in .project/ (Priority: P1)

A maintainer wants to record that a control does not apply to their project, with a reason, in the same place they keep other project metadata. Anyone reading the project should see the claim, and darnit should report it as the project's assertion.

**Why this priority**: Retiring `.baseline.toml` requires a home for the one legitimate thing it carried: the project's own claims about itself.

**Independent Test**: Record a not-applicable claim with a reason in `.project/`, audit the repository, and confirm the report shows the claim as asserted by the project, with the reason and who asserted it.

**Acceptance Scenarios**:

1. **Given** a not-applicable claim with a reason recorded in `.project/`, **When** the repository is audited, **Then** the report shows the control's result as "asserted not applicable" with the reason and asserter.
2. **Given** a claim is recorded, **When** the files darnit writes to `.project/` are checked against the upstream `.project/` schema, **Then** they conform; darnit-specific data lives only in darnit's extension file.
3. **Given** a project assertion that upstream `.project/` has a field for, **When** darnit records it, **Then** it uses the upstream field rather than its extension file.

---

### User Story 3 - Not-applicable claims count only when trusted and uncontradicted (Priority: P1)

An operator audits both their own repositories and repositories they do not control (dependencies, pull requests from forks, repositories swept across an organization). A project's claim that a control does not apply should reduce friction for repositories the operator trusts, and should never silently shrink an audit of a repository the operator does not trust.

**Why this priority**: This is where the trust boundary meets compliance math. Getting it wrong either makes darnit tedious for honest maintainers or lets anyone with write access remove controls from a compliance claim.

**Independent Test**: Audit the same repository content twice -- once listed in the operator's trusted repositories and once not -- and once more with evidence that contradicts the claim, and compare how the claimed control counts toward compliance in each case.

**Acceptance Scenarios**:

1. **Given** a repository in the operator's trusted repositories with a not-applicable claim and no contradicting evidence, **When** it is audited, **Then** the control counts as not applicable and is labelled "asserted" with the asserter.
2. **Given** a repository not in the operator's trusted repositories with the same claim, **When** it is audited, **Then** the claim is shown as pending confirmation and the control counts as non-compliant.
3. **Given** a trusted repository whose not-applicable claim is contradicted by evidence (for example it claims to publish no releases but releases exist), **When** it is audited, **Then** the claim is not honored, the contradiction is reported with its evidence, and the control is evaluated normally.
4. **Given** a pending claim, **When** a trusted party confirms it through darnit's confirmation flow, **Then** later audits honor it until the confirmation expires or the evidence it was based on changes, and the report records who confirmed it and when.
5. **Given** any result that counts as not applicable because of an assertion, **When** an attestation is produced, **Then** the attestation records the result as asserted, with the asserter and, where applicable, the confirmer.

---

### User Story 4 - CI runs apply trust according to the triggering event (Priority: P2)

An operator runs darnit in CI. A run triggered by a push to the default branch of a repository they trust should behave like their own local run; a run triggered by a pull request from a fork must be treated as untrusted even for a trusted repository, because the fork author controls the checked-out content.

**Why this priority**: CI is a primary automation surface, and pull requests from forks are the most common way untrusted content reaches an otherwise trusted repository.

**Independent Test**: Run the same audit under a simulated default-branch push and a simulated fork pull request for a repository in the trusted list, and confirm trust is granted only in the first case.

**Acceptance Scenarios**:

1. **Given** operator CI trust rules that trust default-branch pushes for trusted repositories, **When** an audit runs for such a push, **Then** the repository is treated as trusted.
2. **Given** the same rules, **When** an audit runs for a pull request from a fork, **Then** the repository is treated as untrusted regardless of the trusted list.
3. **Given** no CI trust rule matches the run, **When** an audit runs in CI, **Then** the repository is treated as untrusted.

---

### User Story 5 - Existing .baseline.toml users migrate with clear guidance (Priority: P2)

A maintainer has an existing `.baseline.toml`. After upgrading, they need to know what still applies, what moved, and how to move it, without their audits silently changing meaning.

**Why this priority**: Retiring a user-facing file needs a predictable path, but the population using it is small, so this follows the core stories.

**Independent Test**: Audit a repository with a representative `.baseline.toml` during the deprecation period and confirm the warning names each setting, where it now belongs, and how to migrate; run the migration and confirm the resulting `.project/` and operator configuration reproduce the intended behavior.

**Acceptance Scenarios**:

1. **Given** a repository with a `.baseline.toml`, **When** it is audited during the deprecation period, **Then** darnit warns that the file is deprecated and, for each setting, says whether it is a project assertion (moves to `.project/`) or tool configuration (moves to operator configuration, and is not read from the repository).
2. **Given** the migration is run on that repository, **When** it completes, **Then** project assertions are written to `.project/` and a proposed operator configuration fragment is produced for the operator to review; nothing is written to operator configuration automatically.
3. **Given** the deprecation period has ended, **When** a repository still contains `.baseline.toml`, **Then** darnit ignores it and reports that it was ignored.

### Edge Cases

- A repository-scoped coding-agent registration (a project-level MCP server configuration committed to the repository) launches darnit with arguments pointing at a configuration file inside the repository: darnit must refuse to load operator configuration from within the audited tree and say why.
- The operator configuration file is malformed or has unknown keys: darnit stops with a clear error naming the file and key rather than running with partial configuration.
- The operator configuration file is writable by other users: darnit warns (and in strict mode refuses) because operator configuration is a trust anchor.
- The audited repository is inside the directory that holds operator configuration, or vice versa: repository content is still never read as operator configuration.
- A trusted repository is identified by a different URL form (SSH vs HTTPS, trailing `.git`, case differences): repositories are matched on a canonical identity.
- A not-applicable claim names a control that does not exist in the selected framework: the claim is reported as unknown and has no effect.
- A not-applicable claim has no reason: it is reported and treated as pending even for a trusted repository.
- Evidence needed to check a claim is unavailable (network or permission error): the claim is treated as pending, not as uncontradicted.
- A confirmation was based on evidence that has since changed: the confirmation no longer applies and the claim returns to pending.
- A checkout's version-control configuration names a different repository than the one the operator asked to audit (for example a fork whose remotes point at the upstream project): the operator's target identity is used, and the mismatch is reported.
- Project data in `.project/` sets a value that would make many controls not applicable at once (for example "no releases"): each affected control is treated as asserted not applicable and is subject to the trust and evidence rules.

## Requirements *(mandatory)*

### Functional Requirements

**Operator configuration**

- **FR-001**: darnit MUST support a user-level operator configuration file in a standard per-user location for the host operating system.
- **FR-002**: Every driver (CLI, MCP server, headless harness) MUST locate operator configuration the same way: an explicit path given at launch if present, otherwise the standard per-user location, otherwise built-in defaults.
- **FR-003**: Configuration precedence MUST be: built-in defaults, then operator configuration, then per-run flags. No content of an audited repository may enter this chain.
- **FR-004**: darnit MUST refuse to load operator configuration from a path inside the audited repository, and MUST report the refusal.
- **FR-005**: Operator configuration MUST be able to express: allowed plugins and trusted publishers; MCP servers and their launch commands; integrations and custom checks or controls; storage backends; LLM provider, model, and spending budgets; the list of trusted repositories; CI trust rules; and policy defaults including confirmation expiry.
- **FR-006**: Operator configuration MUST be validated on load; unknown keys and invalid values MUST stop the run with an error naming the file and key.
- **FR-007**: darnit MUST warn when the operator configuration file is writable by users other than its owner, and MUST offer a strict mode in which such a file is refused.
- **FR-008**: darnit MUST NOT provide any environment variable or repository-side switch that grants trust to repository content; trust decisions MUST come only from operator configuration.
- **FR-009**: Every run MUST record, in its report, which operator configuration source was used (path or "built-in defaults") and a digest of its content, without exposing secrets it contains.

**Repository content and assertions**

- **FR-010**: darnit MUST treat all content of the audited repository as untrusted input. Repository content MUST NOT change which commands or checks run, how a step concludes, which plugins, servers, integrations, or stores are used, or any budget or trust setting.
- **FR-011**: Project assertions (including not-applicable claims with reasons) MUST be read from `.project/`, using upstream `.project/` fields where they exist and darnit's `.project/` extension file otherwise.
- **FR-012**: Files darnit writes to `.project/` MUST conform to the upstream `.project/` schema; where `.project/` cannot express a needed assertion, the specification's companion artifacts MUST list the proposed upstream change.
- **FR-013**: Every assertion MUST be reported with who asserted it and where it was recorded.
- **FR-013a**: Project data read from the audited repository that can change a control's applicability (for example a context value such as "has releases" or "platform" that a control's applicability condition depends on) MUST be treated as a project assertion under FR-014 through FR-020. A control made not applicable by such a value is subject to the same trust, evidence, and labelling rules as an explicit not-applicable claim.

**Not-applicable claims and compliance**

- **FR-014**: A project-asserted not-applicable claim MUST count as not applicable only when the repository is trusted (per FR-016) AND no available evidence contradicts the claim.
- **FR-015**: Otherwise the claim MUST be reported as pending confirmation, and the control MUST count as non-compliant (Principle II) until a trusted party confirms the claim.
- **FR-016**: A repository is trusted only if its canonical identity appears in the operator's trusted repositories and, for CI runs, the operator's CI trust rules permit trust for the triggering event. Pull requests from forks MUST never be trusted.
- **FR-016a**: The repository identity used for trust decisions MUST come from the operator (the audit target the operator named) or from CI platform metadata, never solely from the audited checkout's own version-control configuration. When the identity cannot be established from those sources, the repository MUST be treated as untrusted.
- **FR-017**: Controls MAY declare evidence that can contradict a not-applicable claim (for example the platform's release data for a "no releases" claim). When such evidence cannot be obtained, the claim MUST be treated as pending, not uncontradicted.
- **FR-018**: A claim without a reason MUST be treated as pending regardless of trust.
- **FR-019**: A confirmation of a claim MUST record who confirmed it, when, and the evidence it was based on; it MUST lapse when it expires or when that evidence changes.
- **FR-019a**: Confirmations MUST be stored on the operator side (not in the audited repository), keyed by canonical repository identity, the claim, and a digest of the evidence the confirmation was based on.
- **FR-020**: Reports and attestations MUST label every result that counts as not applicable because of an assertion as "asserted", with the asserter and, where present, the confirmer.

**Retiring .baseline.toml**

- **FR-021**: During a deprecation period of at least one minor release, darnit MUST read only project assertions from `.baseline.toml`, treat them exactly as `.project/` assertions under FR-014 through FR-020, and warn for every setting in the file with its new home.
- **FR-022**: darnit MUST provide a migration that moves project assertions from `.baseline.toml` into `.project/` and produces a proposed operator configuration fragment for settings that belong to the operator. The migration MUST NOT write to operator configuration itself.
- **FR-023**: After the deprecation period, darnit MUST ignore `.baseline.toml` and report that it was ignored.
- **FR-024**: Project documentation and generated guidance (including agent skills) MUST describe operator configuration as the only place for tool configuration and MUST NOT instruct users to place tool configuration in the audited repository.

### Key Entities

- **Operator configuration**: Tool configuration owned by whoever runs darnit. Attributes: source (path or defaults), content digest, plugin and publisher trust, MCP servers, integrations and custom checks, stores, LLM settings and budgets, trusted repositories, CI trust rules, policy defaults.
- **Trusted repository entry**: A canonical repository identity the operator trusts, optionally scoped by CI trust rules.
- **CI trust rule**: A condition on the triggering event (for example "push to default branch") under which a trusted repository is treated as trusted in CI.
- **Project assertion**: A claim a project makes about itself, recorded in `.project/`. Attributes: subject (for example a control), claim (for example not applicable), reason, asserter, location.
- **Confirmation**: A trusted party's acceptance of a pending assertion, stored on the operator side. Attributes: repository identity, claim, confirmer, time, evidence digest, expiry.
- **Contradicting evidence**: Evidence a control declares as able to refute a not-applicable claim, with its source and observation time.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: In a test suite that plants tool configuration in every file an audited repository can contain, 100% of planted settings have no effect on what runs or how results conclude, and every one is reported as ignored.
- **SC-002**: The same operator configuration produces identical effective settings under all three drivers in 100% of test cases.
- **SC-003**: For a repository not in the trusted list, 0% of project-asserted not-applicable claims -- explicit claims or applicability-changing project data -- reduce the number of controls counted toward compliance before confirmation.
- **SC-004**: For a trusted repository, 100% of claims with contradicting evidence are reported as contradicted and are not honored.
- **SC-005**: A maintainer with an existing `.baseline.toml` can migrate it in under 5 minutes using the deprecation warning and migration alone, with no audit result changing meaning without a warning.
- **SC-006**: Every attestation produced in the test suite that contains a not-applicable result from an assertion labels it as asserted, with the asserter.

## Assumptions

- The "trusted party" who can confirm a pending claim is the operator, acting through darnit's existing confirmation flow; delegating confirmation to other people is out of scope for this feature.
- Repository identity is canonicalized from the platform host, owner, and name, so different URL forms of the same repository match.
- CI runs are recognized from the CI platform's standard event information; when the event cannot be determined, the run is untrusted.
- Confirmation expiry defaults follow the RFC-0001 proposal (per-key, with a 180-day default) and are overridable in operator configuration.
- Controls that declare no contradicting evidence cannot contradict a claim; for trusted repositories such claims count as not applicable, labelled as asserted.
- Organization-level policy sources are out of scope (tracked in #503); this feature defines only user-level operator configuration.
- The number of existing `.baseline.toml` users is small, so a single-minor-release deprecation period is sufficient.
