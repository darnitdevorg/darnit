# Release Recovery Procedures

Per-channel repair procedures for partial-failure recovery. The release workflow does **not** support re-running on an already-published tag (preflight rejects it per FR-002). Recovery is always channel-by-channel.

> If a `release-failure` issue references this file, find the channel section below and follow the procedure.

## How recovery works

1. The failed channel is named in the `release-failure` GitHub issue (created by the `finalize` job).
2. Each channel's section below documents:
   - **Failure modes** typical for that channel.
   - **Repair steps** that can be run by a maintainer without re-tagging.
   - **Verification** to confirm the channel is healthy after repair.
3. After repair, post a comment on the `release-failure` issue summarising what was done, then close the issue.

If recovery is impossible (e.g., a wheel uploaded under the wrong version), the maintainer must yank the bad artifact at the registry and roll forward to a new patch release. Do **not** attempt to overwrite a published version — every channel listed below treats published artifacts as immutable.

---

## PyPI

The four per-package publish jobs (`publish-darnit`, `publish-darnit-baseline`, `publish-darnit-gittuf`, `publish-darnit-mcp`) are sequenced via `needs:` and `darnit` always publishes first. A failure can leave some packages uploaded and others not.

### Failure mode 1 — One or more packages uploaded; one failed mid-flight

**Symptom**: `release.yml` shows green for some `publish-*` jobs and red for others. PyPI/TestPyPI shows the green ones live.

**Important**: PyPI versions are **immutable**. You cannot re-upload version `X.Y.Z` after one byte of it is on the index, even via the `release.yml` re-run path (which preflight rejects anyway).

**Procedure**:

1. Determine which packages uploaded successfully. The `release.yml` job summary names each failed publish; PyPI's project page is the source of truth (`https://pypi.org/project/<package>/<version>/`).
2. **For the failed packages**:
   - If the failure was transient (network, OIDC token, rate limit) and re-running the publish step succeeds: download the dist artifact from the failed workflow run via `gh run download <run-id> --name dist`. Manually invoke the publish action against the package's `dist/<pkg>/` subdirectory, using the same OIDC environment. PyPI is **not** idempotent — if even one wheel for the version is up, the whole upload is rejected.
   - If the failure was permanent (bad metadata, missing classifier, name collision): **roll forward to a fresh version**. PyPI version numbers cannot be reused; bump to a patch (`X.Y.Z+1`) and re-tag. The already-uploaded packages from the failed run remain on PyPI at the original version but will be unused — yank them via `https://pypi.org/manage/project/<pkg>/release/<version>/`.
3. **For the succeeded packages**: leave them. Yanking is only necessary if the bad release was already advertised.

### Failure mode 2 — Sigstore attestation upload failed

**Symptom**: Wheel uploaded successfully to PyPI but `release.yml` reports a failure in the publish step's attestation sub-step, OR a smoke run reports "no attestation bundles in provenance response".

**Important**: PEP 740 attestations are signed at publish time. You cannot retroactively add a Sigstore attestation to an existing PyPI release.

**Procedure**:

1. Confirm the wheel itself is on PyPI (`pip download <pkg>==<version>` works).
2. Bump to `X.Y.Z+1` and re-tag — the new release will carry a fresh attestation.
3. Yank `X.Y.Z` once `X.Y.Z+1` is up to prevent users from installing the un-attested version.

### Failure mode 3 — TestPyPI failure on a pre-release tag

**Symptom**: `v<X.Y.Z>rc<N>` tag was pushed; `release.yml` failed during the TestPyPI publish step.

**Important**: TestPyPI has more relaxed policies (its index gets nuked periodically) and is less reliable than PyPI. A failure here is **not** a release-blocking event.

**Procedure**:

