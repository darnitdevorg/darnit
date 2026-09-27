# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

## [0.1.1] - 2026-10-03

### Security

- A repository's own `.baseline.toml` is now treated as untrusted input. By
  default only `version`, `settings`, and `extends` naming a registered
  framework are honored; everything else is ignored with a warning: settings
  that could change what darnit executes or trusts (control `passes`,
  `check`, `remediation`, and `config` overrides, custom controls,
  `control_groups`, `adapters`, `mcp_servers`, `stores`, plugin trust
  settings, and `extends` file paths) and per-control `status`/`reason`
  exclusions, which would let the audited party remove controls from its own
  compliance result. These settings are moving to operator
  configuration that lives outside the audited repository.
  See GHSA-96qw-w4fw-5hcm.

### Removed

- Top-level `openspec/` directory. The 25 architectural specs that lived under
  `openspec/specs/<topic>/spec.md` were rehomed; the 12 archived proposals
  under `openspec/changes/archive/` were dropped (history preserved in `git log`).
- `scripts/generate_docs.py` and the `docs/generated/` output directory.
- The `doc-generation` job in `.github/workflows/ci.yml` and the
  "Generated docs are up to date" step in `.github/workflows/release.yml`.
- The "Generated docs" gate (item 4) from the Development Workflow in the
  project constitution.
- Pre-commit hook patterns referencing the openspec path.

### Added

- Operator configuration: a user-level TOML file found the same way by the
  CLI, MCP server, and harness (`--operator-config PATH`, else
  `$XDG_CONFIG_HOME/darnit/config.toml` or `~/.config/darnit/config.toml`,
  else built-in defaults). It is the only source of tool settings: plugins,
  MCP servers, pass overrides, custom controls, stores, LLM settings, trusted
  repositories, CI trust rules, and policy. Unknown keys stop the run, a path
  inside the audited repository is refused, and a file writable by others is
  refused under `--strict-operator-config` (on by default in recognized CI).
  Reports record its source and digest.
- `darnit config show` (resolved operator configuration, digest, permission
  check, and redacted settings), `darnit config trust add|list|remove`
  (edits `[trust].repos`), and `darnit config migrate [REPO] [--force]`
  (writes `.baseline.toml` claims to `.project/darnit.yaml` and prints a
  proposed operator configuration fragment; it never writes operator
  configuration).
- CI trust decisions: in CI a repository is trusted only under the opt-in
  `push-default-branch` rule (GitHub Actions, GitLab CI); pull requests,
  merge requests, and unrecognized CI are untrusted. Locally, `--repo
  HOST/NAMESPACE/NAME` (or an MCP tool's `owner`/`repo`) names the audited
  repository; a checkout's own remotes are never trusted. Reports record the
  decision, its reason, and the CI facts used.
- Assertion outcomes for not-applicable claims from `.project/darnit.yaml`
  (with optional `asserted_by`) and from `.project/` context values that make
  a control not applicable: each claimed control reports `honored`,
  `pending`, or `contradicted`. Operators can confirm a pending claim with
  `confirm_project_data` (`confirm_not_applicable`); confirmations are stored
  operator-side and lapse on expiry or when the claim or its evidence
  changes. Framework controls can declare `contradicted_by` evidence.
- `docs/architecture/` directory containing the 25 rehomed architectural reference
  specs (including the authoritative `framework-design.md`), plus a one-screen
  `README.md` index. These are static reference documentation, not in-flight
  feature specs (those live in `specs/`).
- `specs/017-org-wide-audit-pipeline/` containing the previously in-flight
  openspec proposal, migrated to the speckit spec/plan/tasks layout, with the
  two openspec spec-delta files preserved under `specs/017-org-wide-audit-pipeline/deltas/`.
- This `CHANGELOG.md` file.

### Changed

- `.baseline.toml` is deprecated. In this release darnit reads its
  per-control `status`/`reason` as not-applicable claims under the same rules
  as `.project/` claims, still honors `extends` naming a registered framework,
  ignores its tool settings (see Security above), and warns once per setting
  in the file with the setting's new home. A later release will ignore the
  file with a notice. `darnit init` no longer creates `.baseline.toml`; it
  explains `.project/` claims and operator configuration.
- A not-applicable claim makes a control `N/A` (excluded from the level's
  denominator) only when it is honored: the repository is trusted, an
  explicit claim gives a reason, and no declared evidence contradicts it, or
  an operator confirmed it. Pending claims count as non-compliant and
  contradicted claims have no effect. Remediation skips only honored claims.
- Attestation level compliance uses the same rule as audit reports: WARN,
  ERROR, PENDING_LLM, and pending claims are non-compliant. Assertion-backed
  `N/A` results carry `authority: asserted` and `asserted_by`.
- `darnit install --project` warns that a repository-scoped registration lets
  the repository control how darnit is launched; user scope remains the
  default.
- The built-in audit tool's JSON output is now an object (`metadata`,
  `operator_config`, `trust`, `ignored_repository_settings`,
  `unknown_assertions`, `summary`, `results`, and `warnings` when present)
  instead of a bare list of results.
- The authoritative location of the framework-design specification has moved
  from `openspec/specs/framework-design/spec.md` to
  `docs/architecture/framework-design.md`. The project constitution,
  PR template, `.pre-commit-config.yaml`, `scripts/validate_sync.py`, and
  every reference in `ARCHITECTURE.md`, `CLAUDE.md`, the `docs/` tree, and
  `packaging/README.md` are updated accordingly.
- `scripts/validate_sync.py` was trimmed: the two openspec-dependent checks
  ("Spec Exists" and "Docs Freshness") were removed; the three
  openspec-independent checks (TOML Schema, Pass Types Sync against
  `docs/architecture/framework-design.md`, SARIF Source) are retained.
- The project constitution is bumped to v1.2.0 with a Sync Impact Report
  block documenting the Workflow gate changes and the spec relocation.
- The `_PRUNE_DIRS` set in `packages/darnit-baseline/src/darnit_baseline/remediation/scanner.py`
  no longer lists `"openspec"`.

> **For downstream integrators:** Any tooling that referenced `openspec/...`
> paths will need to update. The constitution's "spec sync" Workflow gate
> continues to apply but is now scoped to TOML schema, handler-name registry,
> and SARIF-from-TOML invariants only -- the openspec-specific "Spec Exists"
> and "Docs Freshness" checks have been removed. See the feature documents
> under `specs/016-openspec-migration/` for the full migration record.
