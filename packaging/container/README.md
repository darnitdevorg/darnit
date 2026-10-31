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
# Run darnit on the current directory: `darnit harness /repo`, the end-to-end
# audit with model calls (ANTHROPIC_API_KEY) and platform checks (GH_TOKEN)
docker run --rm -e ANTHROPIC_API_KEY -e GH_TOKEN -v "$PWD:/repo" ghcr.io/darnitdevorg/darnit:latest

# MCP server on stdio, for agent clients
docker run --rm -i -e GH_TOKEN -v "$PWD:/repo" ghcr.io/darnitdevorg/darnit:latest serve

# Deterministic audit without model calls, for testing
docker run --rm -v "$PWD:/repo" ghcr.io/darnitdevorg/darnit:latest audit /repo

# Print the bundled version
docker run --rm ghcr.io/darnitdevorg/darnit:latest --version
```

The entrypoint is the `darnit` CLI and the default command is `harness /repo`; the image's `WORKDIR` is `/repo`. Without `ANTHROPIC_API_KEY` the harness stops with a setup error, exit 2.

There is no shell. Run another program in the image with `--entrypoint` (for example `--entrypoint git`). For a shell while debugging, build with `--build-arg RUNTIME_BASE=gcr.io/distroless/cc-debian12:debug-nonroot` and run `--entrypoint /busybox/sh`. Git hooks and git credential helpers with arguments do not work in the image; see [`docs/install/container.md`](../../docs/install/container.md#no-shell-inside).

## Image contents

Built from source by this directory's Dockerfile: a release image from its tagged commit, `:edge` from `main`. The packages come from `uv.lock` (frozen); nothing about darnit is installed from PyPI.

- **Base**: `gcr.io/distroless/cc-debian12:nonroot`, pinned by digest (glibc, CA certificates; no shell or package manager)
- **Python**: 3.12 from uv's python-build-standalone builds (`uv python install`), without the parts darnit never loads (Tcl/Tk, IDLE, the embedding library, headers)
- **darnit**: `darnit-mcp`, `darnit-core`, `darnit-baseline`, `darnit-gittuf`, `darnit-reproducibility` and `darnit-csl`, non-editable, without development dependencies. The build fails if `darnit-hello`, `darnit-testchecks`, `pytest` or `ruff` reaches the venv.
- **Downloaded tools**, pinned by version and sha256 per architecture (the Dockerfile notes where each pin came from): `zizmor`, `gittuf`, `gh`; and `uv`, by image digest
- **Debian 12 tools**: `git` (with `git-remote-http` for https), `grep`, `gpg`, `ssh-keygen`. Not pinned to versions, so a rebuild picks up security updates. The build runs `ldd` on every ELF file the image runs and copies each shared library the base lacks from the same Debian release (36 libraries, about 16 MB, 28 of them for git's https transport); an unresolved library fails the build. The dpkg status of each package a file came from is copied to `/var/lib/dpkg/status.d/`, so image scanners see them.
- **Git**: `safe.directory=/repo` in `/etc/gitconfig`. The mounted repository belongs to the host user, not the container user; without the setting git refuses it and the audit loses the repository identity (#586). It turns off git's ownership check for `/repo`, so mount only repositories you would run git in natively; #617 tracks hardening darnit's own git calls.
- **Runtime user**: `nonroot` (uid 65532)
- **Version label**: `org.opencontainers.image.version`, from the `IMAGE_VERSION` build arg (the release version, or the commit sha for `:edge`)

What's deliberately **not** in the image:
- A shell, a package manager, or pip in the venv
- Build toolchain (gcc, make, etc.)
- Apt, pip or uv caches

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
docker run --rm -e ANTHROPIC_API_KEY -e GH_TOKEN -v "$PWD:/repo" darnit-local

# The checks CI runs on pull requests that touch the image
scripts/container-image-smoke.sh darnit-local
```

The image contains the checkout's packages, local changes included. `--build-arg IMAGE_VERSION=<version>` sets the version label (default `dev`). To bump a pinned tool, change its version and sha256 build args together. `--build-arg RUNTIME_BASE=gcr.io/distroless/cc-debian12:debug-nonroot` builds a variant with a busybox shell at `/busybox/sh`, for debugging only.

## Recovery from a bad image

PyPI versions are immutable, container tags are not. If a published image is broken:

- For **`:vX.Y.Z` tags** (immutable in spirit): do **not** repush. Roll forward to `vX.Y.Z+1`. The bad tag stays for historical resolution.
- For **`:latest`**: the next stable release will move it forward automatically.

Detailed procedures: [`packaging/RECOVERY.md`](../RECOVERY.md#container-image).

## See also

- [Container image contract](../../specs/012-packaging-distribution/contracts/container-image-contract.md) — full spec
- [Release workflow](../../.github/workflows/release.yml) — where the image is built and signed
- [User-facing install doc](../../docs/install/container.md)
