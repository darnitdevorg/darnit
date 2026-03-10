# CEL Expression Reference

CEL (Common Expression Language) is used in darnit TOML configurations to evaluate pass results. This reference covers syntax, context variables, and common pitfalls.

## Where CEL is Used

CEL expressions appear in the `expr` field of TOML `[[passes]]` entries:

```toml
[[controls."MY-01".passes]]
handler = "exec"
command = ["gh", "api", "/repos/$OWNER/$REPO"]
output_format = "json"
expr = 'output.json.private == false'
```

After any handler runs, the orchestrator evaluates the `expr` field:
- CEL evaluates to `true` → **PASS**
- CEL evaluates to `false` → **INCONCLUSIVE** (pipeline continues to next pass)
- CEL evaluation error → falls through to handler's exit code / default behavior

## Syntax Rules

CEL uses **C/Java-style syntax**, NOT Python syntax.

### Boolean operators

| Operator | CEL | Python (WRONG) |
|----------|-----|----------------|
| AND | `&&` | ~~`and`~~ |
| OR | `\|\|` | ~~`or`~~ |
| NOT | `!` | ~~`not`~~ |

```
# CORRECT
expr = 'output.json.enabled == true && output.exit_code == 0'
expr = '!(output.any_match)'

# WRONG — will cause parse errors
expr = 'output.json.enabled == true and output.exit_code == 0'
expr = 'not output.any_match'
```

### Comparison operators

Standard C-style: `==`, `!=`, `<`, `>`, `<=`, `>=`

### String operations

```
# Contains
output.stdout.contains("success")

# Starts with / ends with
output.stdout.startsWith("OK")
output.stdout.endsWith(".md")

# Size
output.stdout.size() > 0
```

### List operations

```
# Size
output.json.items.size() > 0

# Check if list contains value
"admin" in output.json.roles

# Exists (any element matches)
output.json.items.exists(x, x.name == "README.md")
```

## Available Context Variables

### For `exec` handler

| Variable | Type | Description |
|----------|------|-------------|
| `output.stdout` | string | Standard output from command |
| `output.stderr` | string | Standard error from command |
| `output.exit_code` | int | Exit code from command |
| `output.json` | object | Parsed JSON (when `output_format = "json"`) |

### For `pattern` handler

| Variable | Type | Description |
|----------|------|-------------|
| `output.any_match` | bool | Whether any content pattern matched |
| `output.files_found` | int | Number of files matching file_patterns |
| `output.matches` | object | Per-pattern match results |

### For API responses

| Variable | Type | Description |
|----------|------|-------------|
| `response.status_code` | int | HTTP status code |
| `response.body` | string | Response body |
| `response.headers` | object | Response headers |

### Project context

| Variable | Type | Description |
|----------|------|-------------|
| `project.*` | various | Values from `.project/project.yaml` |

## Custom Functions

| Function | Signature | Purpose |
|----------|-----------|---------|
| `file_exists(path)` | `string → bool` | Check if file exists at path |
| `json_path(obj, path)` | `object, string → value` | Extract value using dotted path |

## TOML String Escaping

This is the most common source of bugs. TOML has two string types relevant to CEL:

### Literal strings (single-quoted) — PREFERRED

In TOML literal strings (`'...'`), backslashes are **literal characters**. No escape processing occurs.

```toml
# What you write in TOML → What CEL receives
expr = 'output.stdout.matches("version\\s+\\d+\\.\\d+")'
#                                                  ^^
# WRONG — this sends two backslashes to CEL

expr = 'output.stdout.matches("version\s+\d+\.\d+")'
#                                              ^^
# CORRECT — CEL receives \. which is regex for "literal dot"
```

**Rule**: In literal strings, `\.` in TOML = `\.` in CEL regex (matches literal dot).

### Basic strings (double-quoted)

In TOML basic strings (`"..."`), backslashes ARE escape characters. You need double escaping:

```toml
expr = "output.stdout.matches(\"version\\s+\\d+\\\\.\\d+\")"
# Messy — avoid this. Use literal strings instead.
```

### Common escaping mistakes

| TOML literal string | CEL receives | Regex meaning |
|---------------------|-------------|---------------|
| `'\.'` | `\.` | Literal dot |
| `'\\.'` | `\\.` | Backslash + any char (WRONG) |
| `'\n'` | `\n` | Newline |
| `'\\n'` | `\\n` | Literal backslash + n |

**Bottom line**: In TOML literal strings, use `\.` not `\\.` for regex literal dots.

## Common Pitfalls

### 1. Using Python-style boolean operators

```toml
# WRONG — CEL parse error
expr = 'not output.any_match'
expr = 'output.json.enabled and output.exit_code == 0'

# CORRECT
expr = '!(output.any_match)'
expr = 'output.json.enabled && output.exit_code == 0'
```

### 2. Over-escaping in TOML literal strings

```toml
# WRONG — sends \\ to CEL regex
expr = 'output.stdout.matches("v\\d+\\.\\d+")'

# CORRECT — sends \ to CEL regex
expr = 'output.stdout.matches("v\d+\.\d+")'
```

### 3. Missing parentheses with negation

```toml
# Ambiguous — add explicit parentheses
expr = '!output.any_match'

# Clear
expr = '!(output.any_match)'
```

### 4. Accessing nested JSON without null checks

```toml
# May error if output.json is null or missing key
expr = 'output.json.settings.enabled == true'

# Safer — check key exists first
expr = 'has(output.json.settings) && output.json.settings.enabled == true'
```

### 5. Comparing with wrong types

```toml
# WRONG — exit_code is int, "0" is string
expr = 'output.exit_code == "0"'

# CORRECT
expr = 'output.exit_code == 0'
```

## Examples from OpenSSF Baseline

```toml
# Simple boolean check
expr = 'output.json.two_factor_requirement_enabled == true'

# Negated match (file should NOT exist)
expr = 'output.files_found == 0'

# Combined check
expr = 'output.exit_code == 0 && output.json.default_branch_protection.enabled == true'

# Pattern match result
expr = 'output.any_match'

# Negated pattern match
expr = '!(output.any_match)'
```

## Next Steps

- [Implementation Development](implementation-development.md) — Full implementation guide
- [Tutorial: Add a New Control](../tutorials/add-new-control.md) — Use CEL in practice
- Back to [Getting Started](README.md)
