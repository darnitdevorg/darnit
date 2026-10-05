"""One-command CSL 1.0 onboarding for a specification repository.

Runs the whole per-repo sequence: clone, branch, baseline audit, remediate from a
drafted scope file, placeholder scan, final audit, and print the PR commands.

Typical use (two steps per repo):

    # 1. see where the repo stands, and get a scope template to fill in
    uv run python scripts/csl_onboard.py --repo uptane/uptane-standard --audit-only

    # 2. after editing the scope file, do the real run
    uv run python scripts/csl_onboard.py --repo uptane/uptane-standard \
        --scope-file scopes/uptane.md \
        --contacts "Name One <a@x.org>, Name Two <b@y.org>" \
        --code-license Apache-2.0 --spec-name "Uptane"

The scope is passed as a FILE, not a command-line string, so long prose does not
have to survive shell quoting. Nothing is written unless --scope-file is given.
"""

from __future__ import annotations

import argparse
import asyncio
import re
import subprocess
import sys
from pathlib import Path

# Repo names that are ambiguous on their own (several orgs use them), so the
# local directory and the fork get an owner prefix.
_GENERIC = {"specification", "spec", "standard", "docs"}

_SCOPE_TEMPLATE = """[One paragraph: what this Working Group standardizes.]

## In Scope

* **[Component]:** [what it defines]

## Out of Scope

* **[Area]:** [why it is excluded]
"""


def sh(args: list[str], cwd: Path | None = None, check: bool = True) -> str:
    """Run a command and return stdout, echoing the command line."""
    print(f"  $ {' '.join(args)}")
    r = subprocess.run(args, cwd=cwd, capture_output=True, text=True)
    if r.stdout.strip():
        print("    " + r.stdout.strip().replace("\n", "\n    "))
    if check and r.returncode != 0:
        print("    " + (r.stderr.strip() or "failed").replace("\n", "\n    "))
        sys.exit(f"command failed: {' '.join(args)}")
    return r.stdout


def audit(path: Path) -> dict[str, str]:
    """Deterministic audit (no LLM): every control resolves to PASS or FAIL."""
    import darnit_csl  # noqa: F401  - registers the plugin handlers

    from darnit.config import load_controls_from_effective, load_effective_config_by_name
    from darnit.tools.audit import run_sieve_audit

    cfg = load_effective_config_by_name("community-spec", str(path))
    controls = load_controls_from_effective(cfg)
    results, _ = run_sieve_audit(
        owner="", repo="", local_path=str(path), default_branch="main",
        level=3, controls=controls, evaluate_claims=False, stop_on_llm=False,
    )
    return {r["id"]: r["status"] for r in results}


def show(title: str, statuses: dict[str, str]) -> None:
    ok = sum(1 for s in statuses.values() if s == "PASS")
    print(f"\n{title}: {ok}/{len(statuses)} PASS")
    for cid in sorted(statuses):
        mark = "ok  " if statuses[cid] == "PASS" else "FAIL"
        print(f"  {mark} {cid}")


def scan_placeholders(repo: Path) -> list[str]:
    """Return governance files that still contain unfilled template text."""
    from darnit_csl.mcp_tools import _looks_like_placeholder

    hits = []
    for f in sorted((repo / "governance").glob("*.md")):
        # 01 is the verbatim CSL license text; its legal prose is not a placeholder.
        if f.name.startswith("01-"):
            continue
        if _looks_like_placeholder(f.read_text(encoding="utf-8")):
            hits.append(f.name)
    return hits


