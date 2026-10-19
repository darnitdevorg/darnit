# Install darnit from source

For users who want to **try an unreleased feature**, contribute to darnit, or run a specific commit/branch before it ships through one of the published channels ([PyPI](pypi.md), [container](container.md), [Homebrew](homebrew.md), [binary](binary.md), [Claude Code plugin](claude-code-plugin.md)).

There are two routes: install straight from the git URL with `uv tool install` (no clone), or clone the repository and work in the checkout.

## Install from the git URL

```bash
uv tool install --python 3.12 git+https://github.com/darnitdevorg/darnit

darnit --version
darnit list        # openssf-baseline (66 controls), gittuf, reproducibility
```

This installs the workspace root, the `darnit-mcp` package. It provides the `darnit` command and pulls in every workspace plugin. The package is `darnit-mcp`, but the command is `darnit`; there is no `darnit-mcp` command.

Pin a tag, branch or commit with `@`:

```bash
uv tool install --python 3.12 "git+https://github.com/darnitdevorg/darnit@<tag>"
```

Tags up to and including `v0.1.1` predate the root package's `darnit` command ([#621](https://github.com/darnitdevorg/darnit/issues/621)), so `uv tool install` fails on them with "No executables are provided by package `darnit-mcp`". To run any tag without installing it, use `uvx --from`:

```bash
uvx --python 3.12 --from "git+https://github.com/darnitdevorg/darnit@<tag>" darnit audit /path/to/repo
uvx --python 3.12 --from "git+https://github.com/darnitdevorg/darnit@<tag>" darnit serve --framework openssf-baseline   # MCP server
```

## Work in a clone

```bash
# 1. Clone the canonical repository
git clone https://github.com/darnitdevorg/darnit ~/Projects/darnit
cd ~/Projects/darnit

# 2. Optionally switch to a specific feature branch
git checkout <branch-name>

# 3. Install the workspace and its development dependencies
uv sync

# 4. Run darnit from the checkout
uv run darnit list
uv run darnit serve      # MCP server; OpenSSF Baseline by default
```

This is the contributor setup; see [CONTRIBUTING.md](../../CONTRIBUTING.md).

### Put a clone-backed `darnit` on PATH

To run `darnit` from anywhere while it runs your clone's code, install it as an editable `uv tool`:

```bash
uv tool install --python 3.12 \
  --editable packages/darnit \
  --with-editable packages/darnit-baseline \
  --with-editable packages/darnit-gittuf \
  --with-editable packages/darnit-reproducibility

darnit list        # openssf-baseline (66 controls), gittuf, reproducibility
```

The user-facing CLI lives in `packages/darnit/` (the `darnit-core` package), but it discovers compliance implementations via Python entry points exposed by sibling packages:

- `packages/darnit/` → the `darnit-core` framework (CLI, sieve, MCP server)
- `packages/darnit-baseline/` → the OpenSSF Baseline implementation
- `packages/darnit-gittuf/` → the gittuf plugin
- `packages/darnit-reproducibility/` → the reproducibility plugin

`darnit-core` does not depend on the plugins, so each `--with-editable` adds one to the same tool environment. Leave one out and `darnit list` does not show it.

Because the install is editable, switching branches in `~/Projects/darnit` immediately changes what `darnit` runs — no reinstall needed:

```bash
cd ~/Projects/darnit
git checkout feature-branch
darnit --version   # now runs the feature branch's code
```

The only time you need to reinstall is when the workspace dependency set itself changes (e.g., a new sibling package gets added to `packages/`, or pinned versions in any `pyproject.toml` change).

## Why `--python 3.12`?

darnit's workspace targets **Python 3.11 and 3.12** (see `requires-python` in each `pyproject.toml`). Newer Python versions (3.13, 3.14) may work but are not yet covered by darnit's CI matrix, and `tree-sitter-language-pack` doesn't ship wheels for them at the time of writing (see [#268](https://github.com/darnitdevorg/darnit/issues/268)). Pinning the tool venv to 3.12 avoids surprise build-from-source failures and matches what darnit's own CI runs against.

If your system default is 3.11 or 3.12 already, you can omit the flag.

## Running the MCP server

```bash
darnit serve --framework openssf-baseline
```

Or configure it as an MCP server in Claude Code:

```bash
# Recommended: use darnit's install command (writes ~/.claude.json)
darnit install --client claude-code

# Or register manually with the Claude Code CLI
claude mcp add --scope user darnit -- "$(which darnit)" serve --framework openssf-baseline
```

For a project-local MCP config, run `darnit install --project` from the repo root (writes `.mcp.json`).

## Uninstall

```bash
uv tool uninstall darnit-mcp     # installed from the git URL (or from PyPI)
uv tool uninstall darnit-core    # editable install from a clone
```

The clone in `~/Projects/darnit` stays on disk — remove it manually if you no longer want the source tree.

## See also

- [Installation overview](README.md) — decision tree for the published channels.
- [PyPI install](pypi.md) — `uv tool install darnit-mcp` and `uvx --from darnit-mcp darnit`.
- The [maintainer release runbook](../../packaging/README.md) — how releases get produced.
