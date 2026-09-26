# Phase 0 Research: Operator Configuration and Trust Model

Each item records the decision, the rationale, and the alternatives considered. Codebase references are to `main` at the time of writing.

## R1. Where operator configuration lives

- **Decision**: One file per operating system, never discovered by searching upward from the working directory.
  - Linux and macOS: `$XDG_CONFIG_HOME/darnit/config.toml` when `XDG_CONFIG_HOME` is set and absolute, otherwise `~/.config/darnit/config.toml`.
  - Windows: `%APPDATA%\darnit\config.toml`.
  - An explicit `--operator-config PATH` at launch overrides the default location for CLI, MCP server, and harness.
- **Rationale**: Matches gh, uv, ruff, git, direnv, and mise, which all use `~/.config` on macOS as well as Linux. Extending `darnit/stores/defaults/platform_paths.py` (which already resolves data and cache roots without new dependencies, per feature 034) keeps one path-resolution module. Relative `XDG_*` values are ignored per the XDG Base Directory specification.
- **Alternatives considered**: `platformdirs` (not a direct dependency; its macOS behavior for `XDG_CONFIG_HOME` changed in 4.6.0, so results would depend on a transitive version); `~/Library/Application Support` on macOS (unfamiliar location for CLI users); an environment variable selecting the file (rejected: one more ambient input a repository-scoped launcher can set; the flag covers every driver).
- **Naming**: `--operator-config` rather than `--config`, because `darnit serve` already takes a positional framework-config argument and the two must not be confused.

## R2. Trust anchoring for operator configuration

- **Decision**: Operator configuration is loaded only from protected sources, following git's "protected configuration" rule (introduced with `safe.directory` after CVE-2022-24765):
  - **Containment**: after all inputs are applied, resolve the real path of the configuration file and refuse it if it lies inside the audited repository. The check runs for every audit, because an MCP server process may audit several repositories.
  - **Permissions**: on POSIX, following OpenSSH's `StrictModes` check, the file and its parent directories must be owned by the current user (or root) and must not be group- or world-writable. Default: warn. Strict mode: refuse. Strict mode is a launch option (`--strict-operator-config`), on by default in recognized CI; the file itself may only turn it on, since a file that fails the check cannot be trusted to relax it. On Windows, strict mode refuses because the equivalent check is not implemented.
  - **Validation**: unknown keys and invalid values are errors naming the file and dotted key. A required `schema_version = 1`; an unknown or missing version is an error.
  - **Secrets**: referenced by environment-variable name only, so a digest of the file can appear in reports without leaking credentials.
- **Rationale**: The operator configuration is the trust anchor for everything else; a trust anchor that a repository can influence is not one.
- **Alternatives considered**: `direnv allow`-style hash pinning of the configuration file itself (useful later, unnecessary for a file only the operator writes); silently ignoring bad keys (rejected: misplaced trust settings must fail loudly).

## R3. Canonical repository identity

- **Decision**: A small normalizer with no new dependency, producing `host/namespace/name`:
  - host lowercased; ports and user info removed; trailing `.git` removed;
  - path lowercased for hosts known to be case-insensitive (github.com, gitlab.com) and for hosts the operator lists as case-insensitive;
  - scp-like (`git@host:ns/name`), `ssh://`, and `https://` forms normalize to the same value;
  - unknown host aliases do not match (fail closed).
- **Identity source for trust decisions** (FR-016a): the audit target the operator named, then CI platform metadata. The checkout's own remotes are used only as a display hint and never to grant trust, and an `upstream` remote is never preferred over `origin`.
- **Rationale**: Remote URLs come from the checkout's own configuration, which is repository content. Existing helpers drop the host and prefer an `upstream` remote, which identifies a fork clone as its parent; neither is acceptable for a trust decision.
- **Alternatives considered**: `giturlparse` (not designed for security decisions); `git-url-parse` (unmaintained, known ReDoS advisory); pinning numeric platform repository IDs (valuable against repository takeover after rename; recorded as an optional extension, not required for v1).

## R4. CI trust rules

