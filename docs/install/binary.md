# Install darnit from a standalone binary

Direct binary downloads attached to each GitHub Release. The same binaries back the [Homebrew formula](homebrew.md); use this page if you don't want a package manager.

Examples assume version `0.1.0` — substitute the version you want.

## Download

| Platform | Asset |
|---|---|
| macOS arm64 (Apple Silicon) | `darnit-0.1.0-macos-arm64` |
| macOS amd64 (Intel) | `darnit-0.1.0-macos-amd64` |
| Linux arm64 | `darnit-0.1.0-linux-arm64` |
| Linux amd64 | `darnit-0.1.0-linux-amd64` |

```bash
# macOS arm64
curl -LO https://github.com/kusari-oss/darnit/releases/download/v0.1.0/darnit-0.1.0-macos-arm64
chmod +x darnit-0.1.0-macos-arm64
sudo mv darnit-0.1.0-macos-arm64 /usr/local/bin/darnit

darnit --version
```

Substitute the `darnit-0.1.0-<os>-<arch>` filename for your platform.

## Prerequisite

The binary is a [`shiv`](https://shiv.readthedocs.io/) zipapp. **Python 3.11 or 3.12 must be on PATH** when you run it the first time so shiv can extract its bundled site-packages into a per-user cache. Subsequent runs are cached and fast.

If you don't have Python on the host, use the [container image](container.md) or install via [pipx](pypi.md).

## Verify the cosign signature

Every binary asset is signed with cosign keyless OIDC, bound to the canonical `release.yml` workflow in `kusari-oss/darnit`. Download the `.sigstore` bundle alongside the binary:

```bash
curl -LO https://github.com/kusari-oss/darnit/releases/download/v0.1.0/darnit-0.1.0-macos-arm64.sigstore

cosign verify-blob \
  --bundle darnit-0.1.0-macos-arm64.sigstore \
  --certificate-identity-regexp '^https://github\.com/kusari-oss/darnit/\.github/workflows/release\.yml@' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  darnit-0.1.0-macos-arm64
```

A passing verification proves:
- The binary bytes match exactly what was signed.
- The signer was the `release.yml` workflow in `kusari-oss/darnit`.
- The OIDC issuer was GitHub Actions.

## SBOM

Each binary ships with an SPDX-JSON SBOM as a sibling file (`darnit-<...>.sbom.spdx.json`) and a [GitHub Artifact Attestation](https://docs.github.com/en/actions/security-guides/using-artifact-attestations-to-establish-provenance-for-builds) that binds the SBOM to the binary.

Download the SBOM directly:

```bash
curl -LO https://github.com/kusari-oss/darnit/releases/download/v0.1.0/darnit-0.1.0-macos-arm64.sbom.spdx.json
```

Verify the attestation via `gh`:

```bash
gh attestation verify \
  --repo kusari-oss/darnit \
  darnit-0.1.0-macos-arm64
```

## What's not in the binary

- **Python 3.11/3.12** — must be present on the host (prerequisite above).
- **`git` and `gh` CLIs** — some darnit controls invoke them at runtime. If you only have the binary, install `git` and the [GitHub CLI](https://cli.github.com/) separately, or use the [container image](container.md) which bundles them.
- **Windows support** — Windows binaries are not produced (out of scope; darnit's controls assume POSIX tooling).
- **Linux musl/Alpine** — tree-sitter native bindings don't build cleanly on musl; use the container image or `pip install` instead.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `bash: ./darnit-0.1.0-...: No such file or directory` (on Linux) | The shiv shebang points at `python3.11`. Confirm `python3.11` is on PATH (`which python3.11`). |
| First run takes 10+ seconds | Expected — shiv is extracting site-packages into `~/.shiv/` on first run. Subsequent runs are fast. |
| `cosign verify-blob` fails with "no matching signatures" | Wrong binary or wrong `.sigstore` bundle. Both files must be from the same release. |
| Audit complains about missing `git` or `gh` | The binary doesn't bundle them. Install them via your platform's package manager. |
