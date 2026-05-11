# Phase 0 Research: Packaging & Distribution Channels

Resolves all open technical decisions deferred from `spec.md` and `plan.md`. Each section records the decision, rationale, and rejected alternatives.

---

## 1. Standalone-binary builder

**Decision**: `shiv`.

**Rationale**:
- darnit already requires Python ≥3.11 on the host for source installs; users who pick up the binary path are not trying to avoid Python entirely — they want a single relocatable file. `shiv` produces a zipapp that satisfies that need without bundling a Python interpreter.
- `shiv` build times are 5–30 seconds vs. minutes for PyInstaller and tens of minutes for Nuitka. Faster CI per release.
- darnit's dependency graph includes tree-sitter native bindings. `shiv` lets these be installed at first-run extract time into a per-user cache directory using the host Python, which sidesteps the cross-compilation pain PyInstaller hits with native extensions.
- The output is a single file, signable as a blob with `cosign sign-blob`.

**Alternatives considered**:
- **PyInstaller**: produces a true zero-Python-dep binary, but the dist directory is large (~150 MB uncompressed for our deps), build times are long, and tree-sitter bindings have a history of subtle breakage when frozen. Reconsider in a future iteration if users push back on the "Python required" prerequisite.
- **Nuitka**: similar trade-offs to PyInstaller, plus a steeper learning curve. No advantage for our use case.
- **`uv tool install`**: elegant for users who already have `uv`, but it is an install path, not a distribution artifact. We document it as an alternative on the PyPI install page, not as a binary.
- **`pex`**: similar to `shiv` but with a more complex configuration surface. `shiv` is simpler and adequate.

---

## 2. Container base image

**Decision**: `python:3.12-slim` as the base, multi-stage build to keep the final image lean.

**Rationale**:
- Spec target is ≤300 MB compressed (soft). A measured starting point with `python:3.12-slim` + `git` + `gh` + darnit + tree-sitter bindings lands around 220–260 MB compressed in practice. Comfortably under the soft target with headroom.
- `python:3.12-slim` ships a recent Debian base, which makes installing the GitHub CLI straightforward (apt repo). Distroless and Chainguard images require either re-packaging `gh` or accepting a fatter image.
- It is the lowest-friction base for contributors who will later need to debug the image. The package's controls routinely shell out to `git` and `gh`; a base image that supports installing those without contortions matters.
- Multi-stage build: a builder stage installs darnit and prunes caches; the final stage copies only the installed site-packages and the CLI tools, drops the build-time caches.

**Alternatives considered**:
- **Distroless (`gcr.io/distroless/python3`)**: smaller and more secure by default, but adding the GitHub CLI requires bundling a static binary or copying from a builder stage. Adds complexity; defer until a second image variant becomes worthwhile.
- **Chainguard `cgr.dev/chainguard/python`**: excellent SBOM/vuln posture, but apt-style tool installs (`gh`) are awkward. The Chainguard ecosystem encourages building tools from source, which inflates build time. Worth reconsidering for a hardened image variant in v2.
- **`python:3.12` (full)**: blows past the size target (~900 MB compressed). Rejected.
- **Alpine-based (`python:3.12-alpine`)**: musl libc breaks several Python wheels with C extensions (including some tree-sitter bindings). Rejected.

A future hardened-image variant (Chainguard- or distroless-based) is tracked as follow-up, not part of v1.

---

## 3. Signing strategy

**Decision**: Sigstore for PyPI wheels (via `pypa/gh-action-pypi-publish` with `--attestations`), cosign keyless for container images and binary blobs, GitHub Attestations for SBOMs.

