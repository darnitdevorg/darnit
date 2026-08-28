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

The `regex` handler has three internal code paths, each with a
different evidence shape. Which one fires depends on config:

**Standard match path** -- the default, used when `files` resolve to
existing content and `pattern`/`patterns` is set:

| Variable                    | Type                    | Description                                                          |
|-----------------------------|-------------------------|----------------------------------------------------------------------|
| `output.files_checked`      | int                     | Count (NOT list) of files scanned                                    |
| `output.patterns_checked`   | list<string>            | Names of the patterns evaluated                                      |
| `output.any_match`          | bool                    | True if any pattern matched in any file                              |
| `output.results`            | list<dict>              | Up to 20 per-(file, pattern) records: `file`, `pattern_name`, `pattern`, `match_count`, `matched`, `matches_preview` |

**Exclude-globs path** -- used when the pass sets `exclude_globs`
instead of `pattern`s to test:

| Variable               | Type            | Description                                                        |
|------------------------|-----------------|--------------------------------------------------------------------|
| `output.exclude_globs` | list<string>    | The globs the pass declared                                        |
| `output.files_found`   | int             | Number of files that matched an exclude glob                       |
| `output.found_files`   | list<string>    | Up to 10 relative paths of the matched files                       |

**No-files path** -- when the pass's `files` list resolves to zero
matches on disk. Returns INCONCLUSIVE and only exposes:

| Variable                | Type          | Description                                       |
|-------------------------|---------------|---------------------------------------------------|
| `output.files_checked`  | list<string>  | The candidate list that produced no matches       |

The `matches` field the CLAUDE.md notes referenced is not present in
the current handler's evidence -- per-file match detail lives inside
`output.results[]` on the match path. `output.files_checked` is an
`int` on the match path and a `list[string]` on the no-files path;
guard with `has()` or a type check before deep access.

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
`result.*`. `project.*`/`repo.*`/`context.*` are also NOT available
here (see the next section for why).

### Handlers that do NOT evaluate `expr`

`llm_eval`, `llm_extract`, `manual_steps`, `file_create`, `api_call`,
`project_update`, `yaml_inject` do not run a post-step CEL evaluator on
their evidence. Writing an `expr` on their pass config is silently
ignored today; use the handler's own config keys to shape the verdict.

## What is NOT bound in `expr`

The [`CELContext`](../packages/darnit/src/darnit/sieve/cel_evaluator.py)
dataclass declares fields for ambient bindings (`project`, `repo`,
`context`, `files`, `matches`, `response`) that a full-context CEL
call would receive. **None of these are populated on the `expr` path
used by controls today.**

The post-step `expr` evaluator at
[`orchestrator.py:130`](../packages/darnit/src/darnit/sieve/orchestrator.py)
builds its context as literally
`{"output": handler_result.evidence or {}}` -- only `output` is bound.
The `mcp` handler's in-handler CEL similarly binds only
`{"result": raw_response}`
([`_eval_cel_over_result`](../packages/darnit/src/darnit/sieve/builtin_handlers.py)).
Neither path constructs a `CELContext`, so referring to `project.*` or
`repo.*` in an `expr` fails with `undeclared reference to 'project'`.
CEL failure logs a warning and preserves the handler's original
verdict ([`_apply_cel_expr`](../packages/darnit/src/darnit/sieve/orchestrator.py)),
so a broken reference produces a silent no-op rather than a visible
error -- worth flagging in your control tests.

If you need a project-context-scoped skip, put the check on the
control's `when` field instead of the pass's `expr`:

```toml
[controls."OSPS-XX-YY"]
when = { language = "python" }
```

`when` runs against the audit's full project context before the
pass loop starts; `expr` runs on the trimmed post-step context and
does not.

## Bindings that WOULD be available if a caller passes a full CELContext

For completeness -- these are wired in the code but no
production caller (post-step, mcp) uses them today:

| Variable    | Type                      | Populated when                                                  |
|-------------|---------------------------|-----------------------------------------------------------------|
| `project.*` | dict                      | `.project/project.yaml` was read for this audit run             |
| `repo.*`    | dict (path, owner, name)  | Set by the audit driver on every audit                          |
| `context.*` | dict                      | Values the user answered via `darnit collect-context` / harness |

If these ever get wired into the post-step path, existing controls
that reference them today (there are currently none in the shipped
framework) would start seeing them. Track that change here.

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
- **Project-scoped skip:** put `project.language == "python"` on the control's `when` field, not on a pass's `expr` -- `expr` cannot see `project.*` in the post-step path (see "What is NOT bound in `expr`" above).

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
