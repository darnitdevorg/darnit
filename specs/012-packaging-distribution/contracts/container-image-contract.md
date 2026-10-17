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

Base: `python:3.12-slim-bookworm`.

The image is built from source: the tagged commit for a release, `main` for `:edge`. One Dockerfile serves both. Nothing about darnit is installed from PyPI, so the image can carry packages that PyPI does not have, and a release image does not wait for PyPI. (Amended for #585 and #586: the PyPI install had no darnit-csl, no zizmor or gittuf, and lost the repository identity.)

The image MUST contain:
- The workspace packages at the source's versions, installed non-editable from `uv.lock` (`--frozen`) with no development dependencies: `darnit-mcp` (the root package) and what it depends on (`darnit-core`, `darnit-baseline`, `darnit-gittuf`, `darnit-reproducibility`), plus `darnit-csl`. Not `darnit-hello` or `darnit-testchecks`.
- The external tools the controls run, each pinned to a version: `zizmor`, `gittuf`, `gpg` (gnupg), `ssh-keygen` (openssh-client), `git` and `gh`. A tool downloaded at build time is checked against a sha256 pinned per architecture.
- `safe.directory=/repo` in the system git configuration. The mounted repository belongs to the host user, not uid 10001, and without the setting git refuses it and the audit loses the repository identity (#586). A hostile `.git/config` in the mount can do no more here than in a native run; #617 tracks hardening darnit's own git calls.
- A non-root user `darnit` (uid 10001) as the runtime user.
- An `org.opencontainers.image.version` label: the release version or the commit sha, passed by the workflow as a build arg.

The platform checks need a GitHub token in the container: `docker run -e GH_TOKEN ...`.

The image MUST NOT contain:
- A shell history.
- Apt caches (`/var/lib/apt/lists`, `/var/cache/apt`).
- Pip or uv caches, or uv itself.
- Build-time tools (gcc, make, etc.) — these live in the builder stage only.

## Entrypoint & default command

```dockerfile
ENTRYPOINT ["/usr/local/bin/darnit-entrypoint.sh"]
CMD ["audit", "--help"]
```

`darnit-entrypoint.sh` resolves the first positional arg:
- `audit`, `remediate`, `list-controls`, `--version`, `--help` → forwarded to `darnit`.
- `mcp` → forwarded to `darnit serve` (stdio MCP server). (Amended for #621: no package provides a `darnit-mcp` executable; `darnit-mcp` is the package that provides `darnit`.)
- Anything else → executed directly (for advanced users wanting to override).

## Working directory & volumes

- `WORKDIR /repo` — image expects the user's project to be mounted here.
- Recommended invocation: `docker run --rm -v "$PWD:/repo" ghcr.io/kusari-oss/darnit:<tag> audit`.

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

On pull requests that change the image's inputs, CI builds the `linux/amd64` image without pushing it and runs `scripts/container-image-smoke.sh`: `--version`, every framework loads, the bundled tools run, an audit of the mounted checkout finds the repository identity, and an MCP stdio handshake lists tools.
