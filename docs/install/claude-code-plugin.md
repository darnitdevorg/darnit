# Install darnit as a Claude Code plugin

If you're a Claude Code user, the plugin is the cleanest install path. One command and you get four namespaced slash commands plus the darnit MCP server, all version-pinned to the same darnit release.

Examples assume version `0.1.0` — substitute the version you want.

## What you get

Once installed, four slash commands appear in Claude Code (the plugin name `darnit` namespaces them):

| Command | What it does |
|---|---|
| `/darnit:darnit-audit` | Run a compliance audit on the current repository |
| `/darnit:darnit-comply` | Full audit + remediate pipeline |
| `/darnit:darnit-data` | Collect missing project data / context |
| `/darnit:darnit-remediate` | Apply automated fixes for failing controls |

> Per the [Claude Code skills docs](https://code.claude.com/docs/en/skills): "By default, both you and Claude can invoke any skill. You can type `/skill-name` to invoke it directly, and Claude can load it automatically when relevant to your conversation." So you can also just ask Claude in natural language ("audit this repo") and Claude will load the right skill from its `description`. Both paths work.

> **Why is it `/darnit:darnit-audit` and not `/darnit:audit`?** The plugin namespace is `darnit:` (from the plugin name) and the skill name is `darnit-audit` (from `packages/darnit/src/darnit/skills/darnit-audit/SKILL.md`). The skill keeps the `darnit-` prefix so it's namespace-safe even when copied into a non-plugin context. Same reason spec-kit names its commands `/speckit.specify` instead of `/specify`.

The plugin also registers the **`darnit-mcp` MCP server**. Its tools (`audit`, `remediate`, `list_controls`, plus threat-model, project-data, and remediation helpers) become available to Claude automatically.

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

## Verify

After install:

```bash
# List available commands — the four /darnit:darnit-* entries should appear
/help

# Or just run one
/darnit:darnit-audit
```

You can also ask Claude in natural language ("run a compliance audit on this repo") and Claude will auto-load the matching skill.

## What's in the zip

```
darnit/
├── .claude-plugin/
│   └── plugin.json                       # Plugin manifest (auto-loaded by Claude Code)
├── README.md                              # Install instructions (this doc's twin)
├── bin/
│   └── darnit-mcp-runner                 # Wrapper: uvx → pipx → actionable error
└── skills/
    ├── darnit-audit/SKILL.md             # → /darnit:darnit-audit
    ├── darnit-comply/SKILL.md            # → /darnit:darnit-comply
    ├── darnit-data/SKILL.md              # → /darnit:darnit-data
    └── darnit-remediate/SKILL.md         # → /darnit:darnit-remediate
```

Skills are auto-discovered by Claude Code from the `skills/` directory — the manifest does not enumerate them.

## Version pinning

The plugin and the `darnit-mcp` Python package it launches are pinned in **lockstep**. Installing `darnit-claude-plugin-0.1.0.zip` always invokes `darnit-mcp==0.1.0` — never floats. This is enforced inside the plugin manifest (`plugin.json::mcpServers["darnit-mcp"].env.DARNIT_MCP_VERSION`).

If you want a newer version, install the newer plugin zip.

## Using darnit's skills with other AI agents

The four skills under `packages/darnit/src/darnit/skills/` follow the open [Agent Skills standard](https://agentskills.io/specification). They're portable to any Agent Skills-compatible client — Cursor, GitHub Copilot, Codex, OpenHands, Gemini CLI, opencode, Goose, and ~30 others (see [agentskills.io](https://agentskills.io) for the full list).

The **plugin wrapper** (the zip with `.claude-plugin/plugin.json`, the MCP server runner, and the version pin) is **Claude-Code-specific**: it relies on Claude Code's plugin manifest format, its MCP-server discovery, and its `${CLAUDE_PLUGIN_ROOT}` substitution. Other agents don't have those.

But the SKILL.md files themselves are agent-agnostic. To use them on a non-Claude-Code agent today, copy the four `darnit-*/` directories from this repo into your agent's skill directory (typically `~/.your-agent/skills/` or a project-local equivalent — consult your agent's docs). You'll lose the auto-installed MCP server and the auto-pinned version, so you'll need to wire up `darnit-mcp` yourself (e.g., `pip install darnit-mcp==<version>` + register it in your agent's MCP config).

A future darnit release may ship a `darnit install-skills [--agent <slug>]` CLI subcommand that automates this, modelled after [spec-kit's `specify init`](https://github.com/github/spec-kit) pattern. Tracked as out-of-scope for v1.

## Not yet supported

- **Anthropic plugin marketplace**: distribution via the public marketplace is a follow-up. For v1, the GitHub release asset is the canonical install path.
- **First-class plugin support on other coding agents**: out of scope. Use the [cross-agent install path](#using-darnits-skills-with-other-ai-agents) above instead.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `/darnit:darnit-audit` doesn't appear in `/help` | Plugin wasn't loaded. Restart Claude Code; for local installs confirm the `--plugin-dir` path is correct. |
| `darnit plugin: neither 'uvx' nor 'pipx' is available on PATH.` | Install [uv](https://docs.astral.sh/uv/getting-started/installation/) OR [pipx](https://pipx.pypa.io/stable/installation/) and restart Claude Code. |
| The agent says it can't reach the darnit MCP server | The runner script ran but `uvx`/`pipx` failed to fetch `darnit-mcp==<version>` from PyPI. Check network access. The wrapper logs the failure to stderr; check Claude Code's MCP server logs. |
| `/darnit:darnit-audit` runs but the agent doesn't see audit tools | The MCP server probably crashed on startup. Re-run from a shell directly: `DARNIT_MCP_VERSION=0.1.0 CLAUDE_PLUGIN_ROOT=$(pwd)/darnit darnit/bin/darnit-mcp-runner --help` should print darnit-mcp's help and exit 0. |

## Why a plugin instead of just the MCP server?

You could register the darnit MCP server in Claude Code manually (set `mcpServers` in your Claude Code config to invoke `uvx darnit-mcp@0.1.0`). The plugin does this plus:

- **Bundles four skills** — both as slash-command shortcuts (`/darnit:darnit-audit`, etc.) and as descriptions Claude can match on for autonomous invocation.
- **Pins the MCP-server version in lockstep** with the plugin — no drift between the plugin's expectations and the server it launches.
- **Surfaces an actionable error** if the user's environment is missing `uvx`/`pipx`, instead of a silent MCP startup failure.

## Source and license

- Plugin source: [`packaging/claude-plugin/`](https://github.com/kusari-oss/darnit/tree/main/packaging/claude-plugin) in `kusari-oss/darnit`
- Skill source: [`packages/darnit/src/darnit/skills/`](https://github.com/kusari-oss/darnit/tree/main/packages/darnit/src/darnit/skills)
- License: Apache-2.0
