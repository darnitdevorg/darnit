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

> _Filled by Phase 4 (User Story 2)._

Failure modes:

- One platform manifest pushed; the other failed (multi-arch incomplete).
- cosign signing failed after image push.
- SBOM attestation upload failed.

Repair procedure: _TBD in T030._

---

## Standalone binary

> _Filled by Phase 5 (User Story 3) — binary side._

Failure modes:

- Build succeeded for 3 of 4 platforms.
- Signature blob upload failed.
- GitHub Release asset upload failed for one or more files.

Repair procedure: _TBD in T039._

---

## Homebrew

> _Filled by Phase 5 (User Story 3) — Homebrew side._

Failure modes:

- `repository_dispatch` succeeded but the tap workflow did not start.
- The tap workflow opened a PR but auto-merge failed (CI red).
- The auto-merge did not complete within the 30-minute SC-007 budget.

Repair procedure: _TBD in T048._

---

## Claude Code plugin

> _Filled by Phase 6 (User Story 4)._

Failure modes:

- Plugin zip upload to the GitHub Release failed.
- Plugin manifest version pin does not match the release version.
- Skill bundling missed one or more skills.

Repair procedure: _TBD in T057._

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
