# Install darnit via Homebrew

For **macOS arm64 (Apple Silicon)** and **Linux** users with [Homebrew](https://brew.sh/) installed. The formula downloads the [standalone binary](binary.md) attached to each darnit GitHub release — no source build, no Python toolchain needed.

Examples assume version `0.1.0` — `brew` always installs the current stable.

## Install

```bash
brew tap kusari-oss/tap
brew install darnit

darnit --version
```

## Upgrade

```bash
brew update
brew upgrade darnit
```

The Homebrew tap auto-updates within 30 minutes of each stable release. If `brew upgrade` doesn't see a new version you expected, check [release-failure issues](https://github.com/kusari-oss/darnit/labels/release-failure) on the upstream repo.

## Uninstall

```bash
brew uninstall darnit
brew untap kusari-oss/tap   # optional
```

## Supported platforms via Homebrew

- **macOS arm64** (Apple Silicon) ✓
- **Linux arm64** ✓
- **Linux amd64** ✓

**Intel Macs are not supported via Homebrew.** Apple has fully transitioned to Apple Silicon. If you're on an Intel Mac, install via [`pipx`](pypi.md) or run the [Linux amd64 container image](container.md) under emulation.

## What gets installed

`brew install darnit` puts a single `darnit` executable on your `$PATH`. That executable is the same [shiv-built standalone binary](binary.md) you'd download manually from the GitHub release. It bundles `darnit-mcp` and all its Python deps.

You still need on your PATH:
- **Python 3.11 or 3.12** (the shiv shebang depends on it for first-run extraction)
- **`git`** and the **[`gh` CLI](https://cli.github.com/)** — most darnit audit controls shell out to them

Homebrew auto-installs Python 3.12 as a dependency of the formula. `git` is pre-installed on macOS; for Linux brew users, install via your distro's package manager or via `brew install git gh`.

## Verify the install

The formula's own `brew test darnit` invokes `darnit --version` and asserts the output matches the formula's pinned version. To run it manually:

```bash
brew test darnit
```

## How this differs from the direct binary download

The Homebrew formula:
- Downloads exactly the same binary as the [GitHub release asset](binary.md).
- Verifies the SHA-256 against the formula's recorded value (the formula is auto-generated from the release's checksums).
- Installs into Homebrew's prefix (`/opt/homebrew/bin/darnit` on macOS arm64, `/home/linuxbrew/.linuxbrew/bin/darnit` on Linux).
- Provides `brew upgrade` for clean updates.

If you want to verify the binary's [cosign signature](binary.md#verify-the-cosign-signature) independently, follow the binary-download doc — the brew-installed binary lives at `$(brew --prefix darnit)/bin/darnit` and is byte-identical to the downloaded asset.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `brew tap kusari-oss/tap` fails with 404 | The tap repository may not exist yet, or you typo'd the org. Confirm `kusari-oss/homebrew-tap` exists on GitHub. |
| `brew install darnit` succeeds but `darnit --version` says command not found | Linux brew often isn't on your shell's PATH by default. Run `eval "$(/home/linuxbrew/.linuxbrew/bin/brew shellenv)"` and add that line to your shell rc file. |
| `darnit --version` reports the previous version after `brew upgrade` | Brew's formula cache may be stale. Run `brew update` first, then `brew upgrade darnit`. |
| Formula doesn't bump within 30 minutes of a stable release | A release-failure issue should exist; see [upstream `release-failure` label](https://github.com/kusari-oss/darnit/labels/release-failure). |
