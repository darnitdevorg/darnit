# Handler Authoring Guide

This guide is the shortest path from "I need a new control" to "I have a
working control and a handler I can test." It complements
[`docs/IMPLEMENTATION_GUIDE.md`](./IMPLEMENTATION_GUIDE.md), which covers the
full plugin lifecycle in more detail.

Use this guide when you are:

- adding a new TOML control
- choosing between a built-in pass and a custom Python handler
- testing one control at a time while iterating

## Before You Start

Two current naming details are worth knowing up front:

- The built-in file-presence sieve handler registered in code is
  `file_exists`.
- Some older docs and example TOML still say `file_must_exist`. For new
  controls, prefer `file_exists` unless the framework reintroduces an alias.

The current built-in handler names are defined in
`packages/darnit/src/darnit/sieve/builtin_handlers.py`:

- `file_exists`
- `exec`
- `regex`
- `pattern` (alias for `regex`)
- `manual`
- `manual_steps` (same underlying handler as `manual`)

## 1. TOML Control Anatomy

Most controls should start in TOML. A control needs:

- an ID under `[controls."..."]`
- a `name`
- a `description`
- `tags` for filtering and grouping
- one or more `[[controls."...".passes]]` blocks

Here is a complete runnable control using only built-in handlers:

```toml
[metadata]
name = "mini-standard"
display_name = "Mini Standard"
version = "0.1.0"
schema_version = "0.1.0-alpha"
spec_version = "v0"
description = "Minimal framework for local handler authoring"

[controls."MS-DOC-01"]
name = "ReadmeExists"
description = "Project has a README file"
tags = { level = 1, domain = "DOC", documentation = true }

[[controls."MS-DOC-01".passes]]
handler = "file_exists"
files = ["README.md", "README.rst"]

[[controls."MS-DOC-01".passes]]
handler = "manual"
steps = [
    "Open the README and confirm it explains what the project does",
]
```

How this pipeline works:

1. `file_exists` gives a fast deterministic answer for README presence.
2. `manual` is the fallback when automation cannot prove the control.

The audit pipeline stops on the first conclusive result (`PASS` or `FAIL`).

## 2. Built-In Pass Types

### `file_exists`

Use for file or directory presence checks:

```toml
[[controls."MS-DOC-01".passes]]
handler = "file_exists"
files = ["README.md", ".github/workflows"]
```

Notes:

- `files` accepts literal paths and globs.
- A matching directory counts as existing.
- The handler returns evidence like `found_file` and `relative_path`.

### `exec`

Use when you need a command result and want to evaluate it declaratively:

```toml
[[controls."MS-CI-01".passes]]
handler = "exec"
command = ["python", "-c", "import json; print(json.dumps({'enabled': True}))"]
output_format = "json"
expr = "output.json.enabled == true"
```

Useful config keys:

- `command`
- `pass_exit_codes`
- `fail_exit_codes`
- `timeout`
- `env`
- `cwd`
- `output_format = "json"` when you want `output.json` in CEL

Because the pipeline stops on the first conclusive result, put more expensive
or more contextual passes later only when earlier passes may return
`INCONCLUSIVE`.

### `regex` / `pattern`

Use for content matching in one or more files:

```toml
[[controls."MS-SEC-01".passes]]
handler = "pattern"
files = ["SECURITY.md", ".github/SECURITY.md"]
pattern.patterns.reporting = "(?i)report"
pattern.patterns.contact = "(?i)(email|contact)"
min_matches = 1
```

Notes:

- `pattern` is an alias for `regex`.
- The handler returns evidence about matched files and patterns.
- Pair it with `expr` when you need a more specific pass/fail rule.

### `manual`

Use for the last mile when the framework can gather clues but not certainty:

```toml
[[controls."MS-SEC-01".passes]]
handler = "manual"
steps = [
    "Review SECURITY.md for a reporting channel",
    "Confirm the guidance is still current",
]
```

## 3. CEL Expression Basics

CEL expressions let you override a handler verdict based on its evidence. The
orchestrator applies `expr` after a handler returns `PASS` or `FAIL`.

- CEL `true` turns the result into `PASS`.
- CEL `false` turns the result into `INCONCLUSIVE`, so later passes can still run.
- CEL evaluation errors fall back to the handler's original verdict.

