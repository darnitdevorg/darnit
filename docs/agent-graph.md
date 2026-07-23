# Agent Graph: audit → collect\_context → remediate

This document describes the agent graph implemented in
[`darnit/agent/graph.py`](../packages/darnit/src/darnit/agent/graph.py) and
[`darnit/agent/state.py`](../packages/darnit/src/darnit/agent/state.py).

The graph is the state-machine backbone of the interactive compliance pipeline
(`darnit run`). It orchestrates three discrete nodes — **audit**,
**collect\_context**, and **remediate** — that share a single `AuditState`
object as they progress toward a fully-remediated repository.

> **Who should read this?**
> MCP skill integrators building on top of `/darnit-comply`, plugin authors
> embedding the graph in custom workflows, and contributors who want to
> understand how context answers flow from the user through to remediation
> templates.

---

## 1. Overview

```
          ┌────────┐
          │ START  │
          └───┬────┘
              │ AuditState(local_path=…)
              ▼
         ┌─────────┐      error / no findings
         │  audit  │ ──────────────────────────────► END
         └────┬────┘
              │ audit_results populated
              ▼
           route()
          /       \
   WARN +          FAIL
 unanswered        (context
 questions         complete)
      │                 │
      ▼                 ▼
 ┌───────────────┐  ┌──────────┐
 │ collect_      │  │ remediate│
 │ context       │  └────┬─────┘
 └───────┬───────┘       │ remediation_results
         │               ▼
         │ audit_results   END
         │ cleared
         │
         ▼
      audit()   ← re-run with confirmed context
         │
       route()  → remediate / END
```

The `route()` helper decides which node runs next. Callers (e.g. the
`/darnit-comply` skill) loop on `route()` after each node until it returns
`"end"`.

---

## 2. AuditState

**Module**: `darnit.agent.state`

`AuditState` is the single shared envelope that flows through every node.
Create one instance at the start of a session and pass it unchanged between
node calls.

```python
from darnit.agent.state import AuditState

state = AuditState(
    local_path="/path/to/repo",   # required — absolute path to repo root
    owner=None,                   # auto-detected by audit() if None
    repo=None,                    # auto-detected by audit() if None
    framework_name=None,          # defaults to "openssf-baseline"
    level=3,                      # max maturity level to audit (1, 2, or 3)
)
```

### Field reference

| Field | Type | Populated by | Purpose |
|---|---|---|---|
| `local_path` | `str` | caller | Absolute path to the repository being audited |
| `owner` | `str \| None` | `audit()` | GitHub org/user (auto-detected from git remote) |
| `repo` | `str \| None` | `audit()` | Repository name (auto-detected from git remote) |
| `default_branch` | `str` | `audit()` | Default branch, e.g. `"main"` |
| `framework_name` | `str \| None` | caller | Framework to use; defaults to `"openssf-baseline"` |
| `level` | `int` | caller | Maximum maturity level to audit (1–3) |
| `audit_results` | `list[dict]` | `audit()` | Raw result dicts from the latest audit run |
| `feedback_questions` | `list[FeedbackQuestion]` | MCP skill / caller | Context questions for unresolvable WARN controls |
| `context_values` | `dict[str, Any]` | `collect_context()` | Flat `{key: answer}` map built from answered questions |
| `remediation_results` | `list[dict]` | `remediate()` | Outcomes from the remediate node |
| `error` | `str \| None` | any node | Set on fatal errors; causes `route()` to return `"end"` |

### Convenience helpers

```python
state.failing_control_ids()     # → list[str] — controls with status "FAIL"
state.warn_control_ids()        # → list[str] — controls with status "WARN"
state.has_unanswered_questions()  # → bool — True if any FeedbackQuestion is unanswered
state.collect_answered_context()  # → dict[str, Any] — {key: answer} for all answered questions
```

### FeedbackQuestion

```python
from darnit.agent.state import FeedbackQuestion

FeedbackQuestion(
    control_id="OSPS-BR-04.01",  # WARN control that triggered this question
    context_key="has_releases",  # key under which the answer is stored
    question="Does this project publish official releases?",
    answer=None,                 # populated by collect_context()
    answered=False,              # True once the user has provided an answer
)
```

`feedback_questions` must be populated by the caller (or by the MCP skill)
before calling `collect_context()`. The questions are typically derived from
the WARN controls returned by `audit()`.

---

## 3. Nodes

### 3.1 `audit(state) → AuditState`

**What it does**

