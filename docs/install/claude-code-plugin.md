# Install darnit as a Claude Code plugin

If you're a Claude Code user, the plugin is the cleanest install path. One command and you get four slash commands plus the darnit MCP server, all version-pinned to the same darnit release.

Examples assume version `0.1.0` — substitute the version you want.

## What you get

Once installed:
- **Slash commands** appear in Claude Code:
  - `/darnit:audit` — run a compliance audit on the current repository
  - `/darnit:comply` — full audit + remediate pipeline
  - `/darnit:data` — collect missing project data / context
  - `/darnit:remediate` — apply automated fixes for failing controls
- **MCP server** (`darnit-mcp`) registers automatically. Its tools — `audit`, `remediate`, `list_controls`, and the threat-model, project-data, and remediation helpers — become available to the agent.

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

After install, list available slash commands:

```bash
/help
```

You should see the four `/darnit:*` commands. To actually run one:

```bash
/darnit:audit
```

## What's in the zip

```
darnit/
├── .claude-plugin/
│   └── plugin.json                # Plugin manifest (auto-loaded by Claude Code)
├── README.md                       # Install instructions (this doc's twin)
├── bin/
│   └── darnit-mcp-runner          # Wrapper that runs uvx → pipx → actionable error
└── skills/
    ├── audit/SKILL.md
    ├── comply/SKILL.md
    ├── data/SKILL.md
    └── remediate/SKILL.md
```

## Version pinning

The plugin and the `darnit-mcp` Python package it launches are pinned in **lockstep**. Installing `darnit-claude-plugin-0.1.0.zip` always invokes `darnit-mcp==0.1.0` — never floats. This is enforced inside the plugin manifest (`plugin.json::mcpServers["darnit-mcp"].env.DARNIT_MCP_VERSION`).

If you want a newer version, install the newer plugin zip.

## Troubleshooting

| Symptom | Cause |
|---|---|
| `/darnit:audit` doesn't appear in `/help` | Plugin wasn't loaded. Restart Claude Code; for local installs confirm the `--plugin-dir` path is correct. |
| `darnit plugin: neither 'uvx' nor 'pipx' is available on PATH.` | Install [uv](https://docs.astral.sh/uv/getting-started/installation/) OR [pipx](https://pipx.pypa.io/stable/installation/) and restart Claude Code. |
| The agent says it can't reach the darnit MCP server | The runner script ran but `uvx`/`pipx` failed to fetch `darnit-mcp==<version>` from PyPI. Check network access. The wrapper logs the failure to stderr; check Claude Code's MCP server logs. |
| `/darnit:audit` runs but the agent doesn't see audit tools | The MCP server probably crashed on startup. Re-run from a shell directly: `DARNIT_MCP_VERSION=0.1.0 CLAUDE_PLUGIN_ROOT=$(pwd)/darnit darnit/bin/darnit-mcp-runner --help` should print darnit-mcp's help and exit 0. |

## Why a plugin instead of just the MCP server?

You could register the darnit MCP server in Claude Code manually (set `mcpServers` in your Claude Code config to invoke `uvx darnit-mcp@0.1.0`). The plugin does this plus:

- Bundles the four slash-commands as a single install.
- Pins the MCP-server version in lockstep with the plugin (no drift).
- Surfaces an actionable error if the user's environment is missing `uvx`/`pipx`, instead of a silent MCP startup failure.

## Not yet supported

- **Anthropic plugin marketplace**: distribution via the public marketplace is a follow-up. For v1, the GitHub release asset is the canonical install path.
- **Other coding agents** (Cursor, Windsurf, Continue, Cline): out of scope. Use the [pip](pypi.md) or [container](container.md) install paths instead and configure the agent's MCP integration manually.

## Source and license

- Plugin source: [`packaging/claude-plugin/`](https://github.com/kusari-oss/darnit/tree/main/packaging/claude-plugin) in `kusari-oss/darnit`
- License: Apache-2.0
