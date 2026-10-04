# Contract: Step Types, Settings, and Expressions

**Feature**: 044-false-pass-paths | **Date**: 2026-10-04

These are the surfaces that plugin authors, framework authors, and operators can rely on.

## 1. Plugin registration

```python
registry.register(
    "my_check",
    phase="deterministic",
    handler_fn=my_check,
    ceiling={"fail"},                                 # 041
    settings=frozenset({"files", "threshold"}),       # new, optional for plugins
    expression_names=frozenset({"output", "project"}),  # new, default empty
)
```

**Name collisions**

| Situation | Result |
|---|---|
| Registering a name that core already uses | Refused: a WARNING log and an entry in `refused_registrations`; the built-in is unchanged. |
| Registering a name another plugin already uses | Refused the same way; both plugins are named. |
| The same plugin registering the same name again | Allowed. |

**Settings declaration**

| Situation | Result |
|---|---|
| `settings` omitted | One warning per step type: settings are not checked. |
| `settings` given | Unknown step keys fail loading. |

## 2. Framework TOML

**Control-level keys**

Only the defined `ControlConfig` fields are accepted. Anything else fails loading with: framework file, control, key.

**Step keys**

Accepted keys are the common step fields plus the step type's declared `settings` (see data-model.md). Anything else fails loading with: framework file, control, `pass[i]:<handler>`, key.

**Step types**

An unregistered step type in a framework file fails loading. In an operator-supplied pass override or custom control, the control loads, and the audit reports it as ERROR (`missing_tool`).

**`expr` rules**

- `expr` is allowed only on step types with expression names.
- A reference to a name the step type doesn't provide fails loading.
- A syntax error fails loading.
- `expr_decides` needs `expr`, and is allowed only on `exec`, `pattern`, and `regex`; `gh_api` and `mcp` evaluate their own expression, which already decides.

## 3. Expression evaluation

| Step type | Names | Functions |
|---|---|---|
| `exec` | `output` (`stdout`, `stderr`, `exit_code`, `json`), `project` | `file_exists(path)`, `json_path(obj, path)` |
| `pattern`, `regex` | `output` (handler evidence, e.g. `any_match`, `files_found`), `project` | same |
| `gh_api` | `response` (`status_code`, `body`) | same |

**`project` binding**

`project` holds the usable project values (confirmed, or concluded for detectable keys), keyed by canonical name. Reading a key that isn't usable is an evaluation error.

**`file_exists(path)` binding**

It is resolved against the audited repository.

**Outcome rules**

| Expression result | Handler result | Step result |
|---|---|---|
| true | PASS | PASS |
| false | PASS | INCONCLUSIVE |
| false | FAIL | FAIL |
| true | FAIL | INCONCLUSIVE |
| Compile or evaluation error, or a non-boolean value | PASS or FAIL | ERROR, `error.class = evaluation` |

**With `expr_decides = true`** (FR-015), the expression alone decides on a handler PASS:

| Expression result | Handler result | Step result |
|---|---|---|
| true | PASS | PASS |
| false | PASS | FAIL |
| Compile or evaluation error, or a non-boolean value | PASS | ERROR, `error.class = evaluation` |
| Not evaluated | FAIL, WARN, INCONCLUSIVE, or ERROR | Unchanged |

PASS and FAIL still conclude only within the step's effective set. The OSPS-BR-01.01 and OSPS-AC-04.02 zizmor steps set it.

## 4. `gh_api` evidence

`evidence_fields = ["login", "two_factor_authentication"]` keeps only those keys of `response.body` in the stored evidence. It is required for personal-record endpoints: `/user`, `/users/*`, `/orgs/*/members`, `/orgs/*/outside_collaborators`, `/orgs/*/teams/*/members`, `/repos/*/*/collaborators`, and paths under them (framework-design 3.8). An `exec` step running `gh api` against one of them fails loading.

## 5. Reproducibility framework

All five reproducibility step types have ceiling `{"fail"}`. A PASS needs a corpus-backed `promotion` (041) declared on the step.
