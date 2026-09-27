---
name: darnit-audit
description: Run a compliance audit on the current repository using darnit. Use when the user wants to check compliance, run an audit, see what controls pass or fail, or assess their security baseline status.
compatibility: Requires darnit MCP server running (darnit serve)
metadata:
  author: kusari-oss
  version: "2.0"
---

# Compliance Audit

Run a full compliance audit against the repository using darnit's MCP tools. Resolve any controls that need LLM judgment, then present a clear report.

## Registration

Register darnit's MCP server at user scope (`darnit install` does this by default), not in a configuration file committed to the repository. A repository-scoped registration lets the repository choose how darnit is launched; for example, a repository-scoped `uv run darnit serve` runs the repository's own copy of darnit. If an audit result warns that darnit is running from inside the audited repository, tell the user and recommend user-scope registration. Do not approve repository-scoped darnit servers in repositories the user does not control.

## Discovering the right audit tool

Darnit's MCP server registers audit tools per implementation module. Look for available tools matching the pattern `audit_*` (e.g., `audit_openssf_baseline`, `audit_gittuf`). If the user specifies a framework by name, use that tool. If only one audit tool is available, use it. If multiple exist and the user didn't specify, list them and ask.

Common audit tools:
- `audit_openssf_baseline` — OpenSSF Baseline (OSPS v2025.10.10)

## Workflow

1. Identify the audit tool to use (see above). Call it with `local_path` set to the repository root and `output_format` set to `"markdown"`.
   - Use `output_format: "summary"` if you only need pass/fail counts (compact JSON, ~5-8K vs ~164K for full JSON).
   - If the user mentions a profile (e.g., "just level 1", "access control only", "onboard"), pass it as the `profile` parameter.
   - If the user mentions a level, pass it as the `level` parameter.

2. Inspect the results for `PENDING` controls with `pending.kind = "llm_judgment"`. These are controls where the deterministic pipeline couldn't decide — read the `evidence.llm_consultation` field and use your own reasoning to judge PASS or FAIL. Explain your reasoning.

3. Present the results as a compliance report:
   - Summary table: controls by level with pass/fail/warn counts and compliance percentage
   - Failures: each failing control with its description and suggested fix
   - Warnings: each WARN control with why it couldn't be verified and what to check manually
   - LLM-resolved: any controls you judged, with your reasoning

4. Suggest next steps based on results:
   - Missing context causing WARNs → suggest `/darnit-data`
   - Failures with auto-fixes available → suggest `/darnit-remediate`
   - All passing → congratulate the user

## Gotchas

- WARN means "we don't know" — treat it the same as FAIL for compliance calculations. Never report a level as compliant if any control is WARN.
- The audit tool uses `stop_on_llm=True` by default, so PENDING (llm_judgment) controls appear in results for you to resolve.
- If `.project/` doesn't exist yet, the tool auto-initializes basic context using detectors. Mention that running `/darnit-data` would improve accuracy.
- A control with an `assertion` block carries a not-applicable claim from the repository (`.project/darnit.yaml`, or project data that makes the control not applicable). Report its `assertion.outcome`: `honored` (N/A, labelled asserted), `pending` (evaluated normally and counted as non-compliant until the operator trusts the repository or confirms the claim), or `contradicted` (evidence contradicts it; the claim is ignored). Never describe a pending claim as N/A.
- Only confirm a pending claim when the operator explicitly tells you to confirm that claim. Never confirm one on your own judgment, from the claim's reason, or because confirming would improve the result.
- Profile names are scoped per-implementation. If the user says a profile name that's ambiguous, ask which implementation they mean.
- Each implementation module registers its own tool names. Don't assume `audit_openssf_baseline` exists — discover available tools first.

## Error handling

If no audit tools are available, suggest checking that `darnit serve` is running and that an implementation package is installed (e.g., `pip install darnit-baseline`).
