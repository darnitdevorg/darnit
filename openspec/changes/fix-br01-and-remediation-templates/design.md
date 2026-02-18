## Context

BR-01.01 (SecureWorkflowInputs) has a three-pass pipeline:
1. **exec** — runs `zizmor --format json --offline $PATH` with CEL expr `!output.json.exists(f, f.ident == "template-injection")`
2. **pattern** — regex scan for dangerous `${{ github.event.* }}` patterns with CEL expr `!(output.any_match)`
3. **manual** — fallback verification steps

The universal CEL expr fix (`_apply_cel_expr` in orchestrator.py) and the zizmor integration are both working correctly. However, two issues cause suboptimal behavior:

**Issue 1: Zizmor pass falls through unnecessarily.** The exec pass has no `pass_exit_codes`, so zizmor's exit code 14 (findings present) is treated as INCONCLUSIVE. `_apply_cel_expr` only processes PASS/FAIL verdicts, so the CEL expression never evaluates. The pipeline falls through to the pattern handler, which works but bypasses zizmor's superior static analysis.

**Issue 2: Remediation-generated sast.yml introduces zizmor findings.** The `sast_workflow` template uses unpinned action references (`@v4`, `@v3`) and lacks `persist-credentials: false` on checkout. When zizmor scans the repo after remediation, it finds 4 `unpinned-uses` and 1 `artipacked` finding — all from the template-generated file. While these don't cause BR-01.01 to fail (no `template-injection` findings), they would fail other zizmor-based checks and degrade the repo's security posture.

## Goals / Non-Goals

**Goals:**
- Fix zizmor exec pass so the CEL expression actually evaluates (primary checker works as designed)
- Harden CI workflow templates so generated files pass zizmor audit with zero high-severity findings
- Add "do no harm" spec requirement for remediation templates
- Ensure the sast.yml template specifically doesn't introduce `unpinned-uses` or `artipacked` findings

**Non-Goals:**
- SHA-pinning all template action references (the spec explicitly allows major version tags — changing this is a separate discussion)
- Adding zizmor checks for other controls beyond BR-01.01
- Changing the `_apply_cel_expr` behavior for INCONCLUSIVE results (that's a broader framework decision)

## Decisions

### Decision 1: Add `pass_exit_codes` to zizmor exec pass

**Choice:** Add `pass_exit_codes = [0, 10, 11, 12, 13, 14]` to the BR-01.01 exec handler config.

**Rationale:** Zizmor exit codes indicate finding severity (0=none, 10=info, 11=low, 12=medium, 13=high, 14=mixed). All are valid outputs — the CEL expression examines the JSON payload to determine pass/fail, not the exit code. By declaring all codes as "pass", the exec handler returns PASS, which triggers `_apply_cel_expr` to evaluate the actual findings.

**Alternative considered:** Modify `_apply_cel_expr` to also process INCONCLUSIVE results. Rejected because INCONCLUSIVE semantically means "can't determine" and is used as a pipeline-continue signal. Changing this has broader framework implications.

### Decision 2: Add `persist-credentials: false` to all workflow templates

**Choice:** Add `persist-credentials: false` to every `actions/checkout` step in all CI workflow templates.

**Rationale:** This prevents the `artipacked` zizmor finding and is a security best practice (prevents credential leakage via artifacts). All existing kusari workflows already use this pattern. Cost is one extra line per template.

### Decision 3: Do NOT SHA-pin template action references

**Choice:** Keep major version tags (`@v4`, `@v3`) in templates per the existing spec requirement.

**Rationale:** The spec says "SHALL use a major version tag rather than `@latest` or a full SHA." SHA pins would conflict with the spec and create maintenance burden (pins become stale). The `unpinned-uses` zizmor finding is a legitimate security concern but the templates serve as starting points — users should pin when adopting. We should document this trade-off.

### Decision 4: Add "do no harm" spec requirement

**Choice:** Add a requirement to the `ci-workflow-templates` spec: remediation-generated files MUST NOT introduce high-severity findings when scanned by common security tools (zizmor, actionlint).

**Rationale:** The remediation tool should improve compliance, never worsen it. The `artipacked` finding in sast.yml is a concrete example of remediation introducing a new security issue.

## Risks / Trade-offs

- [Templates with major version tags will always trigger `unpinned-uses`] → Document this as known/accepted in templates; users should pin after adoption. The "do no harm" requirement applies to high-severity findings only, and `unpinned-uses` is arguable since the spec explicitly requires version tags.
- [Adding `pass_exit_codes` means zizmor errors (e.g., invalid JSON) could be treated as PASS then evaluated by CEL] → CEL will fail on invalid JSON → `_apply_cel_expr` returns original PASS result. Mitigate by checking `output.json` exists in the CEL expression (already done: `output.json.exists(...)` implicitly handles null).