**Rationale**:
- All three mechanisms share the same OIDC identity (the GitHub Actions workflow's identity), so one signing identity covers every artifact across every channel.
- No long-lived publishing tokens or signing keys live anywhere — satisfies spec FR-007.
- Sigstore attestations on PyPI are now the default expectation for serious open-source Python projects and integrate with `pip install --verify-attestations` (PEP 740).
- cosign + GHCR provides verifiable image signatures consumable by every major policy engine (Kyverno, Connaisseur, Sigstore Policy Controller).
- The same cosign workflow signs detached blobs for binary downloads. Users verify with `cosign verify-blob`.

**Verification surfaces** (must be documented in `docs/install/`):
- PyPI: `python -m sigstore verify identity --bundle <bundle> --cert-identity <workflow-uri> --cert-oidc-issuer https://token.actions.githubusercontent.com <wheel>`
- GHCR: `cosign verify ghcr.io/kusari-oss/darnit:<tag> --certificate-identity-regexp '^https://github\.com/kusari-oss/darnit/' --certificate-oidc-issuer https://token.actions.githubusercontent.com`
- Binary blob: `cosign verify-blob --bundle <.sigstore> --certificate-identity-regexp ... <binary>`

**Alternatives considered**:
- **GPG signatures**: requires key management, key publication, and key rotation. Long-lived keys are exactly what FR-007 forbids. Rejected.
- **GitHub Artifact Attestations only (without cosign)**: works for GitHub-hosted artifacts but does not extend to PyPI or GHCR. Use it as a complement (SBOMs), not a replacement.

---

## 4. Homebrew formula auto-update mechanism

**Decision**: `repository_dispatch` from `kusari-oss/darnit` to `kusari-oss/homebrew-tap` on stable release publish, with a workflow in the tap repo that renders the formula and opens an auto-merging PR.

**Rationale**:
- Keeps the formula template (`packaging/homebrew/darnit.rb.tmpl`) in the source repo where it can be code-reviewed alongside other release infrastructure.
- The tap repo holds only the rendered formula plus its own bump workflow — minimal duplication.
- `repository_dispatch` carries the version and per-platform SHA-256s in its payload; the tap workflow does not need to fetch them. This avoids race conditions where the binary is being uploaded while the formula tries to compute its hash.
- Auto-merging the bump PR is safe because:
  - The payload is signed by the originating workflow's OIDC token.
  - CI in the tap repo runs `brew style` + `brew install --build-from-source` against the rendered formula before merge.
  - A human can always revert via a normal PR.

**Alternatives considered**:
- **`brew bump-formula-pr` from a maintainer's machine**: requires manual action per release. Defeats automation.
- **GitHub App authoring the PR directly with no dispatch**: requires app permissions on both repos. More setup, no benefit over dispatch.
- **Single-repo formula (no separate tap)**: violates Homebrew's tap conventions and complicates `brew tap` UX. Rejected.

---

## 5. Claude Code plugin manifest

**Decision**: Single `manifest.json` declaring an MCP server and bundled slash commands, packaged as a `.zip` artifact attached to each stable GitHub release. The manifest's MCP server command is a shell wrapper that tries `uvx --from darnit-mcp@<version> darnit-mcp` first and falls back to `pipx run darnit-mcp==<version>`.

**Rationale**:
- Matches the public Claude Code plugin convention: a manifest plus optional bundled `skills/` and slash commands.
- Pinning to an exact version in both `uvx` and `pipx` invocations is mandatory — otherwise the plugin and the runtime can drift, which would silently break behavior. Spec FR-004 requires version match across channels.
- The fallback chain (`uvx` → `pipx run` → actionable error) directly implements the FR-017 contract resolved in Clarification Q1.
- A `.zip` artifact attached to the GitHub release is the simplest distribution surface that does not require a Claude Code "marketplace" account. Once Anthropic's marketplace surfaces stabilize, we can submit the same artifact there.

**Open question deferred**: The exact manifest schema (field names for slash commands, skills, MCP server config) tracks Anthropic's published Claude Code plugin spec, which is still evolving. The implementation phase will pin to whichever schema version is current at the time and document the pinned version in `packaging/claude-plugin/README.md`. If the schema changes incompatibly post-v1, that is a follow-up release-engineering task, not a re-spec.

**Alternatives considered**:
- **Bundled standalone binary inside the plugin** (mentioned in clarification Q1 fallback): rejected for v1 because of the platform-specific bundling problem (one plugin artifact serving four arch×OS combos). Tracked as follow-up.
- **No bundled skills, just an MCP server config**: rejected because the skills are the primary value-add for the user; bundling them is what makes the plugin a one-step install.

---

## 6. Release pipeline orchestration

**Decision**: GitHub Actions workflows (`release.yml` + `release-smoke.yml`), tag-triggered, with one job per channel and `needs:` dependencies wiring the order.

**Rationale**:
- Already where every other workflow in the repo lives. No new infrastructure.
- Native support for OIDC tokens (required by all signing decisions) and reusable workflows.
- Per-channel jobs run in parallel where they can. Sequencing constraints (container build needs PyPI to be published first; brew needs binaries) are expressed with `needs:`.
- Per-channel failure isolation comes for free: a failing job does not cancel siblings (we explicitly set `if: always()` for the post-publish summary job).

**Alternatives considered**:
- **`goreleaser` (Go-native release tool)**: high-quality, but its sweet spot is Go binaries with auto-generated changelogs and formula PRs. Stretching it to cover PyPI, container images, and a Claude plugin manifest would require many custom hook scripts — at that point we are writing GitHub Actions inside a wrapper. Rejected.
- **`semantic-release` (Node-native)**: similar story; built for npm and Git-tag-based version inference. Not aligned with our lockstep-versioning + manual-tag model.
- **A custom Python release CLI**: maintenance burden without offsetting benefit. Rejected.

---

## 7. Partial-failure surface (SC-008 implementation choice)

**Decision**: A GitHub issue tagged `release-failure` is automatically created in `kusari-oss/darnit` whenever any per-channel publish job fails for a stable tag. The job summary in the workflow run carries the same information for triage. No Slack/email integration in v1.

**Rationale**:
- The spec requires partial-failure state to be **surfaced** within 5 minutes (SC-008) — it does not require any specific notification channel. A GitHub issue meets this bar and is discoverable by maintainers without external config.
- A GitHub issue is the only surface that persists past the workflow run's UI lifetime, so a failure noticed days later still has a tracking artifact.
- The issue body includes: the failing channel, the tag, the workflow-run URL, and a `Recovery:` section reading from a static `packaging/RECOVERY.md` keyed by channel.
- Pre-release failures (rc tags) do not auto-create issues — they post a workflow summary only. Spec scope is stable-release reliability.

**Alternatives considered**:
- **Slack webhook**: requires per-organization Slack config and rotates webhook URLs. Out of scope; can be added by a downstream user via their own GitHub Action subscribing to the `release-failure` label.
- **Email**: same problem at smaller scale.
- **Status page / external dashboard**: way out of scope.

---

## 8. Versioning mechanics under lockstep

**Decision**: Single `__version__` constant in each public package, sourced from the git tag at release time via a build-time hook. The release workflow rejects a tag whose components differ from `pyproject.toml` versions in any public package, forcing the maintainer to either bump the file or fix the tag.

**Rationale**:
- Lockstep was an explicit Assumption in the spec. This mechanism makes it enforceable in CI rather than a documentation convention.
- The `pyproject.toml` `version` field in the workspace remains the source of truth at development time; the tag is what triggers the release. Validating that the two match prevents the "tag says 0.1.0, wheel says 0.0.9" class of release bug.
- Pre-release tags (`v0.1.0rc1`) require `version = "0.1.0rc1"` in the workspace `pyproject.toml`s at the tagged commit. The release workflow validates this.

**Alternatives considered**:
- **Dynamic versioning from git** (`hatch-vcs`, `setuptools-scm`): would let us skip the `pyproject.toml` bump step, but it makes the version invisible in a source checkout (you have to run a tool to see it), which complicates editor tooling and IDE displays. Rejected.
- **Manual sync without CI enforcement**: relies on maintainer discipline. The point of lockstep is to make drift impossible, not merely discouraged. Rejected.

---

## 9. Public package set lock-in

**Decision**: `darnit`, `darnit-baseline`, `darnit-gittuf`, `darnit-mcp` are the v1 public set. The list is enumerated in `packaging/pypi/public-packages.txt` and the release workflow refuses to publish anything not in that list. `darnit-example`, `darnit-testchecks`, `darnit-plugins` are explicitly internal and never published.

**Rationale**:
- Matches the spec Assumption.
- A single-file source of truth (`public-packages.txt`) is grep-able, code-reviewable, and trivially tested.
- The reverse check — "is this package in the list?" — runs in CI on every release to prevent accidental publication.

**Alternatives considered**:
- **Per-package `publishable = true` flag in `pyproject.toml`**: scatters the source of truth. Rejected.
- **Publish everything**: would surface internal test scaffolding as public artifacts. Strongly rejected.

`packages/darnit-hello/` (the worked example for the third-party packaging guide) is **not** publicly published from this repo — its `pyproject.toml` is the artifact (so users can copy it), but the actual package lives only in-tree for the CI smoke test.

---

## Summary

All technical clarifications resolved. No remaining `NEEDS CLARIFICATION` markers. Phase 1 may proceed.
