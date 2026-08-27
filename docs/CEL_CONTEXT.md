# CEL Context Reference for Control Authors

This page lists every context variable and custom function available in
a CEL `expr` field on a control pass. If you are authoring a new
control, this is the reference. If you are grepping other controls for
"what can I write in `expr`?", start here instead.

Cross-linked from [`docs/HANDLER_AUTHORING.md`](./HANDLER_AUTHORING.md)
and [`docs/architecture/framework-design.md`](./architecture/framework-design.md).

## Where `expr` runs

Two placement rules:

1. **Post-handler CEL (most passes).** After the pass's `handler` runs,
   the orchestrator evaluates `expr` against the handler's evidence
   (see [`orchestrator.py`](../packages/darnit/src/darnit/sieve/orchestrator.py)).
   Truthy `expr` + PASS = PASS. Falsy `expr` + PASS = INCONCLUSIVE
   (handler and CEL disagree; keep going down the pass list). See
   [`specs/020-definitive-fail-verdict/contracts/cel-post-step.md`](../specs/020-definitive-fail-verdict/contracts/cel-post-step.md)
   for the full truth table.

2. **In-handler CEL (`mcp` only).** `handler = "mcp"` evaluates `expr`
   against the JSON result of the MCP tool call before deciding
   PASS/FAIL. See
   [`_eval_cel_over_result` in `builtin_handlers.py`](../packages/darnit/src/darnit/sieve/builtin_handlers.py).

## Available variables per handler

The variables a CEL expression can reference depend on which handler
produced the evidence.

### `exec` handler

The runtime injects `output.*` from the subprocess result:

| Variable            | Type              | Description                                                                            |
|---------------------|-------------------|----------------------------------------------------------------------------------------|
| `output.stdout`     | string            | First 2000 chars of stdout                                                             |
| `output.stderr`     | string            | First 2000 chars of stderr                                                             |
| `output.exit_code`  | int               | Subprocess exit code                                                                   |
| `output.command`    | list<string>      | Resolved command (after `$VAR` substitution)                                           |
| `output.json`       | any               | Parsed JSON body -- only present when the pass sets `output_format = "json"` AND stdout parses cleanly |

```toml
# Exit-code + stdout non-empty
{ handler = "exec", command = ["git", "tag", "--list", "v*"], expr = 'output.stdout != ""' }

# JSON-body assertion (declare output_format so `output.json` is populated)
[[controls."OSPS-AC-01.01".passes]]
handler = "exec"
command = ["gh", "api", "/orgs/$OWNER/settings"]
output_format = "json"
expr = 'has(output.json.two_factor_requirement_enabled) && output.json.two_factor_requirement_enabled == true'
```

Guard `output.json.foo` access with `has()`; a missing key raises a CEL
evaluation error, not a false PASS.

### `file_exists` handler

`output.*` carries the file-presence outcome:

| Variable                | Type         | Description                                                        |
|-------------------------|--------------|--------------------------------------------------------------------|
| `output.found_file`     | string       | Absolute path of the match (present only when the handler PASSes)  |
| `output.relative_path`  | string       | Path relative to repo root                                         |
| `output.files_checked`  | list<string> | Every candidate the handler looked at                              |

Most `file_exists` passes need no `expr` (the presence check is
already the verdict). Reach for CEL only when you want to constrain
which file matched, e.g. `expr = 'output.relative_path == "SECURITY.md"'`.

### `regex` handler (`pattern` alias)

| Variable                | Type                       | Description                                                |
|-------------------------|----------------------------|------------------------------------------------------------|
| `output.files_found`    | int                        | Number of files matched                                    |
| `output.found_files`    | list<string>               | Relative paths of files that matched at least one pattern  |
| `output.files_checked`  | list<string>               | Files the handler scanned                                  |

The `matches` field the CLAUDE.md notes referenced is not present in
the current handler's evidence -- match structure lives inside the
handler's confidence + evidence shaping. If you need per-file match
detail in `expr`, add it to the handler's evidence first.

### `mcp` handler

`expr` is evaluated against the raw JSON return of the MCP tool. The
top-level variable is `result`, so:

```toml
[[controls."OSPS-XX-YY".passes]]
handler = "mcp"
server = "scorecard"
tool = "get_repo_score"
args = { owner = "$OWNER", repo = "$REPO" }
expr = 'result.score >= 7.0'
```