1. Verify the failure was on TestPyPI (the index URL in the publish action's log will show `test.pypi.org`).
2. Optionally re-tag as `v<X.Y.Z>rc<N+1>`. TestPyPI rcN versions are cheap and don't affect stable users.
3. Do **not** promote the failed `rcN` to a stable tag — fix and bump `rcN+1` first.

### Verification after recovery

After any recovery action, re-run the smoke jobs against the published artifacts:

```bash
# Find the smoke workflow run that corresponds to the recovered release
gh run list --repo kusari-oss/darnit --workflow "Release Smoke Tests" --limit 5
gh run rerun <smoke-run-id> --repo kusari-oss/darnit
```

The smoke job is read-only and safe to re-run any number of times.

---

## Container image

The `container_build_push` job pushes a multi-arch manifest, signs each digest with cosign, and attaches an SPDX-JSON SBOM as a cosign attestation. Partial failure surfaces at any of these steps.

### Failure mode 1 — Multi-arch incomplete (one platform pushed, the other failed)

**Symptom**: `docker manifest inspect ghcr.io/kusari-oss/darnit:v<X.Y.Z>` returns only one platform manifest entry instead of two, OR `docker pull --platform linux/arm64 ...` fails while `linux/amd64` works.

**Important**: GHCR tags are technically mutable. We treat them as immutable by convention to give users a stable signing chain to verify against.

**Procedure**:

1. Investigate the cause via the failed job's log (commonly: qemu emulation timeout, buildx OOM, or registry transient).
2. **Do not re-push under the same tag.** Even though GHCR would accept it, the cosign signature on the original digest would no longer match what users pull, breaking the trust chain.
3. Roll forward to `v<X.Y.Z+1>` and re-tag. The bad partial tag stays for historical resolution; downstream users pinned to it get a warning from cosign verify (the signed digest will not match the new push if anyone overwrote it, which is itself a meaningful signal).
4. Document the incident in the release notes for `v<X.Y.Z+1>`.

### Failure mode 2 — Image pushed; cosign signing failed

**Symptom**: `docker pull` works for both platforms but `cosign verify ...` returns "no matching signatures".

**Important**: Without a signature, FR-003 ("every artifact MUST carry a verifiable signature") is violated. The image must not be advertised as a release.

**Procedure**:

1. **Do not** retry just the cosign step manually unless you can do it with the same OIDC identity as the release workflow — a maintainer's local cosign signing would produce a wrong identity and fail user verification.
2. The cleanest recovery is to roll forward: bump to `v<X.Y.Z+1>` and let `release.yml` re-sign the new push.
3. As a fallback for transient signing failures (rare; usually a Fulcio outage), the workflow can be re-run **only** on a fresh tag — `release.yml`'s preflight rejects reruns on already-published tags.
4. Optionally, manually mark the unsigned digest as superseded: push a deprecation note to the release notes for the broken tag.

### Failure mode 3 — SBOM attestation upload failed

**Symptom**: `cosign verify` succeeds but `cosign verify-attestation --type spdx ...` returns "no matching attestations". `cosign download attestation` returns empty.

**Important**: SBOM absence is less severe than signature absence — the artifact is still trustworthy, just lacks the supply-chain manifest. Users can regenerate the SBOM locally via `syft ghcr.io/kusari-oss/darnit:v<X.Y.Z> -o spdx-json`.

**Procedure**:

1. Confirm the image and its signature are present (`cosign verify` works).
2. Re-run only the SBOM attestation step locally with the appropriate OIDC token:
   ```bash
   # On a machine with cosign and a fresh OIDC token for the release workflow
   syft ghcr.io/kusari-oss/darnit:v<X.Y.Z> -o spdx-json > sbom.spdx.json
   cosign attest --yes --predicate sbom.spdx.json --type spdx ghcr.io/kusari-oss/darnit:v<X.Y.Z>
   ```
3. If a manual attestation cannot be produced with the canonical workflow identity, document the gap in the release notes and roll forward in `v<X.Y.Z+1>`.

### Failure mode 4 — :latest still pointing at the previous release after a stable push

**Symptom**: `docker pull ghcr.io/kusari-oss/darnit:latest` returns the previous version's digest.

**Important**: `:latest` movement is part of the release workflow. If it didn't move, the push itself likely failed silently.

**Procedure**:

1. Confirm `:v<X.Y.Z>` pulls successfully.
2. Manually re-push `:latest` to the new digest **only if** the immutable tag verification passes:
   ```bash
   docker buildx imagetools create \
     -t ghcr.io/kusari-oss/darnit:latest \
     ghcr.io/kusari-oss/darnit:v<X.Y.Z>
   ```
3. Verify the move: `cosign verify ghcr.io/kusari-oss/darnit:latest ...` must produce the same identity as `:v<X.Y.Z>`.

### Verification after recovery

```bash
# Pull both platforms
docker pull --platform linux/amd64 ghcr.io/kusari-oss/darnit:v<X.Y.Z>
docker pull --platform linux/arm64 ghcr.io/kusari-oss/darnit:v<X.Y.Z>

# Verify signing identity
cosign verify ghcr.io/kusari-oss/darnit:v<X.Y.Z> \
  --certificate-identity-regexp '^https://github\.com/kusari-oss/darnit/\.github/workflows/release\.yml@' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com

# Verify SBOM attestation
cosign verify-attestation ghcr.io/kusari-oss/darnit:v<X.Y.Z> \
  --type spdx \
  --certificate-identity-regexp '^https://github\.com/kusari-oss/darnit/\.github/workflows/release\.yml@' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

Then re-run the smoke job: `gh run rerun <smoke-run-id> --repo kusari-oss/darnit`.

---

## Standalone binary

The `binary_matrix` job builds on four native runners in parallel (macOS arm64/amd64, Linux arm64/amd64). The `release_attach_binaries` job collects all four sets, creates the GitHub Release, and attaches them. Per spec, missing a platform fails the release for that platform — there is no partial-binary-set acceptance.

### Failure mode 1 — Build succeeded for some platforms, failed for others

**Symptom**: `release.yml` shows 3 of 4 `binary_matrix` matrix entries green and 1 red. The GitHub Release was not created (or was created without the missing platform).

**Important**: shiv builds are reproducible from the tagged commit + the published `darnit-mcp` wheel on PyPI. We can rebuild a missing platform on a maintainer machine without re-tagging.

**Procedure**:

1. Determine the failed platform. The `binary_matrix` job name encodes it (`Build binary (macos-arm64)`, etc.).
2. Investigate via the failed job's log. Common transient causes: runner image hiccup, network blip to PyPI, shiv install failure.
3. Re-run only the failed matrix entry: in the GitHub Actions UI, click **Re-run jobs** → **Re-run failed jobs**. The job is idempotent on a per-platform basis (writes a fresh workflow artifact).
4. After the re-run succeeds, manually attach the binary, signature, and SBOM to the existing GitHub Release:
   ```bash
   gh release upload v<X.Y.Z> \
     darnit-<X.Y.Z>-<os>-<arch> \
     darnit-<X.Y.Z>-<os>-<arch>.sigstore \
     darnit-<X.Y.Z>-<os>-<arch>.sbom.spdx.json \
     --repo kusari-oss/darnit
   ```
5. Re-run the `binary_smoke` matrix to verify the new asset's signature.

If the failure cannot be recovered (e.g., a runner image change broke the build deterministically), roll forward to `v<X.Y.Z+1>` — but the already-published platforms stay on the GH release, since they're signed correctly.

### Failure mode 2 — Signature blob (.sigstore) upload failed for one platform

**Symptom**: The binary exists on the GitHub Release but the `.sigstore` sibling does not, OR the `.sigstore` is empty/truncated.

**Important**: Without a signature, FR-003 ("every artifact MUST carry a verifiable signature") is violated for that platform. Users running `cosign verify-blob` will fail.

**Procedure**:

1. Re-sign the same binary blob with cosign using the canonical workflow OIDC identity. This **must** be done in the workflow context, not on a maintainer's machine — a local signing would produce a wrong identity.
2. Re-running the matrix entry from the Actions UI is the standard recovery path; it re-runs the build + sign + upload sequence.
3. If the matrix entry succeeded but only the upload to GH Release dropped the `.sigstore`, manually upload it via `gh release upload --clobber`. The signature is bound to the binary's bytes, not its location, so re-uploading is safe.

### Failure mode 3 — GitHub Release creation failed (release_attach_binaries)

**Symptom**: All four `binary_matrix` jobs are green but `release_attach_binaries` failed. No GH Release exists for the tag.

**Important**: Container image and PyPI publishes happen earlier in the pipeline and are not blocked by this — they're already live.

**Procedure**:

1. Investigate via the failed job's log. Usual cause: a transient GH API hiccup or a `gh release create` race (if a stale release exists from a prior aborted attempt).
2. If a partial GH release exists (created but missing assets), delete it: `gh release delete v<X.Y.Z> --repo kusari-oss/darnit --yes` (this does NOT delete the tag).
3. Download the workflow artifacts to a local machine:
   ```bash
   gh run download <run-id> --repo kusari-oss/darnit --pattern 'binary-*'
   ```
4. Create the release manually with all assets:
   ```bash
   gh release create v<X.Y.Z> \
     binary-macos-arm64/* \
     binary-macos-amd64/* \
     binary-linux-amd64/* \
     binary-linux-arm64/* \
     --title "darnit <X.Y.Z>" \
     --notes "Manually created after release_attach_binaries failed; see workflow run <url>" \
     --latest \
     --repo kusari-oss/darnit
   ```
5. Re-run `binary_smoke` to verify everything.

### Verification after recovery

```bash
# For each platform:
gh release download v<X.Y.Z> --repo kusari-oss/darnit \
  --pattern 'darnit-<X.Y.Z>-<os>-<arch>*'

chmod +x darnit-<X.Y.Z>-<os>-<arch>
./darnit-<X.Y.Z>-<os>-<arch> --version  # must match <X.Y.Z>

cosign verify-blob \
  --bundle darnit-<X.Y.Z>-<os>-<arch>.sigstore \
  --certificate-identity-regexp '^https://github\.com/kusari-oss/darnit/\.github/workflows/release\.yml@' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  darnit-<X.Y.Z>-<os>-<arch>
```

---

## Homebrew

The Homebrew flow has three steps and three corresponding failure surfaces:

1. **In `kusari-oss/darnit::release.yml`**: `homebrew_dispatch` job sends a `repository_dispatch` event to `kusari-oss/homebrew-tap` with the version + per-platform SHA-256s + the binary URL set.
2. **In `kusari-oss/homebrew-tap::.github/workflows/bump-formula.yml`**: renders `Formula/darnit.rb` from the template, runs `brew style` + `brew install --build-from-source`, opens an auto-merging PR.
3. **In `kusari-oss/homebrew-tap::.github/workflows/ci.yml`**: gates the auto-merge with `brew install --build-from-source` on macOS arm64 + Linux amd64.

### Failure mode 1 — `homebrew_dispatch` sent the event but the tap workflow never started

**Symptom**: `release.yml::homebrew_dispatch` job is green, but no workflow run appears at `https://github.com/kusari-oss/homebrew-tap/actions` for the corresponding time window. No `darnit <version>` PR is opened.

**Common root causes**:
- `HOMEBREW_TAP_TOKEN` secret is missing, expired, or has wrong scope (must be `contents: write` on `kusari-oss/homebrew-tap` only).
- The tap repo doesn't yet exist (see [packaging/README.md "External setup"](README.md#external-setup-one-time)).
- The tap repo doesn't have `bump-formula.yml` installed (was the tap initialized from `packaging/homebrew/tap-workflows/`?).

**Procedure**:

1. Inspect the GitHub Actions log for `homebrew_dispatch` — the `curl` against `/repos/kusari-oss/homebrew-tap/dispatches` will have logged any HTTP error (401/404).
2. If 401: rotate `HOMEBREW_TAP_TOKEN` per the setup runbook. Re-issue the GitHub App's installation token and update the repo secret.
3. If 404: confirm the tap repo exists and `bump-formula.yml` is present.
4. After fixing, manually trigger a new dispatch using `gh api`:
   ```bash
   payload='{"event_type":"darnit-release","client_payload":{"version":"<X.Y.Z>", ...}}'  # use the full payload schema from release.yml
   gh api /repos/kusari-oss/homebrew-tap/dispatches -X POST -H "Accept: application/vnd.github+json" --input - <<< "$payload"
   ```
5. The tap workflow will run and open the PR. From here, recovery follows the standard auto-merge path.

### Failure mode 2 — Tap PR opened but auto-merge failed (CI red on the formula)

**Symptom**: A `darnit <version>` PR exists at `https://github.com/kusari-oss/homebrew-tap/pulls`, but it's not merged. The PR's CI shows a failure on either `brew style` or `brew install --build-from-source`.

**Common root causes**:
- The template (`packaging/homebrew/darnit.rb.tmpl`) is out of sync with the tap-repo `bump-formula.yml`'s expectations (e.g., a placeholder name changed).
- The release binary URL or SHA-256 is wrong (most likely cause: a binary failed to attach to the GH release, so the URL 404s).
- A new Homebrew style rule started failing.

**Procedure**:

1. Open the PR and read the CI log.
2. **If a URL 404s**: the binary is missing from the GH release. Recover the binary attachment first (see [Standalone binary](#standalone-binary) recovery), then re-run the failed tap-repo workflow.
3. **If a SHA-256 mismatch**: compute the SHA-256 of the actual GH release asset and update the formula in the PR (or edit the dispatch payload and re-fire).
4. **If `brew style` is unhappy**: patch the template (`packaging/homebrew/darnit.rb.tmpl`) in this repo, cut a new tag, let `homebrew_dispatch` send a fresh PR. The old PR can be closed.
5. After the PR turns green, `gh pr merge --auto --squash` should pick it up. If auto-merge isn't enabled on the tap repo, merge manually.

### Failure mode 3 — Auto-merge didn't complete within the 30-minute SC-007 budget

**Symptom**: `homebrew_smoke` in this repo failed with "Tap PR for darnit `<version>` did not merge within 30 minutes (SC-007 violation)".

**Procedure**:

1. Check whether the PR exists and is merged. If yes, `homebrew_smoke` simply took too long to notice — re-run the smoke matrix.
2. If the PR exists but isn't merged, follow Failure mode 2.
3. If no PR exists, follow Failure mode 1.

### Failure mode 4 — Template drift between this repo and the tap repo

**Symptom**: Everything looks fine until a release runs, then `bump-formula.yml` in the tap repo fails parsing the template or substituting a placeholder.

**Important**: `bump-formula.yml` (in the tap repo) fetches the formula template (`packaging/homebrew/darnit.rb.tmpl`) from this repo at the tagged commit. The template is versioned alongside the release. The tap-repo workflow itself is not — it must be re-synced manually when this repo's `packaging/homebrew/tap-workflows/` reference copies change.

**Procedure**:

1. Identify which file drifted (template vs. tap-repo workflow).
2. If the **template** changed in a way the **tap workflow** doesn't handle: roll the tap workflow forward by copying the latest `packaging/homebrew/tap-workflows/bump-formula.yml` from this repo into the tap repo's `.github/workflows/`. Tag is irrelevant here — the tap workflow runs on whatever code is on `main`.
3. If the **tap workflow** changed in a way the **template** doesn't handle: cut a new patch release of darnit with the template fixed.

### Verification after recovery

```bash
# Sanity check from a fresh runner or developer machine
brew tap kusari-oss/tap
brew install darnit
darnit --version  # must report <X.Y.Z>
brew test darnit
```

---

## Claude Code plugin

The `plugin_package` job builds the bundle locally (`packaging/claude-plugin/build.sh`), runs three sanity checks in CI (version-pin matches on both axes, skill set matches the contract, runner exec-bit preserved on extraction), and uploads `darnit-claude-plugin-<version>.zip` to the existing GH Release as a new asset.

Recovery is generally simpler than for the other channels because the zip is fully reproducible from the tagged commit — `build.sh` only needs `bash`, `sed`, `zip`, and the source tree.

### Failure mode 1 — Zip upload to GH Release failed

**Symptom**: `plugin_package` job log shows the build succeeded but the `gh release upload` step failed (rate limit, transient API error, network blip).

**Important**: The zip is fully reproducible — running `build.sh` with the same `VERSION` on the tagged commit produces a byte-equivalent bundle (modulo the build timestamp inside the zip, which the `-X` flag strips).

**Procedure**:

1. Locally:
   ```bash
   git checkout v<X.Y.Z>
   VERSION=<X.Y.Z> ./packaging/claude-plugin/build.sh
   ```
   Confirm `dist/claude-plugin/darnit-claude-plugin-<X.Y.Z>.zip` exists.
2. Upload manually:
   ```bash
   gh release upload v<X.Y.Z> \
     dist/claude-plugin/darnit-claude-plugin-<X.Y.Z>.zip \
     --repo kusari-oss/darnit
   ```
3. Re-run `plugin_structural_smoke` and `plugin_behavioral_smoke` from the smoke workflow.

### Failure mode 2 — plugin.json version pin does not match the release version

**Symptom**: `plugin_package` job's "Assert plugin manifest pins the release version" step fails. Or the zip uploaded but `plugin_structural_smoke` reports a mismatch.

**Important**: This is a real bug — the `__VERSION__` substitution in `build.sh` failed, or the template was edited without the build script being updated. The plugin must not ship with a version mismatch (FR-004 lockstep).

**Procedure**:

1. Inspect `packaging/claude-plugin/templates/plugin.json` and `packaging/claude-plugin/build.sh`. Make sure every `__VERSION__` sentinel in the template is substituted in the script.
2. The `build.sh` has a final guard (`grep -q '__VERSION__'`) that bails on unfilled sentinels. If the in-CI assert tripped, the in-`build.sh` guard probably did too — re-read the job log.
3. Roll forward to `v<X.Y.Z+1>` once fixed. Do **not** patch the version inside the zip and re-upload — that breaks any user who already downloaded the bad zip.

### Failure mode 3 — Bundled skill set drifted from the contract

**Symptom**: `plugin_package` job's "Assert bundled skill set matches contract" step fails. Or `plugin_structural_smoke` reports `bundled=X expected=audit,comply,data,remediate`.

**Common cause**: A skill was renamed, added, or removed under `packages/darnit/src/darnit/skills/` without updating either the contract or `build.sh`'s `EXPECTED_SKILLS` array.

**Procedure**:

1. Compare `ls packages/darnit/src/darnit/skills/` against the contract's bundled-set list.
2. If a deliberate change: update both `EXPECTED_SKILLS` in `build.sh` AND the contract in `contracts/claude-plugin-contract.md` in the same PR.
3. If accidental: revert the skill change.

### Failure mode 4 — Runner script not executable after extraction

**Symptom**: `plugin_structural_smoke` reports "Runner script is +x" failed, OR users report "permission denied" when Claude Code tries to invoke the MCP server.

**Important**: The wrapper script is the FR-017 implementation. Without exec permission, the entire plugin is broken.

**Procedure**:

1. `build.sh` does `chmod 0755` on the runner before zipping. If the zip on the GH Release shows mode `0644`, the issue is upstream of the chmod — possibly a `zip` flag (`-X` strips Unix permissions on some platforms when combined with other flags).
2. Rebuild locally and inspect: `unzip -l darnit-claude-plugin-<X.Y.Z>.zip darnit/bin/darnit-mcp-runner` (the `mode` column in extended unzip output should start with `-rwx`).
3. If the mode is wrong even locally, fix `build.sh` first. The fix is most likely removing `-X` or adding `-X-` to preserve permissions.
4. Roll forward to `v<X.Y.Z+1>` once the build produces a correct zip.

### Failure mode 5 — Behavioral smoke fails (uvx path doesn't work in CI)

**Symptom**: `plugin_behavioral_smoke` installs uv, extracts the plugin, then `darnit-mcp-runner --help` exits non-zero — but structural smoke passed.

**Common causes**:
- `uvx --from darnit-mcp==<version> darnit-mcp --help` failed because PyPI/TestPyPI hasn't propagated the new version yet (rare; the `container_build_push` job's PyPI-propagation wait usually fixes this for downstream jobs).
- A change to darnit-mcp's CLI broke `--help` (very unlikely — `--help` is one of the most stable surfaces).

**Procedure**:

1. From a local machine: `uvx --from darnit-mcp==<X.Y.Z> darnit-mcp --help`. Does it work? If yes, the CI failure was transient — re-run.
2. If `uvx` can't fetch the package, see [PyPI section](#pypi) recovery.

### Verification after recovery

```bash
# Download the published zip
gh release download v<X.Y.Z> \
  --repo kusari-oss/darnit \
  --pattern "darnit-claude-plugin-<X.Y.Z>.zip" \
  --dir /tmp/plugin-verify
unzip -q /tmp/plugin-verify/darnit-claude-plugin-<X.Y.Z>.zip -d /tmp/plugin-verify

# Pin matches
jq '.version, .mcpServers["darnit-mcp"].env.DARNIT_MCP_VERSION' \
  /tmp/plugin-verify/darnit/.claude-plugin/plugin.json
# Both lines should print "<X.Y.Z>"

# Skill set
ls /tmp/plugin-verify/darnit/skills/
# Must be exactly: audit comply data remediate

# Runner is +x and the fallback works
test -x /tmp/plugin-verify/darnit/bin/darnit-mcp-runner

DARNIT_MCP_VERSION=<X.Y.Z> \
CLAUDE_PLUGIN_ROOT=/tmp/plugin-verify/darnit \
  /tmp/plugin-verify/darnit/bin/darnit-mcp-runner --help | head -5
# Should print darnit-mcp's help text.
```

---

## Filing a release-failure issue manually

The `finalize` job creates `release-failure` issues automatically. If for any reason it does not (e.g., the workflow itself crashes before `finalize`), open one manually using this template:

```
Title: release-failure: v<X.Y.Z> on <channel>

Channel: <pypi|container|binary|homebrew|claude_plugin>
Tag: v<X.Y.Z>
Workflow run: <URL>
Symptom: <what failed>
Recovery: <link to relevant section in packaging/RECOVERY.md>
```

Tag the issue `release-failure` so dashboards pick it up.
