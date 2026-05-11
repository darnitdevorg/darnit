# Feature Specification: Packaging & Distribution Channels

**Feature Branch**: `012-packaging-distribution`
**Created**: 2026-05-10
**Status**: Draft
**Input**: User description: "Explore the various packaging options and start implementing them"

## Clarifications

### Session 2026-05-11

- Q: Which Python tool runner(s) should the Claude Code plugin treat as acceptable prerequisites for invoking the darnit MCP server? → A: Try `uvx` first, fall back to `pipx run`, error if neither exists. Future invocation modes (bundled binary, container-based) tracked as follow-up; not in scope for v1.
- Q: Which channels should publish pre-releases (release candidates), and which should publish only stable releases? → A: Pre-releases publish to the package index's pre-release channel, the container registry (with `-rc` tags), and GitHub release binary attachments. The Homebrew formula and the Claude Code plugin manifest publish stable releases only.
- Q: What is the compressed size cap for the published container image? → A: 300 MB compressed as a target, not a hard cap. A release exceeding the target is acceptable when justified (e.g., a needed runtime tool was added), but the size must be tracked release-over-release and significant growth must be acknowledged in the release notes.

## Context

Today, the only way to install darnit is to clone the repository and run `uv` against the workspace. That works for contributors and a handful of early evaluators, but it locks out every other audience the project is supposed to serve: security teams who want a single download, CI pipelines that don't want to manage a language toolchain on their runners, macOS engineers whose first instinct is `brew install`, agent users who expect their coding agent to install plugins by name, and third-party teams who want to ship their own compliance implementations on top of darnit's framework.

This feature defines the channels through which darnit is published, and the user-visible outcomes each channel must deliver. The umbrella tracking work is split across upstream issues #228 (PyPI), #229 (binary + pipx + Homebrew), #230 (container image), #231 (Claude Code plugin), and #232 (third-party plugin packaging guide). This spec consolidates them into one feature so the work can be planned, sequenced, and validated coherently.

## User Scenarios & Testing *(mandatory)*

### User Story 1 — Python user installs from a package index (Priority: P1)

A security engineer wants to try darnit on their team's repository. They have Python 3.11 or newer already installed. They run a single package-manager command to install darnit, then run an audit. They never read source code, never clone a repository, and never see a build tool.

After this change, that engineer can install darnit by name from the public Python Package Index. The same path also works for users who prefer isolated tool installation: a single command places `darnit` on their PATH, and the install is fully isolated from any project's Python environment.

**Why this priority**: This is the foundational install path. Every other channel in this feature either depends on it (the Homebrew formula sources from it, the container image installs from it, the Claude Code plugin can invoke it via a Python-runner) or coexists with it as an alternative for the same audience. Without P1, every other channel becomes a bespoke effort.

**Independent Test**: On a clean machine with only a supported Python version installed, install darnit by name from the public package index. Confirm the `darnit` command is on PATH and `darnit --version` prints the expected version. Repeat with the isolated-install workflow (a tool that installs Python packages into their own environments) and confirm the same.

**Acceptance Scenarios**:

1. **Given** a clean machine with a supported Python version, **When** the user runs the standard install command for the public package index, **Then** darnit is installed, the `darnit` command resolves on PATH, and `darnit --version` returns the expected release version.
2. **Given** the same clean machine, **When** the user runs the isolated-tool install command, **Then** darnit is installed into its own isolated environment without affecting any other Python project on the machine, and `darnit --version` still succeeds.
3. **Given** an installed copy of darnit from the package index, **When** the user inspects the artifact's signature using the project's published verification method, **Then** the signature verifies against the project's published identity.
4. **Given** a machine running an unsupported Python version, **When** the user attempts to install darnit, **Then** the package index reports a clear, human-readable error that names the Python version requirement; no partial install occurs.
5. **Given** a release is published, **When** a user installs that exact version six months later, **Then** the install still succeeds (releases are not silently retracted or rewritten).

---

### User Story 2 — CI/CD pipeline runs darnit from a container image (Priority: P2)

A platform engineer wants every pull request in their organization to run a darnit audit and post the results. They do not want to install Python on their runners, manage interpreter versions, or maintain a Dockerfile of their own. They want one image reference, pinned by version, that runs the audit and exits.