There is no `output.*` binding for `handler = "mcp"` passes -- only
`result.*` and any project/repo bindings below.

### Handlers that do NOT evaluate `expr`

`llm_eval`, `llm_extract`, `manual_steps`, `file_create`, `api_call`,
`project_update`, `yaml_inject` do not run a post-step CEL evaluator on
their evidence. Writing an `expr` on their pass config is silently
ignored today; use the handler's own config keys to shape the verdict.

## Bindings available regardless of handler

The [`CELContext`](../packages/darnit/src/darnit/sieve/cel_evaluator.py)
dataclass carries additional bindings the runtime can inject when the
orchestrator constructs a full context (not the trimmed post-step
context most passes see). Ambient bindings that a control author may
reference:

| Variable    | Type                      | Populated when                                                  |
|-------------|---------------------------|-----------------------------------------------------------------|
| `project.*` | dict                      | `.project/project.yaml` was read for this audit run             |
| `repo.*`    | dict (path, owner, name)  | Set by the audit driver on every audit                          |
| `context.*` | dict                      | Values the user answered via `darnit collect-context` / harness |

Typical use:

```toml
# Only apply this pass when project language is Python
{ handler = "exec", command = ["python", "-c", "print('ok')"], expr = 'project.language == "python"' }
```

`project.*` is populated from the `.project/` reader
([`dot_project.py`](../packages/darnit/src/darnit/context/dot_project.py))
plus any control-side auto-detected values (`language`,
`ci_provider`, `platform`).

## Custom CEL functions

Both are registered in
[`CELEvaluator._build_custom_functions()`](../packages/darnit/src/darnit/sieve/cel_evaluator.py).

### `file_exists(path: string) -> bool`

Returns true if `path`, resolved relative to the repo root, exists.
Useful as a boolean guard inside a larger expression:

```toml
# Only PASS if the release-workflow file AND a CHANGELOG both exist
expr = 'file_exists(".github/workflows/release.yml") && (file_exists("CHANGELOG.md") || file_exists("CHANGES.md"))'
```

Returns `false` (never raises) if the repo path is unavailable to the
evaluator.

### `json_path(obj: any, path: string) -> any`

Evaluates a [JMESPath](https://jmespath.org/) expression against `obj`.
Returns the extracted value or `null` on any failure (missing key,
type mismatch, invalid JMESPath).

```toml
[[controls."OSPS-XX-YY".passes]]
handler = "exec"
command = ["gh", "api", "/repos/$OWNER/$REPO/branches/main/protection"]
output_format = "json"
expr = 'json_path(output.json, "required_pull_request_reviews.required_approving_review_count") >= 1'
```

## Common patterns

- **Exit-code + stdout combined:** `output.exit_code == 0 && output.stdout != ""`
- **JSON field with guard:** `has(output.json.foo) && output.json.foo == "expected"`
- **Negated grep (exec):** `!output.stdout.contains("suspicious-string")`
- **Prefix / suffix:** `output.stdout.startsWith("https://")` /
  `output.stdout.endsWith(".pem")`
- **Substring:** `output.stdout.contains("bazel")`
- **File-existence as a guard:** `file_exists("Dockerfile") && output.exit_code == 0`
- **JMESPath extraction:** `json_path(output.json, "runs[0].tool.driver.version")`
- **Project-scoped when clause:** `project.language == "python"` (put this on a `when` field, not `expr`, if you want the whole pass to be skipped rather than resolved INCONCLUSIVE)

## Getting a CEL error

If your expression fails to evaluate (unknown identifier, type
mismatch, missing custom function), the orchestrator logs a warning
and preserves the handler's original verdict. It does NOT flip PASS to
FAIL. Failing CEL is an authoring bug the log surfaces; check the
darnit audit log at `--log-level=DEBUG` if a pass isn't behaving as
you expect.

## Not covered here

- **Sandboxing / timeouts:** CEL runs under a 1-second default timeout
  ([`DEFAULT_TIMEOUT_SECONDS`](../packages/darnit/src/darnit/sieve/cel_evaluator.py)).
  Bump on the `CELEvaluator` init; TOML has no per-pass override yet.
- **New context variables:** adding a variable is a `CELContext` change,
  not a docs change; see the spec-implementation sync gate.
