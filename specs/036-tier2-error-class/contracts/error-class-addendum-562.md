# Addendum: `unexpected_exit` replaces `network` as the exec catch-all

**Amends**: [error-class.md](error-class.md) sections 1 and 2.1
**Issue**: #562
**Authoritative text**: `docs/architecture/framework-design.md` section 3.3 ("Undeclared exit codes") and section 5.2

## Why

Section 2.1 made `network` the class for any undeclared exit code whose stderr matched no pattern. Most such exits never touch the network: `grep` exiting 2 on a missing directory, `git` exiting 128 outside a repository, a binary the shell could not find. Reports and logs then told operators to check their network for a local condition.

## 1. The enum

One value is added. `ErrorClass` and `ERROR_CLASSES` are edited together, as section 1 requires.

| Value | Meaning |
|---|---|
| `unexpected_exit` | A command exited with a code its step did not declare, and nothing in its output identified the cause. |

`network` keeps its other producers (MCP handshake failure and unusable server, section 2.2) and, for `exec`, now means only that stderr shows a connection error.

## 2.1 `exec_handler` (replaces the non-zero-exit rows)

Checked in this order on an exit code in neither `pass_exit_codes` nor `fail_exit_codes`; first match wins. Matching is a case-insensitive substring match on stderr.

| Condition | `error_class` |
|---|---|
| stderr matches `_GH_RATE_LIMIT_PATTERNS` | `rate_limit` |
| stderr matches `_GH_AUTH_PATTERNS` (now also `not logged in`) | `auth` |
| exit code 127, stderr matches `_MISSING_TOOL_PATTERNS` (`command not found`), or a stderr line ends `<executable>: not found` | `missing_tool` |
| stderr matches `_NETWORK_PATTERNS` (name resolution, connection refused, reset, or timed out, failed to connect, network or host unreachable, TLS/SSL or certificate errors, git `unable to access 'http...`) | `network` |
| anything else, including empty stderr | `unexpected_exit` |

The timeout, missing-binary (`FileNotFoundError`), pass, and declared-fail rows are unchanged. The step stays INCONCLUSIVE as before; only its class changes.

The step's message names the exit code, the command, and the first 200 characters of stderr on one line, with non-ASCII characters replaced, so the cause is actionable from the report. The message is what the section 7 WARN log line and the step's pass-history entry carry.

## Unchanged

- `gh_api` status classification, the MCP mapping (section 2.2), the orchestrator's `crashed` (section 2.3), and context auto-detect (section 2.4).
- Propagation (section 3), CEL preservation (section 4), output surfaces (section 5), and validation (section 6). Every surface renders the class name it is given, so no surface needs a new mapping.
