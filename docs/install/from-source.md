# Install darnit from source

For users who want to **try an unreleased feature**, contribute to darnit, or run a specific commit/branch before it ships through one of the published channels ([PyPI](pypi.md), [container](container.md), [Homebrew](homebrew.md), [binary](binary.md), [Claude Code plugin](claude-code-plugin.md)).

This path is necessary today because darnit's packages aren't yet on PyPI. After the first stable release (`v0.1.0`), the published channels become the easier path; from-source becomes a contributor-or-feature-preview workflow.

## Quick install

```bash
# 1. Clone the canonical repository
git clone https://github.com/kusari-oss/darnit ~/Projects/darnit
cd ~/Projects/darnit

# 2. Optionally switch to a specific feature branch
git checkout <branch-name>

# 3. Install as an editable `uv tool` with all three workspace packages
uv tool install --python 3.12 \
  --editable packages/darnit \
  --with-editable packages/darnit-baseline \
  --with-editable packages/darnit-gittuf

# 4. Verify
darnit --version
darnit list        # should show openssf-baseline, 62 controls
```

That's it — `darnit` is on `PATH`, editable-backed by your clone, ready to run.

## Why three `--with-editable` flags?

darnit is a uv workspace. The user-facing CLI lives in `packages/darnit/` (the `darnit-core` package), but it discovers compliance implementations via Python entry points exposed by sibling packages:

- `packages/darnit/` → the `darnit-core` framework (CLI, sieve, MCP server)
- `packages/darnit-baseline/` → the OpenSSF Baseline implementation (62 controls)
- `packages/darnit-gittuf/` → the gittuf plugin

If you install only `packages/darnit/` editable, uv tries to resolve `darnit-baseline` and `darnit-gittuf` from PyPI — and they don't exist on PyPI yet (pre-v0.1.0). The `--with-editable` flags tell uv to add the sibling packages as additional editable members in the same tool venv.

After v0.1.0 ships, this constraint disappears: `uv tool install darnit-mcp` (the workspace root) will resolve everything from PyPI.

## Why `--python 3.12`?

darnit's workspace targets **Python 3.11 and 3.12** (see `requires-python` in each `pyproject.toml`). Newer Python versions (3.13, 3.14) may work but are not yet covered by darnit's CI matrix, and `tree-sitter-language-pack` doesn't ship wheels for them at the time of writing (see [#268](https://github.com/kusari-oss/darnit/issues/268)). Pinning the tool venv to 3.12 avoids surprise build-from-source failures and matches what darnit's own CI runs against.

If your system default is 3.11 or 3.12 already, you can omit the flag.

## Running the MCP server from source

```bash
darnit serve --framework openssf-baseline
```

Or configure it as an MCP server in Claude Code:

```bash
claude mcp add --scope user darnit -- "$(which darnit)" serve --framework openssf-baseline
```

(The `darnit install` command also writes MCP config, but it writes to Claude Desktop's settings file, not Claude Code's — see [#270](https://github.com/kusari-oss/darnit/issues/270). The direct `claude mcp add` command works around that until the install command is fixed.)

## Switching branches

Because the install is editable, switching branches in `~/Projects/darnit` immediately changes what `darnit` runs — no reinstall needed:

```bash
cd ~/Projects/darnit
git checkout feature-branch
darnit --version   # now runs the feature branch's code
```

The only time you need to reinstall is when the workspace dependency set itself changes (e.g., a new sibling package gets added to `packages/`, or pinned versions in any `pyproject.toml` change).

## Uninstall

```bash
uv tool uninstall darnit-core
```

The clone in `~/Projects/darnit` stays on disk — remove it manually if you no longer want the source tree.

## Why not `uv tool install git+https://…`?

Two reasons this doesn't work today:

1. The **workspace root** (`darnit-mcp`) is a virtual package — it has `[tool.uv.workspace]` but no source of its own. `setuptools` errors out trying to build it directly.
2. Installing a **single package by `subdirectory=`** works structurally, but its workspace-sibling dependencies (`darnit-baseline`, `darnit-gittuf`) aren't on PyPI yet. uv tries to resolve them from PyPI, gets 404, fails.

After v0.1.0 puts all four packages on PyPI, `uv tool install darnit-mcp` works in one shot — no clone needed.

## See also

- [Installation overview](README.md) — decision tree for the published channels.
- [PyPI install](pypi.md) — the path after v0.1.0 ships.
- The [maintainer release runbook](../../packaging/README.md) — how releases get produced.
