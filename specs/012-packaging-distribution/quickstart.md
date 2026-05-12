# Quickstart: Installing & Verifying darnit

How to install darnit through each released channel and how to verify the artifact you got is signed by the project.

The decision tree at the top picks the right channel for your situation; the per-channel sections below give the exact commands. All examples assume a release version of `0.1.0` — substitute the real version you want.

---

## Pick your channel

| Your situation | Use this channel |
|---|---|
| You write Python and have Python 3.11+ already installed. | [PyPI / pipx](#pypi--pipx) |
| You run audits from CI/CD pipelines. | [Container image](#container-image) |
| You're on macOS or Linux with Homebrew installed and want one-command install. | [Homebrew](#homebrew) |
| You want a relocatable binary with no Python toolchain to manage. | [Standalone binary](#standalone-binary) |
| You use Claude Code and want darnit available as a plugin. | [Claude Code plugin](#claude-code-plugin) |
| You want to build your own darnit-compatible compliance implementation. | [Third-party plugin guide](#third-party-plugin) |

---

## PyPI / pipx

### Install

```bash
# Direct pip (any virtualenv, any project)
pip install darnit-mcp==0.1.0

# pipx (isolated, recommended for end users)
pipx install darnit-mcp==0.1.0

# uv (modern, fast)
uv tool install darnit-mcp==0.1.0
```

After install, `darnit --version` should print `0.1.0`.

### Pre-releases

Pre-releases are published to TestPyPI. To install one:

```bash
pip install --index-url https://test.pypi.org/simple/ \
            --extra-index-url https://pypi.org/simple/ \
            --pre darnit-mcp==0.1.0rc1
```

### Verify the Sigstore attestation

```bash
pip install sigstore
python -m sigstore verify identity \
    --bundle darnit_mcp-0.1.0-py3-none-any.whl.sigstore.json \
    --cert-identity-regexp '^https://github\.com/kusari-oss/darnit/' \
    --cert-oidc-issuer https://token.actions.githubusercontent.com \
    darnit_mcp-0.1.0-py3-none-any.whl
```

The signing identity should match the `release.yml` workflow at the tagged commit.

---

## Container image

### Run a one-shot audit

```bash
docker run --rm -v "$PWD:/repo" ghcr.io/kusari-oss/darnit:v0.1.0 audit
```

For `podman`, substitute `podman` for `docker` — same flags.

### Pin or float

| Tag | Stability |
|---|---|
| `:v0.1.0` | Immutable; points at one specific release. |
| `:latest` | Latest stable. |
| `:v0.1.0rc1` | Pre-release; never moves under `:latest`. |
| `:edge` | Daily build of `main`; unsigned; for testing only. |

### Verify the cosign signature

```bash
cosign verify ghcr.io/kusari-oss/darnit:v0.1.0 \
    --certificate-identity-regexp '^https://github\.com/kusari-oss/darnit/' \
    --certificate-oidc-issuer https://token.actions.githubusercontent.com
```

### Download the SBOM

```bash
cosign download attestation ghcr.io/kusari-oss/darnit:v0.1.0 \
    | jq -r '.payload' | base64 -d | jq '.predicate' > darnit-sbom.spdx.json
```

---

## Homebrew

### Install

```bash
brew tap kusari-oss/tap
brew install darnit
darnit --version
```

The formula downloads a pre-built binary from the GitHub release. No source build, no Python compile.

### Upgrade

`brew upgrade darnit` picks up new stable releases automatically as the tap is updated.

---

## Standalone binary

### Download

Pick your platform from a GitHub release page:

```bash
curl -LO https://github.com/kusari-oss/darnit/releases/download/v0.1.0/darnit-0.1.0-macos-arm64
chmod +x darnit-0.1.0-macos-arm64
sudo mv darnit-0.1.0-macos-arm64 /usr/local/bin/darnit
darnit --version
```

Available platforms: `macos-arm64`, `linux-arm64`, `linux-amd64`. Intel Macs are not supported — use `pip`/`pipx` or the Linux container image instead.

### Prerequisite

The binary is a `shiv` zipapp. It requires **Python 3.11 or 3.12** on PATH at first run (to extract). Subsequent runs are cached and faster.

### Verify the cosign blob signature

Download the signature bundle alongside the binary:

```bash
curl -LO https://github.com/kusari-oss/darnit/releases/download/v0.1.0/darnit-0.1.0-macos-arm64.sigstore

cosign verify-blob \
    --bundle darnit-0.1.0-macos-arm64.sigstore \
    --certificate-identity-regexp '^https://github\.com/kusari-oss/darnit/' \
    --certificate-oidc-issuer https://token.actions.githubusercontent.com \
    darnit-0.1.0-macos-arm64
```

---

## Claude Code plugin

### Install

Download `darnit-claude-plugin-0.1.0.zip` from the GitHub release page, then install it into your Claude Code workspace per Claude Code's plugin instructions. Once installed, four model-invoked agentic skills become available (no slash commands to type — Claude picks the right skill based on your request):

- `darnit-audit` — Claude runs a compliance audit when you ask for one
- `darnit-data` — Claude collects missing project data / context when you ask to "set up darnit"
- `darnit-comply` — Claude runs the full audit + remediate pipeline
- `darnit-remediate` — Claude applies automated fixes for failing controls

### Prerequisite

The plugin invokes `uvx darnit-mcp` (preferred) or `pipx run darnit-mcp` (fallback). At least one of these MUST be on PATH:

- **`uv`** (provides `uvx`) — https://docs.astral.sh/uv/
- **`pipx`** — https://pipx.pypa.io/

If neither is installed, the plugin emits an actionable error naming both options.

---

## Third-party plugin

If you want to ship your own compliance implementation that darnit discovers automatically, follow the [packaging guide](../../docs/packaging-plugins.md). The repository ships a worked example at `packages/darnit-hello/` you can copy as a starting point.

---

## Verifying every install path

Whatever channel you used, `darnit --version` should print the version you installed. If it doesn't, you got a stale or wrong artifact — verify the signature using the per-channel commands above before trusting it.

For partial-release situations (a stable tag was published but one channel failed), check the upstream repo's [release-failure issues](https://github.com/kusari-oss/darnit/labels/release-failure) — the failed channel will be named there.
