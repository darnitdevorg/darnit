# Install darnit via the container image

This is the recommended install path for **CI/CD pipelines** and any environment that doesn't want to manage a Python toolchain. Examples assume version `0.1.0` — substitute the version you want.

## Run a one-shot audit

```bash
docker run --rm -v "$PWD:/repo" -e GH_TOKEN ghcr.io/darnitdevorg/darnit:v0.1.0 audit
```

`-e GH_TOKEN` passes your GitHub token into the container for the platform checks (branch protection, releases, repository settings). Without it those checks report that they could not be measured. A token with read access to the repository is enough for an audit; `gh auth token` prints the one the GitHub CLI uses.

For `podman` users, substitute `podman` for `docker` — same flags.

### Repository ownership and `safe.directory`

The container runs as uid 10001, and the mounted repository belongs to your user, so git would refuse it as "dubious ownership" and darnit would lose the repository's identity (owner and name). The image sets `safe.directory=/repo` in its system git configuration so git accepts the mount (#586).

The caveat: git's ownership check exists so that a repository someone else controls cannot run commands through its `.git/config` (for example `core.fsmonitor`). With the check off for `/repo`, mount only repositories you would also run git in on your own machine. Inside the container this is no more dangerous than a native run; #617 tracks hardening darnit's own git calls. The setting covers `/repo` only, so mount there.

## Tags

| Tag | Stability |
|---|---|
| `:v0.1.0` | Immutable; points at one specific release. **Use this in CI.** |
| `:latest` | Latest stable. Moves on every stable release. |
| `:v0.1.0rc1` | Pre-release; never moves under `:latest`. |
| `:edge` | Rolling build of `main`, from source, with unreleased changes; **unsigned**, for testing only. |

For production CI, pin to the immutable `:vX.Y.Z` form. `:latest` is convenient for ad-hoc use but bypasses the immutability guarantee you get from pinning.

## Platforms

Multi-arch image; `docker pull` selects the right one automatically.
- `linux/amd64`
- `linux/arm64`

Apple Silicon Macs running Docker Desktop will pull the `arm64` variant by default.

## Subcommands

The entrypoint dispatches the first argument:

| First arg | Behavior |
|---|---|
| `audit` / `remediate` / `list-controls` / `plan` / `profiles` / `validate` | Forwarded to `darnit` CLI |
| `--version` / `--help` | Forwarded to `darnit` CLI |
| `mcp` | Forwarded to `darnit serve` (stdio MCP server) |
| Anything else | Executed directly (escape hatch for `sh`, `gh`, `git`, etc.) |

## Verify the image signature

Every release tag is signed with cosign keyless OIDC. The signing identity binds the image to the `release.yml` workflow in `darnitdevorg/darnit`.

```bash
cosign verify ghcr.io/darnitdevorg/darnit:v0.1.0 \
  --certificate-identity-regexp '^https://github\.com/darnitdevorg/darnit/\.github/workflows/release\.yml@' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

A passing verification proves:
- The image bytes match what was signed.
- The signer was the `release.yml` workflow in `darnitdevorg/darnit`.
- The OIDC issuer was GitHub Actions.

The `:edge` rolling build is **not** signed.

## Download the SBOM

Each signed image has an SPDX-JSON SBOM attached as a cosign attestation:

```bash
cosign download attestation ghcr.io/darnitdevorg/darnit:v0.1.0 \
  | jq -r '.payload' | base64 -d | jq '.predicate' > darnit-sbom.spdx.json
```

Verify the SBOM's signing identity at the same time:

```bash
cosign verify-attestation ghcr.io/darnitdevorg/darnit:v0.1.0 \
  --type spdx \
  --certificate-identity-regexp '^https://github\.com/darnitdevorg/darnit/\.github/workflows/release\.yml@' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

## Image contents

The image is built from source: a release image from its tagged commit, `:edge` from `main`. Both use `packaging/container/Dockerfile` and the versions in `uv.lock`; nothing about darnit comes from PyPI.

- **Base**: `python:3.12-slim-bookworm`
- **darnit packages**: `darnit-mcp`, `darnit-core`, `darnit-baseline`, `darnit-gittuf`, `darnit-reproducibility` and `darnit-csl`, so `darnit list` shows openssf-baseline, gittuf, reproducibility, community-spec and community-spec-optional. No development dependencies.
- **Bundled tools**, each pinned: `zizmor` (workflow analysis, OSPS-AC-04.02 and OSPS-BR-01.01), `gittuf` (GT-01.02), `gpg` and `ssh-keygen` (commit signature checks, GT-02.01), `git`, and `gh` (the GitHub CLI; the platform checks use it)
- **Git configuration**: `safe.directory=/repo` (see [Repository ownership](#repository-ownership-and-safedirectory))
- **Runtime user**: non-root (`darnit`, uid 10001)
- **Working directory**: `/repo` (so `-v "$PWD:/repo"` is the conventional mount)
- **Version label**: `org.opencontainers.image.version` is the release version, or the commit sha for `:edge`

## Build the image locally

From a checkout of the repository:

```bash
docker build -f packaging/container/Dockerfile -t darnit-local .
docker run --rm -v "$PWD:/repo" -e GH_TOKEN darnit-local audit
```

The build installs the checkout's packages, so it includes your local changes. `--build-arg IMAGE_VERSION=<version>` sets the version label (default `dev`). `scripts/container-image-smoke.sh darnit-local` runs the same checks CI runs on pull requests that touch the image.

## CI usage examples

### GitHub Actions

```yaml
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run darnit audit
        env:
          GH_TOKEN: ${{ github.token }}
        run: |
          docker run --rm \
            -v "$PWD:/repo" \
            -e GH_TOKEN \
            ghcr.io/darnitdevorg/darnit:v0.1.0 \
            audit --output json > darnit-audit.json
```

### GitLab CI

```yaml
audit:
  image: ghcr.io/darnitdevorg/darnit:v0.1.0
  script:
    - darnit audit
```

## Prerequisites

- A container runtime: **Docker** ≥ 20.10 or **Podman** ≥ 4.0
- Network access to `ghcr.io` (the image fetches nothing at runtime except what the platform checks ask GitHub for)
- For multi-arch pulls on a non-native architecture: **QEMU** (`docker run --platform`)

## Size budget

The compressed image targets **300 MiB**. Each release records the measured size in its release notes; a release that exceeds the target by >15% over the previous release surfaces a workflow warning.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `Error response from daemon: manifest unknown` | The tag does not exist. Check `gh release list --repo darnitdevorg/darnit` for valid versions. |
| `exec format error` on Apple Silicon | The image was pulled for the wrong architecture. Use `docker pull --platform linux/arm64 ...` or let Docker pick automatically. |
| `cosign verify` fails with "no matching signatures" | You're trying to verify an `:edge` image (unsigned) or the tag was published before this signing scheme. |
| The audit complains about missing `git`/`gh` | The image bundles both — re-pull, since the bundled binaries might have been overridden by a previous `--volume` mount. |
| Platform checks report "could not be measured", or the trust line says `no repository identity` | Pass `-e GH_TOKEN` for the platform checks. A missing identity means git cannot read the repository: mount it at `/repo` (the only path `safe.directory` covers) and check that it has a GitHub `origin` remote. |
