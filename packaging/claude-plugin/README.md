# darnit — Claude Code plugin

> This README is bundled into every `darnit-claude-plugin-<version>.zip` release artifact. The `__VERSION__` placeholder is substituted at build time by `packaging/claude-plugin/build.sh`.
>
> If you're reading this from `packaging/claude-plugin/README.md` in the source tree, you're looking at the template. The published copy at the root of the plugin zip has the real version pinned.

## What this plugin gives you

darnit is an AI-powered compliance auditing framework. Once this plugin is installed in Claude Code:

- Four `/darnit:*` slash commands appear:
  - `/darnit:audit` — run a compliance audit
  - `/darnit:comply` — full audit + remediate pipeline
  - `/darnit:data` — collect missing project data / context
  - `/darnit:remediate` — apply automated fixes
- An MCP server (`darnit-mcp`) is registered with Claude. Its `audit`, `remediate`, `list_controls`, and supporting tools become available to the agent automatically.

The plugin and the MCP server it invokes are pinned to **darnit `__VERSION__`** (lockstep with the parent darnit release).

## Install

### Prerequisite

The plugin invokes `darnit-mcp` via either:
- **`uvx`** (preferred — install [uv](https://docs.astral.sh/uv/getting-started/installation/) and you have `uvx`), or
- **`pipx`** (fallback — install [pipx](https://pipx.pypa.io/stable/installation/)).

At least one of those must be on `PATH` when Claude Code launches the plugin's MCP server. If neither is present the server prints an actionable error message naming both options.

### From the GitHub release asset

```bash
claude --plugin-url \
  https://github.com/kusari-oss/darnit/releases/download/v__VERSION__/darnit-claude-plugin-__VERSION__.zip
```

(Or the equivalent `claude --plugin-dir ./darnit/` after unzipping locally — useful for development.)

### Future: Anthropic marketplace

When/if Anthropic ships a public plugin marketplace, this plugin will be submitted there. For v1, the GitHub release asset is the canonical distribution.

## Verify the install

After install:

```bash
# In a Claude Code session, the slash commands appear automatically:
/darnit:audit ./some-repo

# Or just check the plugin loaded by listing commands:
/help
```

## What gets installed

```
darnit/
├── .claude-plugin/
│   └── plugin.json          # Plugin manifest (auto-loaded by Claude Code)
├── README.md                 # This file
├── bin/
│   └── darnit-mcp-runner    # Wrapper script: uvx → pipx → actionable error
└── skills/
    ├── audit/SKILL.md       # → /darnit:audit
    ├── comply/SKILL.md      # → /darnit:comply
    ├── data/SKILL.md        # → /darnit:data
    └── remediate/SKILL.md   # → /darnit:remediate
```

## Schema version

This plugin targets Claude Code's plugin schema with `.claude-plugin/plugin.json` and skills auto-discovered from `skills/`. If your Claude Code version doesn't recognize the plugin, you may be on a Claude Code version that predates this schema — upgrade Claude Code first.

## Trouble?

| Symptom | Fix |
|---|---|
| `darnit plugin: neither 'uvx' nor 'pipx' is available on PATH.` | Install [uv](https://docs.astral.sh/uv/getting-started/installation/) OR [pipx](https://pipx.pypa.io/stable/installation/). |
| `/darnit:audit` not in slash-command list | Confirm the plugin was loaded (`/help` should list it). On dev installs, restart Claude Code after copying the unzipped plugin into your plugin directory. |
| MCP tools missing in the agent | The runner failed to fetch `darnit-mcp==__VERSION__` from PyPI. Check network access and PyPI availability. The wrapper exits 127 in that case. |

## Source

- Plugin source: `packaging/claude-plugin/` in [kusari-oss/darnit](https://github.com/kusari-oss/darnit)
- darnit framework: same repo, `packages/darnit/`
- Issue tracker: https://github.com/kusari-oss/darnit/issues

## License

Apache-2.0.
