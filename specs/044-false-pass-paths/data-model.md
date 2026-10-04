# Data Model: Close Remaining False-PASS Paths

**Feature**: 044-false-pass-paths | **Date**: 2026-10-04

No new persisted data. This feature changes registration metadata, load-time validation, and one evidence shape.

## SieveHandlerInfo (registration metadata)

| Field | Type | Change |
|---|---|---|
| `settings` | `frozenset[str] \| None` | New. The keys this step type reads from its configuration. `None`: not declared (plugin types only; one warning per type). |
| `expression_names` | `frozenset[str]` | New. The top-level names an `expr` on this step type may reference. Empty means `expr` is not accepted. Built-ins: `exec`, `pattern`, `regex` -> `{"output", "project"}`; `gh_api` -> `{"response"}`. |
| `ceiling` | `frozenset[str]` | Unchanged field. Reproducibility types change to `{"fail"}`. |

## Registry

| Addition | Meaning |
|---|---|
| `refused_registrations: list[RefusedRegistration]` | Each has `name`, `attempted_by` (plugin), and `registered_by` (`"core"` or a plugin). It is reported in `darnit list` and in audit warnings. |

## Common step fields

The fields of `HandlerInvocation`:
- `handler`
- `when`
- `shared`
- `use_locator`
- `authority`
- `existence`
- `concludes`
- `fail_on_miss`
- `fail_on_status`
- `promotion`

Added to them:
- `description` (documentation only);
- `expr`, accepted only when `expression_names` is non-empty.

`expr_decides` (bool, default false) is a declared `HandlerInvocation` field (FR-015). It needs `expr` and is accepted only on step types whose expression the orchestrator evaluates (`exec`, `pattern`, `regex`).

A step key outside these fields and the step type's `settings` is a load error.

## Step result (unchanged model; new uses)

| Case | Status | `error_class` | Evidence additions |
|---|---|---|---|
| Expression fails to compile or evaluate, or is not boolean | `ERROR` | `evaluation` | `expr`, `expr_error` |
| Step type not registered (operator-supplied control only) | `ERROR` | `missing_tool` | `handler` |

## gh_api step setting

| Setting | Type | Meaning |
|---|---|---|
| `evidence_fields` | `list[str]` | Top-level response-body keys kept in evidence. Required when the endpoint is `/user` or `/users/...`. |

## Load errors

All load errors are raised as the existing `AuthorityViolation`, or as a new `FrameworkConfigError` subclass with the same fields: `framework`, `control_id`, `step_id`, `message`. The cases are:
- an unknown control key;
- an unknown step key;
- an unregistered step type in a framework file;
- an undeclared expression name;
- an expression syntax error;
- a missing `evidence_fields` on a personal-record endpoint.
