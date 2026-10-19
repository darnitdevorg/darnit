# Install darnit via the container image

This is the recommended install path for **CI/CD pipelines** and any environment that doesn't want to manage a Python toolchain. Examples assume version `0.1.0` — substitute the version you want.

## Run darnit on a repository

```bash
docker run --rm -e ANTHROPIC_API_KEY -e GH_TOKEN -v "$PWD:/repo" ghcr.io/darnitdevorg/darnit:v0.1.0
```

With no arguments the image runs `darnit harness /repo`: the end-to-end audit, which makes its own model calls and prints a Markdown report to stdout. It exits 0 when no control fails, 1 when one does, 2 on a setup error (for example a missing `ANTHROPIC_API_KEY`; it prints `harness: setup_error, missing ANTHROPIC_API_KEY environment variable, exit 2`) and 3 on an internal error.

- `-e ANTHROPIC_API_KEY` passes your Anthropic API key for the model calls.
- `-e GH_TOKEN` passes your GitHub token for the platform checks (branch protection, releases, repository settings). Without it those checks report that they could not be measured. A token with read access to the repository is enough; `gh auth token` prints the one the GitHub CLI uses.

The arguments are darnit subcommands, because the entrypoint is the `darnit` CLI:

```bash
# MCP server on stdio, for agent clients (note -i)
docker run --rm -i -e GH_TOKEN -v "$PWD:/repo" ghcr.io/darnitdevorg/darnit:v0.1.0 serve

# Deterministic audit without model calls, for testing
docker run --rm -e GH_TOKEN -v "$PWD:/repo" ghcr.io/darnitdevorg/darnit:v0.1.0 audit /repo
```

For `podman` users, substitute `podman` for `docker` — same flags.

### Repository ownership and `safe.directory`

The container runs as the distroless `nonroot` user (uid 65532), and the mounted repository belongs to your user, so git would refuse it as "dubious ownership" and darnit would lose the repository's identity (owner and name). The image sets `safe.directory=/repo` in `/etc/gitconfig` so git accepts the mount (#586).

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

## No shell inside

The runtime is distroless: no shell, no package manager. Arguments go to `darnit`; to run another program in the image, name it with `--entrypoint`:

```bash
docker run --rm --entrypoint git ghcr.io/darnitdevorg/darnit:v0.1.0 --version
docker run --rm -it --entrypoint python ghcr.io/darnitdevorg/darnit:v0.1.0
```

What needs a shell does not work in the image:

- Git hooks in the mounted repository (`.git/hooks/*`, including the pre-commit framework's) cannot run, so a `git commit` from the container fails when the repository has one.
- Git credential helpers that take arguments, such as `gh auth git-credential`, cannot run, so git cannot authenticate over https: pushing a remediation branch and cloning a private repository (`audit_org`) need to run outside the container.

To debug, build the image on the distroless debug base, which adds a busybox shell:

```bash
docker build -f packaging/container/Dockerfile \
  --build-arg RUNTIME_BASE=gcr.io/distroless/cc-debian12:debug-nonroot -t darnit-debug .
docker run --rm -it -v "$PWD:/repo" --entrypoint /busybox/sh darnit-debug
```

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

- **Base**: `gcr.io/distroless/cc-debian12:nonroot` (glibc, CA certificates; no shell or package manager)
- **Python**: 3.12 from uv's python-build-standalone builds
- **darnit packages**: `darnit-mcp`, `darnit-core`, `darnit-baseline`, `darnit-gittuf`, `darnit-reproducibility` and `darnit-csl`, so `darnit list` shows openssf-baseline, gittuf, reproducibility, community-spec and community-spec-optional. No development dependencies.
- **Bundled tools**: `zizmor` (workflow analysis, OSPS-AC-04.02 and OSPS-BR-01.01), `gittuf` (GT-01.02), `gh` (the GitHub CLI; the platform checks use it) and `uv` (a remediation runs `uv lock`), each pinned by version and checksum; `git` with https support, `grep`, `gpg` and `ssh-keygen` (commit signature checks, GT-02.01) from Debian 12, with the security updates current at build time
- **Git configuration**: `safe.directory=/repo` (see [Repository ownership](#repository-ownership-and-safedirectory))
- **Runtime user**: `nonroot` (uid 65532)
- **Working directory**: `/repo` (so `-v "$PWD:/repo"` is the conventional mount)
- **Version label**: `org.opencontainers.image.version` is the release version, or the commit sha for `:edge`

## Build the image locally

From a checkout of the repository:

```bash
docker build -f packaging/container/Dockerfile -t darnit-local .
docker run --rm -e ANTHROPIC_API_KEY -e GH_TOKEN -v "$PWD:/repo" darnit-local
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
      - name: Run darnit
        env:
          ANTHROPIC_API_KEY: ${{ secrets.ANTHROPIC_API_KEY }}
          GH_TOKEN: ${{ github.token }}
        run: |
          docker run --rm \
            -e ANTHROPIC_API_KEY -e GH_TOKEN \
            -v "$PWD:/repo" \
            ghcr.io/darnitdevorg/darnit:v0.1.0 > darnit-report.md
```

### GitLab CI

The image has no shell, so it cannot be a GitLab job's `image:` (the runner runs `script:` in a shell). Run it with `docker run` from a job that has Docker, as in the GitHub Actions example.

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
| `harness: setup_error, missing ANTHROPIC_API_KEY environment variable, exit 2` | Pass `-e ANTHROPIC_API_KEY`, or run `audit /repo` for the deterministic audit. |
| `exec: "sh": executable file not found` | The image has no shell; see [No shell inside](#no-shell-inside). |
| The audit complains about missing `git`/`gh` | The image bundles both — re-pull, since the bundled binaries might have been overridden by a previous `--volume` mount. |
| Platform checks report "could not be measured", or the trust line says `no repository identity` | Pass `-e GH_TOKEN` for the platform checks. A missing identity means git cannot read the repository: mount it at `/repo` (the only path `safe.directory` covers) and check that it has a GitHub `origin` remote. |
