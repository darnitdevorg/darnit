---
name: darnit-audit
description: Run a compliance audit on the current repository using darnit. Use when the user wants to check compliance, run an audit, see what controls pass or fail, or assess their security baseline status.
compatibility: Requires darnit MCP server running (darnit serve)
metadata:
  author: kusari-oss
  version: "1.1"
---

# Compliance Audit

Run a full compliance audit against the repository using darnit's MCP tools. Resolve any controls that need LLM judgment, then present a clear report.

## Discovering the right audit tool

Darnit's MCP server registers audit tools per implementation module. Look for available tools matching the pattern `audit_*` (e.g., `audit_openssf_baseline`, `audit_gittuf`). If the user specifies a framework by name, use that tool. If only one audit tool is available, use it. If multiple exist and the user didn't specify, list them and ask.

Common audit tools:
- `audit_openssf_baseline` — OpenSSF Baseline (OSPS v2025.10.10)

## Workflow

1. Identify the audit tool to use (see above). Call it with `local_path` set to the repository root and `output_format` set to `"markdown"`.
   - If the user mentions a profile (e.g., "just level 1", "access control only", "onboard"), pass it as the `profile` parameter.
   - If the user mentions a level, pass it as the `level` parameter.

2. Inspect the results for `PENDING_LLM` controls. These are controls where the deterministic pipeline couldn't decide — read the `evidence.llm_consultation` field and use your own reasoning to judge PASS or FAIL. Explain your reasoning.

3. Present the results as a compliance report:
   - Summary table: controls by level with pass/fail/warn counts and compliance percentage
   - Failures: each failing control with its description and suggested fix
   - Warnings: each WARN control with why it couldn't be verified and what to check manually
   - LLM-resolved: any controls you judged, with your reasoning

4. Suggest next steps based on results:
   - Missing context causing WARNs → suggest `/darnit-context`
   - Failures with auto-fixes available → suggest `/darnit-remediate`
   - All passing → congratulate the user

## Gotchas

- WARN means "we don't know" — treat it the same as FAIL for compliance calculations. Never report a level as compliant if any control is WARN.
- The audit tool uses `stop_on_llm=True` by default, so PENDING_LLM controls appear in results for you to resolve.
- If `.project/` doesn't exist yet, the tool auto-initializes basic context using detectors. Mention that running `/darnit-context` would improve accuracy.
- Profile names are scoped per-implementation. If the user says a profile name that's ambiguous, ask which implementation they mean.
- Each implementation module registers its own tool names. Don't assume `audit_openssf_baseline` exists — discover available tools first.

## Error handling

If no audit tools are available, suggest checking that `darnit serve` is running and that an implementation package is installed (e.g., `pip install darnit-baseline`).
