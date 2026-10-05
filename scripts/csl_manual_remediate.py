"""Manually drive CSL remediation against a repo, then re-audit.

Run from the darnit repo root:

    uv run python scripts/csl_manual_remediate.py <target-repo-dir>

This is the deterministic (no-LLM) path. It shows steps 5-7 of the pattern:
  5. project_update writes paths back to .project
  6. file_create renders each file from its template
  7. the [+llm_enhance] tag marks files an LLM would refine in the MCP flow

Edit ANSWERS to experiment (governance mode, code license, CoC mode).
"""

import sys
from pathlib import Path

from darnit.config import load_framework_config
from darnit.remediation.executor import RemediationExecutor
from darnit.tools.audit import run_sieve_audit

FW = Path("packages/darnit-csl/src/darnit_csl/community-spec.toml")

ANSWERS = {
    "csl_working_group_scope": (
        "This Working Group standardizes the Foo attestation metadata format "
        "and the rules for verifying Foo attestations across implementations."
    ),
    "csl_coc_contacts": "Jane Doe (jane@example.org), John Roe (@johnroe)",
    "csl_code_license": "MIT",          # try "Apache-2.0"
    "csl_governance_mode": "csl",       # try "umbrella"
    "csl_governance_reference": "CNCF project governance (https://github.com/cncf/foundation/blob/main/charter.md)",
    "csl_coc_policy": "csl",            # try "umbrella"
    "csl_coc_reference": "CNCF Code of Conduct (https://github.com/cncf/foundation/blob/main/code-of-conduct.md)",
}

ORDER = ["CSL-01.01", "CSL-01.02", "CSL-02.01", "CSL-03.01", "CSL-04.01", "CSL-05.01", "CSL-06.01"]


def main(target: str) -> None:
    fw = load_framework_config(FW)
    ex = RemediationExecutor(
        local_path=target,
        owner="example-org",
        repo="spec-repo",
        templates=fw.templates,
        context_values=ANSWERS,
        framework_path=str(FW),
    )

    print("== remediation ==")
    for cid in ORDER:
        res = ex.execute(cid, fw.controls[cid].remediation, dry_run=False)
        tag = " [+llm_enhance]" if any("llm_enhance" in h for h in res.details.get("handlers", [])) else ""
        pu = res.details.get("project_update", "")
        pu = f"  project_update={pu}" if pu else ""
        print(f"  {cid}: success={res.success} :: {res.message}{tag}{pu}")

    # CSL-06 is a manual control (link the docs from the README). Simulate it so
    # the re-audit is fully green.
    readme = Path(target) / "README.md"
    text = readme.read_text(encoding="utf-8") if readme.exists() else "# Spec\n"
    if "02-scope.md" not in text:
        text += "\n## Governance & Licensing\n- [Scope](governance/02-scope.md)\n- [Notices](governance/03-notices.md)\n"
        readme.write_text(text, encoding="utf-8")
        print("  CSL-06.01: applied manual step (added README links)")

    print("\n== generated files ==")
    for f in sorted(Path(target).rglob("*.md")):
        print(f"  {f.relative_to(target)} ({f.stat().st_size} b)")

    print("\n== re-audit ==")
    results, _ = run_sieve_audit(
        owner="o", repo="r", local_path=target,
        default_branch="main", evaluate_claims=False,
        framework_name="community-spec", stop_on_llm=False,
    )
    for r in sorted(results, key=lambda r: r["id"]):
        mark = "PASS" if r["status"] == "PASS" else r["status"]
        print(f"  {r['id']}: {mark}")


if __name__ == "__main__":
    if len(sys.argv) != 2:
        print("usage: uv run python scripts/csl_manual_remediate.py <target-repo-dir>")
        raise SystemExit(2)
    main(sys.argv[1])
