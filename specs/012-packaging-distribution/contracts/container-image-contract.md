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

Base: `python:3.12-slim`.

The image MUST contain:
- The exact PyPI-published version of `darnit-mcp` (installed via `pip install darnit-mcp==<version>` in the builder stage; runtime stage copies the virtualenv).
- `git` (apt).
- `gh` (GitHub CLI, installed from the official apt repo).
- A non-root user `darnit` (uid 10001) as the runtime user.

The image MUST NOT contain:
- A shell history.
- Apt caches (`/var/lib/apt/lists`, `/var/cache/apt`).
- Pip caches (`~/.cache/pip`).
- Build-time tools (gcc, make, etc.) — these live in the builder stage only.

## Entrypoint & default command

```dockerfile
ENTRYPOINT ["/usr/local/bin/darnit-entrypoint.sh"]
CMD ["audit", "--help"]
```

`darnit-entrypoint.sh` resolves the first positional arg:
- `audit`, `remediate`, `list-controls`, `--version`, `--help` → forwarded to `darnit`.
- `mcp` → forwarded to `darnit-mcp` (stdio MCP server).
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