Common context values available in CEL:

- `output.stdout`
- `output.stderr`
- `output.exit_code`
- `output.json`
- `response.status_code`
- `response.body`
- `response.headers`
- `files`
- `matches`
- `project`
- `context`
- `repo`

Custom helper functions available to CEL:

- `file_exists("PATH")`
- `json_path(OBJECT, "JMESPATH_EXPRESSION")`

Examples:

```toml
expr = "output.exit_code == 0"
expr = "output.json.has_pyproject == true"
expr = "file_exists('SECURITY.md')"
expr = "json_path(output.json, 'checks.score') >= 7"
```

A practical pattern is:

1. use `exec` or `pattern` to gather evidence
2. inspect that evidence in JSON output
3. tighten the pass/fail condition with `expr`

## 4. Writing a Custom Python Handler

Use a custom handler when built-in passes are not expressive enough. A sieve
handler is a plain Python function with this signature:

```python
from darnit.sieve.handler_registry import (
    HandlerContext,
    HandlerResult,
    HandlerResultStatus,
)


def readme_description_handler(
    config: dict,
    context: HandlerContext,
) -> HandlerResult:
    ...
```

The real example package in `packages/darnit-example/` already contains a good
reference implementation:

```python
import os
import re

from darnit.sieve.handler_registry import (
    HandlerContext,
    HandlerResult,
    HandlerResultStatus,
)


def readme_description_handler(
    config: dict,
    context: HandlerContext,
) -> HandlerResult:
    readme_names = config.get(
        "readme_names",
        ["README.md", "README", "README.rst", "README.txt"],
    )

    for name in readme_names:
        filepath = os.path.join(context.local_path, name)
        if not os.path.exists(filepath):
            continue

        try:
            with open(filepath, encoding="utf-8", errors="ignore") as f:
                content = f.read()
        except OSError:
            continue

        lines = content.strip().splitlines()
        non_title_lines = []
        for line in lines:
            stripped = line.strip()
            if stripped.startswith("#") or stripped == "" or re.match(r"^[=\\-]+$", stripped):
                continue
            non_title_lines.append(stripped)

        body_text = " ".join(non_title_lines)
        if len(body_text) > 20:
            return HandlerResult(
                status=HandlerResultStatus.PASS,
                message=f"README ({name}) contains a description ({len(body_text)} chars)",
                evidence={"file": name, "body_length": len(body_text)},
            )

        return HandlerResult(
            status=HandlerResultStatus.FAIL,
            message=f"README ({name}) exists but has no substantive description",
            evidence={"file": name, "body_length": len(body_text)},
        )

    return HandlerResult(
        status=HandlerResultStatus.FAIL,
        message="No README file found",
    )
```

Guidelines for custom handlers:

- Read all handler-specific values from `config`.
- Read repository state from `context.local_path`.
- Return `PASS`, `FAIL`, `INCONCLUSIVE`, or `ERROR` explicitly.
- Put data that later passes may need into `evidence`.
- Keep messages short and specific enough for audit output.

## 5. Registering a Custom Handler

Custom sieve handlers are registered with the `SieveHandlerRegistry` in your
implementation's `register_sieve_handlers()` method:

```python
def register_sieve_handlers(self) -> None:
    from darnit.sieve.handler_registry import get_sieve_handler_registry
    from . import handlers

    registry = get_sieve_handler_registry()
    registry.set_plugin_context(self.name)

    registry.register(
        "readme_description",
        phase="deterministic",
        handler_fn=handlers.readme_description_handler,
        description="Check README has substantive content",
    )

    registry.set_plugin_context(None)
```

Then wire the handler into TOML:

```toml
[controls."MS-DOC-02"]
name = "ReadmeHasDescription"
description = "README contains a meaningful project description"
tags = { level = 1, domain = "DOC", documentation = true }

[[controls."MS-DOC-02".passes]]
handler = "readme_description"
readme_names = ["README.md", "README.rst"]

[[controls."MS-DOC-02".passes]]
handler = "manual"
steps = [
    "Confirm the README body describes the project purpose and usage",
]
```

Important distinction:

