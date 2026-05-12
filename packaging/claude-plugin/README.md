# darnit — Claude Code plugin

> This README is bundled into every `darnit-claude-plugin-<version>.zip` release artifact. The `__VERSION__` placeholder is substituted at build time by `packaging/claude-plugin/build.sh`.
>
> If you're reading this from `packaging/claude-plugin/README.md` in the source tree, you're looking at the template. The published copy at the root of the plugin zip has the real version pinned.

## What this plugin gives you

darnit is an AI-powered compliance auditing framework. Once this plugin is installed in Claude Code, four namespaced slash commands appear (the `darnit:` prefix comes from the plugin name):

| Command | What it does |
|---|---|
| `/darnit:darnit-audit` | Run a compliance audit on the current repository |
| `/darnit:darnit-comply` | Full audit + remediate pipeline |
| `/darnit:darnit-data` | Collect missing project data / context |
| `/darnit:darnit-remediate` | Apply automated fixes for failing controls |

Per the Claude Code skills docs, you can also let Claude pick a skill automatically — just describe what you want ("audit this repo") and Claude will load the matching skill from its `description`. Both paths work.

> **Why `/darnit:darnit-audit` and not `/darnit:audit`?** The plugin namespace is `darnit:` and the skill is named `darnit-audit`. Keeping the `darnit-` prefix on the skill makes it namespace-safe even when copied into non-plugin contexts. The redundancy is intentional — same pattern spec-kit uses for `/speckit.specify`.

The plugin also registers the **`darnit-mcp` MCP server** with Claude. Its `audit`, `remediate`, `list_controls`, and supporting tools become available to the agent.

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

## Try it

```
> /darnit:darnit-audit
```

Or just ask Claude:

```
> Run a compliance audit on this repository.
```

Either path lands at the same skill.

## What gets installed

```
darnit/
├── .claude-plugin/
│   └── plugin.json          # Plugin manifest (auto-loaded by Claude Code)
├── README.md                 # This file
├── bin/
│   └── darnit-mcp-runner    # Wrapper script: uvx → pipx → actionable error
└── skills/
    ├── darnit-audit/SKILL.md       # → /darnit:darnit-audit
    ├── darnit-comply/SKILL.md      # → /darnit:darnit-comply
    ├── darnit-data/SKILL.md        # → /darnit:darnit-data
    └── darnit-remediate/SKILL.md   # → /darnit:darnit-remediate
```

Skills are auto-discovered by Claude Code from the `skills/` directory — the manifest does not enumerate them.

## Using darnit's skills on other agents

The skills bundled here follow the open [Agent Skills standard](https://agentskills.io/specification). They are portable to any Agent Skills-compatible client — Cursor, GitHub Copilot, Codex, OpenHands, Gemini CLI, opencode, Goose, and ~30 other tools.

The plugin wrapper (`.claude-plugin/plugin.json`, the MCP-server runner, the version pin) is Claude-Code-specific. The SKILL.md files themselves are not — unzip this bundle and copy the four `skills/darnit-*/` directories into your agent's skill directory. You'll need to wire up the `darnit-mcp` server yourself in your agent's MCP config (e.g., point it at `uvx darnit-mcp==__VERSION__`).

## Schema version

This plugin targets Claude Code's plugin schema with `.claude-plugin/plugin.json` and skills auto-discovered from `skills/`. If your Claude Code version doesn't recognize the plugin, you may be on a Claude Code version that predates this schema — upgrade Claude Code first.

## Trouble?

| Symptom | Fix |
|---|---|
| `darnit plugin: neither 'uvx' nor 'pipx' is available on PATH.` | Install [uv](https://docs.astral.sh/uv/getting-started/installation/) OR [pipx](https://pipx.pypa.io/stable/installation/). |
| `/darnit:darnit-audit` doesn't appear in `/help` | Confirm the plugin was loaded. On dev installs, restart Claude Code after copying the unzipped plugin into your plugin directory. |
| MCP tools missing in the agent | The runner failed to fetch `darnit-mcp==__VERSION__` from PyPI. Check network access and PyPI availability. The wrapper exits 127 in that case. |

## Source

- Plugin source: `packaging/claude-plugin/` in [kusari-oss/darnit](https://github.com/kusari-oss/darnit)
- Skill source: `packages/darnit/src/darnit/skills/` (same repo)
- darnit framework: `packages/darnit/`
- Issue tracker: https://github.com/kusari-oss/darnit/issues

## License

Apache-2.0.
