# Quickstart: Validating Operator Configuration and Trust

Prerequisites: a development checkout (`uv sync`), and two scratch repositories under a temporary directory: `own/` (a repository you will list as trusted) and `other/` (not listed). Both contain a README and `.project/darnit.yaml` with a not-applicable claim for a release-dependent control and a reason.

Contracts referenced: [operator-config.md](contracts/operator-config.md), [drivers-and-cli.md](contracts/drivers-and-cli.md), [asserted-results.md](contracts/asserted-results.md). Entities: [data-model.md](data-model.md).

## 1. Operator configuration is found the same way by every driver

1. Create a user-level operator configuration with `schema_version = 1`, `[trust].repos = ["github.com/<you>/own"]`, and one operator pass override.
2. Run `darnit config show`. Expected: source is the per-user path, a digest is printed, permission check passes.
3. Audit `own/` via the CLI, via the MCP tool function, and via the harness. Expected: each report shows the same `operator_config.digest` and the pass override is applied in all three.
4. Re-run the CLI with `--operator-config` pointing at a second file. Expected: the second file's digest is reported.

## 2. Repository content cannot configure the tool

1. In `other/`, add files that attempt tool configuration (a `.baseline.toml` with passes, servers, stores; an operator-config-shaped file) and point `--operator-config` at a path inside `other/`.
2. Audit `other/`. Expected: the run refuses the in-repository operator configuration with a clear message; with the flag removed, the audit runs, none of the repository's tool settings take effect, and `ignored_repository_settings` lists each one with its new home.

## 3. Not-applicable claims follow the trust and evidence rules

1. Audit `own/` (trusted, no releases). Expected: the claimed control is `N/A`, `assertion.outcome = honored`, labelled asserted.
2. Audit `other/` (not trusted). Expected: `assertion.outcome = pending`; the control counts as non-compliant.
3. Create a release in `own/` (or stub the release evidence) and re-audit. Expected: `assertion.outcome = contradicted`, contradiction evidence reported, control evaluated normally.
4. Confirm the pending claim in `other/` through the confirmation tool; re-audit. Expected: `honored` with `confirmation` populated. Change the claim's reason text; re-audit. Expected: back to `pending`.
5. Put a context value in `other/.project/` that would make release-dependent controls not applicable. Expected: each affected control reports `assertion.origin = context_value:<key>` and `pending`.

## 4. CI trust follows the event

1. Simulate a GitHub `push` to the default branch of `own/` (event payload and environment variables per research R4). Expected: `trust.trusted = true`, reason names the CI rule.
2. Simulate a pull request from a fork. Expected: `trust.trusted = false`, reason `ci: fork pull request`.
3. Simulate an unrecognized CI environment. Expected: untrusted, reason `ci: unknown event`.

## 5. Migration

1. In a copy of a repository with a representative `.baseline.toml`, run an audit. Expected: a deprecation warning listing each setting and its new home.
2. Run `darnit config migrate`. Expected: claims written to `.project/darnit.yaml`; a proposed operator-configuration fragment printed; operator configuration unchanged.
3. Re-audit. Expected: same N/A outcomes as before migration for trusted repositories; no deprecation warning once `.baseline.toml` is removed.

## Checks

```
uv run pytest tests/ --ignore=tests/integration/ -q
uv run ruff check .
uv run python scripts/validate_sync.py --verbose
```
