# Contract: `darnit harness` CLI

**Feature**: 026-darnit-harness
**Date**: 2026-08-05

Command-line surface, argv shape, exit-code semantics, and stderr contract for the `darnit harness` subcommand.

---

## Invocation shape

```text
darnit harness <repo-path> [--framework <name>] [--level {1,2,3}]
                           [--answers <path>]
                           [--format {markdown,json}] [--output <path>]
                           [--per-call-timeout <seconds>]
                           [--total-run-timeout <seconds>]
                           [--verbose | --quiet]
```

## Contract items

- **CLI-1**: Positional `<repo-path>` is required. If absent, argparse prints usage and exits with class 2 (setup error). If the path does not exist or does not contain a `.baseline.toml`, exit class 2 with a message pointing at `darnit init`.
- **CLI-2**: `--framework <name>` overrides `.baseline.toml` `extends` field. If both are absent, exit class 2 with a clear message.
- **CLI-3**: `--level <n>` defaults to 3. Values outside `{1, 2, 3}` are rejected by argparse (exit class 2 via argparse).
- **CLI-4**: `--answers <path>` (optional) adds a file-based `AnswerSource` to the resolver with precedence higher than the auto-discovered `.project/project.yaml`. If the path does not exist or fails to parse as YAML/JSON, exit class 2.
- **CLI-5**: `--format` defaults to `markdown`. `json` is the other supported value in MVP. Unknown values rejected by argparse.
- **CLI-6**: `--output <path>` writes the report to the given path (created if missing; parent directory must already exist). Without `--output`, the report goes to STDOUT.
- **CLI-7**: `--per-call-timeout` defaults to 60 (seconds). Applies to each LLM call individually.
- **CLI-8**: `--total-run-timeout` defaults to 900 (15 minutes). Applies to the whole audit including all LLM calls.
- **CLI-9**: `--verbose` / `--quiet` MAY be added; MVP ships without them. Default output level is INFO on stderr; `--quiet` (if added) suppresses INFO progress lines but keeps the exit-summary; `--verbose` (if added) enables DEBUG lines.
- **CLI-10**: The `darnit harness` subcommand MUST be discoverable via `darnit --help`. Its own `darnit harness --help` MUST document all flags with the semantics above.

## Exit-code contract (per FR-008)

| Code | Class | Meaning |
|------|-------|---------|
| 0 | SUCCESS | Audit completed. Zero FAIL results. All applicable controls PASS or N/A. |
| 1 | AUDIT_FAILURES | Audit completed. At least one FAIL result. |
| 2 | SETUP_ERROR | Setup / config error. Missing credentials, missing repo, unparseable answers file, invalid argv. Audit did NOT run. |
| 3 | INTERNAL_ERROR | Harness internal error. Unhandled exception, total-run timeout, invariant violation. Audit may have partial results. |

- **CLI-11**: A CI script that treats `>=1` as "block deploy" MUST additionally distinguish class 2/3 from class 1 (since 2/3 mean the audit couldn't run). The stderr summary line (CLI-13) makes this distinguishable without parsing exit codes.

## STDERR contract (per FR-009 + FR-009a)

- **CLI-12**: Progress lines during audit execution use Python stdlib logging at INFO level. Format:

  ```text
  INFO:darnit.harness:[N/M] <control_id> <phase-verb> [<detail>]
  ```

  Where `phase-verb` is one of: `starting`, `dispatching_llm`, `resolved_pass`, `resolved_fail`, `resolved_warn`, `resolved_error`, `resolved_na`, `resolved_pending`.

- **CLI-13**: The exit-summary line is emitted immediately before process exit at INFO level, distinguishable by the substring `harness:` at the start of the message. Format:

  For classes 0-1:
  ```text
  INFO:darnit.harness:harness: complete, <P> PASS, <F> FAIL, <W> WARN, <PEND> pending, exit <N>
  ```

  For classes 2-3:
  ```text
  INFO:darnit.harness:harness: <class-name>, <one-line-reason>, exit <N>
  ```

  Example: `INFO:darnit.harness:harness: setup_error, missing ANTHROPIC_API_KEY, exit 2`

- **CLI-14**: Neither the API key nor its length is ever logged. The provider is named by MODEL string (e.g., `anthropic:claude-sonnet-4-6`), not by key.

## STDOUT contract

- **CLI-15**: When `--output` is not passed, the FINAL report writes to STDOUT (Markdown by default, JSON with `--format=json`). STDOUT is otherwise silent (no progress, no summary).
- **CLI-16**: When `--output <path>` is passed, STDOUT is completely silent. The report writes only to the file.

## Compatibility

- **CLI-17**: `darnit --help` and `darnit help` MUST list `harness` as a subcommand alongside `audit`, `run`, `serve`, `list`, `install`, etc. Consistency with the existing subcommand pattern (no `darnit-harness` binary; no `darnit hrns` abbreviation).
- **CLI-18**: Existing subcommands (`darnit audit`, `darnit run`, `darnit serve`, etc.) MUST continue to work unchanged. No shared state or config between `harness` and the others beyond `.project/` and `.baseline.toml` (which they all consume).

## Contract-change procedure

Same shape as feature 024's cmd_run-output contract: if a change to this file lands, the corresponding test in `tests/darnit/harness/test_cli.py` MUST land in the same PR, and the PR description MUST note `Contract change:` explicitly.
