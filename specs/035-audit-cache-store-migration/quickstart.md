# Quickstart: `[stores.cache]` Actually Redirects the Audit Cache

**Feature**: 035-audit-cache-store-migration

Three worked examples an operator can walk through to convince themselves the migration behaves. Each example assumes darnit is installed (`uv tool install darnit` or equivalent) and there's a git repo at `~/src/my-project` to audit against.

## Example 1: CI operator, `local-fs` backend under `$RUNNER_CACHE_DIR`

**Scenario**: a GitHub Actions job that audits the repo on every PR. The runner caches the `$RUNNER_CACHE_DIR/darnit` directory between jobs so a second audit of the same PR commit hits the cache and skips the sieve loop.

**Config** (`.baseline.toml` at repo root):

```toml
[stores.cache]
backend = "local-fs"
root    = "$RUNNER_CACHE_DIR/darnit"
```

**Run 1** (fresh cache):

```bash
$ export RUNNER_CACHE_DIR=/tmp/ci-cache
$ mkdir -p "$RUNNER_CACHE_DIR"
$ darnit audit ~/src/my-project --level 1
[...] audit runs the sieve loop, produces results [...]
INFO  wrote cache (local-fs): /tmp/ci-cache/darnit/<hash>.json
```

The cache file lands under `$RUNNER_CACHE_DIR/darnit/`, NOT `$TMPDIR/darnit/`. Confirm:

```bash
$ ls /tmp/ci-cache/darnit/
5a4c8e9f2b1d3706.json   # <hash> is sha256(abspath(~/src/my-project))[:16]

$ find /tmp/darnit -name "audit-cache.json" 2>/dev/null
# (no output -- no fallback cache in system tempdir)
```

**Run 2** (cache hit, no git changes between runs):

```bash
$ darnit audit ~/src/my-project --level 1
[...] audit skips the sieve loop, reuses cached results [...]
```

The audit driver reads `/tmp/ci-cache/darnit/5a4c8e9f2b1d3706.json`, checks TTL + HEAD + dirty-state (all match), and returns the cached envelope directly. This is the story that was broken pre-feature-035 -- the `[stores.cache]` block used to do nothing.

## Example 2: Zero-config user, upgrade path

**Scenario**: a developer running darnit locally who never touched `.baseline.toml`. They upgrade to a darnit release that includes this feature and expect nothing to change on disk.

**Config**: none. No `.baseline.toml`, or a `.baseline.toml` with no `[stores.*]` block.

**Run**:

```bash
$ darnit audit ~/src/my-project --level 1
[...] audit runs, produces results [...]
```

Cache location:

```bash
$ REPO_HASH=$(python -c "import hashlib, os; print(hashlib.sha256(os.path.abspath(os.path.expanduser('~/src/my-project')).encode()).hexdigest()[:16])")
$ ls "${TMPDIR:-/tmp}/darnit/$REPO_HASH/"
audit-cache.json
```

Byte-for-byte identical to where the pre-feature-035 darnit put it. No release-notes surprise for zero-config users; the on-disk path is unchanged.

## Example 3: Multi-repo operator, shared `local-fs` root

**Scenario**: a maintainer runs audits against several repos from the same machine, all sharing one `[stores.cache] root`. Verifies per-repo isolation.

**Config** (in each repo's `.baseline.toml`):

```toml
[stores.cache]
backend = "local-fs"
root    = "~/.cache/darnit-shared"
```

**Runs**:

```bash
$ darnit audit ~/src/repo-a --level 1
$ darnit audit ~/src/repo-b --level 1
$ ls ~/.cache/darnit-shared/
5a4c8e9f2b1d3706.json   # sha256(abspath(~/src/repo-a))[:16]
9c7f2a4b8e0d1583.json   # sha256(abspath(~/src/repo-b))[:16]
```

Two files, one per repo. Confirms SC-006: two different repos under a shared root do not overwrite each other. If we had used `cache_key = "audit-cache"` in the configured-store case (as we do in the default-store case), both repos would collide on a single file -- that's why the wrapper switches to a per-repo cache_key when the operator has configured a root.

## Bonus: invalidation

If you want to force a fresh audit without changing any code or committing anything:

```bash
$ python -c "from darnit.core.audit_cache import invalidate_audit_cache; invalidate_audit_cache('$HOME/src/my-project')"
$ darnit audit ~/src/my-project --level 1
[...] audit runs the sieve loop (cache miss, no reuse) [...]
```

Behind the scenes, `invalidate_audit_cache` wrote an envelope with `timestamp = "1970-01-01T00:00:00Z"` to the cache location; the next `read_audit_cache` misses on the TTL check.

The file itself remains on disk until the next audit writes over it. That's intentional: the `AuditCacheStore` Protocol has no `delete(key)` method (adding one would ripple through every backend implementation), and the cache path is operator-invisible tempdir in the default case anyway.
