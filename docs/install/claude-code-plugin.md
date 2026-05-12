# Install darnit as a Claude Code plugin

If you're a Claude Code user, the plugin is the cleanest install path. One command and you get four agentic skills plus the darnit MCP server, all version-pinned to the same darnit release.

Examples assume version `0.1.0` — substitute the version you want.

## What you get

Once installed:

- **Four agentic skills** become available to Claude. These are **model-invoked** — you don't type a slash command to trigger them. You talk to Claude naturally, and the agent picks the right skill based on the skill's description:

  | Skill | Triggers Claude when you ask things like |
  |---|---|
  | `darnit-audit` | "Audit this repo." / "Run a compliance check." / "How does this repo score on OpenSSF Baseline?" |
  | `darnit-comply` | "Make this repo compliant." / "Run the full compliance pipeline." |
  | `darnit-data` | "Set up darnit for this project." / "Fill in the project context." |
  | `darnit-remediate` | "Fix the failing compliance controls." / "Apply the auto-remediations." |

- **MCP server** (`darnit-mcp`) registers automatically. Its tools — `audit`, `remediate`, `list_controls`, plus the threat-model, project-data, and remediation helpers — become available to Claude. The agent uses them in the same model-invoked way; you don't see them directly.

> **Skills are not slash commands.** Per the Claude Code [skills docs](https://docs.claude.com/claude-code/skills), skills are model-invoked by default — Claude reads each skill's `description` field and decides when to load it based on your request. You don't need to know their names; just describe what you want.
>
> The plugin namespace (`darnit:`) is how Claude internally disambiguates skills across installed plugins. Whether you can also type `/darnit:audit` to invoke a skill explicitly depends on your Claude Code version — when in doubt, just ask Claude to "run a compliance audit".

## Prerequisite

The plugin invokes `darnit-mcp` via one of two Python runners. **At least one of these must be on `PATH`** when Claude Code launches the plugin's MCP server:

- **`uvx`** (preferred — install [uv](https://docs.astral.sh/uv/getting-started/installation/) and you get `uvx` for free)
- **`pipx`** (fallback — install [pipx](https://pipx.pypa.io/stable/installation/))

If neither is present, the plugin's MCP server exits with `127` and prints a clear message naming both options. No silent failures.

## Install

### From the GitHub release asset

Download `darnit-claude-plugin-0.1.0.zip` from the [release page](https://github.com/kusari-oss/darnit/releases/tag/v0.1.0) and install via the Claude Code plugin URL flag (substitute the actual flag your Claude Code version expects):

```bash
claude --plugin-url \
  https://github.com/kusari-oss/darnit/releases/download/v0.1.0/darnit-claude-plugin-0.1.0.zip
```

### From an unzipped local directory (development)

```bash
curl -L https://github.com/kusari-oss/darnit/releases/download/v0.1.0/darnit-claude-plugin-0.1.0.zip \
  -o darnit-plugin.zip
unzip darnit-plugin.zip   # produces a `darnit/` directory
claude --plugin-dir ./darnit/
```

## Try it

After install, just ask Claude something compliance-related:

```
> Run a compliance audit on this repository.
```

Claude will recognize the request matches the `darnit-audit` skill description, load the skill, and invoke the `audit` tool via the darnit-mcp server. You don't need to know the skill names; the skill descriptions are what Claude reads to make the match.

If you want to inspect what's loaded, the Claude Code UI usually exposes a plugin or skill list — consult your Claude Code version's docs.

## What's in the zip

```
darnit/
├── .claude-plugin/
│   └── plugin.json                # Plugin manifest (auto-loaded by Claude Code)
├── README.md                       # Install instructions (this doc's twin)
├── bin/
│   └── darnit-mcp-runner          # Wrapper that runs uvx → pipx → actionable error
└── skills/
    ├── audit/SKILL.md             # darnit-audit skill (renamed for plugin namespace)
    ├── comply/SKILL.md            # darnit-comply skill
    ├── data/SKILL.md              # darnit-data skill
    └── remediate/SKILL.md         # darnit-remediate skill
```

Skills are auto-discovered by Claude Code from the `skills/` directory — the manifest does not enumerate them.

## Version pinning

The plugin and the `darnit-mcp` Python package it launches are pinned in **lockstep**. Installing `darnit-claude-plugin-0.1.0.zip` always invokes `darnit-mcp==0.1.0` — never floats. This is enforced inside the plugin manifest (`plugin.json::mcpServers["darnit-mcp"].env.DARNIT_MCP_VERSION`).

If you want a newer version, install the newer plugin zip.

## Troubleshooting

| Symptom | Cause |
|---|---|
| Claude doesn't seem to know about darnit when I ask for an audit | The plugin wasn't loaded, or Claude didn't match your request to the skill description. Try being explicit ("use the darnit-audit skill") or check that the plugin is loaded per your Claude Code version's UI. |
| `darnit plugin: neither 'uvx' nor 'pipx' is available on PATH.` | Install [uv](https://docs.astral.sh/uv/getting-started/installation/) OR [pipx](https://pipx.pypa.io/stable/installation/) and restart Claude Code. |
| The agent says it can't reach the darnit MCP server | The runner script ran but `uvx`/`pipx` failed to fetch `darnit-mcp==<version>` from PyPI. Check network access. The wrapper logs the failure to stderr; check Claude Code's MCP server logs. |
| Claude invokes the audit skill but the audit fails immediately | The MCP server probably crashed on startup. Re-run from a shell directly: `DARNIT_MCP_VERSION=0.1.0 CLAUDE_PLUGIN_ROOT=$(pwd)/darnit darnit/bin/darnit-mcp-runner --help` should print darnit-mcp's help and exit 0. |

## Why a plugin instead of just the MCP server?

You could register the darnit MCP server in Claude Code manually (set `mcpServers` in your Claude Code config to invoke `uvx darnit-mcp@0.1.0`). The plugin does this plus:

- **Bundles four skills** — Claude reads their descriptions and knows when to use them automatically, without you having to learn the MCP tool names.
- **Pins the MCP-server version in lockstep with the plugin** — no drift between the plugin's expectations and the server it launches.
- **Surfaces an actionable error** if the user's environment is missing `uvx`/`pipx`, instead of a silent MCP startup failure.

## Not yet supported

- **Anthropic plugin marketplace**: distribution via the public marketplace is a follow-up. For v1, the GitHub release asset is the canonical install path.
- **Other coding agents** (Cursor, Windsurf, Continue, Cline): out of scope. Skills are a Claude Code abstraction. Other agents need to call the darnit MCP server directly — use the [pip](pypi.md) or [container](container.md) install paths and wire the MCP server into the agent's own config.

## Source and license

- Plugin source: [`packaging/claude-plugin/`](https://github.com/kusari-oss/darnit/tree/main/packaging/claude-plugin) in `kusari-oss/darnit`
- Skill source: [`packages/darnit/src/darnit/skills/`](https://github.com/kusari-oss/darnit/tree/main/packages/darnit/src/darnit/skills) (the plugin bundle renames `darnit-X` → `X` for plugin namespacing)
- License: Apache-2.0