- `register_sieve_handlers()` is for `[[controls."...".passes]]` handlers.
- `register_handlers()` is for MCP tool handlers under `[mcp.tools.*]`.

## 6. Testing One Control at a Time

For TOML-only or built-in-handler controls, the fastest feedback loop is the
CLI:

```bash
uv run darnit audit \
  --framework /path/to/mini-standard.toml \
  --include MS-DOC-01 \
  /path/to/repo
```

That keeps the run focused on one control while you tune `files`, `command`,
or `expr`.

For custom sieve handlers, use a direct Python test in addition to CLI coverage.
That catches bugs faster and avoids depending on unrelated controls:

```python
from pathlib import Path

from darnit.sieve.handler_registry import HandlerContext, HandlerResultStatus
from darnit_example.handlers import readme_description_handler


def test_readme_description_handler(tmp_path: Path) -> None:
    (tmp_path / "README.md").write_text("# Example\\n\\nThis project does useful work.\\n")

    result = readme_description_handler(
        {"readme_names": ["README.md"]},
        HandlerContext(local_path=str(tmp_path), control_id="MS-DOC-02"),
    )

    assert result.status == HandlerResultStatus.PASS
    assert result.evidence["file"] == "README.md"
```

Recommended testing workflow:

1. Start with `uv run darnit audit --include ...` for the TOML shape.
2. Add a focused pytest for any custom sieve handler.
3. Only then fold the new control into a larger framework audit.

## 7. Complete Example: Add a New Control

Here is a practical end-to-end sequence for adding a README-quality control:

1. Add the control to your framework TOML.

```toml
[controls."MS-DOC-02"]
name = "ReadmeHasDescription"
description = "README contains a meaningful project description"
tags = { level = 1, domain = "DOC", documentation = true }

[[controls."MS-DOC-02".passes]]
handler = "readme_description"
readme_names = ["README.md", "README.rst"]

[[controls."MS-DOC-02".passes]]
handler = "manual"
steps = ["Confirm the README body explains the project"]
```

2. Add the handler function to `src/<your_package>/handlers.py`.

3. Register it in `register_sieve_handlers()`.

4. Test the handler directly with pytest.

5. Run a single-control audit while iterating:

```bash
uv run darnit audit \
  --framework /path/to/your-framework.toml \
  --include MS-DOC-02 \
  /path/to/repo
```

If you can express the control with `file_exists`, `exec`, `pattern`, and
`manual`, stay in TOML. Reach for Python only when the control genuinely needs
custom logic.

## Reference Files

These files are the best companions while authoring handlers:

- `docs/IMPLEMENTATION_GUIDE.md`
- `CLAUDE.md` sections `Sieve Pattern` and `TOML Schema Features`
- `packages/darnit-example/example-hygiene.toml`
- `packages/darnit-example/src/darnit_example/handlers.py`
- `packages/darnit-example/src/darnit_example/implementation.py`
- `packages/darnit/src/darnit/sieve/builtin_handlers.py`
- `packages/darnit/src/darnit/sieve/handler_registry.py`

## Shared Execution Context

For large tools or API calls that provide data for multiple controls (like OpenSSF Scorecard or an external API), you can use the `ExecutionContext` to ensure the tool is only executed once per audit run.

The `ExecutionContext` is exposed via `handler_ctx.execution_context` natively on custom Python handlers and provides thread-safe caching. 

### Using `get_or_run_tool`

Inside a custom Python handler:

```python
from darnit.sieve.handler_registry import HandlerContext, HandlerResult, HandlerResultStatus

def scorecard_handler(config: dict[str, Any], handler_ctx: HandlerContext) -> HandlerResult:
    ctx = handler_ctx.execution_context
    if not ctx:
        return HandlerResult(
            status=HandlerResultStatus.ERROR,
            message="No execution context available"
        )
        
    def run_scorecard():
        # Expensive blocking call
        return {"data": "some_expensive_computation"}

    # get_or_run_tool is thread-safe and will only execute run_scorecard once per `tool_key`
    scorecard_data = ctx.get_or_run_tool("scorecard", run_scorecard)
    
    # Process the scorecard data for this specific control
    return HandlerResult(
        status=HandlerResultStatus.PASS,
        message="Scorecard passed",
        evidence=scorecard_data
    )
```
