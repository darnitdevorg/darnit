# Contract: Claude Code Plugin

## Scope

Publishes a Claude Code plugin artifact `darnit-claude-plugin-<version>.zip` attached to each **stable** GitHub Release. Pre-release tags do not produce a plugin artifact (per clarification Q2).

The plugin name is `darnit`. Once installed, Claude Code auto-discovers four **agentic skills** under `skills/`. Per the [Claude Code skills spec](https://docs.claude.com/claude-code/skills), skills are **model-invoked** by default — Claude reads each skill's frontmatter `description` and decides when to load the skill from the user's natural-language request. Skills are **not slash commands**; the plugin namespace (`darnit:`) is what Claude uses internally to disambiguate skills across plugins.

## Artifact contents

```
darnit-claude-plugin-<version>.zip
├── .claude-plugin/
│   └── plugin.json                # Claude Code plugin manifest (auto-discovered)
├── README.md                       # Install instructions
├── bin/
│   └── darnit-mcp-runner          # Wrapper script: uvx → pipx run → actionable error
└── skills/
    ├── darnit-audit/
    │   └── SKILL.md               # → /darnit:darnit-audit
    ├── darnit-comply/
    │   └── SKILL.md               # → /darnit:darnit-comply
    ├── darnit-data/
    │   └── SKILL.md               # → /darnit:darnit-data
    └── darnit-remediate/
        └── SKILL.md               # → /darnit:darnit-remediate
```

**Skills are auto-discovered** by Claude Code from the `skills/` directory at the plugin root. The plugin manifest does **not** enumerate them.

**Skill names**: copied verbatim from `packages/darnit/src/darnit/skills/` — no rename. The [Agent Skills standard](https://agentskills.io/specification) requires the parent directory name and the frontmatter `name:` field to match, and the `darnit-` prefix keeps the skills namespace-safe even when used outside the plugin wrapper (e.g., copied directly into `~/.claude/skills/` for non-plugin Claude Code use, or into another Agent Skills client's skill directory). The plugin-namespaced invocation form is `/darnit:darnit-audit` — slightly redundant aesthetically, but spec-compliant, unambiguous, and consistent with the same pattern spec-kit uses for its commands (`/speckit.specify`).

A CI check asserts the bundle's `skills/` directory contains exactly `{darnit-audit, darnit-comply, darnit-data, darnit-remediate}`. Adding or removing skills mid-release is a deliberate change to the contract and requires updating this document.

## Manifest shape

`packaging/claude-plugin/plugin.json` (templated; `<version>` substituted by the release workflow). Lives at `.claude-plugin/plugin.json` inside the bundle.

```json
{
  "name": "darnit",
  "version": "<version>",
  "description": "AI-powered compliance auditing for the OpenSSF Baseline and related frameworks.",
  "author": {
    "name": "Kusari",
    "email": "info@kusari.dev"
  },
  "homepage": "https://github.com/kusari-oss/darnit",
  "repository": "https://github.com/kusari-oss/darnit",
  "license": "Apache-2.0",
  "keywords": ["security", "compliance", "openssf", "baseline", "audit"],
  "mcpServers": {
    "darnit-mcp": {
      "command": "${CLAUDE_PLUGIN_ROOT}/bin/darnit-mcp-runner",
      "args": [],
      "env": {
        "DARNIT_MCP_VERSION": "<version>"
      }
    }
  }
}
```

> **Note**: Field names track the published Claude Code plugin spec at the time of v1 implementation (`.claude-plugin/plugin.json`, `mcpServers`, skills auto-discovered from `skills/`). If the schema changes before v1 ships, the implementation MUST update this contract and `packaging/claude-plugin/plugin.json` in lockstep.

## MCP server invocation (implements FR-017)

Claude Code's plugin manifest does **not** support a fallback chain natively. The contract uses a wrapper script that the manifest invokes:

`packaging/claude-plugin/bin/darnit-mcp-runner`:

```bash
#!/bin/sh
# Wrapper invoked by the Claude Code plugin to start darnit-mcp.
# DARNIT_MCP_VERSION is set by plugin.json's mcpServers.env.
set -eu
exec_via_uvx() {
    command -v uvx >/dev/null 2>&1 || return 1
    exec uvx --from "darnit-mcp==${DARNIT_MCP_VERSION}" darnit-mcp
}
exec_via_pipx() {
    command -v pipx >/dev/null 2>&1 || return 1
    exec pipx run "darnit-mcp==${DARNIT_MCP_VERSION}"
}
exec_via_uvx 2>/dev/null
exec_via_pipx 2>/dev/null
echo "darnit plugin: neither 'uvx' nor 'pipx' is available on PATH." >&2
echo "Install one of:" >&2
echo "  - uv (provides uvx):  https://docs.astral.sh/uv/getting-started/installation/" >&2
echo "  - pipx:               https://pipx.pypa.io/stable/installation/" >&2
exit 127
```

The runner is `chmod +x` at build time, and `plugin.json` references it via `${CLAUDE_PLUGIN_ROOT}` so the path resolves regardless of where Claude Code installs the plugin.

Version pinning (`darnit-mcp==<version>`) is **mandatory** — the plugin and the runtime must be in lockstep. A plugin v0.1.0 invoking `darnit-mcp` without a version pin would silently float to whatever PyPI ships next, violating spec FR-004 (version match across channels).

## Smoke test

### Structural smoke (always)

```bash
unzip -t darnit-claude-plugin-<version>.zip                                # zip integrity

unzip -p darnit-claude-plugin-<version>.zip .claude-plugin/plugin.json \
  | jq -e '.version == "<version>"'                                        # version pin

unzip -p darnit-claude-plugin-<version>.zip .claude-plugin/plugin.json \
  | jq -e '.mcpServers["darnit-mcp"].env.DARNIT_MCP_VERSION == "<version>"'  # MCP version pin

# skill set matches the contract
unzip -l darnit-claude-plugin-<version>.zip \
  | awk '/skills\/[a-z]+\/SKILL\.md$/ {sub("^.*skills/",""); sub("/SKILL.md$",""); print}' \
  | sort \
  | diff - <(printf 'darnit-audit\ndarnit-comply\ndarnit-data\ndarnit-remediate\n')

# wrapper script is executable
unzip -l darnit-claude-plugin-<version>.zip bin/darnit-mcp-runner \
  | grep -q '^-rwx'
```

### Behavioral smoke

`release-smoke.yml` extracts the bundle into a tempdir and invokes the wrapper directly:

```bash
# In a container with uvx installed:
DARNIT_MCP_VERSION=<version> CLAUDE_PLUGIN_ROOT=<extracted-dir> \
  <extracted-dir>/bin/darnit-mcp-runner --help
```

That exercises the same fallback chain Claude Code would hit, without depending on Anthropic's plugin test harness.

When (and if) Anthropic ships a publicly available plugin test harness, the behavioral smoke can be extended to install the plugin into a hermetic Claude Code instance and confirm all four `/darnit:<skill>` commands resolve.

## What this contract does not promise

- **Distribution via Anthropic's plugin marketplace.** v1 distributes via the GitHub Release asset; users install with `claude --plugin-url https://github.com/kusari-oss/darnit/releases/download/v<X.Y.Z>/darnit-claude-plugin-<X.Y.Z>.zip` (or whatever incantation Claude Code currently supports). Marketplace submission is a follow-up.
- **Cross-agent compatibility** (Cursor, Windsurf, etc.). Out of scope per spec Assumptions.
- **Bundled standalone binary fallback.** Tracked as follow-up per clarification Q1 / Out of Scope.
