# Contract: Container Image

## Registry & coordinates

- Registry: `ghcr.io`
- Repository: `ghcr.io/kusari-oss/darnit`
- Tag convention (stable releases):
  - `ghcr.io/kusari-oss/darnit:v<X.Y.Z>` (immutable; one of these per Release)
  - `ghcr.io/kusari-oss/darnit:latest` (moves to the newest stable on each stable release; never points at a pre-release)
- Tag convention (pre-releases):
  - `ghcr.io/kusari-oss/darnit:v<X.Y.Z>rc<N>` (immutable)
  - `:latest` is **not** moved.
- Edge build (non-release):
  - `ghcr.io/kusari-oss/darnit:edge` (rebuilt on every push to `main`; unsigned; not part of the release pipeline)

## Architectures

Two platforms per release, in one multi-arch manifest:

- `linux/amd64`
- `linux/arm64`

The release workflow uses `docker/setup-buildx-action` + `docker/build-push-action` with `platforms: linux/amd64,linux/arm64`. Both single-arch manifests must build successfully or the channel fails.

## Image contents

Base: `gcr.io/distroless/cc-debian12:nonroot`, pinned by digest: glibc, CA certificates and the `nonroot` user, with no shell and no package manager.

The image is built from source: the tagged commit for a release, `main` for `:edge`. One Dockerfile serves both. Nothing about darnit is installed from PyPI, so the image can carry packages that PyPI does not have, and a release image does not wait for PyPI. (Amended for #585 and #586: the PyPI install had no darnit-csl, no zizmor or gittuf, and lost the repository identity.)

The image MUST contain:
- Python 3.12 from uv's python-build-standalone builds, and a virtual environment built against it.
- The workspace packages at the source's versions, installed non-editable from `uv.lock` (`--frozen`) with no development dependencies: `darnit-mcp` (the root package) and what it depends on (`darnit-core`, `darnit-baseline`, `darnit-gittuf`, `darnit-reproducibility`), plus `darnit-csl`. Not `darnit-hello` or `darnit-testchecks`.
- The external tools the controls and remediations run. `zizmor`, `gittuf`, `gh` and `uv` are downloads pinned to a version and checked against a sha256 per architecture (uv by image digest). `git` (with its https transport), `grep`, `gpg` and `ssh-keygen` come from Debian 12 without a version pin, so a rebuild picks up security updates. They bring exactly the shared libraries they load that the base lacks, and the dpkg status of their packages so image scanners see them.
- `safe.directory=/repo` in `/etc/gitconfig`. The mounted repository belongs to the host user, not the container user, and without the setting git refuses it and the audit loses the repository identity (#586). A hostile `.git/config` in the mount can do no more here than in a native run; #617 tracks hardening darnit's own git calls.
- The non-root `nonroot` user (uid 65532) as the runtime user.
- An `org.opencontainers.image.version` label: the release version or the commit sha, passed by the workflow as a build arg.

The harness needs `ANTHROPIC_API_KEY`, and the platform checks need a GitHub token: `docker run -e ANTHROPIC_API_KEY -e GH_TOKEN ...`.

The image MUST NOT contain:
- A shell. What needs one fails: git hooks, git credential helpers that take arguments (such as `gh auth git-credential`), and exec steps that run `sh -c` (OSPS-BR-01.01 has an evidence-only one, which reports `missing_tool`).
- A package manager, or apt, pip or uv caches.
- Build-time tools (gcc, make, etc.) — these live in the builder stages only.

## Entrypoint & default command

```dockerfile
ENTRYPOINT ["darnit"]
CMD ["harness", "/repo"]
```

The entrypoint is the darnit CLI, and the arguments are a darnit subcommand. (Contract correction: this replaces the shell entrypoint and its dispatch table. No versioned image was published with them.)
- No arguments run `darnit harness /repo`, the primary entry point: an end-to-end audit that makes its own model calls. Without `ANTHROPIC_API_KEY` it stops with its setup error, exit 2.
- `serve` runs the stdio MCP server for agent integrations (`docker run -i`).
- `audit /repo` runs the deterministic audit, for testing.
- Any other darnit subcommand works the same way. Another program in the image runs with `--entrypoint`.

## Working directory & volumes

- `WORKDIR /repo` — image expects the user's project to be mounted here.
- Recommended invocation: `docker run --rm -e ANTHROPIC_API_KEY -e GH_TOKEN -v "$PWD:/repo" ghcr.io/kusari-oss/darnit:<tag>`.

## Size budget

Spec target: **300 MB compressed** (soft). The release workflow MUST:
- Record compressed size of the manifest in the GitHub Actions job summary for each Release.
- Emit a workflow **warning** (not failure) if compressed size exceeds the previous Release by >15%.
- Record the size in the auto-generated release notes.

A release exceeding 300 MB compressed is permitted but the release notes MUST acknowledge it and explain why.

## Signing

Each per-arch digest is signed with cosign keyless (OIDC) using the release workflow's identity:

```bash
cosign sign --yes ghcr.io/kusari-oss/darnit@sha256:<digest>
```

The signing identity certificate must satisfy:
```
--certificate-identity-regexp '^https://github\.com/kusari-oss/darnit/\.github/workflows/release\.yml@refs/tags/v[0-9]+\.[0-9]+\.[0-9]+'
--certificate-oidc-issuer https://token.actions.githubusercontent.com
```

## SBOM

`syft` generates an SPDX-JSON SBOM of the final image. It is attached as a cosign attestation:

```bash
cosign attest --yes --predicate sbom.spdx.json --type spdx ghcr.io/kusari-oss/darnit@sha256:<digest>
```

Users download with `cosign download attestation ghcr.io/kusari-oss/darnit:<tag>`.

## Smoke test

In `release-smoke.yml`:

```bash
docker pull ghcr.io/kusari-oss/darnit:<tag>
docker run --rm ghcr.io/kusari-oss/darnit:<tag> --version | grep "<version>"
cosign verify ghcr.io/kusari-oss/darnit:<tag> \
  --certificate-identity-regexp '^https://github.com/kusari-oss/darnit/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

Both must succeed.

On pull requests that change the image's inputs, CI builds the `linux/amd64` image without pushing it and runs `scripts/container-image-smoke.sh`: `--version`, every framework loads, each bundled tool runs, the default command without `ANTHROPIC_API_KEY` stops with exit 2, `audit /repo` on the mounted checkout finds the repository identity, and `serve` completes an MCP stdio handshake.
