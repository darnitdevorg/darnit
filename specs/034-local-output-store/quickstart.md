# Quickstart: Writing artifacts outside the audited repo (034)

**Feature**: 034-local-output-store
**Audience**: operators configuring darnit for outside-repo storage

Three end-to-end examples, in order of adoption difficulty. Each is a two-block `.baseline.toml` snippet with no further code changes.

---

## 1. OSPO leader consolidates attestations across many repos

**Goal**: every audit's attestation lands in `~/darnit-attestations/`, backed up together, discoverable to your SBOM pipeline. Not touching the audited repos.

**Config to add to each repo's `.baseline.toml`**:

```toml
[stores.attestation]
backend = "local-fs"
root    = "$DARNIT_ATT_ROOT"   # or a literal path like "~/darnit-attestations"
```

**Multi-repo templating**: darnit does NOT ship an org-level config layer (see spec Q1). The operator handles "one config for 30 repos" via one of:

1. **Env-var interpolation (easiest)**: keep `root = "$DARNIT_ATT_ROOT"` in every repo's `.baseline.toml`. Set `DARNIT_ATT_ROOT=~/darnit-attestations` once per machine (shell profile, systemd unit, CI runner config). All 30 repos share that root without duplicating literals.
2. **CI/CD templating**: your CI workflow rewrites `.baseline.toml` before invoking `darnit audit` (envsubst, sed, Jinja).
3. **Cookiecutter / repo-init tool**: one-shot copy of the `[stores.attestation]` block into each repo the first time you onboard it.

**Verify**:

```bash
cd my-repo
darnit audit .
# audit runs; attestation lands at $DARNIT_ATT_ROOT/<repo>-baseline-attestation.intoto.json
ls -1 $DARNIT_ATT_ROOT/
# should list the newly-written bundle
grep "wrote attestation (local-fs)" audit-log
# should show the resolved absolute path
```

**Log line** (FR-015):

```
INFO darnit.stores.local: wrote attestation (local-fs): /home/mike/darnit-attestations/acme-widget-baseline-attestation.intoto.json
```

**What did NOT change**: `<repo>/.darnit/attestations/` is not created (SC-002). Reports and audit-cache still live in-repo (SC-007). `.project/project.yaml` still lives in-repo (FR-009).

---

## 2. CI runner: cache in a persistent volume, reports as job artifacts

**Goal**: on a CI runner where the repo is a fresh checkout per job, keep the audit cache in a persistent volume the CI system already caches between jobs, and drop reports into a per-job artifacts directory the CI system already uploads.

**Config**:

```toml
[stores.cache]
backend = "local-fs"
root    = "$RUNNER_CACHE_DIR/darnit"

[stores.report]
backend = "local-fs"
root    = "$RUNNER_ARTIFACTS_DIR/darnit-reports"
```

**Behavior**:

- First-run: cache write goes to `$RUNNER_CACHE_DIR/darnit/`. Next-run: cache read hits because the runner restored the cache; audit skips the sieve loop, cost drops to seconds.
- Reports land where the CI runner's artifact-upload step is already configured to look. Markdown/JSON/SARIF each become their own file under that root; one log line per format.
- Attestations still land in-repo (unless a third block redirects them).

**Verify**:

```bash
# Run twice back-to-back, second should hit cache:
darnit audit .   # miss, populates $RUNNER_CACHE_DIR/darnit/<hash>.json
darnit audit .   # hit, log shows cache read
ls $RUNNER_ARTIFACTS_DIR/darnit-reports/
# should list <report_id>.md, .json, .sarif
```

**Log lines**:

```
INFO darnit.stores.local: wrote report:markdown (local-fs): /ci/artifacts/darnit-reports/audit-2026-09-01.md
INFO darnit.stores.local: wrote report:json (local-fs): /ci/artifacts/darnit-reports/audit-2026-09-01.json
INFO darnit.stores.local: wrote report:sarif (local-fs): /ci/artifacts/darnit-reports/audit-2026-09-01.sarif
```

---

## 3. Individual developer: XDG defaults on Linux, Apple conventions on macOS

**Goal**: no path-typing at all. Let darnit put artifacts where your OS says user-scoped app data goes.

**Config**:

```toml
[stores.attestation]
backend = "user-local"

[stores.report]
backend = "user-local"

[stores.cache]
backend = "user-local"
```

**Resolved paths**:

| Platform | Attestations | Reports | Cache |
|---|---|---|---|
| Linux (XDG defaults) | `~/.local/share/darnit/attestations/` | `~/.local/share/darnit/reports/` | `~/.cache/darnit/audit-cache/` |
| Linux (`XDG_DATA_HOME=/mnt/x`) | `/mnt/x/darnit/attestations/` | `/mnt/x/darnit/reports/` | (uses `XDG_CACHE_HOME` similarly) |
| macOS | `~/Library/Application Support/darnit/attestations/` | `~/Library/Application Support/darnit/reports/` | `~/Library/Caches/darnit/audit-cache/` |
| Windows | `%LOCALAPPDATA%\darnit\Data\attestations\` | `%LOCALAPPDATA%\darnit\Data\reports\` | `%LOCALAPPDATA%\darnit\Cache\audit-cache\` |

**Verify** (macOS):

```bash
darnit audit .
ls ~/Library/Application\ Support/darnit/attestations/
ls ~/Library/Caches/darnit/audit-cache/
```

**Log line**:

```
INFO darnit.stores.local: wrote attestation (user-local): /Users/mike/Library/Application Support/darnit/attestations/my-repo-baseline-attestation.intoto.json
```

**What did NOT change**: `.project/project.yaml` is not redirected -- there is no `user-local` registration for `[stores.project]`. Even if the operator sets `[stores.project] backend = "user-local"` explicitly in TOML, `darnit audit` fails at `resolve_stores()` time with `StoreNotInstalled: user-local not registered under darnit.stores.project` before any control runs. (This is FR-009 in enforced form.)

---

## Troubleshooting

**`KeyError: DARNIT_ATT_ROOT`** at audit start: the env var referenced in `root` isn't set. `local-fs` uses `missing="raise"` mode on env-var interpolation (research R-003), so a typo or an unset variable is a hard error. Fix by exporting the variable OR by writing a literal path.

**`StoreOperationError: attestation write failed`**: the resolved `root` is unwritable, the disk is full, or the file already exists and is locked. The error names the backend, kind, and path (SC-008). darnit does NOT silently fall back to the in-repo default (feature 033 FR-012).

**Cache misses on second run**: check that the same `$RUNNER_CACHE_DIR` was restored between runs and that the git HEAD commit hash matches. Cache TTL is 3600s by default; refresh the cache if the audit is older.

**File landed with weird `_`s in the name**: your `bundle_id` / `report_id` / `cache_key` contained filesystem-unsafe characters (`/`, `..`, shell metacharacters, spaces). The store sanitized them to prevent path traversal (SC-005). This is expected. Rename the caller's identifier if you want cleaner filenames.

**`user-local` chose the wrong platform**: if you're running on a container image whose `platform.system()` returns something unexpected, `user-local` falls back to XDG defaults. Force a specific path by switching to `local-fs` with an explicit `root`.
