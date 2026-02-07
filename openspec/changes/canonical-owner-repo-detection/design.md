## Context

Six separate `_detect_owner_repo()` functions exist across the codebase, each with slightly different behavior:

| Location | Method | Fork-aware | Returns |
|----------|--------|-----------|---------|
| `darnit/core/utils.py:149` | `gh repo view` | No | `dict` or `None` |
| `darnit_baseline/tools.py:894` | `git remote get-url` with upstream-first | **Yes** | `tuple[str, str]` |
| `darnit/server/tools/builtin_audit.py:147` | Wraps `detect_repo_from_git()` | No | `tuple[str, str]` |
| `darnit/server/tools/builtin_remediate.py:185` | Wraps `detect_repo_from_git()` | No | `tuple[str, str]` |
| `darnit/cli.py:498` | `git remote get-url origin` | No | `tuple` |
| `darnit/config/context_storage.py:391` | Inline call to `detect_repo_from_git()` | No | N/A (inline) |

The `darnit_baseline/tools.py` version is the only fork-aware detector. It checks `upstream` remote first, falling back to `origin`. But `darnit-baseline` can't be imported by framework packages (separation rule), so each framework module re-implemented detection from scratch — always defaulting to `origin` only.

The current `detect_repo_from_git()` in `darnit.core.utils` uses `gh repo view` without specifying a remote, so `gh` decides which remote to use (typically `origin`). It returns a dict with owner/repo/metadata.

## Goals / Non-Goals

**Goals:**
- Upgrade `detect_repo_from_git()` to be the single canonical detector with fork-aware upstream-first behavior
- Delete all 5 private `_detect_owner_repo()` functions and replace call sites
- Maintain the same return type (`dict | None`) with an added `source` field
- Add a convenience helper `detect_owner_repo()` that returns `tuple[str, str]` for call sites that only need owner/repo
- Add spec requirement so future code follows the same pattern

**Non-Goals:**
- Changing how `gh` CLI authentication works
- Supporting non-GitHub remotes (GitLab, Bitbucket) — deferred
- Caching detection results across calls within a session — deferred
- Consolidating `_detect_default_branch()` functions (separate concern)

## Decisions

### 1. Two-tier detection strategy: git-first, gh-enrichment

**Decision:** Use `git remote get-url` to check remotes in order (upstream → origin), parse the URL for owner/repo, then optionally call `gh repo view` for enriched metadata (is_private, default_branch).

**Rationale:** The current `detect_repo_from_git()` calls `gh repo view` without specifying which remote to query, so `gh` picks one — usually `origin`. We can't control `gh`'s remote selection, but we CAN control which remote URL we parse. By parsing `git remote get-url` ourselves first, we control the resolution order. Then `gh repo view {owner}/{repo}` (with the explicit nwo) fetches metadata for the correct repo.

**Alternative considered:** Only use `gh repo view` with `--repo` flag. Rejected because `gh repo view --repo owner/repo` still requires knowing the owner/repo first — circular dependency. Also, `gh` may not be installed; `git` always is in a git repo.

### 2. Add `detect_owner_repo()` convenience wrapper

**Decision:** Add a thin wrapper that returns `tuple[str, str]` for call sites that only need owner and repo name.

```python
def detect_owner_repo(
    local_path: str,
    *,
    prefer_upstream: bool = True,
    owner: str | None = None,
    repo: str | None = None,
) -> tuple[str, str]:
    """Convenience wrapper returning (owner, repo) tuple."""
```

**Rationale:** 5 of 6 call sites only need `(owner, repo)`. The full dict return from `detect_repo_from_git()` is useful for tools that need `default_branch` or `is_private`, but most callers just want the two strings. A convenience function prevents every call site from doing `info.get("owner", ""), info.get("repo", path.name)`.

### 3. Resolution order: upstream → origin, configurable

**Decision:** Default resolution order is `["upstream", "origin"]`. Callers can pass `prefer_upstream=False` to reverse this.

```python
def detect_repo_from_git(
    local_path: str,
    *,
    prefer_upstream: bool = True,
    owner: str | None = None,
    repo: str | None = None,
) -> dict[str, str] | None:
```

**Rationale:** The `darnit_baseline/tools.py` version already proved this pattern works. Making upstream-first the default means new code gets fork-correct behavior without thinking about it. The `prefer_upstream` parameter exists for the rare case where someone genuinely wants the fork's settings.

### 4. Explicit owner/repo short-circuits detection

**Decision:** When both `owner` and `repo` are provided, skip all subprocess calls and return immediately with `source: "explicit"`.

**Rationale:** This supports CI environments where the repo is known, avoids unnecessary subprocess calls, and matches the existing pattern in `darnit_baseline/tools.py` where `owner = owner or detected_owner`.

### 5. Delete private detectors, not deprecate

**Decision:** Delete all 5 `_detect_owner_repo()` functions immediately. Do not deprecate or keep as wrappers.

**Rationale:** These are private functions (leading underscore). No external consumers depend on them. Keeping them as wrappers adds confusion — someone will call the local one instead of the canonical one. Clean deletion with call-site migration is the right approach.

### 6. `source` field in return dict

**Decision:** Add a `source` field to the returned dict indicating which remote (or override) provided the owner/repo: `"upstream"`, `"origin"`, `"explicit"`, or `"fallback"`.

**Rationale:** Aids debugging when the wrong repo is resolved. The audit output or logs can show "Detected owner/repo from upstream remote" vs "from origin remote" so users understand what's happening.

## Risks / Trade-offs

**[Behavior change for non-fork repos]** → Repos with only `origin` remote are unaffected (upstream check returns nothing, falls through to origin). Repos with both `upstream` and `origin` will now resolve to upstream everywhere — this is the desired fix. No risk of regression for the common (non-fork) case.

**[`gh repo view` call may slow down if given explicit nwo]** → We call `gh repo view owner/repo` instead of bare `gh repo view`. Performance should be equivalent since GitHub's API is the same either way. If `gh` is missing entirely, we still have owner/repo from git remote parsing; we just lose `is_private` and `default_branch` metadata.

**[`upstream` remote may not exist on all forks]** → Some users fork via GitHub but don't configure an `upstream` remote. Mitigation: when `upstream` remote doesn't exist, we fall back to `origin` — same as current behavior. This is acceptable because users who care about fork correctness will have `upstream` configured (standard git workflow).

**[Breaking change for `detect_repo_from_git()` callers]** → Adding `prefer_upstream`, `owner`, `repo` parameters are all keyword-only with defaults, so existing callers continue to work. The return dict gains a `source` field — additive, no breakage.

## Open Questions

None — the implementation path is straightforward.