1. Calls `prepare_audit()` to auto-detect `owner`, `repo`, and
   `default_branch` from the git remote if they are `None` in state.
2. Calls `run_checks()` with `stop_on_llm=True` and the confirmed
   `context_values` already in state, so re-audit passes benefit from
   previously-confirmed answers.
3. Stores results in `state.audit_results` and clears `state.error` on
   success. Sets `state.error` on failure.

**When to call it**

- At the start of a session.
- Again after `collect_context()` clears `state.audit_results` (signalling
  that a re-audit is required with the newly confirmed context).

**Signature**

```python
from darnit.agent.graph import audit

state = audit(state)
```

**Error handling**

If `prepare_audit()` returns a non-`None` error string, `state.error` is set
and `state.audit_results` remains empty. If `run_checks()` raises, the
exception message is captured in `state.error`. Either way, `route()` will
return `"end"` and the caller can inspect `state.error` for diagnostics.

---

### 3.2 `collect_context(state, answers) → AuditState`

**What it does**

1. Validates every answer value for shell metacharacters, null bytes, and
   newlines. Raises `ValueError` immediately if any value is unsafe — no
   partial writes occur.
2. Records each answer on the matching `FeedbackQuestion` in
   `state.feedback_questions` (sets `.answer` and `.answered = True`).
3. Rebuilds `state.context_values` from **all** answered questions (not
   just the ones answered in this call), giving downstream nodes a complete
   flat map.
4. Persists `state.context_values` to `.project/project.yaml` via
   `save_context_values()`. This is non-fatal: if the write fails, the
   in-memory values are still set and the node continues.
5. **Clears `state.audit_results`** to signal that a re-audit is needed.
   `route()` detects the empty list and returns `"audit"`.

**When to call it**

When `route()` returns `"collect_context"` — i.e. WARN controls exist and
there are unanswered feedback questions.

**Signature**

```python
from darnit.agent.graph import collect_context

state = collect_context(state, answers={
    "has_releases": "yes",
    "maintainer": "alice",
})
```

`answers` is a `dict[str, str]` mapping `context_key` values (as declared on
`FeedbackQuestion`) to user-supplied strings. Keys that do not match any
question are silently ignored. Passing an empty dict is a no-op.

**Security**

Answer values are validated before any state mutation. The following
characters are rejected: `\x00 \n \r ; | & $ \`` `( ) { } [ ] < > \`.
These are the characters that could enable injection via
`RemediationExecutor._substitute_command()` even when `shell=False`.

---

### 3.3 `remediate(state, dry_run=False) → AuditState`

**What it does**

1. Returns early (no-op) if `state.failing_control_ids()` is empty.
2. Loads the `FrameworkConfig` for `state.framework_name` (defaults to
   `"openssf-baseline"`). If the config cannot be loaded, logs a warning and
   returns with no changes.
3. Instantiates `RemediationExecutor` with `context_values=state.context_values`
   so that `${context.*}` tokens in remediation templates are substituted with
   confirmed answers from `collect_context()`.
4. For each failing control, calls `executor.execute()`. Controls without a
   remediation definition are recorded as `status: "skipped"`. Executor
   exceptions are caught, logged, and recorded as `success: False`.
5. Stores all outcomes in `state.remediation_results`.

**When to call it**

When `route()` returns `"remediate"` — i.e. FAIL controls exist (and all
context questions are answered or there are none).

**Signature**

```python
from darnit.agent.graph import remediate

# Dry-run: show what would change
state = remediate(state, dry_run=True)

# Apply changes
state = remediate(state, dry_run=False)
```

**`remediation_results` schema**

Each entry in `state.remediation_results` is a dict with the following fields:

| Field | Type | Meaning |
|---|---|---|
| `control_id` | `str` | The control that was remediated |
| `status` | `str` | `"skipped"` when no remediation is defined |
| `reason` | `str` | Present when `status == "skipped"` |
| `success` | `bool` | `True` if `executor.execute()` succeeded |
| `message` | `str` | Human-readable outcome or error message |
| `dry_run` | `bool` | Mirrors the `dry_run` argument |
| `details` | `dict` | Implementation-specific extra data |

---

### 3.4 `route(state) → str`

**Return values**

| Return value | Condition |
|---|---|
| `"end"` | `state.error` is set |
| `"audit"` | `state.audit_results` is empty (cleared by `collect_context`) |
| `"collect_context"` | WARN controls exist **and** `state.has_unanswered_questions()` |
| `"remediate"` | FAIL controls exist (and no pending context questions) |
| `"end"` | No FAIL or WARN controls remain |

```python
from darnit.agent.graph import route