After this change, the engineer references a published container image in their CI configuration. The image runs on the two most common CPU architectures, carries a verifiable signature, and ships an SBOM as an attestation. The image is small enough that it does not dominate CI pull time, and it contains the runtime tools darnit's controls expect to invoke (such as `git` and the GitHub CLI).

**Why this priority**: CI is one of darnit's largest deployment surfaces and the audience least willing to manage a Python toolchain on the host. P2 because the same user can fall back to P1 (install in a CI step that already has Python) in the interim; the container image makes the experience first-class.

**Independent Test**: On a clean machine with only a container runtime installed, pull the published image by version tag and run a darnit audit against a sample repository mounted as a volume. The audit must complete and produce output. Then verify the image signature using a standard verification tool and download the attached SBOM.

**Acceptance Scenarios**:

1. **Given** a clean machine with only a container runtime installed, **When** the engineer pulls the published image and runs an audit against a mounted repository, **Then** the audit produces output identical in shape to what a PyPI-installed darnit produces.
2. **Given** the published image, **When** the engineer requests a specific platform architecture (the two most common CPU architectures), **Then** the appropriate variant is pulled automatically.
3. **Given** an image tagged for a specific version, **When** the engineer verifies its signature using a standard verification tool, **Then** the signature verifies against the project's published identity.
4. **Given** an image tagged for a specific version, **When** the engineer downloads its attached attestation, **Then** an SBOM listing the image's contents is available and consumable by standard SBOM tooling.
5. **Given** an image is pulled fresh, **When** the engineer measures the compressed image size, **Then** it stays within an agreed budget that does not materially slow CI runs (target: well under one second of pull-time per typical CI region for the size).

---

### User Story 3 — Engineer installs via the platform's native package manager (Priority: P3)

A senior engineer evaluating darnit on a Mac (or a Linux developer who uses Homebrew) wants to install it the same way they install every other CLI tool on their machine. They expect a single command, no Python toolchain management, no manual download-and-unzip step, and an automatic update path when a new release ships.

After this change, that engineer can install darnit from a Homebrew tap. The formula downloads a pre-built standalone binary attached to each GitHub release — not source — so installation is fast and does not depend on the user having Python installed. The same binaries that back the Homebrew formula are also directly downloadable from each release for users who want to skip the package manager entirely.

**Why this priority**: This is the highest-trust install path for individual engineers and the one most likely to convert a casual evaluator into a regular user. P3 because it is built on top of the binary artifacts and PyPI release plumbing; it can only ship after those foundations exist.

**Independent Test**: On a clean macOS machine (arm64 and amd64 separately), run the Homebrew install command. Confirm `darnit --version` succeeds afterward. Separately, on a clean machine, download the standalone binary for the appropriate platform from a GitHub release, place it on PATH, and confirm `darnit --version` succeeds.

**Acceptance Scenarios**:

1. **Given** a clean macOS machine, **When** the engineer runs the Homebrew install command for darnit, **Then** the install completes and `darnit --version` succeeds on the appropriate architecture (Apple Silicon or Intel).
2. **Given** the same setup on Linux with Homebrew installed, **When** the engineer runs the install command, **Then** the install completes successfully on the appropriate architecture.
3. **Given** a new darnit release is published, **When** the next Homebrew update runs on the engineer's machine, **Then** the formula reflects the new release within a short, documented window without requiring the engineer to take any extra action.
4. **Given** a release exists, **When** the engineer downloads the standalone binary directly from the GitHub release for their platform, places it on PATH, and runs it, **Then** `darnit --version` succeeds with no other installation steps.
5. **Given** a downloaded binary, **When** the engineer verifies its signature using the project's documented method, **Then** the signature verifies against the project's published identity.

---

### User Story 4 — Coding-agent user installs darnit as a plugin (Priority: P4)

A developer working in a coding agent (initial target: Claude Code) wants to enable darnit's audit, context, comply, and remediate skills in their agent with one install command. They do not want to write configuration files, register MCP servers manually, copy skill files, or know how darnit's internals are wired. They just want the agent to expose the four skills and the audit/remediate tools.