- **Decision**: CI trust is opt-in per rule; the default rule list is empty. The only v1 rule is `push-default-branch`:
  - GitHub Actions: event `push`, ref type branch, `GITHUB_REF` equals `refs/heads/<repository.default_branch>` from the event payload, the CI-reported repository identity matches a trusted entry, and the checked-out commit equals `GITHUB_SHA`.
  - GitLab CI: `CI_PIPELINE_SOURCE=push`, `CI_COMMIT_BRANCH` equals `CI_DEFAULT_BRANCH`, no merge-request context, and the CI-reported project identity matches a trusted entry.
  - Every pull-request, merge-request, `workflow_run`, and merge-queue event is untrusted. Fork detection, where needed for reporting, compares head and base repository IDs (a missing head repository counts as a fork); `head.repo.fork` is not used because it is true for same-repository pull requests inside a forked repository.
  - Unknown CI platform or undeterminable event: untrusted.
  - Reports record the CI facts used, so a consumer can see why trust was or was not granted.
- **Rationale**: Default-branch pushes are the only common event where the checked-out content has been through the repository's own review; pull requests from forks are authored by someone outside it.
- **Alternatives considered**: trusting same-repository pull requests (deferred: depends on branch-protection guarantees darnit cannot verify cheaply); a general expression language for rules (deferred until there is demand).

## R5. Repository-scoped agent registrations

- **Decision**: Documentation and skills instruct users to register darnit's MCP server at user scope. At each audit the server warns when its working directory, or the project directory an agent reports, lies inside the audited repository, and the containment check in R2 prevents operator configuration from being read from there.
- **Rationale**: Several coding agents let project-level configuration set an MCP server's command, arguments, and environment, and some load it without a prompt in non-interactive modes. darnit cannot control how it was launched, so it must not depend on launch-time inputs for trust.

## R6. Where project assertions and confirmations live

- **Decision**:
  - Not-applicable claims move to the existing `controls` section of `.project/darnit.yaml` (`{control_id: {status, reason}}`), extended with an optional `asserted_by`. When absent, the asserter is recorded as "repository content" (the claim is attributed to the repository, not to a person).
  - Applicability-changing project data (context values that a control's applicability condition reads) is treated as an assertion under the same rules (FR-013a).
  - Confirmations are stored on the operator side under the darnit data root, keyed by canonical repository identity, claim, and evidence digest (FR-019a), never in the audited repository.
  - Upstream `.project/` (schema 1.0.0) has no exemption concept and rejects unknown fields; darnit keeps these in its extension file and records a proposed upstream addition in the plan's follow-ups.
- **Rationale**: Reuses an existing home rather than inventing a new file; keeps untrusted content and trust decisions physically separate.
- **Alternatives considered**: a new `.project/exemptions.yaml` (another file to discover and validate, no benefit); storing confirmations in `.project/` (rejected: repository content cannot hold trust decisions).

## R7. Evidence that can contradict a not-applicable claim

- **Decision**: Controls may declare `contradicted_by` evidence in framework TOML: a reference to an existing detection or check whose result refutes the claim (for example the release-detection pipeline for a "no releases" claim). If the evidence cannot be obtained, the claim is pending (FR-017). Controls that declare nothing cannot be contradicted; for trusted repositories their claims count, labelled as asserted.
- **Rationale**: TOML-first (Principle III), and reuses the detection pipelines that already exist (for example release detection).
- **Initial coverage**: release-dependent controls (the most common not-applicable claims) declare the release-detection evidence; the context key that feeds them is corrected to list every control that depends on it.

## R8. Migration from .baseline.toml

- **Decision**: For one minor release, darnit reads only project assertions from `.baseline.toml`, applies FR-014 to FR-020 to them, and warns for every setting with its new home. A `darnit config migrate` command writes the assertions into `.project/darnit.yaml` and prints (never writes) a proposed operator configuration fragment for tool settings. After the deprecation release the file is ignored with a notice.
- **Test impact**: 8 fixture `.baseline.toml` files and 17 test modules construct user configuration; the parity-test corpus uses `.baseline.toml` as a fixture marker and needs a different marker.

## Follow-ups outside this feature

- Organization-level policy source (#503).
- Upstream `.project/` proposal for an exemption or applicability field.
- Attestation compliance math (#492) must treat pending claims as non-compliant; this feature's labelling depends on it but does not fix it.
