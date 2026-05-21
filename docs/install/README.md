# Installing darnit

darnit ships through five channels. Pick the one that matches your situation; each has its own page below with the exact commands and a verification recipe.

## Quick decision tree

| You are… | Use this channel | Page |
|---|---|---|
| A Python developer with Python 3.11 or 3.12 installed | **PyPI / pipx / uv** | [pypi.md](pypi.md) |
| Running darnit from a CI/CD pipeline | **Container image** (GHCR) | [container.md](container.md) |
| On macOS arm64 or Linux with Homebrew | **Homebrew** | [homebrew.md](homebrew.md) |
| Want a self-contained binary, no package manager | **Standalone binary** | [binary.md](binary.md) |
| A Claude Code user who wants `/darnit:darnit-audit` and the MCP server in one install | **Claude Code plugin** | [claude-code-plugin.md](claude-code-plugin.md) |
| Want to try an unreleased feature, contribute, or run a specific branch | **From source** (clone + `uv tool install --editable`) | [from-source.md](from-source.md) |
| Building your own darnit-compatible compliance plugin | (not an install path — see [`docs/packaging-plugins.md`](../packaging-plugins.md)) | — |

If you're not sure: **`pipx install darnit-mcp`** works for most users and is the simplest path. The other channels exist because real-world environments have constraints (no Python, locked-down CI runners, brew-only macOS workflows, agent-first usage).

## What's the same across all channels

- **One `darnit` command** on PATH after install. Use `darnit audit`, `darnit remediate`, `darnit list-controls`, etc.
- **Same version, same artifact identity.** A release tag (`v0.1.0`) produces a Sigstore-signed PyPI wheel, a cosign-signed container image, four cosign-signed binaries, a Homebrew formula bump, and a Claude Code plugin zip — all derived from the same tagged commit. `darnit --version` reports the same string regardless of which channel installed it.
- **Verifiable signing identity.** Every channel ships with a signature you can verify back to `kusari-oss/darnit`'s `release.yml` workflow. The exact verification command differs per channel; each page has it.

## What differs

| | PyPI | Container | Homebrew | Binary | Claude plugin |
|---|---|---|---|---|---|
| Needs Python on the host | ✅ 3.11+ | ❌ bundled | ❌ runs the binary | ✅ 3.11+ for shiv | ✅ for `uvx`/`pipx` |
| Needs a container runtime | ❌ | ✅ Docker/Podman | ❌ | ❌ | ❌ |
| Bundles `git` + `gh` | ❌ install separately | ✅ | ❌ install separately | ❌ install separately | ❌ (caller's env) |
| Auto-updates | `pip install -U` | `:latest` tag | `brew upgrade` | manual download | plugin update |
| Pre-release support | ✅ TestPyPI | ✅ `-rc` tags | ❌ stable only | ✅ marked pre-release | ❌ stable only |
| Multi-arch | ❌ pure-Python | ✅ amd64+arm64 | ✅ on supported OS+arch | ✅ macOS arm64, Linux amd64+arm64 | n/a |
| Apple Silicon (macOS arm64) | ✅ | ✅ | ✅ | ✅ | ✅ |
| Intel Macs (macOS amd64) | ✅ | ✅ (via emulation) | ❌ out of scope | ❌ out of scope | ✅ |
| Windows | partial (untested) | ✅ via WSL2 or container runtime | ❌ | ❌ | partial |

## Verifying signatures

Every install page has a "Verify" section with the exact command. The common shape:

```bash
# PyPI (Sigstore)
python -m sigstore verify identity \
  --bundle <bundle> \
  --cert-identity-regexp '^https://github\.com/kusari-oss/darnit/' \
  --cert-oidc-issuer https://token.actions.githubusercontent.com \
  <artifact>

# Container / binary (cosign)
cosign verify[-blob] \
  --certificate-identity-regexp '^https://github\.com/kusari-oss/darnit/' \
  --certificate-oidc-issuer https://token.actions.githubusercontent.com \
  <artifact>
```

If any of these fail with "identity mismatch", **do not trust the artifact** — it may be tampered with or from an unofficial source.

## Partial releases

Occasionally a release will succeed on some channels and fail on others (PyPI succeeded, container build failed, etc.). When that happens:

- The successful channels stay published — they were signed correctly.
- A `release-failure` issue appears on the [upstream repo](https://github.com/kusari-oss/darnit/labels/release-failure) naming the failed channel.
- The release notes include a per-channel timing table; channels that failed or exceeded the SC-007 budget are flagged.

If you're trying to use a channel that's behind, check the latest release notes and the `release-failure` label.

## See also

- [Third-party plugin packaging guide](../packaging-plugins.md) — building your own darnit-compatible plugin
- [Maintainer release runbook](../../packaging/README.md) — for the team cutting releases
- [Recovery procedures](../../packaging/RECOVERY.md) — per-channel partial-failure recovery
