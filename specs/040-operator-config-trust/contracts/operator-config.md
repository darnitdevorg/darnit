# Contract: Operator Configuration File

## Location resolution (all drivers)

1. `--operator-config PATH` given at launch (CLI subcommands, `darnit serve`, `darnit harness`).
2. Otherwise the default location:
   - Linux/macOS: `$XDG_CONFIG_HOME/darnit/config.toml` if `XDG_CONFIG_HOME` is set and absolute, else `~/.config/darnit/config.toml`.
   - Windows: `%APPDATA%\darnit\config.toml`.
3. Otherwise built-in defaults.

The resolved real path is refused if it lies inside the audited repository (checked per audit). A missing default file is not an error; a missing explicit path is.

## Format

TOML. Every table forbids unknown keys. Errors name the file and the dotted key.

```toml
schema_version = 1

[plugins]
allowed = ["openssf-baseline", "reproducibility"]   # empty or absent: all installed
trusted_publishers = ["https://github.com/darnitdevorg"]
allow_unsigned = false

[mcp_servers.scanner]
command = ["scanner-mcp", "--stdio"]
env = { SCANNER_TOKEN = "SCANNER_TOKEN" }          # value names an environment variable
trusted_publisher = "https://github.com/example"

[controls."OSPS-DO-01.01"]
passes = [ { handler = "file_exists", files = ["README.md", "README.rst"] } ]

[stores.report]
backend = "filesystem"

[llm]
provider = "anthropic"
model = "claude-sonnet-5"
max_cost_usd_per_run = 2.00

[trust]
repos = ["github.com/example/project"]
case_insensitive_hosts = ["git.example.com"]
ci = [ { event = "push-default-branch" } ]

[operator]
identity = "alice@example.com"                   # recorded as confirmed_by; defaults to the OS user

[policy]
confirmation_expiry_days = 180
strict_permissions = true                         # may only turn strict mode ON; see below
```

## Guarantees

- Nothing in the audited repository can add to, override, or select this configuration.
- There is no environment variable that grants trust to repository content.
- Every report records `operator_config.source` (path or `builtin-defaults`) and `operator_config.digest` (SHA-256 of the file bytes). Secrets never appear in the file, so the digest is safe to publish.

## Permission check (POSIX)

The file and each parent directory up to the user's home (or filesystem root) must be owned by the current user or root and must not be group- or world-writable.

Strict mode is on when `--strict-operator-config` is given at launch, when running in recognized CI, or when the file sets `policy.strict_permissions = true`. The file cannot turn strict mode off, because a file that fails the check is exactly the file that must not be trusted to relax it.

| Result | Strict mode off | Strict mode on |
|---|---|---|
| Pass | load | load |
| Fail | warn, load | refuse, exit non-zero |
| Not checkable (Windows) | warn, load | refuse |