After this change, the developer can install darnit as a first-class plugin in their coding agent. The plugin bundles the MCP server invocation, the four existing skills, and any necessary configuration. When installed, the four slash commands appear in the agent immediately and operate against the user's current repository without further setup.

**Why this priority**: darnit's primary user is a coding agent — this is the most natural install path for the actual audience. P4 because it depends on at least one underlying install path existing (P1 or P3) so the plugin has something to invoke; without those, the plugin install would have to bundle its own Python toolchain or binary, which is a larger scope.

**Independent Test**: On a clean install of the supported coding agent, run the plugin install command. Verify all four skills appear in the agent's skill list, then invoke the audit skill against a sample repository and confirm it produces output without requiring any other manual setup.

**Acceptance Scenarios**:

1. **Given** a fresh install of the supported coding agent on a developer's machine, **When** the developer runs the documented plugin install command, **Then** the plugin installs successfully and all four darnit skills become available in the agent.
2. **Given** the plugin is installed, **When** the developer invokes the audit skill against a sample repository, **Then** the skill executes, the MCP server is started transparently, and the audit produces output identical in shape to a CLI-invoked audit.
3. **Given** the plugin is installed, **When** the developer's machine has neither a Python toolchain nor a darnit binary pre-installed, **Then** the plugin either bundles or installs the necessary runtime automatically on first use, or it fails with a clear, actionable message naming the prerequisite to install.
4. **Given** a new darnit release ships, **When** the user updates their plugin, **Then** the updated plugin uses the new darnit version without requiring the user to manage anything beyond a plugin-update command.

---

### User Story 5 — Third-party team ships their own implementation plugin (Priority: P5)

A platform team at another company wants to publish their internal compliance baseline as a darnit implementation. They have read about darnit's plugin protocol but cannot tell from the source code alone how to lay out their package, declare their entry point, sign their artifact, or test it end-to-end against darnit's framework before publishing. They need a single document that tells them exactly what to do, plus a working tiny example they can copy.

After this change, that team can read a published packaging guide and a worked "hello-world" implementation, follow the steps, and publish their own implementation. After installation, darnit discovers their implementation automatically through the existing plugin protocol without any modifications to darnit itself.

**Why this priority**: The framework already supports third-party plugins via entry points, but the path is undocumented externally — today, someone who wants to do this has to read darnit's source. Documenting it unlocks an ecosystem. P5 because the underlying mechanism already exists; this story is documentation and example work, not new framework capability.

**Independent Test**: A test team unrelated to darnit's core maintainers follows the guide from a clean state and publishes a minimal implementation as a separate package. After installing both darnit and the new implementation on the same machine, the new implementation appears in darnit's implementation list and at least one of its controls can be audited end-to-end.

**Acceptance Scenarios**:

1. **Given** the published packaging guide and the worked hello-world example, **When** an external developer follows the steps in order, **Then** they produce a publishable package that registers a working implementation, with no need to read darnit's source to fill gaps.
2. **Given** a published third-party implementation, **When** a user installs both darnit and the third-party implementation on the same machine, **Then** darnit's implementation-discovery surface lists the third-party implementation without any additional configuration step.
3. **Given** the hello-world example, **When** a developer audits its single control end-to-end, **Then** the audit succeeds and produces output in the same shape as built-in implementations.
4. **Given** the published guide, **When** a developer needs to sign their plugin artifact, **Then** the guide describes a signing path that integrates with darnit's existing plugin-trust configuration without ad-hoc instructions.

---

### Edge Cases

