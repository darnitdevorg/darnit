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

## Validation log

Run on 2026-09-26 against scratch repositories under the session scratchpad (`040-quickstart/`), with `HOME`, `XDG_CONFIG_HOME`, and `XDG_DATA_HOME` pointed at a temporary directory so the maintainer's own operator configuration and confirmations were not touched, CI variables unset unless a step sets them, and darnit run from the development checkout's virtualenv. `own/` and `other/` each have a README, `.project/project.yaml`, and a `.project/darnit.yaml` claim `OSPS-BR-06.01: n/a, "Pre-1.0 project with no releases yet"` (a control that declares `contradicted_by = has_releases`). The operator configuration lists `github.com/example/own` and overrides `OSPS-DO-01.01` passes to require `OPERATOR-OVERRIDE.md`.

`has_releases` detection ends with `gh release list --repo OWNER/REPO`; for these non-existent GitHub repositories that call fails, so the evidence is unobtainable and a trusted claim stays `pending` (FR-017, observed on the first run). As the quickstart allows, a `gh` stub on `PATH` that reports no releases was used for the remaining steps.

| Step | Command | Result | Evidence |
|---|---|---|---|
| 1.2 | `darnit config show` | pass | source is `$XDG_CONFIG_HOME/darnit/config.toml`, digest `f5dc54ce...`, permission check `passed`, strict `no` |
| 1.3 CLI | `darnit audit own -f openssf-baseline --include OSPS-DO-01.01,OSPS-BR-06.01 -o json --repo github.com/example/own` | pass | digest `f5dc54ce...`; `OSPS-DO-01.01` FAIL "None of the required files found: ['OPERATOR-OVERRIDE.md']" (override applied) |
| 1.3 MCP | `audit_openssf_baseline(local_path=own, owner, repo, level=2, output_format="json")` | pass | same digest; same `OSPS-DO-01.01` override result |
| 1.3 harness | `HarnessRun(framework_name="openssf-baseline", level=2, target=..., llm_step=MockLLMStep)` | pass | same digest; same override result. Run through the Python API with a mock LLM step because the CLI harness would call the real LLM API |
| 1.4 | CLI audit with `--operator-config home/alt/second.toml` (no override) | pass | reported digest `86005a05...` equals `shasum -a 256` of the second file; `OSPS-DO-01.01` PASS |
| 2.1 | CLI audit of `other/` with `--operator-config other/.darnit/config.toml` | pass | exit 1, "Refusing operator configuration ...: it is inside the audited repository" |
| 2.2 | CLI audit of `other/` without the flag; `other/` has a `.baseline.toml` with `mcp_servers`, `stores`, an exec `passes` override, and an operator-shaped `.darnit/config.toml` | pass | exit 0; marker directory empty (no planted command or server ran); `ignored_repository_settings` lists `.baseline.toml` `mcp_servers`, `stores`, `controls.OSPS-DO-01.01.passes` and `.darnit/config.toml` `schema_version`, `trust`, `controls`, each with new home `operator configuration`; deprecation warnings present |
| 3.1 | CLI audit of `own/` (trusted, gh stub) | pass | `OSPS-BR-06.01` N/A, `authority: asserted`, `assertion.outcome = honored` |
| 3.2 | CLI audit of `other/` (not trusted) | pass | trust `not listed`; `OSPS-BR-06.01` FAIL with `assertion.outcome = pending` |
| 3.3 | Copy of `own/` with a `CHANGELOG.md`, audited as `github.com/example/own` | pass | `outcome = contradicted`; contradiction `evidence_source = context.has_releases detection (detect_pipeline:file_exists)`; control FAIL |
| 3.4 | `confirm_project_data(local_path=other, confirm_not_applicable=["OSPS-BR-06.01"], owner="example", repo="other", host="github.com")`, re-audit, then change the claim's reason and re-audit | pass | confirmation written under the temporary `HOME` (`Library/Application Support/darnit/trust/confirmations.json`), nothing in `other/`; `honored` with `confirmation.confirmed_by/confirmed_at/expires_at`; after the reason change `pending`, `confirmation: null` |
| 3.5 | `other/.project/darnit.yaml` replaced by `context: {has_releases: false}`; `darnit audit other -t domain=BR` | pass | `OSPS-BR-02.01`, `OSPS-BR-04.01`, `OSPS-BR-06.01` report `origin = context_value:has_releases`, location `.project/darnit.yaml:context.has_releases`, `outcome = pending` |
| 4.1 | `GITHUB_ACTIONS=true GITHUB_EVENT_NAME=push GITHUB_REF=refs/heads/main GITHUB_REF_TYPE=branch GITHUB_REPOSITORY=example/own GITHUB_SHA=<HEAD> GITHUB_EVENT_PATH=push.json`; operator config with `ci = [{event = "push-default-branch"}]` | pass | `trusted = true`, reason `ci: push to default branch`, `ci_facts` recorded |
| 4.2 | Same with `GITHUB_EVENT_NAME=pull_request` and a payload whose head repo id differs from the base | pass | `trusted = false`, reason `ci: fork pull request`, `fork: true` |
| 4.3 | `CI=true` only | pass | `trusted = false`, reason `ci: unknown event` |
| 5.1 | Copy of `own/` without `.project/darnit.yaml` and with a representative `.baseline.toml` (`extends`, `mcp_servers`, `stores`, a claim, a passes override, a custom control); CLI audit | pass | `OSPS-BR-06.01` honored from `.baseline.toml:controls.OSPS-BR-06.01`; one warning per setting (7), each naming its new home: `.project/darnit.yaml` for the status and reason, operator configuration for the rest, `--framework` for `extends` |
| 5.2 | `darnit config migrate legacy` | pass | exit 0 in 0.14 s wall time; claim written to `legacy/.project/darnit.yaml`; proposed fragment printed (`[mcp_servers.scanner]`, `[stores.report]`, `[controls."OSPS-DO-01.01"]`, `[custom_controls.CUSTOM-01]`), `extends` listed as not migrated; operator configuration SHA-256 unchanged; `.baseline.toml` left in place |
| 5.3 | Re-audit with both files, then after deleting `.baseline.toml` | pass | both runs: `OSPS-BR-06.01` N/A honored from `.project/darnit.yaml`; with `.baseline.toml` still present the warnings remain, after deletion `warnings` is absent |

SC-005: the migration itself took 0.14 s; reading the warnings, running `darnit config migrate`, reviewing its output, and re-auditing took well under the five-minute target. No audit result changed meaning without a warning: before migration the claim was honored with a warning per setting, and after migration the same outcome came from `.project/darnit.yaml`.

Observations: `load_user_config` logs its pre-existing "Ignoring settings" warning three times per CLI audit (it is called from several places); the per-setting deprecation warnings are emitted once per audit.