def main() -> int:
    p = argparse.ArgumentParser()
    p.add_argument("--repo", required=True, help="owner/name, e.g. uptane/uptane-standard")
    p.add_argument("--scope-file", help="markdown file holding the drafted scope")
    p.add_argument("--contacts", default="", help="real Code of Conduct contacts")
    p.add_argument("--coc-policy", choices=["csl", "umbrella", "org"], default="csl",
                   help="org = point the notices at an existing project/org Code of Conduct")
    p.add_argument("--coc-reference", default="",
                   help="markdown sentence linking the existing CoC (required with --coc-policy org)")
    p.add_argument("--code-license", default="Apache-2.0")
    p.add_argument("--governance-mode", choices=["csl", "umbrella"], default="csl",
                   help="'umbrella' references existing project governance instead "
                        "of asserting the verbatim CSL policy")
    p.add_argument("--governance-reference", default="",
                   help="what the umbrella governance is (name or URL)")
    p.add_argument("--spec-name", default="")
    p.add_argument("--workdir", default=".", help="where repos are cloned")
    p.add_argument("--branch", default="csl-compliance")
    p.add_argument("--dir", default=None, help="override local directory name")
    p.add_argument("--audit-only", action="store_true", help="baseline audit, write nothing")
    a = p.parse_args()

    owner, _, name = a.repo.partition("/")
    if not owner or not name:
        return print("--repo must be owner/name") or 1
    slug = a.dir or (f"{owner}-{name}" if name in _GENERIC else name)
    workdir = Path(a.workdir).resolve()
    repo_dir = workdir / slug

    print(f"== {a.repo}  ->  {repo_dir}")
    if not repo_dir.exists():
        sh(["git", "clone", f"https://github.com/{a.repo}.git", slug], cwd=workdir)
    branches = sh(["git", "branch", "--list", a.branch], cwd=repo_dir)
    sh(["git", "checkout"] + ([] if branches.strip() else ["-b"]) + [a.branch], cwd=repo_dir)

    show("baseline", audit(repo_dir))

    if a.audit_only or not a.scope_file:
        tmpl = workdir / f"{slug}-scope.md"
        if not tmpl.exists():
            tmpl.write_text(_SCOPE_TEMPLATE, encoding="utf-8")
            print(f"\nscope template written: {tmpl}")
        print("\nNext: fill in that file, then re-run with")
        print(f'  --scope-file "{tmpl}" --contacts "Name <email>, Name <email>"')
        print('  (or, if the project already has a Code of Conduct: '
              '--coc-policy org --coc-reference "<markdown sentence linking it>")')
        return 0

    scope = Path(a.scope_file).read_text(encoding="utf-8").strip()
    # The csl_scope template already supplies the "# Scope" heading and the
    # closing "Any changes of Scope are not retroactive." line. Strip them from
    # the supplied body so they are not emitted twice.
    scope = re.sub(r"\A#\s*Scope\s*\n+", "", scope)
    scope = re.sub(r"\n*Any changes of Scope are not retroactive\.\s*\Z", "", scope).strip()
    if not scope:
        return print("scope file is empty") or 1

    from darnit_csl.mcp_tools import remediate_community_spec

    print("\n== remediate")
    report = asyncio.run(remediate_community_spec(
        local_path=str(repo_dir), scope=scope, coc_contacts=a.contacts,
        code_license=a.code_license, spec_name=a.spec_name or name,
        governance_mode=a.governance_mode,
        governance_reference=a.governance_reference,
        coc_policy=a.coc_policy, coc_reference=a.coc_reference,
    ))
    print("  " + report.replace("\n", "\n  "))
    if report.lstrip().startswith("Error:"):
        return 1

    hits = scan_placeholders(repo_dir)
    if hits:
        print(f"\nPLACEHOLDER TEXT STILL PRESENT: {', '.join(hits)}")
        return 1
    print("\nplaceholder scan: clean")

    show("after remediation", audit(repo_dir))

    fork = f"{owner}-{name}" if name in _GENERIC else name
    print(f"""
== review these before committing
  {repo_dir / 'governance' / '02-scope.md'}
  {repo_dir / 'governance' / '03-notices.md'}
  {repo_dir / 'governance' / '05-governance.md'}

== then
  cd {repo_dir}
  git add governance README.md README.rst
  git commit -m "Add Community Specification License (CSL 1.0) file set"
  gh repo fork {a.repo} --clone=false --fork-name {fork}
  git remote rename origin upstream
  git remote add origin https://github.com/<you>/{fork}.git
  git push -u origin {a.branch}
  gh pr create --repo {a.repo} --draft --base $(git symbolic-ref --short refs/remotes/upstream/HEAD 2>/dev/null | sed 's|upstream/||' || echo main) \\
    --title "Add Community Specification License (CSL 1.0) files"
""")
    return 0


if __name__ == "__main__":
    sys.exit(main())