- **Release tag mistyped or rolled back**: A malformed or rolled-back tag must not trigger a public release. The release pipeline must reject anything that does not match the expected tag pattern, and once a release is published, it must not be silently rewritten in place (immutability of published versions).
- **Partial publish failure**: If a release pipeline uploads some artifacts and then fails (for example, PyPI succeeds but container push fails), the release must be marked clearly as incomplete and the documented recovery path must allow re-running the failed steps without producing duplicates.
- **Unsupported host environment**: Each channel must fail fast and human-readably when the host doesn't meet its prerequisites (wrong Python version for PyPI, missing container runtime, wrong architecture, missing Homebrew, agent version below the plugin's minimum).
- **Architecture coverage gaps**: Users on architectures the project doesn't ship binaries for (today: Windows, Linux on architectures outside the two most common) must get a clear message pointing them to the source-install path, not a silent failure or a binary that crashes.
- **Stale Homebrew formula**: If a release ships but the formula auto-update fails, the formula must remain pinned to the previous working release rather than briefly publishing a broken state. A monitoring signal must surface the stale formula so it can be fixed.
- **Plugin invocation when prerequisites missing**: A coding-agent plugin must not produce silent failure when its underlying runtime is missing. It must surface a clear prerequisite error to the agent user.
- **Third-party implementation conflicts with built-in**: If a third-party implementation declares the same name as a built-in implementation, the framework must surface the conflict at install or discovery time, not produce undefined behavior at audit time.
- **Signature verification by default vs. opt-in**: At least one supported install path must allow signature verification as a documented step. The verification path must work against a freshly downloaded artifact with no prior trust setup beyond installing the standard verification tool.

## Requirements *(mandatory)*

### Functional Requirements

#### General release machinery

- **FR-001**: Each release MUST be triggered by a single, repeatable, auditable action (a tag on the canonical repository) and MUST produce all per-channel artifacts for that release from the same commit.
- **FR-002**: Each release artifact MUST be derivable solely from its tagged source commit, with no out-of-band inputs. The signing certificate on every artifact MUST bind it to a specific workflow run on a specific tag in the canonical repository (verifiable by anyone via the published verification commands). Re-running the release pipeline on an already-published tag is rejected by design (see release-workflow contract) — the pipeline does not promise byte-deterministic rebuilds; it promises a verifiable single source of origin.
- **FR-003**: Every published artifact MUST carry a signature verifiable against the project's published identity using a standard, openly documented verification tool.
- **FR-004**: Versioning across the workspace packages MUST follow a single, documented strategy and MUST be applied consistently across channels (the version of an installed PyPI package, the tag of an installed container image, and the version reported by an installed binary must match for the same release).
- **FR-005**: A new release MUST update each channel's primary user-facing surface (PyPI listing, container registry tag, GitHub release with binary assets, Homebrew formula, agent plugin manifest) within a documented window after the tag is pushed.

#### Package index (PyPI)

- **FR-006**: The public package-index publication MUST cover the set of packages the project designates as user-facing, and MUST exclude packages designated as internal-only (test-only or example-only). The exact set MUST be documented in the release process.
- **FR-007**: The package-index publication MUST use credential-less authentication backed by the publishing platform's identity, with no long-lived publishing tokens stored anywhere.
- **FR-008**: A pre-release flow MUST exist that publishes release candidates to the following channels: the public package index's pre-release area (e.g., TestPyPI or equivalent), the container registry under a distinct `-rc` tag, and GitHub release binary attachments marked as pre-release. The Homebrew formula and the Claude Code plugin manifest MUST NOT auto-update from pre-release tags; they update only on stable releases. The release pipeline MUST treat pre-release tags differently from stable tags by default and MUST surface this distinction in published artifact metadata.

#### Container image

- **FR-009**: A container image MUST be published per release, available on at least the two most widespread CPU architectures, signed, and accompanied by a downloadable SBOM as an attestation.
- **FR-010**: The container image MUST include the runtime command-line tools that darnit's controls routinely invoke when those tools are not optional for the typical audit (for example, version control and the GitHub CLI). The image's compressed size targets 300 MB; this is a soft target, not a hard cap — releases that exceed it are permitted with justification, but compressed size MUST be reported in the release notes and tracked release-over-release.
- **FR-011**: The image MUST be runnable with sensible defaults so that a single `run`-style invocation against a mounted repository can produce an audit result.

#### Standalone binary and Homebrew

- **FR-012**: Each release MUST publish standalone, self-contained binary artifacts for macOS and Linux on the two most common CPU architectures, downloadable from the GitHub release page.
- **FR-013**: A Homebrew tap MUST exist and MUST publish a formula for darnit that installs from the standalone binary artifacts published in FR-012 (not from source).
- **FR-014**: When a new release is published, the Homebrew formula MUST update automatically within a documented window, without manual intervention from a maintainer.

