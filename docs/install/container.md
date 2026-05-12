# Install darnit via the container image

This is the recommended install path for **CI/CD pipelines** and any environment that doesn't want to manage a Python toolchain. Examples assume version `0.1.0` — substitute the version you want.

## Run a one-shot audit

```bash
docker run --rm -v "$PWD:/repo" ghcr.io/kusari-oss/darnit:v0.1.0 audit
```

For `podman` users, substitute `podman` for `docker` — same flags.

## Tags

| Tag | Stability |
|---|---|
| `:v0.1.0` | Immutable; points at one specific release. **Use this in CI.** |
| `:latest` | Latest stable. Moves on every stable release. |
| `:v0.1.0rc1` | Pre-release; never moves under `:latest`. |
| `:edge` | Rolling build of `main`; **unsigned**, for testing only. |

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
| `mcp` | Forwarded to `darnit-mcp` (stdio MCP server) |
| Anything else | Executed directly (escape hatch for `sh`, `gh`, `git`, etc.) |

## Verify the image signature

Every release tag is signed with cosign keyless OIDC. The signing identity binds the image to the `release.yml` workflow in `kusari-oss/darnit`.

```bash
cosign verify ghcr.io/kusari-oss/darnit:v0.1.0 \
  --certificate-identity-regexp '^https://github\.com/kusari-oss/darnit/\.github/workflows/release\.yml@' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

A passing verification proves:
- The image bytes match what was signed.
- The signer was the `release.yml` workflow in `kusari-oss/darnit`.
- The OIDC issuer was GitHub Actions.

The `:edge` rolling build is **not** signed.

## Download the SBOM

Each signed image has an SPDX-JSON SBOM attached as a cosign attestation:

```bash
cosign download attestation ghcr.io/kusari-oss/darnit:v0.1.0 \
  | jq -r '.payload' | base64 -d | jq '.predicate' > darnit-sbom.spdx.json
```

Verify the SBOM's signing identity at the same time:

```bash
cosign verify-attestation ghcr.io/kusari-oss/darnit:v0.1.0 \
  --type spdx \
  --certificate-identity-regexp '^https://github\.com/kusari-oss/darnit/\.github/workflows/release\.yml@' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

## Image contents

- **Base**: `python:3.12-slim-bookworm`
- **darnit**: installed from PyPI at the pinned version
- **Bundled CLIs**: `git`, `gh` (the GitHub CLI — many controls invoke it)
- **Runtime user**: non-root (`darnit`, uid 10001)
- **Working directory**: `/repo` (so `-v "$PWD:/repo"` is the conventional mount)

## CI usage examples

### GitHub Actions

```yaml
jobs:
  audit:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
      - name: Run darnit audit
        run: |
          docker run --rm \
            -v "$PWD:/repo" \
            -v "${{ github.workspace }}/.audit:/audit-out" \
            ghcr.io/kusari-oss/darnit:v0.1.0 \
            audit --output /audit-out/report.md
```

### GitLab CI

```yaml
audit:
  image: ghcr.io/kusari-oss/darnit:v0.1.0
  script:
    - darnit audit
```

## Prerequisites

- A container runtime: **Docker** ≥ 20.10 or **Podman** ≥ 4.0
- Network access to `ghcr.io` (and PyPI, indirectly, for the build phase only — runtime doesn't fetch from PyPI)
- For multi-arch pulls on a non-native architecture: **QEMU** (`docker run --platform`)

## Size budget

The compressed image targets **300 MiB**. Each release records the measured size in its release notes; a release that exceeds the target by >15% over the previous release surfaces a workflow warning.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `Error response from daemon: manifest unknown` | The tag does not exist. Check `gh release list --repo kusari-oss/darnit` for valid versions. |
| `exec format error` on Apple Silicon | The image was pulled for the wrong architecture. Use `docker pull --platform linux/arm64 ...` or let Docker pick automatically. |
| `cosign verify` fails with "no matching signatures" | You're trying to verify an `:edge` image (unsigned) or the tag was published before this signing scheme. |
| The audit complains about missing `git`/`gh` | The image bundles both — re-pull, since the bundled binaries might have been overridden by a previous `--volume` mount. |
