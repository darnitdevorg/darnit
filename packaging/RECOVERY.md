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

> _Filled by Phase 3 (User Story 1)._

Failure modes:

- Upload to PyPI succeeded for some packages and failed for others.
- Sigstore attestation upload failed.
- TestPyPI publish failed for a pre-release tag.

Repair procedure: _TBD in T018._

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