#### Coding-agent plugin

- **FR-015**: An installable coding-agent plugin MUST exist for at least one supported agent (initial target: Claude Code) that bundles the existing four skills and the MCP server configuration into a single installable unit.
- **FR-016**: Once installed, the plugin MUST make the four skills (`darnit-audit`, `darnit-context`, `darnit-comply`, `darnit-remediate`) available in the agent without requiring the user to edit configuration files or register the MCP server by hand.
- **FR-017**: The plugin MUST attempt to invoke the MCP server via `uvx` first, and if `uvx` is not found on PATH, MUST attempt the same invocation via `pipx run`. If neither runner is present, the plugin MUST surface a single, actionable error message naming both prerequisites and a documented install path for each, rather than failing silently.

#### Third-party plugin packaging guide

- **FR-018**: A published guide MUST describe how an external team packages a new implementation as a darnit plugin, including the minimum required project metadata, the entry-point declaration, the way controls are defined, the way the plugin is tested, the signing path, and the trust configuration.
- **FR-019**: The guide MUST be accompanied by a runnable hello-world implementation in its own directory that can be packaged and installed independently of darnit's primary implementations.

#### Cross-channel

- **FR-020**: Each channel MUST publish prerequisites prominently in its install documentation (the host Python version, the host architecture, the container runtime, the agent version, etc.).
- **FR-021**: Documentation MUST exist that maps a user's situation to the recommended channel (a single decision tree or comparable artifact) so a user lands on the right channel on first read.
- **FR-022**: The release process MUST be documented end-to-end so any maintainer with the appropriate permissions can perform a release without tribal knowledge.

### Key Entities

- **Release**: A versioned, immutable bundle of artifacts produced by tagging the canonical repository. Carries a single version identifier that appears identically across every channel for that release.
- **Channel**: A distinct user-facing distribution surface (public package index, container registry, Homebrew tap, GitHub release binary assets, coding-agent plugin marketplace). Each channel produces its own artifact form, but all channels for a given release reference the same source commit and version.
- **Artifact**: A single signed, versioned output of the release pipeline (a wheel, a container image, a binary, a formula bump, a plugin manifest). Each artifact has at minimum: a version, a channel, a signature, and a published location.
- **Attestation**: Verifiable metadata associated with an artifact — at minimum a signature and (for the container image and binaries) an SBOM. Consumable by the project's documented verification tooling.
- **Plugin** (third-party implementation): A separately published, separately versioned compliance implementation that darnit discovers at runtime via its entry-point mechanism. Not produced by darnit's release pipeline; produced by external teams following the published guide.

## Success Criteria *(mandatory)*

### Measurable Outcomes

