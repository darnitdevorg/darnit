# Tap repo workflows — reference copies

The `kusari-oss/homebrew-tap` repository owns its own workflow files. They live in the **tap repo's** `.github/workflows/` directory, not in this darnit source tree.

These files here are **reference copies** so the renderer (`bump-formula.yml`) ships next to the template it consumes (`packaging/homebrew/darnit.rb.tmpl`). When darnit's release pipeline changes the template, the corresponding tap-repo workflow change is reviewed in the same PR.

## How to use these (one-time tap setup)

After [creating the `kusari-oss/homebrew-tap` repository](../../README.md#external-setup-one-time) on GitHub:

```bash
git clone https://github.com/kusari-oss/homebrew-tap.git
cd homebrew-tap

mkdir -p .github/workflows
cp ../darnit/packaging/homebrew/tap-workflows/bump-formula.yml .github/workflows/
cp ../darnit/packaging/homebrew/tap-workflows/ci.yml          .github/workflows/

git add .github/workflows/
git commit -m "Initial CI + formula-bump workflows from kusari-oss/darnit"
git push
```

## Drift

If you edit `bump-formula.yml` or `ci.yml` here without also updating the tap repo, the tap will continue to run the old version. The release-failure recovery path (in [`packaging/RECOVERY.md`](../../RECOVERY.md#homebrew)) names this drift as the most common cause of "dispatch fired but no PR appeared."

For any change to these files, the PR must include an "After-merge maintainer action" note in its body stating which files need to be re-synced into the tap repo.

## Files

| File | Tap-repo destination | Purpose |
|---|---|---|
| `bump-formula.yml` | `.github/workflows/bump-formula.yml` | Triggered by `repository_dispatch` from `kusari-oss/darnit::release.yml::homebrew_dispatch`. Fetches the formula template from this repo at the release's tagged commit, substitutes payload values, runs `brew style` + `brew install --build-from-source`, opens an auto-merging PR. |
| `ci.yml` | `.github/workflows/ci.yml` | Lint + install test on every PR touching `Formula/`. This is what gates the auto-merge that `bump-formula.yml` requests. |

## Secrets required in the tap repo

None on the tap-repo side. The dispatching workflow (in `kusari-oss/darnit`) holds the credentials. The tap repo uses its built-in `GITHUB_TOKEN` for the in-repo PR + auto-merge.
