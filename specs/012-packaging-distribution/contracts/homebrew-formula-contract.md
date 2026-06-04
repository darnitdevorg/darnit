# Contract: Homebrew Formula

## Scope

Renders and publishes `Formula/darnit.rb` in the `kusari-oss/homebrew-tap` repository on each **stable** release. Pre-release tags do not touch the formula (per clarification Q2).

## Tap repository layout

```
kusari-oss/homebrew-tap/
├── .github/
│   └── workflows/
│       └── bump-formula.yml      # Listens for repository_dispatch
└── Formula/
    └── darnit.rb                 # Rendered from packaging/homebrew/darnit.rb.tmpl
```

The tap repo is owned by the same org and has CODEOWNERS restricting writes to release maintainers.

## Cross-repo dispatch contract

The release workflow in `kusari-oss/darnit` sends a `repository_dispatch` event after the binary matrix completes:

```json
{
  "event_type": "darnit-release",
  "client_payload": {
    "version": "0.1.0",
    "darnit_repo": "kusari-oss/darnit",
    "release_url": "https://github.com/kusari-oss/darnit/releases/tag/v0.1.0",
    "sha256_macos_arm64": "<sha256>",
    "sha256_macos_amd64": "<sha256>",
    "sha256_linux_arm64": "<sha256>",
    "sha256_linux_amd64": "<sha256>",
    "binary_url_template": "https://github.com/kusari-oss/darnit/releases/download/v0.1.0/darnit-0.1.0-{os}-{arch}"
  }
}
```

Authentication: the dispatching workflow uses a GitHub App token (configured per `packaging/README.md`) with `contents: write` on `kusari-oss/homebrew-tap` only.

## Formula template

`packaging/homebrew/darnit.rb.tmpl` in this repo. The tap workflow renders it with the dispatch payload:

```ruby
class Darnit < Formula
  desc "AI-powered compliance auditing framework"
  homepage "https://github.com/kusari-oss/darnit"
  version "{{ version }}"
  license "Apache-2.0"

  on_macos do
    on_arm do
      url "{{ binary_url_template | replace('{os}', 'macos') | replace('{arch}', 'arm64') }}"
      sha256 "{{ sha256_macos_arm64 }}"
    end
    on_intel do
      url "{{ binary_url_template | replace('{os}', 'macos') | replace('{arch}', 'amd64') }}"
      sha256 "{{ sha256_macos_amd64 }}"
    end
  end

  on_linux do
    on_arm do
      url "{{ binary_url_template | replace('{os}', 'linux') | replace('{arch}', 'arm64') }}"
      sha256 "{{ sha256_linux_arm64 }}"
    end
    on_intel do
      url "{{ binary_url_template | replace('{os}', 'linux') | replace('{arch}', 'amd64') }}"
      sha256 "{{ sha256_linux_amd64 }}"
    end
  end

  depends_on "python@3.12"

  def install
    bin.install Dir["darnit-#{version}-*"].first => "darnit"
  end

  test do
    assert_match version.to_s, shell_output("#{bin}/darnit --version")
  end
end
```

Vendored into the tap repo on each dispatch so the tap workflow has a self-contained source.

## Tap workflow behavior

`kusari-oss/homebrew-tap/.github/workflows/bump-formula.yml`:

1. Receives dispatch.
2. Validates payload: required keys present, SHA-256s are 64-char hex.
3. Renders `Formula/darnit.rb` from the vendored template.
4. Runs `brew style Formula/darnit.rb` and `brew install --build-from-source Formula/darnit.rb`. Both must pass.
5. Opens a PR titled `darnit <version>` with the rendered formula.
6. Auto-merges the PR when CI is green (uses `gh pr merge --auto --squash`).

## Smoke test

Triggered from `release-smoke.yml` in this repo, runs after the auto-merge completes:

```bash
# macOS arm64 runner
brew tap kusari-oss/tap
brew install darnit
darnit --version | grep "<version>"

# Linux runner
brew tap kusari-oss/tap
brew install darnit
darnit --version | grep "<version>"
```

A 30-minute polling loop waits for the auto-merge (SC-007). If the merge does not complete within the window, the smoke test fails and a `release-failure` issue is created.

## What this contract does not promise

- **Submission to homebrew-core**: out of scope for v1; this is a tap-only release. Migrating to homebrew-core is a separate future task.
- **Backward formula compatibility**: each release replaces `Formula/darnit.rb` wholesale. Users wanting an older version use `brew install darnit@<version>` only if the tap maintains versioned formulae, which v1 does not (single `darnit.rb` only). Pinning to an old version requires checking out the tap repo at a previous commit, which is acceptable as a power-user workflow.
