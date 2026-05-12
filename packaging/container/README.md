# darnit container image

Official darnit container image published to `ghcr.io/kusari-oss/darnit` on every release tag.

> End-user install documentation: [`docs/install/container.md`](../../docs/install/container.md). This README sits next to the Dockerfile and is the source for the image's overview on GHCR.

## Pull

```bash
# Pin to a specific release
docker pull ghcr.io/kusari-oss/darnit:v0.1.0

# Latest stable
docker pull ghcr.io/kusari-oss/darnit:latest

# Pre-release (not promoted to :latest)
docker pull ghcr.io/kusari-oss/darnit:v0.1.0rc1

# Rolling build of main (unsigned)
docker pull ghcr.io/kusari-oss/darnit:edge
```

## Run

```bash
# Audit the current directory
docker run --rm -v "$PWD:/repo" ghcr.io/kusari-oss/darnit:latest audit

# Run as the MCP server (stdio)
docker run --rm -i ghcr.io/kusari-oss/darnit:latest mcp

# Print the bundled version
docker run --rm ghcr.io/kusari-oss/darnit:latest --version
```

The image's `WORKDIR` is `/repo`. The entrypoint dispatches the first arg to `darnit` (for `audit`/`remediate`/`list-controls`/`plan`/`profiles`/`validate`/`--version`/`--help`), to `darnit-mcp` for `mcp`, or executes the user's command directly otherwise.

## Image contents

- **Base**: `python:3.12-slim-bookworm`
- **darnit**: installed from PyPI via `pip install darnit-mcp==<version>` (the version is recorded as the `org.opencontainers.image.version` OCI label)
- **CLIs**: `git`, `gh` (GitHub CLI from `cli.github.com`)
- **Runtime user**: `darnit` (uid 10001), non-root

What's deliberately **not** in the image:
- `pip` from a build context (the runtime stage has the venv pre-built; no in-place installs)
- Build toolchain (gcc, make, etc.)
- Apt or pip caches
- Shell history

## Platforms

The release image is multi-arch:
- `linux/amd64`
- `linux/arm64`

`docker pull` automatically selects the right manifest for your host.

## Signatures

Every release tag (stable and pre-release) is signed with cosign keyless OIDC.

```bash
cosign verify ghcr.io/kusari-oss/darnit:v0.1.0 \
  --certificate-identity-regexp '^https://github\.com/kusari-oss/darnit/\.github/workflows/release\.yml@' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

The `:edge` rolling build is **not** signed — it's for development only.

## SBOM

Each signed image has an SPDX-JSON SBOM attached via cosign attestation:

```bash
cosign download attestation ghcr.io/kusari-oss/darnit:v0.1.0 \
  | jq -r '.payload' | base64 -d | jq '.predicate' > darnit-sbom.spdx.json
```

## Size

Compressed-size target: 300 MB (soft). The release workflow records the size in each release's notes and emits a workflow warning if growth exceeds 15% vs. the previous release.

## Building locally

The image is normally built by the release pipeline, but you can build it locally for testing:

```bash
# Build for the current platform only. VERSION must be a real darnit-mcp
# release on PyPI (or TestPyPI if you adjust the install command).
docker build \
  --build-arg VERSION=0.1.0 \
  -t darnit-local \
  -f packaging/container/Dockerfile \
  .

docker run --rm -v "$PWD:/repo" darnit-local audit
```

The `--build-arg VERSION` is required — the Dockerfile refuses to build without an explicit pinned version.

## Recovery from a bad image

PyPI versions are immutable, container tags are not. If a published image is broken:

- For **`:vX.Y.Z` tags** (immutable in spirit): do **not** repush. Roll forward to `vX.Y.Z+1`. The bad tag stays for historical resolution.
- For **`:latest`**: the next stable release will move it forward automatically.

Detailed procedures: [`packaging/RECOVERY.md`](../RECOVERY.md#container-image).

## See also

- [Container image contract](../../specs/012-packaging-distribution/contracts/container-image-contract.md) — full spec
- [Release workflow](../../.github/workflows/release.yml) — where the image is built and signed
- [User-facing install doc](../../docs/install/container.md)
