# Contract: Standalone Binary Artifacts

## Artifact set per Release

Three artifacts, one per `(os, arch)`:

| Filename | Platform | Built on |
|---|---|---|
| `darnit-<version>-macos-arm64` | macOS arm64 (Apple Silicon) | `macos-14` runner |
| `darnit-<version>-linux-arm64` | Linux arm64 | `ubuntu-22.04-arm` runner |
| `darnit-<version>-linux-amd64` | Linux amd64 | `ubuntu-22.04` runner |

macOS amd64 (Intel) is **out of scope** per the spec — Apple has fully transitioned to Apple Silicon. Intel Mac users install via `pip install` or run the Linux/amd64 container image under Rosetta-equivalent emulation.

A missing in-scope platform fails the Release (no partial binary set).

## Builder

`shiv` (decision recorded in `research.md` §1).

```bash
shiv \
  --console-script darnit \
  --python "/usr/bin/env python3.11" \
  --compressed \
  --output-file darnit-<version>-<os>-<arch> \
  darnit-mcp==<version>
```

The shiv zipapp expects Python ≥3.11 on PATH at runtime. The binary refuses to run on older Python with a clear error message; the install docs name this prerequisite explicitly.

## Naming

- Stable: `darnit-<X.Y.Z>-<os>-<arch>`
- Pre-release: `darnit-<X.Y.Z>rc<N>-<os>-<arch>` (also marked pre-release in the GitHub Release).

## Signing

Each binary is signed as a detached blob with cosign keyless:

```bash
cosign sign-blob --yes --bundle darnit-<version>-<os>-<arch>.sigstore darnit-<version>-<os>-<arch>
```

The `.sigstore` bundle is attached to the same GitHub Release alongside the binary.

## SBOM

`syft` runs against the shiv zipapp's contents (which expand to a known site-packages tree):

```bash
syft darnit-<version>-<os>-<arch> -o spdx-json > darnit-<version>-<os>-<arch>.sbom.spdx.json
```

The SBOM is attested via GitHub Artifact Attestations:

```bash
gh attestation create --predicate-type https://spdx.dev/Document \
  --predicate darnit-<version>-<os>-<arch>.sbom.spdx.json \
  darnit-<version>-<os>-<arch>
```

## GitHub Release attachment

For stable tags, the GitHub Release is created with `--latest` and binaries + their `.sigstore` bundles + their SBOMs attached. For pre-releases, `--prerelease` is set instead, and `:latest` movement is suppressed.

## Smoke test

For each platform on its matching runner:

```bash
chmod +x darnit-<version>-<os>-<arch>
./darnit-<version>-<os>-<arch> --version | grep "<version>"

cosign verify-blob \
  --bundle darnit-<version>-<os>-<arch>.sigstore \
  --certificate-identity-regexp '^https://github.com/kusari-oss/darnit/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  darnit-<version>-<os>-<arch>
```

Both must succeed.

## What this contract does not promise

- **Windows binaries** are not produced. Out of scope per spec.
- **Linux musl** (Alpine) binaries are not produced. tree-sitter native bindings do not build cleanly on musl; users on Alpine must use the container image or build from source.
- **A binary that requires no Python on the host**. `shiv` zipapps still need a Python interpreter ≥3.11 to extract on first run. Documenting this as a prerequisite is mandatory in `docs/install/binary.md`.