- **SC-001**: A user with a supported Python version installed can run a single install command from the public package index and have `darnit --version` succeed within 60 seconds on a typical broadband connection.
- **SC-002**: A CI pipeline using the published container image can complete a darnit audit of a small reference repository (one runtime tool's worth of fetched dependencies) in under 90 seconds end-to-end on a standard hosted runner, with image-pull time accounting for less than 20% of that budget. The compressed image size targets 300 MB; releases that exceed the target are permitted when justified, but the size MUST be tracked release-over-release and material growth MUST be called out in the release notes.
- **SC-003**: A macOS engineer can install darnit via Homebrew with one command and have `darnit --version` succeed within 60 seconds on a typical broadband connection, on both Apple Silicon and Intel.
- **SC-004**: A coding-agent user can install the plugin and successfully run `/darnit-audit` against a sample repository without touching any configuration file, on the first attempt.
- **SC-005**: An external developer following the third-party packaging guide can produce a published implementation that darnit discovers, in under one engineering-day of work, without reading darnit's source code.
- **SC-006**: Every public artifact carries a signature that verifies against the project's published identity using a standard verification tool, with the verification command discoverable from the install documentation in one click.
- **SC-007**: A new release's per-channel surfaces all reflect the new version within 30 minutes of the release tag being pushed. Synchronous channels (PyPI, container registry, GitHub release binaries, plugin manifest) are bounded by the release workflow's runtime; the workflow MUST fail-fast and surface a `release-failure` issue if total runtime for a stable tag exceeds 30 minutes. Asynchronous channels (Homebrew formula via cross-repo dispatch) MUST surface the same failure if the tap PR is not merged within 30 minutes of dispatch. The `finalize` job records per-channel published-at timestamps and flags any channel exceeding the budget in the release notes and in any failure issue.
- **SC-008**: A release pipeline failure on a single channel does not block other channels from publishing for that release, and the partial-failure state is surfaced (not silently swallowed) within 5 minutes of the failure.
- **SC-009**: The decision-tree documentation lets a new evaluator select the right install channel for their situation correctly on the first read in 90% of cases in informal user testing.

## Assumptions

- **Supported Python versions**: The same range the project targets today (3.11 and 3.12). Adding 3.13 is out of scope for this feature.
- **Versioning strategy**: Lockstep across all workspace packages. Each release produces the same version number on every public package. This is the simplest model and matches how the workspace currently versions itself. Independent per-package versioning is deliberately out of scope; if the project later wants it, that is a new feature.
- **Public vs. internal packages**: `darnit`, `darnit-baseline`, `darnit-gittuf`, and `darnit-mcp` are public; `darnit-example`, `darnit-testchecks`, and `darnit-plugins` are internal/example-only and not published to the public index for this feature. The exact list can be revised during planning.
- **Architecture coverage for binaries and containers**: macOS arm64 and amd64, Linux arm64 and amd64. Windows is explicitly deferred — darnit shells out heavily to POSIX tooling today, and adding Windows support is a separate, larger scope.
- **Signature scheme**: A keyless, OIDC-backed signing identity scheme (the most common pattern for modern open-source projects) is assumed. Specific tooling choices belong in the plan, not this spec.
- **Container registry**: GitHub's container registry, given the project already lives on GitHub. Mirroring to additional registries is out of scope.
- **Homebrew tap location**: A single project-wide tap (one tap that may later host multiple kusari tools). Submitting to homebrew-core is a follow-up, not part of this feature.
- **Coding-agent target**: Claude Code is the first and only agent in scope for this feature. Other agents (Cursor, Windsurf, Continue, Cline) are explicitly deferred to follow-up features.
- **Plugin runtime invocation**: The Claude Code plugin invokes the MCP server through `uvx` by default and falls back to `pipx run` if `uvx` is not available. The plugin does not bundle a Python toolchain or a darnit binary in v1; the user is expected to have one of the two runners installed. Additional invocation modes — bundling the standalone binary from User Story 3, or invoking through a container image — are explicit follow-up work, not part of v1.
- **Release cadence**: This feature does not commit to a release cadence (weekly, monthly, on-demand). It commits only to making each release, whenever it happens, propagate cleanly across all channels.
- **Repository home**: All release pipelines live in the upstream `kusari-oss/darnit` repository. The historical `kusaridev/darnit-mcp` URLs in `pyproject.toml` are treated as project metadata to be reconciled during planning, not a separate distribution home.

## Out of Scope

- **Windows binaries, Homebrew on Windows, or Windows-specific channels**: Excluded because darnit's controls assume POSIX tooling. Tracked separately.
- **Other coding agents** (Cursor, Windsurf, Continue, Cline, etc.): Excluded from this feature; covered by future work once Claude Code is solid.
- **Mirroring to additional package indexes or registries** (Anaconda, Docker Hub, Quay): Excluded for v1.
- **Independent per-package versioning across the workspace**: Excluded; lockstep is the v1 strategy.
- **A separate composite "darnit-all" mega-package**: Excluded; users compose their own install set from the public packages.
- **Cross-implementation composition** (the feature filed in upstream issue #233): Distinct feature, not packaged or sequenced here.
- **A dedicated release cadence schedule**: Excluded; the spec covers the mechanics of releasing, not when releases happen.
- **Additional Claude Code plugin invocation modes**: Bundling the standalone binary inside the plugin, or invoking the MCP server through a container image, are deferred. v1 supports `uvx`/`pipx run` only; alternative modes will be tracked as follow-up issues once v1 is stable in the field.
