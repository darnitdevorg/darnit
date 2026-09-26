# Contract: Drivers, CLI, and MCP

## Flags

| Surface | New or changed |
|---|---|
| All audit-running CLI subcommands (`audit`, `run`, `harness`) | `--operator-config PATH` |
| `darnit serve` | `--operator-config PATH` (distinct from the existing positional framework config) |
| `darnit config show` | Prints the resolved source, digest, permission-check result, and effective settings with secrets redacted. |
| `darnit config migrate [REPO]` | Moves project assertions from `REPO/.baseline.toml` into `REPO/.project/darnit.yaml`; prints a proposed operator-configuration fragment for tool settings. Never writes operator configuration. Refuses to overwrite existing `.project/darnit.yaml` claims for the same control without `--force`. |
| `darnit config trust add IDENTITY` / `trust list` / `trust remove` | Convenience editors for `[trust].repos`, operating only on the operator configuration file. |
| `darnit install` | Writes MCP registrations at user scope by default. A project-scoped registration requires an explicit flag and prints a warning explaining why user scope is recommended. |

## Audit target identity

- CLI and harness: the operator may pass `--repo HOST/NS/NAME` explicitly. Otherwise, outside CI, identity comes from the checkout's `origin` remote and is marked `checkout_hint` (never trusted); inside recognized CI, from CI metadata.
- MCP tools: the tool's `owner`/`repo` (and optional `host`) arguments are the operator target, because the operator's agent supplied them; the checkout's remotes are a hint only.
- A mismatch between the operator target and the checkout's `origin` remote is reported, not silently resolved.

## Report fields (all drivers, all output formats that carry metadata)

```
operator_config: { source, digest, permission_check }
trust: { repository, identity_source, trusted, reason, ci_facts }
ignored_repository_settings: [ { file, key, new_home } ]
```

## MCP server behavior

- On each audit call, the server resolves operator configuration and applies the containment check against that call's target.
- When the server's working directory, or a project directory reported by the agent, lies inside the audited repository, the tool result includes a warning recommending user-scope registration.
- Confirmation of a pending claim is exposed through the existing confirmation tool, extended to accept `control_id` + claim; the confirmation is written to operator-side storage.
