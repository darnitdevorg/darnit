# darnit — Claude Code plugin

> This README is bundled into every `darnit-claude-plugin-<version>.zip` release artifact. The `__VERSION__` placeholder is substituted at build time by `packaging/claude-plugin/build.sh`.
>
> If you're reading this from `packaging/claude-plugin/README.md` in the source tree, you're looking at the template. The published copy at the root of the plugin zip has the real version pinned.

## What this plugin gives you

darnit is an AI-powered compliance auditing framework. Once this plugin is installed in Claude Code:

- **Four agentic skills** become available to Claude. Skills are **model-invoked** — you don't type a slash command to trigger them. Just ask Claude naturally and it picks the right skill based on the skill's description:

  | Skill | Triggers when you ask things like |
  |---|---|
  | `darnit-audit` | "Audit this repo." / "Run a compliance check." |
  | `darnit-comply` | "Make this repo compliant." / "Run the full pipeline." |
  | `darnit-data` | "Set up darnit for this project." / "Fill in the project context." |
  | `darnit-remediate` | "Fix the failing compliance controls." |

- **MCP server** (`darnit-mcp`) registers with Claude. Its `audit`, `remediate`, `list_controls`, and supporting tools become available to the agent automatically.

The plugin and the MCP server it invokes are pinned to **darnit `__VERSION__`** (lockstep with the parent darnit release).

> Per the [Claude Code skills docs](https://docs.claude.com/claude-code/skills), skills are model-invoked. The plugin namespace (`darnit:`) is how Claude internally disambiguates skills across plugins. Whether you can also type a slash form like `/darnit:audit` to invoke explicitly depends on your Claude Code version — when in doubt, just describe what you want.

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

After install, just ask Claude:

```
> Run a compliance audit on this repository.
```

Claude will match the request to the `darnit-audit` skill's description, load the skill, and invoke the appropriate darnit-mcp tool.

## What gets installed

```
darnit/
├── .claude-plugin/
│   └── plugin.json          # Plugin manifest (auto-loaded by Claude Code)
├── README.md                 # This file
├── bin/
│   └── darnit-mcp-runner    # Wrapper script: uvx → pipx → actionable error
└── skills/
    ├── audit/SKILL.md       # darnit-audit (auto-discovered by Claude Code)
    ├── comply/SKILL.md      # darnit-comply
    ├── data/SKILL.md        # darnit-data
    └── remediate/SKILL.md   # darnit-remediate
```

Skill directory names are short (`audit`, `comply`, `data`, `remediate`) so the plugin-namespaced identifier reads cleanly as `darnit:audit` rather than `darnit:darnit-audit`. Skills are auto-discovered by Claude Code from the `skills/` directory — the manifest does not enumerate them.

## Schema version

This plugin targets Claude Code's plugin schema with `.claude-plugin/plugin.json` and skills auto-discovered from `skills/`. If your Claude Code version doesn't recognize the plugin, you may be on a Claude Code version that predates this schema — upgrade Claude Code first.

## Trouble?

| Symptom | Fix |
|---|---|
| `darnit plugin: neither 'uvx' nor 'pipx' is available on PATH.` | Install [uv](https://docs.astral.sh/uv/getting-started/installation/) OR [pipx](https://pipx.pypa.io/stable/installation/). |
| Claude doesn't seem to know about darnit | Confirm the plugin was loaded (consult your Claude Code version's plugin UI). Try being explicit: "use the darnit-audit skill". |
| MCP tools missing in the agent | The runner failed to fetch `darnit-mcp==__VERSION__` from PyPI. Check network access and PyPI availability. The wrapper exits 127 in that case. |

## Source

- Plugin source: `packaging/claude-plugin/` in [kusari-oss/darnit](https://github.com/kusari-oss/darnit)
- Skill source: `packages/darnit/src/darnit/skills/` (same repo)
- darnit framework: `packages/darnit/`
- Issue tracker: https://github.com/kusari-oss/darnit/issues

## License

Apache-2.0.
