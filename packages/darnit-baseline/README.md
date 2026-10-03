# darnit-baseline

OpenSSF Baseline (OSPS v2025.10.10) compliance implementation for the [darnit](../darnit) framework — **62 controls** across **8 domains** and **3 maturity levels** (25 L1, 17 L2, 20 L3).

## How Controls Are Verified

Each control runs through a **sieve pipeline** — a sequence of passes that stops at the first conclusive result:

```
file_exists  →  exec / pattern  →  manual
     ↓              ↓                 ↓
File presence   Commands (gh api)   Human review
checks          & regex patterns    (fallback)
```

**Pass types:**

- **file_exists** — checks for specific files (README.md, SECURITY.md, LICENSE, etc.)
- **exec** — runs a command (typically `gh api`) and evaluates output with a CEL expression
- **pattern** — searches file contents with regex, optionally evaluates with CEL
- **manual** — fallback steps for human verification

**Conservative by default:** A control that hasn't been explicitly verified as passing reports WARN (needs verification). The system never assumes compliance.

## Control Reference

Controls gated by `platform = "github"` require the GitHub CLI (`gh`). Additional conditions are noted inline.

### OSPS-AC — Access Control (6 controls)

| Control | Lvl | What It Checks | How | Auto-Remediation |
|---------|-----|----------------|-----|------------------|
| AC-01.01 | 1 | MFA required for org members | `exec` gh api | Manual (no API; steps state who loses access) |
| AC-02.01 | 1 | Repository allows forking | `exec` gh api | None (removed: enabling forking is not what the control requires, #513) |
| AC-03.01 | 1 | PRs required for primary branch | `exec` gh api | Platform: require pull requests |
| AC-03.02 | 1 | Primary branch deletion blocked | `exec` gh api | Platform: prevent deletion |
| AC-04.01 | 2 | Workflows declare `permissions:` *(GitHub Actions)* | `pattern` workflows | Adds `permissions: {}` to workflows (`safe = false`: approve individually) |
| AC-04.02 | 3 | Permissions scoped to least privilege *(GitHub Actions)* | `pattern` workflows | Manual |

### OSPS-BR — Build & Release (11 controls)

| Control | Lvl | What It Checks | How | Auto-Remediation |
|---------|-----|----------------|-----|------------------|
| BR-01.01 | 1 | Workflows handle untrusted inputs safely *(GitHub Actions)* | `exec` zizmor / `pattern` | `exec` zizmor --fix |
| BR-01.02 | 1 | Branch names handled safely in workflows *(GitHub Actions)* | `pattern` workflows | Manual |
| BR-02.01 | 2 | Unique version IDs per release *(if has_releases)* | `exec` gh release list | Manual |
| BR-02.02 | 3 | Assets clearly linked to release IDs | `exec` gh release list | Manual |
| BR-03.01 | 1 | Repository URL uses HTTPS | `exec` gh api | — |
| BR-03.02 | 1 | Distribution channels use HTTPS | `pattern` README, INSTALL.md | — |
| BR-04.01 | 2 | Releases include change log *(if has_releases)* | `exec` gh api / `file` CHANGELOG | Manual |
| BR-05.01 | 2 | Uses standard dependency tooling | `file` package.json, pyproject.toml, etc. | Manual |
| BR-06.01 | 2 | Releases are cryptographically signed *(if has_releases)* | `pattern` workflows, docs | Creates release-signing.yml |
| BR-07.01 | 1 | Secret files are gitignored | `file` + `pattern` .gitignore | Creates .gitignore |
| BR-07.02 | 3 | Secrets management policy documented | `pattern` SECURITY.md, docs | Manual |

### OSPS-DO — Documentation (7 controls)

| Control | Lvl | What It Checks | How | Auto-Remediation |
|---------|-----|----------------|-----|------------------|
| DO-01.01 | 1 | Repository has a README | `file` README.md | Creates README.md |
| DO-02.01 | 1 | Bug reporting process documented | `file` issue template / `pattern` | Creates bug_report.md template |
| DO-03.01 | 3 | Support documentation available | `file` SUPPORT.md | Creates SUPPORT.md |
| DO-03.02 | 3 | Release author verification instructions | `pattern` docs | Creates RELEASE-VERIFICATION.md |
| DO-04.01 | 3 | Support scope and duration documented | `pattern` SUPPORT.md, docs | Creates SUPPORT.md |
| DO-05.01 | 3 | End-of-support policy documented | `pattern` SUPPORT.md, docs | Creates SUPPORT.md |
| DO-06.01 | 2 | Dependency management documented | `pattern` README, docs | Creates docs/DEPENDENCIES.md |

### OSPS-GV — Governance (6 controls)

| Control | Lvl | What It Checks | How | Auto-Remediation |
|---------|-----|----------------|-----|------------------|
| GV-01.01 | 2 | Governance documentation exists | `file` GOVERNANCE.md, MAINTAINERS.md, etc. | Creates GOVERNANCE.md *(needs: maintainers)* |
| GV-01.02 | 2 | Roles and responsibilities documented | `pattern` governance docs | Creates MAINTAINERS.md *(needs: maintainers)* |
| GV-02.01 | 1 | Issues or Discussions enabled | `exec` gh api | — |
| GV-03.01 | 1 | Contributing guidelines exist | `file` CONTRIBUTING.md | Creates CONTRIBUTING.md |
| GV-03.02 | 2 | Contribution requirements documented | `pattern` CONTRIBUTING.md | Creates CONTRIBUTING.md |
| GV-04.01 | 3 | Collaborator review policy documented | `file` CODEOWNERS / `pattern` | Creates CODEOWNERS *(needs: maintainers)* |

### OSPS-LE — Legal (5 controls)

| Control | Lvl | What It Checks | How | Auto-Remediation |
|---------|-----|----------------|-----|------------------|
| LE-01.01 | 1 | Repository has a license file | `file` LICENSE | Manual (contributor sign-off: DCO or CLA, #508) |
| LE-02.01 | 1 | License is OSI-approved | `exec` gh api | Creates LICENSE for the confirmed `license_type` |
| LE-02.02 | 1 | Releases include license info | `exec` gh release view | — |
| LE-03.01 | 1 | License file present in repository root | `file` LICENSE | Creates LICENSE for the confirmed `license_type` |
| LE-03.02 | 1 | License included in release archives *(if has_releases)* | `exec` gh release view | — |

### OSPS-QA — Quality Assurance (13 controls)

| Control | Lvl | What It Checks | How | Auto-Remediation |
|---------|-----|----------------|-----|------------------|
| QA-01.01 | 1 | Repository is publicly accessible | `exec` gh api | Platform: make repo public (high-impact; approve individually) |
| QA-01.02 | 1 | Commit history is publicly visible | `exec` gh api | Manual |
| QA-02.01 | 1 | Dependency manifest exists | `file` package.json, pyproject.toml, etc. | Manual |
| QA-02.02 | 3 | SBOM delivered with compiled assets *(if has_compiled_assets)* | `pattern` workflows | Creates sbom.yml |
| QA-03.01 | 2 | Status checks required before merge | `exec` gh api | Manual |
| QA-04.01 | 1 | Subprojects are documented *(if has_subprojects)* | `pattern` README, docs | Manual |
| QA-04.02 | 3 | Subprojects enforce equal security *(if has_subprojects)* | `pattern` security files | Manual |
| QA-05.01 | 1 | No generated executables in repo | `pattern` absence check | Manual |
| QA-05.02 | 1 | No unreviewable binary artifacts | `pattern` absence check | Manual |
| QA-06.01 | 2 | CI includes automated tests | `pattern` workflows | Creates ci.yml (ecosystem-aware: Python/Node/Rust/Go) |
| QA-06.02 | 3 | Testing instructions documented | `pattern` README, docs | Creates docs/TESTING.md (ecosystem-aware: Python/Node/Rust/Go) |
| QA-06.03 | 3 | Test requirements for contributions | `pattern` CONTRIBUTING.md | Manual |
| QA-07.01 | 3 | PRs require approval before merge | `exec` gh api | Platform: require at least 1 approval |

### OSPS-SA — Security Assessment (4 controls)

| Control | Lvl | What It Checks | How | Auto-Remediation |
|---------|-----|----------------|-----|------------------|
| SA-01.01 | 2 | Design docs show actions and actors | `pattern` architecture docs | Creates ARCHITECTURE.md |
| SA-02.01 | 2 | API/interface documentation available | `pattern` API docs, README | — |
| SA-03.01 | 2 | Security assessment before releases *(if has_releases)* | `manual` / `pattern` | Creates SECURITY-ASSESSMENT.md |
| SA-03.02 | 3 | Threat model documentation available | `file` THREAT_MODEL.md / `pattern` | Creates THREAT_MODEL.md (`llm_enhance`) |

### OSPS-VM — Vulnerability Management (10 controls)

| Control | Lvl | What It Checks | How | Auto-Remediation |
|---------|-----|----------------|-----|------------------|
| VM-01.01 | 2 | Security policy includes disclosure process | `pattern` SECURITY.md | Manual |
| VM-02.01 | 1 | Repository has a security policy | `file` SECURITY.md | Creates SECURITY.md |
| VM-03.01 | 2 | Private vulnerability reporting enabled | `exec` gh api / `pattern` | Platform: enable private reporting |
| VM-04.01 | 2 | Repository supports security advisories | `exec` gh api | Manual |
| VM-04.02 | 3 | VEX policy documented | `pattern` SECURITY.md, docs | Creates docs/VEX-POLICY.md |
| VM-05.01 | 3 | SCA remediation policy documented | `pattern` docs | Creates docs/SCA-POLICY.md |
| VM-05.02 | 3 | Pre-release SCA workflow configured | `pattern` workflows | Creates sca.yml |
| VM-05.03 | 3 | Automated dependency scanning configured | `file` dependabot.yml, renovate.json | Creates dependabot.yml (ecosystem-aware: Python/Node/Rust/Go) |
| VM-06.01 | 3 | SAST remediation policy documented | `pattern` docs | Creates docs/SAST-POLICY.md |
| VM-06.02 | 3 | Automated SAST in CI pipeline | `pattern` workflows | Creates sast.yml |

## Project Context

Context values serve two purposes: **(1)** they gate which controls apply to your project via `when` clauses, and **(2)** they populate templates during remediation. Only confirmed values (and, for Auto-Detect keys, values detected in the current run) are used. A control gated by context that has no usable value stays applicable, and a remediation template that needs such a value stops with `confirmation required: <key>`.

Confirm context with the `confirm_project_data` MCP tool, which records who confirmed it and when (in `.project/darnit.yaml` for a repository you trust, otherwise operator-side). A detected value for a key without Auto-Detect is only proposed as a candidate for you to accept or correct. A value in `.project/` without a confirmation record, including one edited by hand or written by an earlier darnit version, is a candidate until you confirm it; `get_pending_data` lists these under `stored_unconfirmed`, and `confirm_project_data(confirm_stored=[...], reject_stored=[...])` reviews them in one call.

| Key | Type | Auto-Detect | Controls | Usage |
|-----|------|-------------|----------|-------|
| `maintainers` | list or path | No (candidate proposed) | GV-01.01, GV-01.02, GV-04.01 | Template variable in GOVERNANCE.md, MAINTAINERS.md, CODEOWNERS. Remediation blocks until confirmed. |
| `security_contact` | string | No (candidate proposed) | VM-01.01, VM-02.01, VM-03.01 | Populates SECURITY.md template. Remediation blocks until confirmed. |
| `governance_model` | enum | No | GV-01.01, GV-01.02 | Selects governance template variant |
| `has_subprojects` | boolean | No | QA-04.01, QA-04.02 | When-clause: controls only run if `true` |
| `has_releases` | boolean | Yes | BR-02.01, BR-04.01, BR-06.01, LE-03.02, SA-03.01 | When-clause: controls only run if `true` |
| `is_library` | boolean | No | DO-04.01, BR-01.01 | Audit hints for accuracy |
| `has_compiled_assets` | boolean | No | QA-02.02 | When-clause: control only runs if `true` |
| `ci_provider` | enum | Yes | BR-01.01, BR-01.02, AC-04.01, AC-04.02 | When-clause: controls only run if `"github"` |
| `license_type` | enum (`mit`, `apache-2.0`, `bsd-3-clause`, `other`) | No | LE-02.01, LE-03.01 | Selects the LICENSE template when no license file exists; `other` gives manual steps. darnit never picks a license |

**Auto-detected without prompting:** `detected_ecosystem` (from manifest files: pyproject.toml → python, package.json → node, Cargo.toml → rust, go.mod → go) is detected automatically by `collect_auto_context()` and injected into both audit and remediation paths. It never appears in `get_pending_context` questions.

## Remediation Capabilities

Remediation previews by default and applies only what it previewed (`docs/architecture/framework-design.md` sections 4 and 15):

- **Preview, then approve.** `remediate_audit_findings` (and `darnit run`) preview unless asked to apply. The preview lists each file to be created or changed, each platform setting before and after, each command, and a digest per plan item and platform change set. An apply carries `approve` with the digests the person approved; `dry_run=False` alone approves nothing.
- **Platform changes never weaken settings.** The platform engine reads the current settings first, changes only what the control requires, writes nothing when the settings (or an active ruleset) already satisfy it, uses the repository's default branch, and reads the result back. The operator configuration's `[remediation]` policy (`prompt` by default, `manual`, or `auto`) decides whether darnit asks first; a high-impact change (making the repository public) is never covered by a batch approval.
- **Files.** `overwrite = false` everywhere: an existing file is never replaced, and a file with your uncommitted changes is not written. `safe = false` remediations and steps that cannot be previewed exactly need their own approval.
- **Commits.** The git tools commit only the files the run wrote (tracked in an operator-side run manifest), never stash, and stop on a detached HEAD, a merge or rebase in progress, or a branch with commits darnit did not make.
- **Outcomes.** Each control reports `fixed` only when something changed and a re-check passes; otherwise `changed_not_passing`, `changed_not_verified`, `unchanged` (with the reason), `needs_approval`, `needs_confirmation`, `manual`, or `error`.

The implementation declares: file creations for 31 controls (27 unique files), 5 platform settings, 2 exec fixes (zizmor), a `yaml_inject` fix (AC-04.01), and the threat model generator (SA-03.02). Three governance controls (GV-01.01, GV-01.02, GV-04.01) block until project maintainers are confirmed via `confirm_project_data`, and LE-02.01 and LE-03.01 until a `license_type` is confirmed. 19 controls provide manual guidance only, and 6 are verification-only with no remediation.

### File Creation (31 actions across 28 unique files)

Each action generates a file from a built-in template. Template quality ratings:

- **Production-ready** — substantive content, follows best practices, minimal customization needed
- **Good scaffold** — correct structure, needs project-specific content added
- **Starter** — minimal placeholder, must be customized before use

Five templates have `llm_enhance` prompts (marked with \*) that request LLM-based customization of the generated content.

#### Root Project Files

| Control | File | Quality | Notes |
|---------|------|:-------:|-------|
| DO-01.01 | `README.md` | Scaffold\* | Generic clone/install, usage section is placeholder. `llm_enhance`, `project_update` |
| VM-02.01 | `SECURITY.md` | Production\* | Disclosure process, timelines (48h/7d/90d), VEX section. `llm_enhance` |
| GV-03.01 | `CONTRIBUTING.md` | Scaffold | Fork workflow, PR guidelines; dev setup is placeholder |
| GV-03.02 | `CONTRIBUTING.md` | Scaffold | Same template as GV-03.01 (no-op if already created) |
| GV-01.01 | `GOVERNANCE.md` | Scaffold\* | Roles, decision making. `llm_enhance`. **Needs: maintainers** |
| GV-01.02 | `MAINTAINERS.md` | Scaffold | Responsibilities, criteria. **Needs: maintainers** |
| GV-04.01 | `CODEOWNERS` | Scaffold | Single global ownership rule. **Needs: maintainers** |
| LE-02.01, LE-03.01 | `LICENSE` | Production | MIT, Apache-2.0, or BSD-3-Clause for the confirmed `license_type`; no default license. Never replaces an existing license file |
| BR-07.01 | `.gitignore` | Production | Covers .env, \*.pem, \*.key, cloud creds (AWS/GCP/Azure) |
| DO-03.01 | `SUPPORT.md` | Production | Getting help, scope table, EOL policy with 30-day notice |
| DO-04.01 | `SUPPORT.md` | Production | Support scope variant (no-op if DO-03.01 ran first) |
| DO-05.01 | `SUPPORT.md` | Production | End-of-support variant (no-op if DO-03.01 ran first) |
| SA-01.01 | `ARCHITECTURE.md` | Scaffold\* | Components/actors/data flow — all example data. `llm_enhance` |
| SA-02.01 | `API.md` | Scaffold\* | Interface tables, usage examples — all placeholder. `llm_enhance` |
| SA-03.02 | `THREAT_MODEL.md` | Production\* | Full STRIDE on Python web services and Go cobra-based CLIs; thin on non-cobra Go CLIs and other library projects. See [coverage scope](../../README.md#threat-model-coverage-scope). `llm_enhance`, `project_update` |

#### CI Workflows (`.github/workflows/`)

| Control | File | Quality | Notes |
|---------|------|:-------:|-------|
| QA-06.01 | `ci.yml` | Production | Ecosystem-aware: Python (pytest), Node (npm test), Rust (cargo test), Go (go test). Auto-detected via `detected_ecosystem` context |
| VM-05.02 | `sca.yml` | Production | Pinned `dependency-review-action`, `fail-on-severity: high` |
| VM-06.02 | `sast.yml` | Production | Pinned CodeQL init/autobuild/analyze, weekly schedule |
| QA-02.02 | `sbom.yml` | Production | Pinned syft SPDX generation + release asset upload |
| BR-06.01 | `release-signing.yml` | Scaffold | Pinned `attest-build-provenance`; `subject-path: '.'` needs customization |

#### GitHub Config

| Control | File | Quality | Notes |
|---------|------|:-------:|-------|
| VM-05.03 | `.github/dependabot.yml` | Production | Ecosystem-aware: includes github-actions + detected ecosystem (pip/npm/cargo/gomod). Auto-detected via `detected_ecosystem` context |
| DO-02.01 | `.github/ISSUE_TEMPLATE/bug_report.md` | Production | Standard template: reproduce, expected, actual, environment |

#### Policy Documentation (`docs/`)

| Control | File | Quality | Notes |
|---------|------|:-------:|-------|
| DO-06.01 | `docs/DEPENDENCIES.md` | Production | 3-tier update cadence, 4-severity vulnerability response |
| SA-03.01 | `docs/SECURITY-ASSESSMENT.md` | Scaffold | 5-item audit checklist, 4-step review process |
| DO-03.02 | `docs/RELEASE-VERIFICATION.md` | Scaffold | Git tag, GitHub badge, Sigstore/cosign verification |
| BR-07.02 | `docs/SECRETS-POLICY.md` | Production | Rotation (90d), revocation, CI/CD secrets, annual review |
| VM-04.02 | `docs/VEX-POLICY.md` | Scaffold | VEX purpose, publication methods, OpenVEX/CISA links |
| VM-05.01 | `docs/SCA-POLICY.md` | Production | Scanning frequency, 4-severity thresholds, exception process |
| VM-06.01 | `docs/SAST-POLICY.md` | Production | 3 scanning triggers, severity handling, exception process |
| QA-06.02 | `docs/TESTING.md` | Production | Ecosystem-aware: Python (pytest/coverage), Node (npm test/jest), Rust (cargo test), Go (go test/race). Auto-detected via `detected_ecosystem` context |
| QA-06.03 | `docs/TEST-REQUIREMENTS.md` | Scaffold | Contribution test requirements; `make test` placeholder |

### Platform Settings (5 requirements)

Each is a `platform_setting` requirement handled by the platform engine, not a payload. Requirements on the same branch in one run are combined into one change set.

| Control | Target | Requirement | Impact |
|---------|--------|-------------|--------|
| AC-03.01 | `branch_protection` | `require_pull_request` | platform |
| AC-03.02 | `branch_protection` | `prevent_deletion` | platform |
| QA-07.01 | `branch_protection` | `require_approvals = 1` (a minimum; never lowers a higher count) | platform |
| QA-01.01 | `repository` | `visibility = "public"` | high-impact: all code, history, and Actions logs become public |
| VM-03.01 | `vulnerability_reporting` | `enabled = true` | platform |

OSPS-AC-01.01 (organization two-factor enforcement) has no API and is manual under every policy.

### Exec (2 actions)

| Control | Command | Notes |
|---------|---------|-------|
| BR-01.01 | `zizmor --fix=all --offline` | Requires external `zizmor` tool. Applies all fixes including unsafe. GitHub Actions only |
| BR-01.02 | `zizmor --fix=all --offline` | Same command, targets branch name injection patterns |

### Manual-Only (19 controls)

These controls provide step-by-step guidance but cannot be auto-remediated.

| Control | Why Manual |
|---------|-----------|
| AC-01.01 | Organization two-factor enforcement has no API; enabling it removes members and bots without 2FA |
| LE-01.01 | Contributor sign-off (DCO or CLA) is a project decision and a process, not a file |
| QA-01.02 | Commit history visibility — verification-only, nothing to change programmatically |
| QA-02.01 | Dependency manifest — project-specific; can't generate a real lockfile |
| QA-04.01 | Subproject documentation — requires human knowledge of project structure |
| QA-05.01 | No generated executables — requires human judgment on what to remove |
| QA-05.02 | No binary artifacts — requires human judgment on what to remove |
| AC-04.02 | Least-privilege permissions — requires per-workflow security analysis |
| BR-01.03 | Isolating untrusted code from privileged credentials in CI - requires per-workflow review |
| BR-01.04 | Sanitizing collaborator input in CI - requires per-workflow review |
| BR-02.01 | Unique version IDs — release versioning process is project-specific |
| BR-04.01 | Changelog in releases — changelog content is project-specific |
| BR-05.01 | Standard dependency tooling — tool adoption is a project-level decision |
| BR-02.02 | Assets linked to release IDs — release artifact process is project-specific |
| DO-07.01 | Build instructions - project-specific |
| QA-03.01 | Required status checks — which checks to require depends on CI setup |
| QA-04.02 | Subproject security parity — requires cross-repo security review |
| VM-01.01 | Disclosure process in SECURITY.md — content verification is judgment-based |
| VM-04.01 | Security advisory support — GitHub platform feature, manual enablement |

### No Remediation (6 controls)

Verification-only controls that check conditions which already exist or can't be meaningfully auto-remediated: AC-02.01 (its former remediation enabled forking, #513), BR-03.01 (HTTPS repo URL), BR-03.02 (HTTPS distribution), GV-02.01 (Issues/Discussions enabled), LE-02.02 (License in releases), LE-03.02 (License in release archives).

### Template Quality Summary

| Rating | Count | Description |
|--------|:-----:|-------------|
| Production-ready | 19 | Substantive content following best practices — minimal customization needed |
| Good scaffold | 12 | Correct structure — needs project-specific content added |
| Starter | 0 | Minimal placeholder — must be customized before use |

**6 templates with `llm_enhance` prompts**: README.md, SECURITY.md, GOVERNANCE.md, ARCHITECTURE.md, API.md, THREAT_MODEL.md — these request LLM-based customization using project context.

### Known Limitations

- Templates use `$OWNER`, `$REPO`, `$BRANCH` variables resolved from git remote — may be wrong for forks or non-standard remote names
- `security@$OWNER.github.io` in SECURITY.md is a placeholder email — almost always needs customization
- A LICENSE is created only for a confirmed `license_type`; without one the remediation stops with `confirmation required: license_type`
- CI workflows, dependabot, and testing docs auto-detect ecosystem from manifest files — falls back to generic starter if ecosystem is unrecognized
- `release-signing.yml` uses `subject-path: '.'` which should be customized to actual release artifacts
- `llm_enhance` prompts are captured in templates but the LLM integration path isn't fully wired in the remediation executor
- Three SUPPORT.md controls (DO-03.01, DO-04.01, DO-05.01) each create the same file with different templates — only the first to run takes effect due to `overwrite = false`
- Platform remediations require `gh` CLI authentication that can read and write the settings (`repo`, admin access for branch protection); a token that cannot read them changes nothing
- `zizmor --fix=all` applies all fixes including potentially unsafe ones — review changes before committing
- Manual-only controls have varying depth of guidance (some have 2 steps, some have 6)
- `dependabot.yml` auto-detects project ecosystem — falls back to `github-actions` only if ecosystem is unrecognized
- Ecosystem detection maps primary language to ecosystem (python→python, javascript/typescript→node, go→go, rust→rust, java→java, ruby→ruby); unrecognized languages get no ecosystem
- **Monorepo limitation:** Language and ecosystem auto-detection only checks manifest files at the repository root (e.g., `pyproject.toml`, `go.mod`, `package.json`). Nested service directories are not scanned. In a monorepo with multiple languages, only the root-level manifest is detected — check order favors Go and Rust over Python and JavaScript. Use `confirm_project_data(detected_ecosystem="...")` to override if the wrong ecosystem is selected

## External Tool Dependencies

Some controls use external tools for deeper analysis. These are **optional** — controls gracefully fall back to built-in pattern matching when a tool is unavailable.

| Tool | Controls | Purpose | Install |
|------|----------|---------|---------|
| [zizmor](https://docs.zizmor.sh/) | BR-01.01 | GitHub Actions static analysis (template injection) | `cargo install zizmor` or `brew install zizmor` |
| [gh](https://cli.github.com/) | AC-*, BR-02/03/04, LE-02/03, QA-01/03/07, GV-02, VM-03/04 | GitHub API queries | `brew install gh` |
| [jq](https://jqlang.github.io/jq/) | — | JSON processing (used internally by some exec passes) | `brew install jq` |

## Org-Wide Audits

Audit every repository in a GitHub organization (or user account) one at a time. The workflow uses two MCP tools: one to discover repos, and another to audit each individually.

**Prerequisites:** `gh` CLI installed and authenticated (`gh auth login`).

### Step 1: List repos — `list_org_repos`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `owner` | string | *(required)* | GitHub org or user name |
| `include_archived` | bool | `false` | Include archived repositories |

Returns a JSON object:
```json
{"owner": "my-org", "repos": ["repo-a", "repo-b", "repo-c"], "count": 3}
```

### Step 2: Audit each repo — `audit_org`

| Parameter | Type | Default | Description |
|-----------|------|---------|-------------|
| `owner` | string | *(required)* | GitHub org or user name |
| `repo` | string | *(required)* | Repository name to audit |
| `level` | int | `3` | Maximum OSPS maturity level (1, 2, or 3) |
| `tags` | string or list | `null` | Filter controls by tags (e.g., `"domain=AC"`) |
| `output_format` | string | `"markdown"` | `"markdown"` or `"json"` |

Clones the repo to a temp directory, runs the full audit pipeline, returns the report, and cleans up.

### Example Workflow

```python
# 1. Discover repos
list_org_repos(owner="my-org")
# → {"repos": ["frontend", "backend", "infra"], "count": 3}

# 2. Audit each repo individually
audit_org(owner="my-org", repo="frontend", level=1)
audit_org(owner="my-org", repo="backend", level=1)
audit_org(owner="my-org", repo="infra", level=1)

# JSON output for a single repo
audit_org(owner="my-org", repo="frontend", output_format="json")
```

### Write-Back Routing

When remediating org-wide audit findings, each action is classified as targeting either:

- **`[org]`** — Shared metadata in the org's `.project` repo (e.g., `security.contact`, `maintainers`, `governance`). Only classified as org-level when the field exists in the org config.
- **`[repo]`** — Repo-specific artifacts (e.g., `SECURITY.md`, `CODEOWNERS`, CI config). Always repo-level regardless of org config.

This classification appears in the audit report's "Write-back Routing" section to help you decide where to apply fixes.

### How It Works

1. **Enumerate** (`list_org_repos`) — `gh repo list {owner}` fetches all repos (filters archived by default)
2. **Clone** (`audit_org`) — The repo is shallow-cloned (`--depth 1`) to a temp directory
3. **Audit** — Standard `run_sieve_audit()` pipeline runs against the clone, including `.project/` context resolution (org-level `.project` repo metadata is merged automatically)
4. **Return** — Single-repo report is returned (fits within MCP response limits)
5. **Cleanup** — Temp directory is removed even on errors

Failures are non-fatal: if a repo fails to clone or audit, the error is returned in the response.

## Package Structure

```
darnit_baseline/
├── attestation/     # In-toto attestation support
├── config/          # Project context configuration
├── formatters/      # Output formatting (Markdown, JSON, SARIF)
├── remediation/     # Remediation orchestration
├── rules/           # SARIF rule definitions (from TOML)
└── threat_model/    # Threat model generation
```

## Installation

```bash
pip install darnit-baseline
```

This automatically installs `darnit` as a dependency.

## License

Apache-2.0