next_step = route(state)  # "audit" | "collect_context" | "remediate" | "end"
```

---

## 4. context\_values and the re-audit loop

The central mechanism that makes the graph useful is the way `context_values`
flow from the user through to both the re-audit pass and to remediation
templates.

```
collect_context(state, answers={"has_releases": "yes"})
    │
    ├─ state.feedback_questions[i].answered = True
    ├─ state.context_values = {"has_releases": "yes"}
    ├─ save_context_values(local_path, {"has_releases": "yes"})
    │       └─ writes .project/project.yaml
    └─ state.audit_results = []          ← triggers re-audit

route(state) → "audit"

audit(state)
    │
    └─ run_checks(…)                     ← sieve reads .project/project.yaml
           │                               context-dependent controls now resolve
           └─ state.audit_results = […]

route(state) → "remediate"

remediate(state)
    │
    └─ RemediationExecutor(context_values=state.context_values)
           │
           └─ ${context.has_releases} substituted in remediation templates
```

**Key invariant**: `state.context_values` is always the union of **all**
answered questions seen so far, not just the most recent batch. This means
successive calls to `collect_context()` accumulate answers rather than
replacing them.

---

## 5. MCP skill integration

The agent graph is the Python-level abstraction. MCP skills (`/darnit-audit`,
`/darnit-comply`, etc.) orchestrate it through MCP tool calls rather than
calling the graph functions directly.

### Skill-to-node mapping

| Skill | Nodes involved |
|---|---|
| `/darnit-audit` | `audit()` only — runs checks and returns a report |
| `/darnit-data` | Drives `collect_context()` via `get_pending_data` / `confirm_project_data` MCP tools |
| `/darnit-remediate` | `remediate()` — runs an internal audit first, then applies fixes |
| `/darnit-comply` | Full loop: `audit → collect_context → audit → remediate` |

### Typical `/darnit-comply` loop (pseudocode)

```python
state = AuditState(local_path=repo_root)

while True:
    next_step = route(state)

    if next_step == "audit":
        state = audit(state)

    elif next_step == "collect_context":
        # Present state.feedback_questions to the user via MCP tool
        answers = ask_user(state.feedback_questions)
        state = collect_context(state, answers)

    elif next_step == "remediate":
        # Show dry-run plan; get confirmation; apply
        state = remediate(state, dry_run=True)
        if user_confirms(state.remediation_results):
            state = remediate(state, dry_run=False)
        break

    elif next_step == "end":
        break
```

### WARN vs FAIL

- **WARN** means "we don't know" — the sieve could not determine compliance
  automatically. WARN controls trigger `collect_context` to gather the missing
  information, after which a re-audit can produce a conclusive PASS or FAIL.
- **FAIL** means the control was definitively checked and found non-compliant.
  FAIL controls trigger `remediate`.

Never report a level as compliant if any control is WARN.

---

## 6. Source files

| File | Purpose |
|---|---|
| [`packages/darnit/src/darnit/agent/graph.py`](../packages/darnit/src/darnit/agent/graph.py) | Node implementations: `audit`, `collect_context`, `remediate`, `route` |
| [`packages/darnit/src/darnit/agent/state.py`](../packages/darnit/src/darnit/agent/state.py) | `AuditState` and `FeedbackQuestion` dataclasses |
| [`tests/darnit/agent/test_graph.py`](../tests/darnit/agent/test_graph.py) | Unit tests for all nodes and the `route` helper |
| [`tests/darnit/agent/test_state.py`](../tests/darnit/agent/test_state.py) | Unit tests for `AuditState` helpers |
| [`packages/darnit/src/darnit/skills/darnit-comply/SKILL.md`](../packages/darnit/src/darnit/skills/darnit-comply/SKILL.md) | `/darnit-comply` skill that orchestrates the full loop |
| [`packages/darnit/src/darnit/skills/darnit-data/SKILL.md`](../packages/darnit/src/darnit/skills/darnit-data/SKILL.md) | `/darnit-data` skill that drives context collection |

## 7. Related documentation

- [ARCHITECTURE.md](../ARCHITECTURE.md) — overall framework architecture and
  the three-layer design
- [docs/WORKFLOW.md](WORKFLOW.md) — Mermaid diagrams for audit internals,
  remediation flow, and context lifecycle
- [docs/getting-started/using-skills.md](getting-started/using-skills.md) —
  how to invoke skills from Claude Code
