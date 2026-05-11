# Contract: Claude Code Plugin

## Scope

Publishes a Claude Code plugin artifact `darnit-claude-plugin-<version>.zip` attached to each **stable** GitHub Release. Pre-release tags do not produce a plugin artifact (per clarification Q2).

## Artifact contents

```
darnit-claude-plugin-<version>.zip
├── manifest.json                       # Claude Code plugin manifest
├── README.md                            # Install instructions
└── skills/
    ├── darnit-audit/
    │   └── SKILL.md
    ├── darnit-context/
    │   └── SKILL.md
    ├── darnit-comply/
    │   └── SKILL.md
    └── darnit-remediate/
        └── SKILL.md
```

The `skills/` tree is copied verbatim from the repo root `skills/` at the tagged commit. A CI check asserts the set is exactly `["darnit-audit", "darnit-context", "darnit-comply", "darnit-remediate"]`. Adding or removing skills mid-release is a deliberate change to the contract and requires updating this document.

## Manifest shape

`packaging/claude-plugin/manifest.json` (templated; `<version>` substituted by the release workflow):

```json
{
  "name": "darnit",
  "displayName": "Darnit Compliance Auditor",
  "version": "<version>",
  "description": "AI-driven compliance auditing for the OpenSSF Baseline and related frameworks.",
  "publisher": "kusari-oss",
  "license": "Apache-2.0",
  "homepage": "https://github.com/kusari-oss/darnit",
  "mcpServers": {
    "darnit": {
      "command": "sh",
      "args": [
        "-c",
        "uvx --from darnit-mcp==<version> darnit-mcp 2>/dev/null || pipx run darnit-mcp==<version> 2>/dev/null || (echo 'darnit plugin: neither uvx nor pipx is available on PATH. Install one of: https://docs.astral.sh/uv/ or https://pipx.pypa.io/' >&2; exit 1)"
      ]
    }
  },
  "skills": [
    {"path": "skills/darnit-audit"},
    {"path": "skills/darnit-context"},
    {"path": "skills/darnit-comply"},
    {"path": "skills/darnit-remediate"}
  ]
}
```

> **Note**: The exact field names (`mcpServers`, `skills`, etc.) track the Claude Code plugin spec as published at the time of v1 implementation. If the schema names change before v1 ships, the implementation MUST update this contract and `packaging/claude-plugin/manifest.json` in lockstep.

## MCP server invocation (implements FR-017)

The `command`/`args` shell snippet implements the three-tier fallback resolved in clarification Q1:

1. Attempt `uvx --from darnit-mcp==<version> darnit-mcp`. Suppress stderr from this attempt (it should not pollute the agent's view when the next attempt succeeds).
2. On failure, attempt `pipx run darnit-mcp==<version>`. Same stderr suppression.
3. On second failure, emit a single, actionable error to stderr naming both prerequisites and their install URLs, and exit non-zero.

Version pinning (`==<version>`) is **mandatory** — the plugin and the runtime must be in lockstep. A plugin v0.1.0 invoking `uvx darnit-mcp` (no version) would silently float to whatever PyPI ships next, violating spec FR-004 (version match across channels).

## Smoke test

Runs in `release-smoke.yml` on a hermetic Claude Code test environment (mechanism TBD with Anthropic's plugin testing tooling; if no such tool is publicly available at v1, the smoke test does a structural validation only — JSON-schema check + zip integrity + exit-code check on the MCP server command — and a manual smoke-test step is added to `packaging/RECOVERY.md`).

Structural smoke (always):

```bash
unzip -t darnit-claude-plugin-<version>.zip                       # zip integrity
jq -e '.version == "<version>"' manifest.json                     # version pin
jq -e '.skills | length == 4' manifest.json                       # skill count
diff <(jq -r '.skills[].path' manifest.json | sort) \
     <(ls skills | sort | sed 's|^|skills/|')                     # skill paths match contents
```

Behavioral smoke (when Claude Code testing tooling is available):

```bash
# pseudo-code; exact incantation depends on Anthropic's tooling
claude-code-plugin install ./darnit-claude-plugin-<version>.zip
claude-code-plugin list-skills | grep -c '^darnit-' | grep -q '^4$'
```

## What this contract does not promise

- **Distribution via the official Claude Code plugin marketplace** (when it exists). v1 distributes via the GitHub Release asset; marketplace submission is a follow-up.
- **Cross-agent compatibility** (Cursor, Windsurf, etc.). Out of scope per spec Assumptions.
- **Bundled standalone binary fallback**. Tracked as follow-up per clarification Q1 / Out of Scope.
