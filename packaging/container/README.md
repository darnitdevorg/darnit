# darnit container image

Official darnit container image published to `ghcr.io/darnitdevorg/darnit` on every release tag.

> End-user install documentation: [`docs/install/container.md`](../../docs/install/container.md). This README sits next to the Dockerfile and is the source for the image's overview on GHCR.

## Pull

```bash
# Pin to a specific release
docker pull ghcr.io/darnitdevorg/darnit:v0.1.0

# Latest stable
docker pull ghcr.io/darnitdevorg/darnit:latest

# Pre-release (not promoted to :latest)
docker pull ghcr.io/darnitdevorg/darnit:v0.1.0rc1

# Rolling build of main, from source (unsigned)
docker pull ghcr.io/darnitdevorg/darnit:edge
```

## Run

```bash
# Audit the current directory (GH_TOKEN lets the platform checks run)
docker run --rm -v "$PWD:/repo" -e GH_TOKEN ghcr.io/darnitdevorg/darnit:latest audit

# Run as the MCP server (stdio)
docker run --rm -i ghcr.io/darnitdevorg/darnit:latest mcp

# Print the bundled version
docker run --rm ghcr.io/darnitdevorg/darnit:latest --version
```

The image's `WORKDIR` is `/repo`. The entrypoint dispatches the first arg to `darnit` (for `audit`/`remediate`/`list-controls`/`plan`/`profiles`/`validate`/`--version`/`--help`), to `darnit serve` for `mcp`, or executes the user's command directly otherwise.

## Image contents

Built from source by this directory's Dockerfile: a release image from its tagged commit, `:edge` from `main`. The packages come from `uv.lock` (frozen); nothing about darnit is installed from PyPI.

- **Base**: `python:3.12-slim-bookworm`
- **darnit**: `darnit-mcp`, `darnit-core`, `darnit-baseline`, `darnit-gittuf`, `darnit-reproducibility` and `darnit-csl`, non-editable, without development dependencies. The build fails if `darnit-hello`, `darnit-testchecks`, `pytest` or `ruff` reaches the venv.
- **Tools**, each pinned (downloads also by sha256 per architecture; the Dockerfile notes where each pin came from): `zizmor`, `gittuf`, `gpg` (gnupg), `ssh-keygen` (openssh-client), `git`, `gh`
- **Git**: `safe.directory=/repo` in the system configuration. The mounted repository belongs to the host user, not uid 10001; without the setting git refuses it and the audit loses the repository identity (#586). It turns off git's ownership check for `/repo`, so mount only repositories you would run git in natively; #617 tracks hardening darnit's own git calls.
- **Runtime user**: `darnit` (uid 10001), non-root
- **Version label**: `org.opencontainers.image.version`, from the `IMAGE_VERSION` build arg (the release version, or the commit sha for `:edge`)

What's deliberately **not** in the image:
- uv, or a pip in the venv (the runtime stage copies the pre-built venv; no in-place installs)
- Build toolchain (gcc, make, etc.)
- Apt, pip or uv caches
- Shell history

## Platforms

The release image is multi-arch:
- `linux/amd64`
- `linux/arm64`

`docker pull` automatically selects the right manifest for your host.

## Signatures

Every release tag (stable and pre-release) is signed with cosign keyless OIDC.

```bash
cosign verify ghcr.io/darnitdevorg/darnit:v0.1.0 \
  --certificate-identity-regexp '^https://github\.com/darnitdevorg/darnit/\.github/workflows/release\.yml@' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

The `:edge` rolling build is **not** signed — it's for development only.

## SBOM

Each signed image has an SPDX-JSON SBOM attached via cosign attestation:

```bash
cosign download attestation ghcr.io/darnitdevorg/darnit:v0.1.0 \
  | jq -r '.payload' | base64 -d | jq '.predicate' > darnit-sbom.spdx.json
```

## Size

Compressed-size target: 300 MB (soft). The release workflow records the size in each release's notes and emits a workflow warning if growth exceeds 15% vs. the previous release.

## Building locally

From the repository root:

```bash
docker build -f packaging/container/Dockerfile -t darnit-local .
docker run --rm -v "$PWD:/repo" -e GH_TOKEN darnit-local audit

# The checks CI runs on pull requests that touch the image
scripts/container-image-smoke.sh darnit-local
```

The image contains the checkout's packages, local changes included. `--build-arg IMAGE_VERSION=<version>` sets the version label (default `dev`). To bump a pinned tool, change its version and sha256 build args together.

## Recovery from a bad image

PyPI versions are immutable, container tags are not. If a published image is broken:

- For **`:vX.Y.Z` tags** (immutable in spirit): do **not** repush. Roll forward to `vX.Y.Z+1`. The bad tag stays for historical resolution.
- For **`:latest`**: the next stable release will move it forward automatically.

Detailed procedures: [`packaging/RECOVERY.md`](../RECOVERY.md#container-image).

## See also

- [Container image contract](../../specs/012-packaging-distribution/contracts/container-image-contract.md) — full spec
- [Release workflow](../../.github/workflows/release.yml) — where the image is built and signed
- [User-facing install doc](../../docs/install/container.md)
